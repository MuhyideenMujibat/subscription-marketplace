from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from conftest import auth_client
from payments.models import Payment
from subscriptions.models import Subscription
from subscriptions.tasks import expire_subscriptions

pytestmark = pytest.mark.django_db

URL = "/api/subscriptions/"


def subscribe(client, plan):
    return client.post(URL, {"plan_id": plan.id}, format="json")


def test_successful_subscription_creation(customer_client, customer, plan):
    res = subscribe(customer_client, plan)
    assert res.status_code == 201, res.data
    assert res.data["status"] == "PENDING"
    assert res.data["payment_reference"].startswith("PAY-")
    sub = Subscription.objects.get(pk=res.data["subscription_id"])
    assert sub.customer == customer and sub.status == Subscription.Status.PENDING
    assert sub.start_date is None  # not active until payment
    payment = Payment.objects.get(reference=res.data["payment_reference"])
    assert payment.amount == plan.price and payment.status == Payment.Status.PENDING


def test_repeat_request_while_pending_returns_same_subscription(customer_client, plan):
    first = subscribe(customer_client, plan)
    second = subscribe(customer_client, plan)
    assert second.status_code == 200
    assert second.data["subscription_id"] == first.data["subscription_id"]
    assert second.data["payment_reference"] == first.data["payment_reference"]
    assert Subscription.objects.count() == 1 and Payment.objects.count() == 1


def test_duplicate_active_subscription_rejected(customer_client, customer, plan, send_webhook):
    res = subscribe(customer_client, plan)
    send_webhook({"event": "payment.success", "reference": res.data["payment_reference"],
                  "provider_reference": "SIM-1", "amount": str(plan.price)})
    dup = subscribe(customer_client, plan)
    assert dup.status_code == 409
    assert dup.data["error"]["code"] == "already_subscribed"
    assert Subscription.objects.filter(customer=customer, plan=plan).count() == 1


def test_db_constraint_blocks_duplicate_open_subscription(customer, plan):
    """Even bypassing the API, PostgreSQL refuses a 2nd open subscription."""
    from django.db import IntegrityError, transaction

    Subscription.objects.create(customer=customer, plan=plan, status="ACTIVE",
                                start_date=timezone.now(), end_date=timezone.now() + timedelta(days=30))
    with pytest.raises(IntegrityError), transaction.atomic():
        Subscription.objects.create(customer=customer, plan=plan, status="PENDING")


def test_can_resubscribe_after_cancellation(customer_client, plan):
    first = subscribe(customer_client, plan)
    customer_client.post(f"{URL}{first.data['subscription_id']}/cancel/")
    again = subscribe(customer_client, plan)
    assert again.status_code == 201
    assert again.data["subscription_id"] != first.data["subscription_id"]


def test_pending_subscription_is_not_active_without_payment(customer_client, plan):
    """Insufficient/invalid payment state: no webhook => stays PENDING, no dates."""
    res = subscribe(customer_client, plan)
    sub = Subscription.objects.get(pk=res.data["subscription_id"])
    assert sub.status == "PENDING" and sub.end_date is None and sub.next_billing_date is None


def test_failed_payment_keeps_subscription_pending_and_retry_gets_new_reference(customer_client, plan, send_webhook):
    res = subscribe(customer_client, plan)
    send_webhook({"event": "payment.failed", "reference": res.data["payment_reference"],
                  "provider_reference": "SIM-F", "amount": str(plan.price), "reason": "Insufficient funds"})
    sub = Subscription.objects.get(pk=res.data["subscription_id"])
    assert sub.status == "PENDING"
    assert Payment.objects.get(reference=res.data["payment_reference"]).failure_reason == "Insufficient funds"

    retry = subscribe(customer_client, plan)
    assert retry.data["subscription_id"] == sub.id
    assert retry.data["payment_reference"] != res.data["payment_reference"]  # fresh payment


def test_cancellation(customer_client, plan):
    res = subscribe(customer_client, plan)
    cancel = customer_client.post(f"{URL}{res.data['subscription_id']}/cancel/")
    assert cancel.status_code == 200
    assert cancel.data["status"] == "CANCELLED" and cancel.data["cancelled_at"]
    # can't cancel twice
    again = customer_client.post(f"{URL}{res.data['subscription_id']}/cancel/")
    assert again.status_code == 400


def test_cannot_cancel_someone_elses_subscription(customer_client, plan, make_user):
    res = subscribe(customer_client, plan)
    stranger = auth_client(make_user(User.Role.CUSTOMER))
    assert stranger.post(f"{URL}{res.data['subscription_id']}/cancel/").status_code == 404


def test_expiry_task_marks_past_subscriptions_expired(customer, plan, make_plan, provider):
    now = timezone.now()
    past = Subscription.objects.create(customer=customer, plan=plan, status="ACTIVE",
                                       start_date=now - timedelta(days=31), end_date=now - timedelta(minutes=1))
    future = Subscription.objects.create(customer=customer, plan=make_plan(provider), status="ACTIVE",
                                         start_date=now, end_date=now + timedelta(days=30))
    cancelled = Subscription.objects.create(customer=customer, plan=make_plan(provider), status="CANCELLED",
                                            start_date=now - timedelta(days=40), end_date=now - timedelta(days=10))
    assert expire_subscriptions.delay().get() == 1
    past.refresh_from_db(); future.refresh_from_db(); cancelled.refresh_from_db()
    assert past.status == "EXPIRED"
    assert future.status == "ACTIVE"
    assert cancelled.status == "CANCELLED"  # untouched


# ----------------------------- listing / visibility / performance -----------------------------

def _make_subs(customer, provider, make_plan, n, status="ACTIVE"):
    now = timezone.now()
    for _ in range(n):
        p = make_plan(provider)
        s = Subscription.objects.create(customer=customer, plan=p, status=status,
                                        start_date=now, end_date=now + timedelta(days=30))
        Payment.objects.create(subscription=s, reference=f"PAY-{s.id}-X", amount=p.price,
                               status="SUCCEEDED", paid_at=now)


def test_list_filter_and_pagination(customer_client, customer, provider, make_plan, settings):
    _make_subs(customer, provider, make_plan, 25, "ACTIVE")
    _make_subs(customer, provider, make_plan, 3, "EXPIRED")
    res = customer_client.get(URL + "?status=ACTIVE")
    assert res.data["count"] == 25 and len(res.data["results"]) == 20
    page2 = customer_client.get(URL + "?status=ACTIVE&page=2")
    assert len(page2.data["results"]) == 5
    assert customer_client.get(URL + "?status=EXPIRED").data["count"] == 3
    assert customer_client.get(URL + "?status=NOPE").status_code == 400


def test_list_has_no_n_plus_one(customer_client, customer, provider, make_plan, django_assert_max_num_queries):
    _make_subs(customer, provider, make_plan, 20)
    # COUNT + page query (with JOINs) + 1 prefetch for payments (+ auth user lookup) — constant.
    with django_assert_max_num_queries(4):
        res = customer_client.get(URL)
    assert len(res.data["results"]) == 20


def test_visibility_customer_provider_admin(customer, customer_client, provider, make_plan, make_user):
    _make_subs(customer, provider, make_plan, 2)
    other_provider = make_user(User.Role.PROVIDER)
    other_customer = make_user(User.Role.CUSTOMER)
    _make_subs(other_customer, other_provider, make_plan, 3)

    assert customer_client.get(URL).data["count"] == 2
    assert auth_client(provider).get(URL).data["count"] == 2  # provider sees their customers
    assert auth_client(other_provider).get(URL).data["count"] == 3
    admin = User.objects.create_superuser(email="admin@example.com", password="Str0ng-pass!")
    assert auth_client(admin).get(URL).data["count"] == 5
