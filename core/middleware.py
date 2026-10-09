"""Attaches a request id to every request (and its log lines) for tracing."""
import contextvars
import uuid

_request_id = contextvars.ContextVar("request_id", default=None)


def get_request_id():
    return _request_id.get()


class RequestIDMiddleware:
    header = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get(self.header) or uuid.uuid4().hex
        token = _request_id.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            _request_id.reset(token)
        response["X-Request-ID"] = request_id
        return response
