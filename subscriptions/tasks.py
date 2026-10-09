from celery import shared_task

from core.tasks import ReliableTask

from .services import expire_due_subscriptions


@shared_task(base=ReliableTask, name="subscriptions.tasks.expire_subscriptions")
def expire_subscriptions():
    """Run periodically by Celery Beat (see CELERY_BEAT_SCHEDULE). Safe to run concurrently."""
    return expire_due_subscriptions()
