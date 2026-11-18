"""A scripted stand-in for the chat model, for drills that must not call a paid API.

Serves POST /v1/chat/completions. The first request of a conversation asks for the `runbook`
tool; once a tool result is in the messages it answers with a fixed triage JSON that quotes the
first line of that result. Usage: python fake_openai.py [port]. Stdlib only.
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


def _alert_name(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        text = str(message.get("content") or "")
        if message.get("role") == "user" and "Alerts firing now:" in text:
            return text.split("- ", 1)[1].split(" ", 1)[0]
    return "unknown"


def reply(body: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = body.get("messages", [])
    tool_results = [m for m in messages if m.get("role") == "tool"]
    if not tool_results:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "runbook",
                        "arguments": json.dumps({"alertName": _alert_name(messages)}),
                    },
                }
            ],
        }
        finish = "tool_calls"
    else:
        first_line = str(tool_results[-1].get("content", "")).strip().splitlines()[0][:120]
        triage = {
            "summary": f"Scripted triage of {_alert_name(messages)}.",
            "likelyCause": "Scripted model: no real analysis was done.",
            "evidence": [f"runbook: {first_line}"],
            "nextSteps": ["Follow the runbook section for this alert."],
        }
        message = {"role": "assistant", "content": json.dumps(triage)}
        finish = "stop"
    return {
        "id": "chatcmpl-scripted",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "scripted"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (name fixed by http.server)
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        payload = json.dumps(reply(body)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write("fake-model: " + (format % args) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
