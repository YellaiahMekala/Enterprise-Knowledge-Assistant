"""A local stand-in for the Bedrock Converse API, for testing without an AWS account.

    python -m eka.tools.bedrock_stub --port 8765

Then run the core with
    EKA_CHAT_PROVIDER=bedrock  EKA_CHAT_MODEL=<any model id>  EKA_BEDROCK_REGION=us-east-1
    EKA_BEDROCK_ENDPOINT_URL=http://127.0.0.1:8765
    AWS_ACCESS_KEY_ID=fake  AWS_SECRET_ACCESS_KEY=fake

The core uses its real Bedrock adapter and boto3 unchanged: requests are signed, sent over HTTP and
parsed by botocore, including the binary event stream of ConverseStream. Only the answer is not
real: it comes from the offline extractive model. For real Bedrock, remove
EKA_BEDROCK_ENDPOINT_URL and the fake keys; no code changes.

The stub checks that a request is SigV4-signed for the bedrock service, not that the signature is
valid.
"""

import argparse
import json
import struct
import time
import zlib
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from eka.adapters.chat_fake import FakeChatModel
from eka.domain.models import ChatMessage

_model = FakeChatModel()


def _messages(body: dict[str, Any]) -> list[ChatMessage]:
    messages = [
        ChatMessage(role="system", content=part["text"])
        for part in body.get("system", [])
        if "text" in part
    ]
    for turn in body.get("messages", []):
        text = "\n".join(part["text"] for part in turn.get("content", []) if "text" in part)
        messages.append(ChatMessage(role=turn["role"], content=text))
    return messages


def _error(status: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"message": message}, status_code=status, headers={"x-amzn-ErrorType": kind}
    )


def _signed_for_bedrock(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.startswith("AWS4-HMAC-SHA256 ") and "/bedrock/aws4_request" in auth


def _max_tokens(body: dict[str, Any]) -> int:
    return int(body.get("inferenceConfig", {}).get("maxTokens", 600))


def _usage(body: dict[str, Any], answer: str) -> dict[str, int]:
    # Rough token counts (4 characters per token), so a report shows the field is filled in.
    prompt = sum(len(m.content) for m in _messages(body)) // 4
    completion = len(answer) // 4
    return {"inputTokens": prompt, "outputTokens": completion, "totalTokens": prompt + completion}


def event_message(event_type: str, payload: dict[str, Any]) -> bytes:
    """One message of the AWS event stream encoding: prelude, headers, payload, CRCs."""
    headers = b""
    for name, value in (
        (":event-type", event_type),
        (":content-type", "application/json"),
        (":message-type", "event"),
    ):
        raw_name, raw_value = name.encode(), value.encode()
        headers += struct.pack(">B", len(raw_name)) + raw_name
        headers += struct.pack(">BH", 7, len(raw_value)) + raw_value
    body = json.dumps(payload).encode()
    total = 12 + len(headers) + len(body) + 4
    prelude = struct.pack(">II", total, len(headers))
    prelude += struct.pack(">I", zlib.crc32(prelude))
    message = prelude + headers + body
    return message + struct.pack(">I", zlib.crc32(message))


def create_app() -> FastAPI:
    app = FastAPI(title="Bedrock Converse stub", docs_url=None, redoc_url=None)

    @app.post("/model/{model_id:path}/converse-stream")
    async def converse_stream(model_id: str, request: Request) -> Response:
        if not _signed_for_bedrock(request):
            return _error(403, "AccessDeniedException", "request is not signed for bedrock")
        body = await request.json()
        answer = await _model.complete(_messages(body), max_tokens=_max_tokens(body))
        started = time.monotonic()

        def events() -> Iterator[bytes]:
            yield event_message("messageStart", {"role": "assistant"})
            for word in answer.split(" "):
                delta = {"delta": {"text": word + " "}, "contentBlockIndex": 0}
                yield event_message("contentBlockDelta", delta)
            yield event_message("contentBlockStop", {"contentBlockIndex": 0})
            yield event_message("messageStop", {"stopReason": "end_turn"})
            latency = int((time.monotonic() - started) * 1000)
            meta = {"usage": _usage(body, answer), "metrics": {"latencyMs": latency}}
            yield event_message("metadata", meta)

        return StreamingResponse(events(), media_type="application/vnd.amazon.eventstream")

    @app.post("/model/{model_id:path}/converse")
    async def converse(model_id: str, request: Request) -> Response:
        if not _signed_for_bedrock(request):
            return _error(403, "AccessDeniedException", "request is not signed for bedrock")
        started = time.monotonic()
        body = await request.json()
        answer = await _model.complete(_messages(body), max_tokens=_max_tokens(body))
        return JSONResponse(
            {
                "output": {"message": {"role": "assistant", "content": [{"text": answer}]}},
                "stopReason": "end_turn",
                "usage": _usage(body, answer),
                "metrics": {"latencyMs": int((time.monotonic() - started) * 1000)},
            }
        )

    return app


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(prog="python -m eka.tools.bedrock_stub", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
