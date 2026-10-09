import json
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from payments.gateway import SIGNATURE_HEADER, gateway
from plans.models import Plan


@pytest.fixture(autouse=True)
def _test_settings(settings):
    # Tests use an in-memory cache and run Celery tasks inline (no worker needed).
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.PAYMENT_WEBHOOK_SECRET = "test-secret"
    settings.PAYMENT_WEBHOOK_VERIFY_SIGNATURE = True
    from config.celery import app

    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = False
    from django.core.cache import cache

    cache.clear()
    yield


@pytest.fixture
def api():
    return APIClient()


def auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def make_user(db):
    counter = {"n": 0}

    def _make(role=User.Role.CUSTOMER, email=None, password="Str0ng-pass!"):
        counter["n"] += 1
        email = email or f"{role.lower()}{counter['n']}@example.com"
        return User.objects.create_user(email=email, password=password, role=role)

    return _make


@pytest.fixture
def customer(make_user):
    return make_user(User.Role.CUSTOMER)


@pytest.fixture
def provider(make_user):
    return make_user(User.Role.PROVIDER)


@pytest.fixture
def customer_client(customer):
    return auth_client(customer)


@pytest.fixture
def provider_client(provider):
    return auth_client(provider)


@pytest.fixture
def make_plan(db):
    def _make(provider, **kw):
        defaults = dict(name=f"Plan {Plan.objects.count() + 1}", price=Decimal("15000.00"),
                        billing_interval=Plan.BillingInterval.MONTHLY, is_active=True)
        defaults.update(kw)
        return Plan.objects.create(provider=provider, **defaults)

    return _make


@pytest.fixture
def plan(make_plan, provider):
    return make_plan(provider)


def signed_webhook(client, payload: dict, signature: str | None = None):
    body = json.dumps(payload).encode()
    headers = {SIGNATURE_HEADER: signature if signature is not None else gateway.sign(body)}
    return client.post("/api/payments/webhook/", data=body, content_type="application/json", headers=headers)


@pytest.fixture
def send_webhook():
    def _send(payload, signature=None, client=None):
        return signed_webhook(client or APIClient(), payload, signature)

    return _send
