"""
Webhook processing — the most important function in the project.

Idempotency has THREE layers:
  1. WebhookEvent.idempotency_key is UNIQUE. A replay of the exact same event is
     detected and answered with 200 "duplicate" and NO side effects.
  2. The Payment row is locked with SELECT ... FOR UPDATE. If two workers get the
     same (or conflicting) event at the same moment, the second waits for the
     first to commit, then sees the payment is no longer PENDING and does nothing.
  3. Database constraints: provider_reference is UNIQUE and a subscription can
     have only one SUCCEEDED payment.

Side effects outside the DB (the email) are queued with transaction.on_commit,
so they happen only if — and after — the transaction really commits.
"""
import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from subscriptions.models import Subscription
from subscriptions.services import activate_subscription

from .models import Payment, WebhookEvent
from .serializers import EVENT_FAILED, EVENT_SUCCESS

logger = logging.getLogger(__name__)


@dataclass
class WebhookResult:
    http_status: int
    outcome: str  # processed | duplicate | already_processed | rejected
    message: str
    payment: Payment | None = None


def make_idempotency_key(data: dict) -> str:
    raw = f"{data['event']}|{data['reference']}|{data['provider_reference']}|{Decimal(data['amount']):.2f}"
    return hashlib.sha256(raw.encode()).hexdigest()


def process_webhook(data: dict, raw_payload: dict) -> WebhookResult:
    key = make_idempotency_key(data)

    # Fast path: we've already handled this exact event.
    previous = WebhookEvent.objects.filter(idempotency_key=key).first()
    if previous:
        if previous.status == WebhookEvent.Status.REJECTED:
            # Replaying a rejected event gets the same rejection, still with no side effects.
            return WebhookResult(404 if previous.payment_id is None else 400, "rejected", previous.message)
        return WebhookResult(200, "duplicate", "Event already processed; no changes made.", previous.payment)

    try:
        with transaction.atomic():
            result = _process_locked(data, raw_payload, key)
    except IntegrityError:
        # Another worker inserted the same WebhookEvent between our check and our insert.
        logger.info("webhook_duplicate_race", extra={"reference": data["reference"]})
        return WebhookResult(200, "duplicate", "Event already received.")
    return result


def _record(key, data, raw_payload, status, message, payment=None):
    WebhookEvent.objects.create(
        idempotency_key=key,
        event_type=data["event"],
        reference=data["reference"],
        provider_reference=data.get("provider_reference", ""),
        payload=raw_payload,
        status=status,
        message=message[:255],
        payment=payment,
    )


def _process_locked(data, raw_payload, key) -> WebhookResult:
    reference = data["reference"]

    # Lock the payment row (and its subscription) for the rest of this transaction.
    payment = (
        Payment.objects.select_for_update(of=("self", "subscription"))
        .select_related("subscription", "subscription__plan")
        .filter(reference=reference)
        .first()
    )
    if payment is None:
        msg = "Unknown payment reference."
        _record(key, data, raw_payload, WebhookEvent.Status.REJECTED, msg)
        logger.warning("webhook_unknown_reference", extra={"reference": reference})
        return WebhookResult(404, "rejected", msg)

    if Decimal(data["amount"]) != payment.amount:
        msg = f"Amount mismatch: expected {payment.amount}, got {data['amount']}."
        _record(key, data, raw_payload, WebhookEvent.Status.REJECTED, msg, payment)
        logger.warning("webhook_amount_mismatch", extra={"reference": reference, "expected": str(payment.amount), "got": str(data["amount"])})
        return WebhookResult(400, "rejected", msg, payment)

    if data.get("currency") and data["currency"].upper() != payment.currency:
        msg = f"Currency mismatch: expected {payment.currency}, got {data['currency']}."
        _record(key, data, raw_payload, WebhookEvent.Status.REJECTED, msg, payment)
        return WebhookResult(400, "rejected", msg, payment)

    if payment.status != Payment.Status.PENDING:
        # Payment already final (a different event already settled it). No-op.
        msg = f"Payment already {payment.status}; no changes made."
        _record(key, data, raw_payload, WebhookEvent.Status.PROCESSED, msg, payment)
        return WebhookResult(200, "already_processed", msg, payment)

    now = timezone.now()
    payment.provider_reference = data["provider_reference"]

    if data["event"] == EVENT_SUCCESS:
        payment.status = Payment.Status.SUCCEEDED
        payment.paid_at = now
        activated = activate_subscription(payment.subscription, now=now)
        if not activated and payment.subscription.status == Subscription.Status.CANCELLED:
            payment.requires_refund = True
        payment.save(update_fields=["status", "paid_at", "provider_reference", "requires_refund", "updated_at"])
        _record(key, data, raw_payload, WebhookEvent.Status.PROCESSED, "Payment succeeded.", payment)

        if activated:
            from .tasks import send_payment_success_email

            payment_id = payment.id
            # Queue the email ONLY after commit; HTTP response doesn't wait for it.
            transaction.on_commit(lambda: send_payment_success_email.delay(payment_id))
        logger.info("payment_succeeded", extra={"reference": reference, "activated": activated})
        return WebhookResult(200, "processed", "Payment succeeded.", payment)

    if data["event"] == EVENT_FAILED:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = data.get("reason") or "Payment failed at provider."
        payment.save(update_fields=["status", "failure_reason", "provider_reference", "updated_at"])
        _record(key, data, raw_payload, WebhookEvent.Status.PROCESSED, "Payment failed.", payment)
        # Subscription stays PENDING; the customer can POST /api/subscriptions/ again
        # to get a fresh payment reference for the same pending subscription.
        logger.info("payment_failed", extra={"reference": reference})
        return WebhookResult(200, "processed", "Payment failure recorded.", payment)

    raise ValueError("Unsupported event")  # serializer prevents this
