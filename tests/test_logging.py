import json
import logging
import sys

from eka.logging_config import ContextFilter, JsonFormatter
from eka.request_context import RequestContext, _current


def test_json_formatter_writes_one_parseable_object() -> None:
    record = logging.LogRecord("eka.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "eka.test"
    assert "request_id" not in entry


def test_json_formatter_includes_exception_details() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "eka.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )
    entry = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in entry["exception"]


def test_context_fields_appear_in_json_logs() -> None:
    token = _current.set(RequestContext(request_id="abc123", user_id="alice"))
    try:
        record = logging.LogRecord("eka.test", logging.INFO, __file__, 1, "msg", (), None)
        ContextFilter().filter(record)
    finally:
        _current.reset(token)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["request_id"] == "abc123"
    assert entry["user_id"] == "alice"


def test_access_fields_appear_in_json_logs() -> None:
    record = logging.LogRecord("eka.access", logging.INFO, __file__, 1, "GET /x 200", (), None)
    record.route, record.status, record.duration_ms = "/x", 200, 1.5
    entry = json.loads(JsonFormatter().format(record))
    assert (entry["route"], entry["status"], entry["duration_ms"]) == ("/x", 200, 1.5)


def test_outside_a_request_the_filter_marks_the_id_as_absent() -> None:
    record = logging.LogRecord("eka.test", logging.INFO, __file__, 1, "msg", (), None)
    ContextFilter().filter(record)
    assert record.request_id == "-"  # type: ignore[attr-defined]
    assert record.user_id is None  # type: ignore[attr-defined]
