from django.contrib import admin

from payments.models import Payment

from .models import Subscription


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    fields = ("reference", "amount", "currency", "status", "provider_reference", "created_at")
    readonly_fields = fields


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "plan", "provider", "status", "start_date", "end_date", "created_at")
    list_filter = ("status", "created_at", "plan__provider", "plan__billing_interval")
    search_fields = ("customer__email", "plan__name", "plan__provider__email", "payments__reference")
    date_hierarchy = "created_at"
    list_select_related = ("customer", "plan", "plan__provider")
    raw_id_fields = ("customer", "plan")
    inlines = [PaymentInline]

    @admin.display(ordering="plan__provider__email")
    def provider(self, obj):
        return obj.plan.provider
