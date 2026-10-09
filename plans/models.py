from django.conf import settings
from django.db import models


class Plan(models.Model):
    class BillingInterval(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        YEARLY = "YEARLY", "Yearly"

    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="plans",
        limit_choices_to={"role": "PROVIDER"},
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    billing_interval = models.CharField(max_length=10, choices=BillingInterval.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="plan_price_positive"),
            models.CheckConstraint(
                condition=models.Q(billing_interval__in=["MONTHLY", "YEARLY"]),
                name="plan_billing_interval_valid",
            ),
            # A provider can't have two plans with the same name.
            models.UniqueConstraint(fields=["provider", "name"], name="uniq_plan_name_per_provider"),
        ]
        indexes = [
            # Public listing: WHERE is_active = true ORDER BY created_at DESC
            models.Index(fields=["is_active", "-created_at"], name="plan_active_created_idx"),
            # Provider's own plans: WHERE provider_id = ? ORDER BY created_at DESC
            models.Index(fields=["provider", "-created_at"], name="plan_provider_created_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_billing_interval_display()}) - {self.provider}"
