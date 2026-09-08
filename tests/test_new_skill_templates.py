"""Offline regressions for the nine skills bundled in #263."""
import asyncio
import hashlib
import hmac
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

SKILLS = Path(__file__).resolve().parents[1] / 'zeline' / 'skills'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def shop(tmp_path, monkeypatch):
    templates = SKILLS / 'telegram-commerce-bot' / 'templates'
    shutil.copy(templates / 'tripay-gateway.py', tmp_path / 'tripay_gateway.py')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, 'tripay_gateway', raising=False)
    module = load(templates / 'bot-template.py', 'shop_template_test')
    module.DB_PATH = str(tmp_path / 'nested' / 'shop.db')
    # Isolate payment/security tests from the independent missing-directory bug.
    Path(module.DB_PATH).parent.mkdir()
    module.init_db()
    with sqlite3.connect(module.DB_PATH) as db:
        db.execute("INSERT INTO orders (user_id,product,price,tripay_ref,payment_amount) VALUES (42,'Product',100,'REF',100)")
        db.execute("INSERT INTO stock (product,credential) VALUES ('Product','secret_`text')")
    return module


def test_callback_signs_exact_raw_bytes():
    gateway = load(SKILLS / 'telegram-commerce-bot/templates/tripay-gateway.py', 'tripay_test')
    raw = b'{ "status": "PAID", "reference": "REF" }'
    signature = hmac.new(b'key', raw, hashlib.sha256).hexdigest()
    assert gateway.TripayPayment.verify_callback(raw, signature, 'key')
    assert not gateway.TripayPayment.verify_callback(raw + b' ', signature, 'key')
    assert not gateway.TripayPayment.verify_callback(raw, '', 'key')
    assert not gateway.TripayPayment.verify_callback({}, signature, 'key')


def test_delivery_requires_confirmed_payment(shop):
    bot = SimpleNamespace(send_message=AsyncMock())
    assert asyncio.run(shop.deliver_order(1, bot)) is False
    bot.send_message.assert_not_called()


def test_delivery_failure_reserves_same_stock_and_does_not_mark_done(shop):
    with sqlite3.connect(shop.DB_PATH) as db:
        db.execute("UPDATE orders SET status='paid'")
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('offline')))
    assert asyncio.run(shop.deliver_order(1, bot)) is False
    with sqlite3.connect(shop.DB_PATH) as db:
        assert db.execute('SELECT status FROM orders').fetchone()[0] == 'delivery_failed'
        assert db.execute('SELECT status FROM stock').fetchone()[0] == 'reserved'
    bot.send_message = AsyncMock()
    assert asyncio.run(shop.deliver_order(1, bot)) is True
    assert asyncio.run(shop.deliver_order(1, bot)) is True
    bot.send_message.assert_awaited_once()


def test_foreign_order_does_not_query_payment(shop):
    query = SimpleNamespace(data='check_1', from_user=SimpleNamespace(id=99),
                            answer=AsyncMock(), edit_message_text=AsyncMock())
    def forbidden(*args):
        pytest.fail('payment queried for another buyer')
    shop.tripay.check_payment = forbidden
    asyncio.run(shop.button_handler(SimpleNamespace(callback_query=query), SimpleNamespace(bot=None)))


def test_wrong_amount_never_delivers(shop):
    query = SimpleNamespace(data='check_1', from_user=SimpleNamespace(id=42),
                            answer=AsyncMock(), edit_message_text=AsyncMock())
    shop.tripay.check_payment = lambda ref: {'success': True, 'status': 'PAID', 'reference': ref, 'amount': 1}
    bot = SimpleNamespace(send_message=AsyncMock())
    asyncio.run(shop.button_handler(SimpleNamespace(callback_query=query), SimpleNamespace(bot=bot)))
    bot.send_message.assert_not_called()
    with sqlite3.connect(shop.DB_PATH) as db:
        assert db.execute('SELECT status FROM orders').fetchone()[0] == 'pending'


def test_matching_payment_delivers_to_buyer(shop):
    query = SimpleNamespace(data='check_1', from_user=SimpleNamespace(id=42),
                            answer=AsyncMock(), edit_message_text=AsyncMock())
    shop.tripay.check_payment = lambda ref: {'success': True, 'status': 'PAID', 'reference': ref, 'amount': 100}
    bot = SimpleNamespace(send_message=AsyncMock())
    asyncio.run(shop.button_handler(SimpleNamespace(callback_query=query), SimpleNamespace(bot=bot)))
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.args[0] == 42
    with sqlite3.connect(shop.DB_PATH) as db:
        assert db.execute('SELECT status FROM orders').fetchone()[0] == 'done'


def test_payment_detail_preserves_reference_and_bounds_request(monkeypatch):
    gateway = load(SKILLS / 'telegram-commerce-bot/templates/tripay-gateway.py', 'tripay_detail_test')
    def get(url, **kwargs):
        assert kwargs['timeout'] == 30
        assert kwargs['params'] == {'reference': 'REF&other=x'}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'success': True, 'data': {'reference': 'REF&other=x', 'status': 'PAID', 'amount': 100}})
    monkeypatch.setattr(gateway.requests, 'get', get)
    result = gateway.TripayPayment('key', 'private', 'merchant').check_payment('REF&other=x')
    assert result['reference'] == 'REF&other=x'


def test_qris_timeout_is_reported_without_retry(monkeypatch):
    gateway = load(SKILLS / 'telegram-commerce-bot/templates/tripay-gateway.py', 'tripay_timeout_test')
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs)
        assert kwargs['timeout'] == 30
        raise gateway.requests.Timeout('offline')
    monkeypatch.setattr(gateway.requests, 'post', post)
    result = gateway.TripayPayment('key', 'private', 'merchant').create_qris(100, order_id='ORDER')
    assert result['success'] is False
    assert len(calls) == 1


def test_create_accepts_checkout_url_without_pay_url(monkeypatch):
    gateway = load(SKILLS / 'telegram-commerce-bot/templates/tripay-gateway.py', 'tripay_create_test')
    payload = {'reference': 'REF', 'merchant_ref': 'ORDER', 'qr_url': 'https://example.invalid/qr',
               'qr_string': 'QR', 'checkout_url': 'https://example.invalid/pay', 'amount': 105, 'status': 'UNPAID'}
    monkeypatch.setattr(gateway.requests, 'post', lambda *a, **kw: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'success': True, 'data': payload}))
    result = gateway.TripayPayment('key', 'private', 'merchant').create_qris(100)
    assert result['pay_url'] == payload['checkout_url']


def test_checkout_stores_gateway_total_including_fees(shop):
    product = next(iter(shop.PRODUCTS))
    price = shop.PRODUCTS[product]['price']
    shop.tripay.create_qris = lambda **kw: {'success': True, 'reference': 'NEW',
        'amount': price + 500, 'qr_url': 'https://example.invalid/qr'}
    query = SimpleNamespace(data='buy_' + product,
        from_user=SimpleNamespace(id=42, username='buyer'), message=SimpleNamespace(chat_id=42),
        answer=AsyncMock(), edit_message_text=AsyncMock())
    asyncio.run(shop.button_handler(SimpleNamespace(callback_query=query),
        SimpleNamespace(bot=SimpleNamespace(send_photo=AsyncMock()))))
    with sqlite3.connect(shop.DB_PATH) as db:
        assert db.execute("SELECT payment_amount FROM orders WHERE tripay_ref='NEW'").fetchone()[0] == price + 500


def test_init_db_creates_parent(shop, tmp_path):
    shop.DB_PATH = str(tmp_path / 'newdir' / 'db.sqlite')
    shop.init_db()
    assert Path(shop.DB_PATH).exists()


def test_documentation_pipeline_does_not_pass_scripts_as_arguments():
    root = SKILLS / 'documentation-site'
    for path in root.rglob('*.md'):
        assert 'python3 section_*.py' not in path.read_text(), str(path)


def test_delivery_concurrent_calls_send_once(shop):
    with sqlite3.connect(shop.DB_PATH) as db:
        db.execute("UPDATE orders SET status='paid'")
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def send(*args, **kwargs):
            started.set()
            await release.wait()
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))
        first = asyncio.create_task(shop.deliver_order(1, bot))
        await started.wait()
        assert await shop.deliver_order(1, bot) is False
        release.set()
        assert await first is True
        bot.send_message.assert_awaited_once()
    asyncio.run(scenario())


def test_airdrop_accepts_timezone_aware_api_dates(monkeypatch, capsys):
    import json
    import runpy
    import urllib.request
    from datetime import datetime, timezone
    monkeypatch.setattr(sys, 'argv', ['fetch-latest-airdrops.py', '7'])
    data = [{'date': datetime.now(timezone.utc).isoformat(),
             'title': {'rendered': 'Test'}, 'link': 'https://example.invalid/'}]
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **kw:
                        SimpleNamespace(read=lambda: json.dumps(data).encode()))
    runpy.run_path(str(SKILLS / 'riset-airdrop/scripts/fetch-latest-airdrops.py'))
    assert '**Test**' in capsys.readouterr().out


def test_rebrand_example_uses_real_python(tmp_path):
    import re
    text = (SKILLS / 'fork-and-rebrand-webapp/SKILL.md').read_text()
    section = text.split('## Step 3', 1)[1].split('## Step 4', 1)[0]
    code = re.search(r'```python\n(.*?)```', section, re.S).group(1)
    code = code.replace('Path.home() / "NEWNAME"', repr(str(tmp_path)))
    (tmp_path / 'file with spaces.jsx').write_text('OldBrand oldbrand')
    exec(compile(code, '<skill-example>', 'exec'), {})
    assert (tmp_path / 'file with spaces.jsx').read_text() == 'NewBrand newbrand'
