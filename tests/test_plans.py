import pytest

from accounts.models import User
from conftest import auth_client
from plans.models import Plan

pytestmark = pytest.mark.django_db

URL = "/api/plans/"
BODY = {"name": "Gold", "description": "All access", "price": "15000.00", "billing_interval": "MONTHLY"}


def test_provider_creates_plan(provider_client, provider):
    res = provider_client.post(URL, BODY, format="json")
    assert res.status_code == 201, res.data
    plan = Plan.objects.get(pk=res.data["id"])
    assert plan.provider == provider
    assert plan.is_active is True


def test_customer_cannot_create_plan(customer_client):
    assert customer_client.post(URL, BODY, format="json").status_code == 403


def test_anonymous_cannot_create_plan(api):
    assert api.post(URL, BODY, format="json").status_code == 401


def test_invalid_price_and_interval(provider_client):
    res = provider_client.post(URL, {**BODY, "price": "0", "billing_interval": "WEEKLY"}, format="json")
    assert res.status_code == 400
    assert {"price", "billing_interval"} <= set(res.data["error"]["details"])


def test_provider_cannot_modify_another_providers_plan(make_user, make_plan):
    owner = make_user(User.Role.PROVIDER)
    other = make_user(User.Role.PROVIDER)
    plan = make_plan(owner)
    client = auth_client(other)
    assert client.patch(f"{URL}{plan.id}/", {"price": "1.00"}, format="json").status_code == 403
    assert client.delete(f"{URL}{plan.id}/").status_code == 403
    plan.refresh_from_db()
    assert str(plan.price) == "15000.00"


def test_owner_can_update_and_delete(provider_client, plan):
    res = provider_client.patch(f"{URL}{plan.id}/", {"price": "20000.00"}, format="json")
    assert res.status_code == 200
    assert res.data["price"] == "20000.00"
    assert provider_client.delete(f"{URL}{plan.id}/").status_code == 204


def test_cannot_delete_plan_with_subscriptions(provider_client, customer_client, plan):
    customer_client.post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
    res = provider_client.delete(f"{URL}{plan.id}/")
    assert res.status_code == 409
    assert res.data["error"]["code"] == "plan_has_subscriptions"


def test_public_list_shows_only_active_plans(api, make_plan, provider):
    make_plan(provider, name="A")
    make_plan(provider, name="B", is_active=False)
    res = api.get(URL)
    assert res.status_code == 200
    assert [p["name"] for p in res.data["results"]] == ["A"]


def test_provider_mine_includes_inactive(provider_client, make_plan, provider):
    make_plan(provider, name="A")
    make_plan(provider, name="B", is_active=False)
    res = provider_client.get(URL + "?mine=true")
    assert {p["name"] for p in res.data["results"]} == {"A", "B"}


def test_inactive_plan_cannot_receive_subscriptions(customer_client, make_plan, provider):
    plan = make_plan(provider, is_active=False)
    res = customer_client.post("/api/subscriptions/", {"plan_id": plan.id}, format="json")
    assert res.status_code == 400
    assert res.data["error"]["code"] == "plan_inactive"


# ----------------------------- caching -----------------------------

def test_plan_list_is_cached(api, make_plan, provider, django_assert_num_queries):
    make_plan(provider)
    first = api.get(URL)
    assert first["X-Cache"] == "MISS"
    with django_assert_num_queries(0):
        second = api.get(URL)
    assert second["X-Cache"] == "HIT"
    assert second.data == first.data


def test_cache_invalidated_on_create_update_delete(api, provider_client, django_capture_on_commit_callbacks):
    # Invalidation runs in transaction.on_commit -> execute those callbacks in the test.
    commit = lambda: django_capture_on_commit_callbacks(execute=True)  # noqa: E731
    assert api.get(URL).data["count"] == 0
    assert api.get(URL)["X-Cache"] == "HIT"

    with commit():
        created = provider_client.post(URL, BODY, format="json")  # create
    res = api.get(URL)
    assert res["X-Cache"] == "MISS" and res.data["count"] == 1

    with commit():
        provider_client.patch(f"{URL}{created.data['id']}/", {"name": "Platinum"}, format="json")  # update
    res = api.get(URL)
    assert res["X-Cache"] == "MISS" and res.data["results"][0]["name"] == "Platinum"

    with commit():
        provider_client.delete(f"{URL}{created.data['id']}/")  # delete
    res = api.get(URL)
    assert res["X-Cache"] == "MISS" and res.data["count"] == 0
