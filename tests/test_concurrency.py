"""
Real concurrency tests: several threads, each with its OWN database connection,
hit the same code at the same instant (a Barrier releases them together).

`transaction=True` makes pytest-django really commit to PostgreSQL, so row
locks and unique constraints behave exactly like production.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection, transaction

from conftest import auth_client, signed_webhook
from payments.models import Payment, WebhookEvent
from plans.models import Plan
from subscriptions.models import Subscription

pytestmark = pytest.mark.django_db(transaction=True)

N = 8


def run_concurrently(fn, n=N):
    barrier = threading.Barrier(n)

    def worker(i):
        try:
            barrier.wait()
            return fn(i)
        finally:
            connection.close()  # each thread owns a connection; close it

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def test_simultaneous_subscribe_requests_create_one_subscription(customer, plan):
    def subscribe(_):
        return auth_client(customer).post("/api/subscriptions/", {"plan_id": plan.id}, format="json")

    responses = run_concurrently(subscribe)
    codes = sorted(r.status_code for r in responses)
    assert codes.count(201) == 1, codes
    assert all(c in (200, 201) for c in codes), codes
    assert Subscription.objects.filter(customer=customer, plan=plan).count() == 1
    assert Payment.objects.count() == 1
    # Every caller got the SAME payment reference back.
    assert len({r.data["payment_reference"] for r in responses}) == 1


def test_same_webhook_delivered_concurrently_is_processed_once(customer, plan, settings):
    res = auth_client(customer).post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
    body = {"event": "payment.success", "reference": res.data["payment_reference"],
            "provider_reference": "STRIPE-RACE", "amount": str(plan.price)}

    from rest_framework.test import APIClient

    responses = run_concurrently(lambda _: signed_webhook(APIClient(), body))
    outcomes = [r.data["outcome"] for r in responses]
    assert outcomes.count("processed") == 1, outcomes
    assert all(r.status_code == 200 for r in responses)
    assert WebhookEvent.objects.count() == 1
    assert Payment.objects.get().status == "SUCCEEDED"
    assert Subscription.objects.get().status == "ACTIVE"


def test_two_workers_different_events_same_payment(customer, plan):
    """Two different gateway events for one payment (success with 2 provider refs):
    the row lock serialises them; exactly one wins, the other is a no-op."""
    res = auth_client(customer).post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
    ref = res.data["payment_reference"]

    from rest_framework.test import APIClient

    def send(i):
        return signed_webhook(APIClient(), {"event": "payment.success", "reference": ref,
                                             "provider_reference": f"GW-{i}", "amount": str(plan.price)})

    responses = run_concurrently(send)
    outcomes = sorted(r.data["outcome"] for r in responses)
    assert outcomes.count("processed") == 1, outcomes
    assert set(outcomes) <= {"processed", "already_processed"}
    assert Payment.objects.filter(status="SUCCEEDED").count() == 1


def test_plan_deactivated_while_subscription_is_being_created(customer, plan):
    """
    Thread A locks the plan and deactivates it (slowly). Thread B tries to subscribe
    in the middle. B must wait for A's lock and then see the plan as inactive.
    """
    locked = threading.Event()
    result = {}

    def deactivate():
        try:
            with transaction.atomic():
                p = Plan.objects.select_for_update().get(pk=plan.pk)
                locked.set()
                time.sleep(0.5)  # B is now blocked on the lock
                p.is_active = False
                p.save()
        finally:
            connection.close()

    def subscribe():
        try:
            locked.wait()
            result["res"] = auth_client(customer).post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
        finally:
            connection.close()

    a, b = threading.Thread(target=deactivate), threading.Thread(target=subscribe)
    a.start(); b.start(); a.join(); b.join()

    assert result["res"].status_code == 400
    assert result["res"].data["error"]["code"] == "plan_inactive"
    assert Subscription.objects.count() == 0


def test_cancel_and_expire_race_does_not_resurrect(customer, plan):
    """Expiry's conditional UPDATE re-checks status, so it never overwrites CANCELLED."""
    from datetime import timedelta

    from django.utils import timezone

    from subscriptions.services import expire_due_subscriptions

    now = timezone.now()
    sub = Subscription.objects.create(customer=customer, plan=plan, status="ACTIVE",
                                      start_date=now - timedelta(days=31), end_date=now - timedelta(seconds=1))
    locked = threading.Event()

    def cancel():
        try:
            with transaction.atomic():
                s = Subscription.objects.select_for_update().get(pk=sub.pk)
                locked.set()
                time.sleep(0.4)
                s.status = "CANCELLED"
                s.save()
        finally:
            connection.close()

    def expire():
        try:
            locked.wait()
            expire_due_subscriptions()
        finally:
            connection.close()

    a, b = threading.Thread(target=cancel), threading.Thread(target=expire)
    a.start(); b.start(); a.join(); b.join()
    sub.refresh_from_db()
    assert sub.status == "CANCELLED"
