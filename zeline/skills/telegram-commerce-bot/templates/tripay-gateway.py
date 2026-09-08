# Tripay Payment Gateway — Standalone Module
# Copy into your bot project. Fill in credentials from tripay.co.id

import hashlib
import hmac
import json
import requests
from datetime import datetime


class TripayPayment:
    def __init__(self, api_key, private_key, merchant_code):
        self.api_key = api_key
        self.private_key = private_key
        self.merchant_code = merchant_code
        self.base_url = "https://tripay.co.id/api-sandbox"  # Ganti ke api untuk production

    def _sign(self, merchant_ref, amount):
        raw = f"{self.merchant_code}{merchant_ref}{amount}"
        return hmac.new(
            self.private_key.encode(),
            raw.encode(),
            hashlib.sha256
        ).hexdigest()

    def create_qris(self, amount, customer_name="Customer", order_id=None, expired=24):
        """Generate QRIS payment. Returns dict with qr_url (PNG), pay_url, reference."""
        import uuid
        merchant_ref = order_id or f"INV-{uuid.uuid4().hex[:10].upper()}"

        payload = {
            "method": "QRISC",
            "merchant_ref": merchant_ref,
            "amount": amount,
            "customer_name": customer_name[:50],
            "order_items": [
                {"name": "Digital Product", "price": amount, "quantity": 1}
            ],
            "expired_time": int((datetime.now().timestamp() + expired * 3600)),
            "signature": self._sign(merchant_ref, amount)
        }

        headers = {"Authorization": f"Bearer {self.api_key}"}
        r = requests.post(f"{self.base_url}/transaction/create", json=payload, headers=headers)
        data = r.json()

        if data.get("success"):
            return {
                "success": True,
                "reference": data["data"]["reference"],
                "merchant_ref": data["data"]["merchant_ref"],
                "qr_url": data["data"]["qr_url"],
                "qr_string": data["data"]["qr_string"],
                "pay_url": data["data"]["pay_url"],
                "amount": data["data"]["amount"],
                "status": data["data"]["status"],
            }
        return {"success": False, "error": data.get("message", "Unknown error")}

    def check_payment(self, reference):
        """Check payment status by Tripay reference."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        r = requests.get(
            f"{self.base_url}/transaction/detail?reference={reference}",
            headers=headers
        )
        data = r.json()

        if data.get("success"):
            return {
                "success": True,
                "status": data["data"]["status"],  # UNPAID, PAID, EXPIRED, FAILED
                "amount": data["data"]["amount"],
                "paid_at": data["data"].get("paid_at"),
            }
        return {"success": False, "error": data.get("message")}

    @staticmethod
    def verify_callback(callback_data, private_key, merchant_code):
        """Verify Tripay webhook callback signature. Returns True if valid."""
        callback_dict = dict(callback_data)
        signature = callback_dict.pop("signature", "")
        payload = json.dumps(callback_dict, separators=(',', ':'))
        expected = hmac.new(
            private_key.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature == expected
