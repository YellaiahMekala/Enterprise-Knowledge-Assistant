# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Process-wide logging: plain text for local runs, one JSON object per line in containers.

Records carry ``request_id`` and ``user_id`` from the request context. Logs hold ids only, never
document text, question text, keys or tokens.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from eka.request_context import current_context

_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s]: %(message)s"
# Extra fields the access log adds to a record; copied into the JSON object when present.
_EXTRA_FIELDS = ("method", "route", "status", "duration_ms")


class ContextFilter(logging.Filter):
    """Copies the current request context onto each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = current_context()
        record.request_id = ctx.request_id if ctx else "-"
        record.user_id = ctx.user_id if ctx else None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id and request_id != "-":
            entry["request_id"] = request_id
        user_id = getattr(record, "user_id", None)
        if user_id:
            entry["user_id"] = user_id
        for name in _EXTRA_FIELDS:
            if hasattr(record, name):
                entry[name] = getattr(record, name)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str, *, json_logs: bool) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter(_TEXT_FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn installs its own handlers before the app is created; route its records through ours.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # The request middleware writes the access log (with request id and route template), so
    # uvicorn's own access line would be a duplicate.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
