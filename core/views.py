from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(responses={200: dict, 503: dict})
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Liveness/readiness probe: checks the database and Redis."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "error"
    try:
        cache.set("healthcheck", "ok", 5)
        checks["cache"] = "ok" if cache.get("healthcheck") == "ok" else "error"
    except Exception:  # noqa: BLE001
        checks["cache"] = "error"
    healthy = all(v == "ok" for v in checks.values())
    return Response({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)
