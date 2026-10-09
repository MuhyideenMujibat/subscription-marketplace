import json
import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .gateway import SIGNATURE_HEADER, gateway
from .serializers import WebhookSerializer
from .services import process_webhook

logger = logging.getLogger(__name__)


@extend_schema(
    request=WebhookSerializer,
    parameters=[OpenApiParameter(SIGNATURE_HEADER, str, OpenApiParameter.HEADER, description="HMAC-SHA256 of raw body")],
    responses={200: dict, 400: dict, 401: dict, 404: dict},
)
@api_view(["POST"])
@authentication_classes([])  # the gateway is not a logged-in user...
@permission_classes([AllowAny])  # ...it proves who it is with the HMAC signature instead.
def payment_webhook(request):
    """POST /api/payments/webhook/ — called by the payment provider."""
    raw_body = request.body  # read BEFORE request.data so we sign the exact bytes received
    signature = request.headers.get(SIGNATURE_HEADER)
    if not gateway.verify_signature(raw_body, signature):
        logger.warning("webhook_bad_signature")
        return Response(
            {"error": {"code": "invalid_signature", "message": "Invalid webhook signature.", "details": {}}},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        raw_payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        raw_payload = {}
    serializer = WebhookSerializer(data=raw_payload)
    serializer.is_valid(raise_exception=True)

    result = process_webhook(serializer.validated_data, raw_payload)
    body = {"outcome": result.outcome, "message": result.message}
    if result.http_status >= 400:
        body = {"error": {"code": f"webhook_{result.outcome}", "message": result.message, "details": {}}}
    return Response(body, status=result.http_status)
