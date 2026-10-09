"""
Error handling strategy
-----------------------
* Business-rule violations are raised from the service layer as `DomainError`
  subclasses (they know their HTTP status and a machine-readable code).
* Every error response has the same shape:

    {"error": {"code": "plan_inactive", "message": "...", "details": {...}}}
"""
import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class DomainError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "domain_error"
    message = "The request could not be completed."

    def __init__(self, message=None, *, code=None, details=None):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)


class NotFound(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Conflict(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            status=exc.status_code,
        )

    response = exception_handler(exc, context)
    if response is None:
        # Unhandled exception -> let Django log it and return a 500.
        logger.exception("unhandled_exception", extra={"view": str(context.get("view"))})
        return None

    code = getattr(exc, "default_code", "error")
    if isinstance(exc, APIException) and isinstance(response.data, dict) and "detail" in response.data:
        message = str(response.data["detail"])
        details = {}
    else:
        message = "Invalid input." if response.status_code == 400 else "Request failed."
        details = response.data
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
