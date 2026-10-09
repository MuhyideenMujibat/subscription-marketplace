from django.contrib import admin

from .models import Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "price", "currency", "billing_interval", "is_active", "created_at")
    list_filter = ("is_active", "billing_interval", "created_at", "provider")
    search_fields = ("name", "provider__email")
    date_hierarchy = "created_at"
    list_select_related = ("provider",)
    autocomplete_fields = ("provider",)
