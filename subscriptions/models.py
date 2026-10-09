from django.conf import settings
from django.db import models


class Subscription(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        PAST_DUE = "PAST_DUE", "Past due"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired"

    # Statuses that count as "the customer already has this plan".
    OPEN_STATUSES = (Status.PENDING, Status.ACTIVE, Status.PAST_DUE)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="subscriptions"
    )
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    next_billing_date = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # THE key integrity rule, enforced by PostgreSQL itself (partial unique index):
            # one customer can have at most ONE open (pending/active/past-due)
            # subscription per plan. Even if two requests race past the
            # application checks, the second INSERT fails.
            models.UniqueConstraint(
                fields=["customer", "plan"],
                condition=models.Q(status__in=["PENDING", "ACTIVE", "PAST_DUE"]),
                name="uniq_open_subscription_per_customer_plan",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["PENDING", "ACTIVE", "PAST_DUE", "CANCELLED", "EXPIRED"]),
                name="subscription_status_valid",
            ),
            # An active subscription must have its dates set.
            models.CheckConstraint(
                condition=~models.Q(status="ACTIVE")
                | models.Q(start_date__isnull=False, end_date__isnull=False),
                name="active_subscription_has_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(start_date__isnull=True)
                | models.Q(end_date__gt=models.F("start_date")),
                name="subscription_end_after_start",
            ),
        ]
        indexes = [
            # Customer's list filtered by status: WHERE customer_id=? AND status=?
            models.Index(fields=["customer", "status", "-created_at"], name="sub_customer_status_idx"),
            # Provider's view goes through plan: WHERE plan_id IN (...) AND status=?
            models.Index(fields=["plan", "status"], name="sub_plan_status_idx"),
            # Expiry task: WHERE status='ACTIVE' AND end_date <= now()
            models.Index(
                fields=["end_date"],
                condition=models.Q(status__in=["ACTIVE", "PAST_DUE"]),
                name="sub_expiry_scan_idx",
            ),
        ]

    def __str__(self):
        return f"Subscription #{self.pk} {self.customer} -> {self.plan.name} [{self.status}]"
