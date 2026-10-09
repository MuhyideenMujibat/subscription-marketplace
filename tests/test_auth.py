import pytest

from accounts.models import User
from conftest import auth_client

pytestmark = pytest.mark.django_db

REGISTER = "/api/auth/register/"
LOGIN = "/api/auth/login/"
ME = "/api/auth/me/"


def test_register_customer(api):
    res = api.post(REGISTER, {"email": "Ada@Example.com", "password": "Str0ng-pass!"}, format="json")
    assert res.status_code == 201, res.data
    assert res.data["user"]["email"] == "ada@example.com"  # normalised
    assert res.data["user"]["role"] == "CUSTOMER"
    assert "access" in res.data["tokens"]


def test_register_provider(api):
    res = api.post(REGISTER, {"email": "p@example.com", "password": "Str0ng-pass!", "role": "PROVIDER"}, format="json")
    assert res.status_code == 201
    assert User.objects.get(email="p@example.com").role == User.Role.PROVIDER


def test_cannot_register_as_admin(api):
    res = api.post(REGISTER, {"email": "x@example.com", "password": "Str0ng-pass!", "role": "ADMIN"}, format="json")
    assert res.status_code == 400
    assert not User.objects.filter(email="x@example.com").exists()


def test_duplicate_email_rejected_case_insensitive(api, make_user):
    make_user(email="dup@example.com")
    res = api.post(REGISTER, {"email": "DUP@example.com", "password": "Str0ng-pass!"}, format="json")
    assert res.status_code == 400
    assert "email" in res.data["error"]["details"]


def test_weak_password_rejected(api):
    res = api.post(REGISTER, {"email": "w@example.com", "password": "12345678"}, format="json")
    assert res.status_code == 400


def test_login_returns_jwt_and_me_works(api, make_user):
    make_user(email="login@example.com", password="Str0ng-pass!")
    res = api.post(LOGIN, {"email": "LOGIN@example.com", "password": "Str0ng-pass!"}, format="json")
    assert res.status_code == 200, res.data
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
    me = api.get(ME)
    assert me.status_code == 200
    assert me.data["email"] == "login@example.com"


def test_login_wrong_password(api, make_user):
    make_user(email="l2@example.com")
    res = api.post(LOGIN, {"email": "l2@example.com", "password": "wrong"}, format="json")
    assert res.status_code == 401


def test_me_requires_auth(api):
    assert api.get(ME).status_code == 401


def test_user_cannot_change_own_role(customer):
    client = auth_client(customer)
    res = client.patch(ME, {"role": "ADMIN", "first_name": "Ada"}, format="json")
    assert res.status_code == 200
    customer.refresh_from_db()
    assert customer.role == User.Role.CUSTOMER  # ignored
    assert customer.first_name == "Ada"  # other fields still editable


def test_permission_enforcement_customer_cannot_create_plan(customer_client):
    res = customer_client.post("/api/plans/", {"name": "x", "price": "10", "billing_interval": "MONTHLY"}, format="json")
    assert res.status_code == 403


def test_permission_enforcement_provider_cannot_subscribe(provider_client, plan):
    res = provider_client.post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
    assert res.status_code == 403
