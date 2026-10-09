from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    reference = models.CharField(max_length=64, unique=True)  # our reference, sent to the gateway
    subscription = models.ForeignKey(
        "subscriptions.Subscription", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # The gateway's own id for the charge (e.g. "STRIPE-123456"). Unique when present,
    # so the same gateway charge can never be applied to two payments.
    provider_reference = models.CharField(max_length=128, null=True, blank=True, unique=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Payment succeeded but the subscription was already cancelled -> money must go back.
    requires_refund = models.BooleanField(default=False)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
            models.CheckConstraint(
                condition=models.Q(status__in=["PENDING", "SUCCEEDED", "FAILED"]), name="payment_status_valid"
            ),
            # A succeeded payment must record when it was paid.
            models.CheckConstraint(
                condition=~models.Q(status="SUCCEEDED") | models.Q(paid_at__isnull=False),
                name="succeeded_payment_has_paid_at",
            ),
            # At most ONE successful payment per subscription (no double charge applied).
            models.UniqueConstraint(
                fields=["subscription"],
                condition=models.Q(status="SUCCEEDED"),
                name="uniq_succeeded_payment_per_subscription",
            ),
        ]
        indexes = [
            models.Index(fields=["subscription", "status"], name="payment_sub_status_idx"),
            models.Index(fields=["status", "-created_at"], name="payment_status_created_idx"),
        ]

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency} [{self.status}]"


class WebhookEvent(models.Model):
    """
    Every webhook we receive is stored here (audit log + idempotency).
    `idempotency_key` is UNIQUE, so the same event can only be recorded once.
    """

    class Status(models.TextChoices):
        PROCESSED = "PROCESSED", "Processed"
        REJECTED = "REJECTED", "Rejected"

    idempotency_key = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=50)
    reference = models.CharField(max_length=64, db_index=True)
    provider_reference = models.CharField(max_length=128, blank=True)
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices)
    message = models.CharField(max_length=255, blank=True)
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="webhook_events")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} {self.reference} [{self.status}]"
