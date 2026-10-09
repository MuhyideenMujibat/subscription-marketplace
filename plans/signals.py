"""
Invalidate the plan-list cache whenever a plan changes — from the API, the
Django admin, or a shell. `on_commit` makes sure we only invalidate after the
change is really saved (otherwise a reader could re-cache the old data).
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import invalidate_plan_list_cache
from .models import Plan


@receiver(post_save, sender=Plan)
@receiver(post_delete, sender=Plan)
def plan_changed(sender, **kwargs):
    transaction.on_commit(invalidate_plan_list_cache)
