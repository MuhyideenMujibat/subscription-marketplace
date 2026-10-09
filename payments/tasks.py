import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.tasks import ReliableTask

from .models import Payment

logger = logging.getLogger(__name__)


@shared_task(base=ReliableTask, name="payments.tasks.send_payment_success_email")
def send_payment_success_email(payment_id):
    """
    Simulated email (console backend prints it). Idempotent: if Celery delivers the
    task twice (acks_late + worker crash), `notification_sent_at` stops a 2nd email.
    """
    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .select_related("subscription__customer", "subscription__plan")
            .get(pk=payment_id)
        )
        if payment.notification_sent_at:
            logger.info("payment_email_already_sent", extra={"payment_id": payment_id})
            return "skipped"
        sub = payment.subscription
        send_mail(
            subject="Your subscription is active",
            message=(
                f"Hi {sub.customer.email},\n\n"
                f"We received your payment of {payment.currency} {payment.amount} "
                f"(ref {payment.reference}).\nYour '{sub.plan.name}' subscription is active "
                f"until {sub.end_date:%Y-%m-%d}.\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[sub.customer.email],
        )
        payment.notification_sent_at = timezone.now()
        payment.save(update_fields=["notification_sent_at", "updated_at"])
    logger.info("payment_email_sent", extra={"payment_id": payment_id})
    return "sent"
