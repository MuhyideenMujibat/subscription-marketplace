"""
Pretend to be the payment provider.

    python manage.py simulate_webhook PAY-XXXX               # print signed curl command
    python manage.py simulate_webhook PAY-XXXX --send        # POST it to the running server
    python manage.py simulate_webhook PAY-XXXX --event payment.failed --send
"""
import json
import urllib.error
import urllib.request
import uuid

from django.core.management.base import BaseCommand, CommandError

from payments.gateway import SIGNATURE_HEADER, gateway
from payments.models import Payment


class Command(BaseCommand):
    help = "Build (and optionally send) a signed payment webhook for a payment reference."

    def add_arguments(self, parser):
        parser.add_argument("reference")
        parser.add_argument("--event", default="payment.success", choices=["payment.success", "payment.failed"])
        parser.add_argument("--amount", help="Override the amount (to test mismatch).")
        parser.add_argument("--provider-reference", default=None)
        parser.add_argument("--url", default="http://127.0.0.1:8000/api/payments/webhook/")
        parser.add_argument("--send", action="store_true", help="Actually POST it to --url")

    def handle(self, *args, **opts):
        try:
            payment = Payment.objects.get(reference=opts["reference"])
        except Payment.DoesNotExist:
            raise CommandError("No payment with that reference.")

        payload = {
            "event": opts["event"],
            "reference": payment.reference,
            "provider_reference": opts["provider_reference"] or f"SIM-{uuid.uuid4().hex[:12].upper()}",
            "amount": opts["amount"] or str(payment.amount),
        }
        body = json.dumps(payload).encode()
        signature = gateway.sign(body)

        self.stdout.write(self.style.MIGRATE_HEADING("Payload:"))
        self.stdout.write(body.decode())
        self.stdout.write(self.style.MIGRATE_HEADING(f"{SIGNATURE_HEADER}:"))
        self.stdout.write(signature)
        self.stdout.write(self.style.MIGRATE_HEADING("curl:"))
        self.stdout.write(
            f"curl -X POST {opts['url']} -H 'Content-Type: application/json' "
            f"-H '{SIGNATURE_HEADER}: {signature}' -d '{body.decode()}'"
        )

        if opts["send"]:
            req = urllib.request.Request(
                opts["url"], data=body, method="POST",
                headers={"Content-Type": "application/json", SIGNATURE_HEADER: signature},
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    self.stdout.write(self.style.SUCCESS(f"{resp.status} {resp.read().decode()}"))
            except urllib.error.HTTPError as exc:
                self.stdout.write(self.style.ERROR(f"{exc.code} {exc.read().decode()}"))
