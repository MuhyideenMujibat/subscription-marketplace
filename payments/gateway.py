"""
Simulated payment provider.

In real life this would call Paystack/Stripe to initialise a charge. Here it:
  * generates unique payment references (PAY-<32 hex chars>)
  * signs / verifies webhook payloads with HMAC-SHA256 (like Paystack's
    `x-paystack-signature` or Stripe's `Stripe-Signature`).
"""
import hashlib
import hmac
import uuid

from django.conf import settings

SIGNATURE_HEADER = "X-Webhook-Signature"


class SimulatedPaymentGateway:
    def new_reference(self) -> str:
        return f"PAY-{uuid.uuid4().hex.upper()}"

    def sign(self, raw_body: bytes) -> str:
        return hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()

    def verify_signature(self, raw_body: bytes, signature: str | None) -> bool:
        if not settings.PAYMENT_WEBHOOK_VERIFY_SIGNATURE:
            return True
        if not signature:
            return False
        # compare_digest = constant-time comparison (prevents timing attacks).
        return hmac.compare_digest(self.sign(raw_body), signature)


gateway = SimulatedPaymentGateway()
