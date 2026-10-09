from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Provider, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("email", "role", "is_active", "is_staff", "date_joined")
    list_filter = ("role", "is_active", "is_staff", "date_joined")
    search_fields = ("email", "first_name", "last_name")
    date_hierarchy = "date_joined"
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("first_name", "last_name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "role", "password1", "password2")}),
    )


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "last_name", "plan_count", "is_active", "date_joined")
    list_filter = ("is_active", "date_joined")
    search_fields = ("email", "first_name", "last_name")
    date_hierarchy = "date_joined"
    readonly_fields = ("email", "date_joined", "last_login")
    fields = ("email", "first_name", "last_name", "is_active", "date_joined", "last_login")

    def get_queryset(self, request):
        from django.db.models import Count

        return super().get_queryset(request).annotate(_plan_count=Count("plans"))

    @admin.display(ordering="_plan_count", description="Plans")
    def plan_count(self, obj):
        return obj._plan_count

    def has_add_permission(self, request):
        return False  # providers sign up through the API
