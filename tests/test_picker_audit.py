"""Offline regression coverage for Telegram picker responsiveness and validation."""
import importlib
import unittest
from unittest import mock


class PickerAuditTests(unittest.TestCase):
    def setUp(self):
        self.telegram = importlib.import_module("zeline.gateways.telegram")
        self.providers = [
            {"slug": "z", "name": "Zulu", "base_url": "https://z.invalid/v1", "api_key": "", "model": "cx/model"},
            {"slug": "a", "name": "Alpha", "base_url": "https://a.invalid/v1", "api_key": "", "model": "ag/model"},
        ]

    def test_root_picker_never_fetches_catalog(self):
        tg = self.telegram
        with mock.patch.object(tg, "_MODELS_CACHE", {}), \
             mock.patch.object(tg, "_MODEL_META_CACHE", {}), \
             mock.patch.object(tg, "_model_button_logos", return_value={}), \
             mock.patch.object(tg._HTTP, "get", side_effect=tg.requests.Timeout) as get:
            text, markup = tg._provider_picker_payload(self.providers, "z")
        get.assert_not_called()
        self.assertIn("Current: cx/model", text)
        rows = markup["inline_keyboard"]
        self.assertTrue(all(len(row) == 1 for row in rows))
        self.assertEqual([row[0]["callback_data"] for row in rows],
                         ["provider:1", "provider:0", "model:cancel"])
        self.assertTrue(all(row[0]["style"] == "primary" for row in rows[:-1]))
        self.assertNotIn("style", rows[-1][0])

    def test_root_picker_uses_cached_route_count_without_refresh(self):
        tg = self.telegram
        cache = {"https://z.invalid/v1": (0, ["cx/model", "ag/model", "ag/other"])}
        with mock.patch.object(tg, "_MODELS_CACHE", cache), \
             mock.patch.object(tg, "_model_button_logos", return_value={}), \
             mock.patch.object(tg._HTTP, "get", side_effect=tg.requests.Timeout) as get:
            _, markup = tg._provider_picker_payload(self.providers, "z")
        get.assert_not_called()
        self.assertEqual(markup["inline_keyboard"][1][0]["text"], "✓ Zulu (2)")

    def test_malformed_callbacks_do_not_select_or_discover_models(self):
        tg = self.telegram
        invalid = ["provider:-1", "routes:-1", "route:-1:0", "route:0:-1",
                   "route:0:0:extra", "model:-1:0", "model:0:-1", "model:-1",
                   "model:0:0:extra"]
        for data in invalid:
            with self.subTest(data=data), \
                 mock.patch.object(tg, "_configured_providers", return_value=self.providers), \
                 mock.patch.object(tg, "_model_button_logos", return_value={}), \
                 mock.patch.object(tg, "_discover_provider_models", return_value=["cx/model", "ag/model"]) as discover, \
                 mock.patch.object(tg, "_discover_models", return_value=["cx/model"]) as legacy, \
                 mock.patch.object(tg.config, "stored_config_copy", return_value={"provider": {}}), \
                 mock.patch.object(tg.config, "save_config") as save, \
                 mock.patch.object(tg, "_model_switch_text", return_value="Switched"), \
                 mock.patch.object(tg, "_edit_interactive") as edit, \
                 mock.patch.object(tg, "_api_call"):
                sessions = mock.Mock()
                tg._handle_callback("offline", {"id": "test", "data": data,
                                    "message": {"chat": {"id": 1}, "message_id": 2}}, sessions)
                discover.assert_not_called()
                legacy.assert_not_called()
                save.assert_not_called()
                sessions.switch_provider.assert_not_called()
                self.assertIn("expired", edit.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
