from unittest import mock

import pytest
from django.core import mail

from payments.models import Payment, WebhookEvent
from subscriptions.models import Subscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def pending(customer_client, plan):
    res = customer_client.post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
    return Payment.objects.select_related("subscription").get(reference=res.data["payment_reference"])


def payload(payment, **over):
    data = {"event": "payment.success", "reference": payment.reference,
            "provider_reference": "STRIPE-123456", "amount": str(payment.amount)}
    data.update(over)
    return data


def test_successful_webhook_activates_subscription_and_emails(pending, send_webhook, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        res = send_webhook(payload(pending))
    assert res.status_code == 200 and res.data["outcome"] == "processed"
    pending.refresh_from_db()
    sub = pending.subscription
    sub.refresh_from_db()
    assert pending.status == "SUCCEEDED" and pending.provider_reference == "STRIPE-123456" and pending.paid_at
    assert sub.status == "ACTIVE"
    assert sub.start_date and sub.end_date > sub.start_date
    assert sub.next_billing_date == sub.end_date
    assert (sub.end_date - sub.start_date).days in (28, 29, 30, 31)  # MONTHLY
    assert len(callbacks) == 1  # email queued only after commit
    assert len(mail.outbox) == 1 and "active" in mail.outbox[0].subject
    pending.refresh_from_db()
    assert pending.notification_sent_at is not None


def test_yearly_plan_gets_one_year(customer_client, make_plan, provider, send_webhook):
    plan = make_plan(provider, billing_interval="YEARLY")
    res = customer_client.post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
    send_webhook({"event": "payment.success", "reference": res.data["payment_reference"],
                  "provider_reference": "S-Y", "amount": str(plan.price)})
    sub = Subscription.objects.get(pk=res.data["subscription_id"])
    assert (sub.end_date - sub.start_date).days in (365, 366)


def test_failed_webhook(pending, send_webhook):
    res = send_webhook(payload(pending, event="payment.failed", reason="Card declined"))
    assert res.status_code == 200
    pending.refresh_from_db()
    assert pending.status == "FAILED" and pending.failure_reason == "Card declined"
    assert pending.subscription.status == "PENDING"
    assert len(mail.outbox) == 0


def test_invalid_reference(send_webhook, db):
    res = send_webhook({"event": "payment.success", "reference": "PAY-DOESNOTEXIST",
                        "provider_reference": "X", "amount": "100.00"})
    assert res.status_code == 404
    assert WebhookEvent.objects.get().status == "REJECTED"


def test_incorrect_amount(pending, send_webhook):
    res = send_webhook(payload(pending, amount="1.00"))
    assert res.status_code == 400
    assert "mismatch" in res.data["error"]["message"].lower()
    pending.refresh_from_db()
    assert pending.status == "PENDING" and pending.subscription.status == "PENDING"


def test_invalid_signature_rejected(pending, send_webhook):
    res = send_webhook(payload(pending), signature="not-a-real-signature")
    assert res.status_code == 401
    pending.refresh_from_db()
    assert pending.status == "PENDING"
    assert WebhookEvent.objects.count() == 0


def test_missing_signature_rejected(pending, api):
    res = api.post("/api/payments/webhook/", payload(pending), format="json")
    assert res.status_code == 401


def test_malformed_payload(send_webhook, db):
    res = send_webhook({"event": "payment.refunded", "reference": "x"})
    assert res.status_code == 400


def test_duplicate_webhook_is_idempotent(pending, send_webhook, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        first = send_webhook(payload(pending))
    sub = Subscription.objects.get(pk=pending.subscription_id)
    snapshot = (sub.start_date, sub.end_date, sub.updated_at)

    with mock.patch("payments.tasks.send_payment_success_email.delay") as delay:
        for _ in range(3):
            with django_capture_on_commit_callbacks(execute=True):
                again = send_webhook(payload(pending))
            assert again.status_code == 200 and again.data["outcome"] == "duplicate"
        delay.assert_not_called()

    sub.refresh_from_db()
    assert (sub.start_date, sub.end_date, sub.updated_at) == snapshot  # dates didn't move
    assert first.data["outcome"] == "processed"
    assert WebhookEvent.objects.count() == 1
    assert Payment.objects.filter(status="SUCCEEDED").count() == 1
    assert len(mail.outbox) == 1  # exactly one email


def test_conflicting_second_event_does_not_change_settled_payment(pending, send_webhook):
    send_webhook(payload(pending))
    # A later "failed" event (different provider_reference) for an already-paid payment.
    res = send_webhook(payload(pending, event="payment.failed", provider_reference="STRIPE-999"))
    assert res.status_code == 200 and res.data["outcome"] == "already_processed"
    pending.refresh_from_db()
    assert pending.status == "SUCCEEDED" and pending.provider_reference == "STRIPE-123456"
    assert pending.subscription.status == "ACTIVE"


def test_payment_after_cancellation_flags_refund(pending, customer_client, send_webhook):
    customer_client.post(f"/api/subscriptions/{pending.subscription_id}/cancel/")
    res = send_webhook(payload(pending))
    assert res.status_code == 200
    pending.refresh_from_db()
    assert pending.status == "SUCCEEDED" and pending.requires_refund is True
    assert pending.subscription.status == "CANCELLED"
    assert len(mail.outbox) == 0


def test_email_task_is_idempotent(pending, send_webhook, django_capture_on_commit_callbacks):
    from payments.tasks import send_payment_success_email

    with django_capture_on_commit_callbacks(execute=True):
        send_webhook(payload(pending))
    assert send_payment_success_email(pending.id) == "skipped"  # e.g. Celery re-delivery
    assert len(mail.outbox) == 1
