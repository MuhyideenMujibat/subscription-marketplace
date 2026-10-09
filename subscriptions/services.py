"""
Subscription business logic (service layer).

Views stay thin: they validate input and call these functions. All the
transaction / locking rules live here, in one place.
"""
import logging

from dateutil.relativedelta import relativedelta
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.exceptions import Conflict, DomainError, NotFound
from payments.gateway import gateway
from payments.models import Payment
from plans.models import Plan

from .models import Subscription

logger = logging.getLogger(__name__)


class PlanInactive(DomainError):
    code = "plan_inactive"
    message = "This plan is not accepting new subscriptions."


class AlreadySubscribed(Conflict):
    code = "already_subscribed"
    message = "You already have an active subscription to this plan."


class InvalidSubscriptionState(DomainError):
    code = "invalid_subscription_state"


def _pending_result(subscription, payment, created):
    return {"subscription": subscription, "payment": payment, "created": created}


def create_subscription(*, customer, plan_id):
    """
    Create a PENDING subscription + PENDING payment and return the payment reference.

    Concurrency:
      1. `SELECT ... FOR UPDATE` on the plan row. Plan deactivation (PATCH) takes the
         same lock, so we either see the plan before deactivation (and finish first)
         or after it (and reject). Two subscribe requests for the same plan also queue
         up here, so the second one sees the first one's subscription.
      2. The partial UniqueConstraint on (customer, plan) for open statuses is the
         final safety net: if anything slips through, the DB rejects the duplicate.

    Idempotency for double-clicks: if the customer already has a PENDING subscription
    for this plan, we return it (and its pending payment) instead of creating another.
    """
    try:
        with transaction.atomic():
            try:
                plan = Plan.objects.select_for_update().get(pk=plan_id)
            except Plan.DoesNotExist:
                raise NotFound("Plan not found.", code="plan_not_found")
            if not plan.is_active:
                raise PlanInactive()

            existing = (
                Subscription.objects.select_for_update()
                .filter(customer=customer, plan=plan, status__in=Subscription.OPEN_STATUSES)
                .first()
            )
            if existing:
                if existing.status != Subscription.Status.PENDING:
                    raise AlreadySubscribed()
                payment = existing.payments.filter(status=Payment.Status.PENDING).order_by("-created_at").first()
                if payment is None:
                    payment = _create_payment(existing, plan)
                return _pending_result(existing, payment, created=False)

            subscription = Subscription.objects.create(
                customer=customer, plan=plan, status=Subscription.Status.PENDING
            )
            payment = _create_payment(subscription, plan)
    except IntegrityError:
        # Lost a race with an identical request; the DB constraint caught it.
        existing = (
            Subscription.objects.filter(customer=customer, plan_id=plan_id, status__in=Subscription.OPEN_STATUSES)
            .select_related("plan")
            .first()
        )
        if existing and existing.status == Subscription.Status.PENDING:
            payment = existing.payments.filter(status=Payment.Status.PENDING).order_by("-created_at").first()
            return _pending_result(existing, payment, created=False)
        raise AlreadySubscribed()

    logger.info(
        "subscription_created",
        extra={"subscription_id": subscription.id, "payment_reference": payment.reference, "customer_id": customer.id},
    )
    return _pending_result(subscription, payment, created=True)


def _create_payment(subscription, plan):
    # Amount is copied from the plan NOW, so later price changes don't affect this payment.
    return Payment.objects.create(
        subscription=subscription,
        reference=gateway.new_reference(),
        amount=plan.price,
        currency=plan.currency,
        status=Payment.Status.PENDING,
    )


def compute_period(start, billing_interval):
    if billing_interval == Plan.BillingInterval.YEARLY:
        return start + relativedelta(years=1)
    return start + relativedelta(months=1)


def activate_subscription(subscription, *, now=None):
    """
    Called by the payment webhook (inside its transaction, with the subscription row
    already locked). Returns True if the subscription was activated.
    """
    now = now or timezone.now()
    if subscription.status != Subscription.Status.PENDING:
        # e.g. the customer cancelled while the payment was in flight.
        logger.warning(
            "payment_succeeded_for_non_pending_subscription",
            extra={"subscription_id": subscription.id, "status": subscription.status},
        )
        return False
    end = compute_period(now, subscription.plan.billing_interval)
    subscription.status = Subscription.Status.ACTIVE
    subscription.start_date = now
    subscription.end_date = end
    subscription.next_billing_date = end
    subscription.save(update_fields=["status", "start_date", "end_date", "next_billing_date", "updated_at"])
    return True


def cancel_subscription(*, subscription_id, user):
    with transaction.atomic():
        try:
            sub = Subscription.objects.select_for_update().get(pk=subscription_id)
        except Subscription.DoesNotExist:
            raise NotFound("Subscription not found.")
        if sub.customer_id != user.id and not user.is_admin_role:
            raise NotFound("Subscription not found.")  # don't leak existence
        if sub.status not in Subscription.OPEN_STATUSES:
            raise InvalidSubscriptionState(f"A {sub.status} subscription cannot be cancelled.")
        sub.status = Subscription.Status.CANCELLED
        sub.cancelled_at = timezone.now()
        sub.next_billing_date = None
        sub.save(update_fields=["status", "cancelled_at", "next_billing_date", "updated_at"])
    logger.info("subscription_cancelled", extra={"subscription_id": sub.id})
    return sub


def expire_due_subscriptions(*, now=None, batch_size=500):
    """
    Mark ACTIVE / PAST_DUE subscriptions whose end_date has passed as EXPIRED.

    Uses a conditional bulk UPDATE (`WHERE id IN (...) AND status IN (...)`).
    PostgreSQL re-checks the WHERE clause after waiting on any row lock, so a
    subscription that was cancelled at the same moment is NOT overwritten.
    Batching keeps each transaction (and its locks) short.
    """
    now = now or timezone.now()
    total = 0
    while True:
        ids = list(
            Subscription.objects.filter(status__in=[Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE], end_date__lte=now)
            .values_list("id", flat=True)[:batch_size]
        )
        if not ids:
            break
        updated = Subscription.objects.filter(
            id__in=ids,
            status__in=[Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE],
            end_date__lte=now,
        ).update(status=Subscription.Status.EXPIRED, next_billing_date=None, updated_at=now)
        total += updated
        if len(ids) < batch_size:
            break
    if total:
        logger.info("subscriptions_expired", extra={"count": total})
    return total
