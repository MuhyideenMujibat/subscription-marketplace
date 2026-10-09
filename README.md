# Subscription Marketplace & Payment Platform — Backend

Django + DRF backend where **customers** subscribe to **providers'** plans, pay through a (simulated)
payment gateway, and get activated only when the gateway's **webhook** confirms payment.

**Stack:** Python 3.12 · Django 5.1 · Django REST Framework · SimpleJWT · PostgreSQL 16 · Redis 7 · Celery 5 (+ Beat) · drf-spectacular (OpenAPI) · pytest

```
config/          settings, urls, celery app
core/            error handler, JSON logging, request-id middleware, health check, Celery base task + dead-letter table
accounts/        custom User (email login, roles), register / login / me, permissions
plans/           Plan model, CRUD API, Redis cache + invalidation
subscriptions/   Subscription model, service layer (create/activate/cancel/expire), list filters, Celery expiry task
payments/        Payment + WebhookEvent models, simulated gateway (HMAC), idempotent webhook service, email task
tests/           auth, plans, subscriptions, payments, real multi-thread concurrency tests
```

---

## 1. Install and run

### Option A — Docker (everything in one command)
```bash
cp .env.example .env
docker compose up --build            # web :8000, worker, beat, postgres, redis
docker compose exec web python manage.py createsuperuser
```

### Option B — Local Python, Postgres/Redis in Docker
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # Windows: copy .env.example .env
docker compose up -d db redis        # or use locally installed Postgres + Redis
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Then open: API docs **http://127.0.0.1:8000/api/docs/** · Admin **http://127.0.0.1:8000/admin/** · Health **/api/health/**

> PostgreSQL is exposed on host port **5433** (not 5432) so it doesn't clash with a locally installed PostgreSQL.

## 2. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev value | Django secret key |
| `DJANGO_DEBUG` | `False` | Debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_HOST` / `POSTGRES_PORT` | `marketplace` … `localhost` / `5433` | Database |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker + results |
| `REDIS_CACHE_URL` | `redis://localhost:6379/1` | Django cache |
| `PLAN_LIST_CACHE_TTL` | `300` | Seconds the plan list stays cached |
| `EXPIRY_TASK_EVERY_MINUTES` | `5` | How often Beat runs the expiry task |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | `30` / `7` | Token lifetimes |
| `PAYMENT_CURRENCY` | `NGN` | Currency for new plans |
| `PAYMENT_WEBHOOK_SECRET` | dev value | HMAC secret shared with the gateway |
| `PAYMENT_WEBHOOK_VERIFY_SIGNATURE` | `True` | Turn signature check on/off |
| `EMAIL_BACKEND` | console | "Simulated" email = printed by the worker |
| `LOG_LEVEL` | `INFO` | Log level (JSON logs) |

## 3. Database setup
PostgreSQL is required (partial unique indexes and `SELECT … FOR UPDATE` are used deliberately).
```sql
CREATE USER marketplace WITH PASSWORD 'marketplace' CREATEDB;
CREATE DATABASE marketplace OWNER marketplace;
```
```bash
python manage.py migrate
```
(`CREATEDB` lets the test runner create the test database.)

## 4. Redis setup
`docker compose up -d redis` or install Redis locally (Linux/macOS: package manager; Windows: Docker or WSL).
DB 0 is the Celery broker/result backend, DB 1 is the cache. Check: `redis-cli ping` → `PONG`.

## 5. Celery worker
```bash
celery -A config worker -l info
# Windows (no fork support):
celery -A config worker -l info --pool=solo
```

## 6. Celery Beat
```bash
celery -A config beat -l info
```
Schedule is in `settings.CELERY_BEAT_SCHEDULE`: `subscriptions.tasks.expire_subscriptions` every `EXPIRY_TASK_EVERY_MINUTES`.

## 7. Running tests
```bash
python -m pytest                 # 53 tests
python -m pytest --create-db     # after model changes
python -m pytest tests/test_concurrency.py -v
```
Tests need PostgreSQL (the concurrency tests use real threads, real commits and real row locks).
Cache is swapped for in-memory and Celery runs eagerly, so Redis/worker are not needed for tests.

## 8. API documentation & examples
Interactive OpenAPI docs: **`/api/docs/`** (schema at `/api/schema/`).
All error responses share one shape: `{"error": {"code": "...", "message": "...", "details": {...}}}`.

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/api/auth/register/` | anyone | `role` = `CUSTOMER` (default) or `PROVIDER`; never `ADMIN` |
| POST | `/api/auth/login/` | anyone | returns `access` + `refresh` JWT |
| POST | `/api/auth/refresh/` | anyone | refresh token → new access |
| GET/PATCH | `/api/auth/me/` | logged in | `role`, `email` read-only |
| GET | `/api/plans/` | public | active plans, **cached** · `?mine=true` provider's own (incl. inactive) |
| POST | `/api/plans/` | provider | |
| GET/PATCH/DELETE | `/api/plans/{id}/` | owner for writes | DELETE → 409 if plan has subscriptions (deactivate instead) |
| POST | `/api/subscriptions/` | customer | `{"plan_id": 1}` → PENDING + payment reference |
| GET | `/api/subscriptions/` | logged in | `?status=ACTIVE&page=2&plan=1` · customer: own · provider: their customers · admin: all |
| GET | `/api/subscriptions/{id}/` | logged in | |
| POST | `/api/subscriptions/{id}/cancel/` | owning customer | |
| POST | `/api/payments/webhook/` | payment gateway | HMAC-signed |
| GET | `/api/health/` | public | DB + Redis check |

**Full flow with curl**
```bash
B=http://127.0.0.1:8000/api
# provider
curl -X POST $B/auth/register/ -H "Content-Type: application/json" \
  -d '{"email":"prov@test.com","password":"Str0ng-pass!","role":"PROVIDER"}'
curl -X POST $B/auth/login/ -H "Content-Type: application/json" \
  -d '{"email":"prov@test.com","password":"Str0ng-pass!"}'          # copy "access" -> $PT
curl -X POST $B/plans/ -H "Authorization: Bearer $PT" -H "Content-Type: application/json" \
  -d '{"name":"Gold","description":"All access","price":"15000.00","billing_interval":"MONTHLY"}'
# customer
curl -X POST $B/auth/register/ -H "Content-Type: application/json" \
  -d '{"email":"cust@test.com","password":"Str0ng-pass!"}'           # copy tokens.access -> $CT
curl -X POST $B/subscriptions/ -H "Authorization: Bearer $CT" -H "Content-Type: application/json" \
  -d '{"plan_id": 1}'
# -> {"subscription_id":1,"payment_reference":"PAY-EA2B…","amount":"15000.00","currency":"NGN","status":"PENDING"}

# act as the payment gateway (signs the payload with PAYMENT_WEBHOOK_SECRET and POSTs it)
python manage.py simulate_webhook PAY-EA2B… --send
python manage.py simulate_webhook PAY-EA2B… --event payment.failed --send
python manage.py simulate_webhook PAY-EA2B…            # just prints a ready-to-run signed curl

curl "$B/subscriptions/?status=ACTIVE" -H "Authorization: Bearer $CT"
```

**Webhook body** (header `X-Webhook-Signature: hex(HMAC_SHA256(secret, raw_body))`)
```json
{"event": "payment.success", "reference": "PAY-8F92A1…", "provider_reference": "STRIPE-123456", "amount": "15000.00"}
```
Responses: `200 processed` · `200 duplicate` · `200 already_processed` · `400` bad payload / amount mismatch · `401` bad signature · `404` unknown reference.

## 9. Authentication approach
* Custom `accounts.User` (`AbstractBaseUser`): `USERNAME_FIELD = "email"`, no username.
* Email is normalised to lowercase and protected by a **case-insensitive unique constraint** (`UNIQUE (LOWER(email))`), so `A@x.com` and `a@x.com` cannot both exist even under concurrent sign-ups (an `IntegrityError` there becomes a 409).
* Stateless **JWT** via SimpleJWT (`Authorization: Bearer <access>`), short-lived access + refresh token.
* Roles: `CUSTOMER`, `PROVIDER`, `ADMIN`. Sign-up only allows CUSTOMER/PROVIDER. `role` is `read_only` in every user serializer, so no endpoint can change it; only Django admin can. A DB `CHECK` constraint restricts the column to the three values.
* Permissions are small DRF classes: `IsCustomer`, `IsProvider`, `IsPlanOwnerOrReadOnly` (object-level). A provider editing another provider's plan gets **403**; a customer touching someone else's subscription gets **404** (we don't reveal it exists).

## 10. Payment / webhook architecture
```
Customer ── POST /subscriptions {plan_id} ──► create_subscription()  [1 transaction]
                                                ├─ lock plan row, check is_active
                                                ├─ Subscription(PENDING)
                                                └─ Payment(PENDING, reference=PAY-<uuid>, amount=plan.price)
          ◄── {subscription_id, payment_reference, status: PENDING}
Customer pays at gateway (simulated)
Gateway ── POST /payments/webhook (HMAC signed) ──► verify signature ─► validate body ─► process_webhook()  [1 transaction]
                                                        ├─ dedupe via WebhookEvent.idempotency_key (UNIQUE)
                                                        ├─ SELECT payment + subscription FOR UPDATE
                                                        ├─ verify reference exists, amount (and currency) match
                                                        ├─ payment PENDING? → SUCCEEDED / FAILED
                                                        ├─ success → subscription ACTIVE, start/end/next_billing dates
                                                        ├─ store WebhookEvent (audit)
                                                        └─ on_commit → Celery: send_payment_success_email
```
* The subscription is **never** activated by the subscribe call — only by a verified webhook.
* `amount` is copied onto the Payment at creation, so a provider changing the price later doesn't break verification.
* Dates: `start = now`, `end = start + 1 month | 1 year` (`relativedelta`, so Jan 31 → Feb 28/29 correctly), `next_billing_date = end`.
* `payment.failed`: payment → FAILED with reason; subscription stays PENDING. Calling `POST /subscriptions/` again for that plan returns the same subscription with a **fresh** payment reference (retry flow).
* Success for a subscription the customer already cancelled: payment is recorded as SUCCEEDED, subscription stays CANCELLED, and `requires_refund=True` is set (visible/filterable in admin).
* Signature: HMAC-SHA256 over the **raw** request body with a shared secret, compared with `hmac.compare_digest` (constant time). Invalid/missing → 401 and nothing is stored.

## 11. Idempotency strategy
| Layer | Mechanism | What it stops |
|---|---|---|
| Event | `WebhookEvent.idempotency_key` = SHA-256 of `event|reference|provider_reference|amount`, **UNIQUE** | Exact replays → `200 duplicate`, zero side effects. Two simultaneous identical deliveries: the second INSERT fails on the unique index → treated as duplicate. |
| State machine | Payment is locked `FOR UPDATE`; only `PENDING` payments can change | A *different* event for an already-settled payment (e.g. late `failed` after `success`) → `200 already_processed`, no change |
| Database | `provider_reference` UNIQUE; partial unique "one SUCCEEDED payment per subscription" | Even buggy code can't apply one charge twice or double-pay a subscription |
| Side effects | Email queued with `transaction.on_commit`; task locks the payment and checks `notification_sent_at` | No email for rolled-back transactions; Celery re-delivery (acks_late) never sends twice |
| Subscribe | Repeat `POST /subscriptions/` while PENDING returns the existing subscription + payment (200) | Double-clicks don't create extra payments |

Rejected events (bad amount, unknown reference) are also stored, and replaying them returns the same rejection.

## 12. Concurrency strategy
| Scenario | Handling |
|---|---|
| Two simultaneous subscribe requests (same customer + plan) | `create_subscription` runs in `transaction.atomic()` and starts with `Plan.objects.select_for_update()`, so the requests queue; the second sees the first's PENDING subscription and returns it. Backstop: **partial `UniqueConstraint(customer, plan) WHERE status IN (PENDING, ACTIVE, PAST_DUE)`** — if anything slips past, PostgreSQL rejects the INSERT and we return the existing one. Tested with 8 threads. |
| Same webhook received many times / at once | Unique idempotency key + payment row lock (above). Tested with 8 threads → exactly one `processed`. |
| Two workers processing the same payment with different events | `select_for_update(of=("self","subscription"))` serialises them; the loser sees a non-PENDING payment and no-ops. Tested. |
| Plan deactivated while a subscription is being created | Both operations lock the **same plan row** (`PATCH` does `select_for_update` before saving). Either the subscription commits first (and was valid at that moment), or deactivation commits first and the subscription sees `is_active=False` → 400 `plan_inactive`. Tested deterministically. |
| Expiry task vs. cancellation | Expiry is a conditional `UPDATE … WHERE id IN (…) AND status IN ('ACTIVE','PAST_DUE') AND end_date <= now`. PostgreSQL re-evaluates the WHERE after waiting on a row lock, so a row cancelled meanwhile is not overwritten. Batches of 500 keep locks short. Two Beat runs overlapping are harmless. Tested. |
| Duplicate sign-up | Case-insensitive unique index on email; `IntegrityError` → 409. |

Trade-off: locking the plan row serialises subscription *creation* per plan. Transactions are tiny (a few inserts), so throughput is fine for a marketplace; for very hot plans you could lock per customer instead and keep the partial unique index as the guarantee.

## 13. Database indexing decisions
| Table | Index | Query it serves |
|---|---|---|
| user | `UNIQUE(LOWER(email))`, `role` | login lookup, role filtering in admin |
| plan | `(is_active, created_at DESC)` | public plan list |
| plan | `(provider_id, created_at DESC)` | `?mine=true`, admin filter by provider |
| plan | `UNIQUE(provider_id, name)` | integrity: no duplicate names per provider |
| subscription | partial `UNIQUE(customer_id, plan_id) WHERE status IN (open)` | integrity + "does customer already have this plan?" |
| subscription | `(customer_id, status, created_at DESC)` | customer's list `?status=ACTIVE` ordered by newest |
| subscription | `(plan_id, status)` | provider's list (joins via plan) |
| subscription | partial `(end_date) WHERE status IN ('ACTIVE','PAST_DUE')` | expiry scan — small index, only rows that can expire |
| payment | `UNIQUE(reference)`, `UNIQUE(provider_reference)` | webhook lookup + integrity |
| payment | `(subscription_id, status)` | find pending payment for retry; prefetch |
| payment | `(status, created_at DESC)` | admin filtering |
| webhookevent | `UNIQUE(idempotency_key)`, `reference`, `received_at` | dedupe, audit search |

**Query optimisation for `GET /api/subscriptions/`:** `select_related("customer", "plan", "plan__provider")` pulls related rows through JOINs in the same query, and `prefetch_related(Prefetch("payments", …))` loads all payments for the page in **one** extra query. A page of 20 costs a constant ~3 queries (COUNT, page, payments) instead of 1 + 20×3. A test asserts this (`test_list_has_no_n_plus_one`). Admin list views use `list_select_related` for the same reason.

## 14. Caching strategy
* `GET /api/plans/` (public list) is cached in Redis for `PLAN_LIST_CACHE_TTL` (5 min). Each query string (page/filters) is a separate entry. Response header `X-Cache: HIT|MISS`.
* **Versioned keys:** `plans:list:v<N>:<query>`. Invalidation = `INCR plans:list:version` — one atomic O(1) Redis operation that makes every cached page stale at once (no `KEYS`/`SCAN` deletes). Old keys simply expire.
* Invalidation is triggered by `post_save`/`post_delete` signals on `Plan`, wrapped in `transaction.on_commit`, so it covers API, admin and shell changes and only fires after the change is really committed (avoids re-caching old data).
* Not cached: `?mine=true` (per-user, includes inactive) and detail views.

## 15. Assumptions & trade-offs
* Payment provider is simulated: no real checkout URL; `simulate_webhook` plays the gateway. Signatures follow the Paystack/Stripe style (HMAC-SHA256).
* "Active subscription" uniqueness also covers PENDING and PAST_DUE, so a customer can't open a second subscription while one is pending — the pending one is reused (and can get a new payment reference after a failure).
* Cancellation is immediate (status CANCELLED, `next_billing_date` cleared). "Cancel at period end" would be an easy extension.
* Recurring renewal charging is out of scope; `PAST_DUE` exists in the model and is treated as "open" and as expirable, ready for a renewal job.
* Plans with subscriptions can't be hard-deleted (`on_delete=PROTECT` keeps payment history) → 409, deactivate instead.
* Currency is a single setting (NGN by default); amount verification also checks currency when the gateway sends it.
* Provider listing of customers is done through `GET /api/subscriptions/` (scoped to the provider's plans) rather than a separate endpoint.

## Bonus items included
Docker Compose · OpenAPI/Swagger (`/api/docs/`) · structured JSON logging with request IDs (`X-Request-ID`) · unified error format + domain exceptions · service-layer architecture (`*/services.py`) · webhook HMAC signature verification · Celery retries with exponential backoff + jitter, `acks_late` · dead-letter table (`core.FailedTask`, in admin) for tasks that exhaust retries · health endpoint (`/api/health/`) · GitHub Actions CI (Postgres + Redis services, migration check, tests) · DB `CHECK`/`UNIQUE`/partial-unique constraints for every important rule.
