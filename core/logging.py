"""Structured JSON logging. Each log line is one JSON object (easy to ship to ELK/Datadog/Loki)."""
import json
import logging
from datetime import datetime, timezone

from core.middleware import get_request_id

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class RequestIDFilter(logging.Filter):
    def filter(self, record):
        record.request_id = get_request_id()
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Anything passed via `extra={...}` becomes a top-level JSON field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
