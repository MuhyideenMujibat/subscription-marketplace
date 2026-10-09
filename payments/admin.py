from django.contrib import admin

from .models import Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "provider", "amount", "currency", "status", "requires_refund", "created_at")
    list_filter = ("status", "requires_refund", "currency", "created_at", "subscription__plan__provider")
    search_fields = ("reference", "provider_reference", "subscription__customer__email", "subscription__plan__provider__email")
    date_hierarchy = "created_at"
    list_select_related = ("subscription__customer", "subscription__plan__provider")
    raw_id_fields = ("subscription",)
    readonly_fields = ("reference", "provider_reference", "paid_at", "notification_sent_at", "created_at", "updated_at")

    @admin.display(ordering="subscription__customer__email")
    def customer(self, obj):
        return obj.subscription.customer

    @admin.display(ordering="subscription__plan__provider__email")
    def provider(self, obj):
        return obj.subscription.plan.provider


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "reference", "provider_reference", "status", "message", "received_at")
    list_filter = ("status", "event_type", "received_at")
    search_fields = ("reference", "provider_reference", "idempotency_key")
    date_hierarchy = "received_at"
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]
