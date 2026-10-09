from django.contrib import admin

from .models import FailedTask


@admin.register(FailedTask)
class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ("task_name", "task_id", "resolved", "created_at")
    list_filter = ("resolved", "task_name", "created_at")
    search_fields = ("task_name", "task_id", "exception")
    readonly_fields = ("task_name", "task_id", "args", "kwargs", "exception", "traceback", "created_at")
