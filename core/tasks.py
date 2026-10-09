"""Shared Celery task base with retries + dead-letter handling."""
import logging

from celery import Task

logger = logging.getLogger(__name__)


class ReliableTask(Task):
    """
    Base class for our tasks:
    * retries automatically with exponential backoff + jitter,
    * when retries are exhausted, records the task in `FailedTask` (dead-letter).
    """

    abstract = True
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 5

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        from core.models import FailedTask

        logger.error(
            "task_failed_permanently",
            extra={"task": self.name, "task_id": task_id, "error": repr(exc)},
        )
        try:
            FailedTask.objects.update_or_create(
                task_id=task_id,
                defaults={
                    "task_name": self.name,
                    "args": list(args),
                    "kwargs": dict(kwargs),
                    "exception": repr(exc),
                    "traceback": str(einfo),
                },
            )
        except Exception:  # noqa: BLE001 - never let DLQ bookkeeping crash the worker
            logger.exception("failed_to_record_dead_letter")
        super().on_failure(exc, task_id, args, kwargs, einfo)
