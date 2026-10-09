from django.db import models


class FailedTask(models.Model):
    """
    "Dead-letter" table: when a Celery task has used up all its retries,
    we store it here so an admin can see it and re-run it later.
    """

    task_name = models.CharField(max_length=255, db_index=True)
    task_id = models.CharField(max_length=255, unique=True)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    exception = models.TextField()
    traceback = models.TextField(blank=True)
    resolved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_name} [{self.task_id}]"
