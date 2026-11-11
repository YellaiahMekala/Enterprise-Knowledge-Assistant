"""The real Bedrock adapter and boto3 against the local Converse stand-in, with fake AWS keys.

These tests cover what the stub-client tests cannot: SigV4 signing, the HTTP request botocore
builds, JSON parsing of Converse, and decoding of the binary ConverseStream event stream.
"""

import asyncio
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from botocore.eventstream import EventStreamBuffer

from eka.adapters.chat_bedrock import BedrockChat
from eka.domain.errors import ModelUnavailable
from eka.domain.models import ChatMessage
from eka.tools.bedrock_stub import create_app, event_message
from tests.helpers import make_settings

MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
PROMPT = [
    ChatMessage("system", "Answer only from the passages and cite them."),
    ChatMessage(
        "user",
        '<passage n="1" source="leave.md">\nStaff get 24 days of annual leave.\n</passage>\n'
        '<passage n="2" source="vpn.md">\nThe VPN needs a hardware token.\n</passage>\n\n'
        "Question: How many days of annual leave do staff get?",
    ),
]


@pytest.fixture(scope="module")
def stub_url() -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("stub did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def fake_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def bedrock(url: str) -> BedrockChat:
    return BedrockChat(model_id=MODEL, region="us-east-1", endpoint_url=url, retries=0)


@pytest.mark.usefixtures("fake_aws")
def test_converse_through_boto3_returns_the_answer_with_its_citation(stub_url: str) -> None:
    text = asyncio.run(bedrock(stub_url).complete(PROMPT, max_tokens=100))

    assert text == "Staff get 24 days of annual leave. [1]"


@pytest.mark.usefixtures("fake_aws")
def test_converse_stream_is_decoded_by_botocore(stub_url: str) -> None:
    async def collect() -> list[str]:
        return [part async for part in bedrock(stub_url).stream(PROMPT, max_tokens=100)]

    parts = asyncio.run(collect())

    assert len(parts) > 1
    assert "".join(parts).strip() == "Staff get 24 days of annual leave. [1]"


def test_unsigned_request_is_refused(stub_url: str) -> None:
    response = httpx.post(f"{stub_url}/model/{MODEL}/converse", json={"messages": []})

    assert response.status_code == 403
    assert response.headers["x-amzn-ErrorType"] == "AccessDeniedException"


@pytest.mark.usefixtures("fake_aws")
def test_unreachable_endpoint_is_a_model_error_not_a_crash() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # closed again, so nothing listens here

    with pytest.raises(ModelUnavailable):
        asyncio.run(bedrock(f"http://127.0.0.1:{port}").complete(PROMPT, max_tokens=10))


def test_event_message_round_trips_through_the_botocore_decoder() -> None:
    buffer = EventStreamBuffer()
    buffer.add_data(event_message("contentBlockDelta", {"delta": {"text": "hi"}}))

    (message,) = list(buffer)

    assert message.headers[":event-type"] == "contentBlockDelta"
    assert message.payload == b'{"delta": {"text": "hi"}}'


def test_endpoint_setting_is_optional_and_empty_means_real_aws() -> None:
    assert make_settings(bedrock_endpoint_url="").bedrock_endpoint_url is None
    assert (
        make_settings(bedrock_endpoint_url="http://127.0.0.1:8765").bedrock_endpoint_url
        == "http://127.0.0.1:8765"
    )
