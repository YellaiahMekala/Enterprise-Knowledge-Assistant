"""The OpenAI-compatible adapter against a mocked transport: no network, no key."""

import json
from collections.abc import Callable

import httpx
import pytest

from eka.adapters.chat_fake import FakeChatModel
from eka.adapters.chat_openai import OpenAICompatibleChat
from eka.domain.errors import ModelTimeout, ModelUnavailable
from eka.domain.models import ChatMessage

KEY = "sk-test-secret-key-value"
MESSAGES = [ChatMessage("system", "rules"), ChatMessage("user", "question")]


def sse(*fragments: str, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': f}}]})}\n\n" for f in fragments]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


class Harness:
    def __init__(
        self, handler: Callable[[httpx.Request], httpx.Response], retries: int = 2
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

        def recording(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        self.model = OpenAICompatibleChat(
            base_url="https://llm.example/v1/",
            api_key=KEY,
            model="some-model",
            timeout_seconds=5,
            retries=retries,
            client=httpx.AsyncClient(transport=httpx.MockTransport(recording)),
            sleep=sleep,
        )


@pytest.mark.anyio
async def test_complete_sends_the_documented_request_and_returns_the_text() -> None:
    harness = Harness(lambda request: reply("hello [1]"))
    assert await harness.model.complete(MESSAGES, max_tokens=50) == "hello [1]"
    request = harness.requests[0]
    assert str(request.url) == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "some-model" and body["max_tokens"] == 50
    assert body["temperature"] == 0 and body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]


@pytest.mark.anyio
async def test_rate_limits_and_server_errors_are_retried_with_backoff() -> None:
    answers = iter([httpx.Response(429), httpx.Response(503), reply("ok")])
    harness = Harness(lambda request: next(answers))
    assert await harness.model.complete(MESSAGES, max_tokens=5) == "ok"
    assert len(harness.requests) == 3 and harness.sleeps == [0.5, 1.0]


@pytest.mark.anyio
async def test_retries_are_bounded() -> None:
    harness = Harness(lambda request: httpx.Response(500), retries=2)
    with pytest.raises(ModelUnavailable):
        await harness.model.complete(MESSAGES, max_tokens=5)
    assert len(harness.requests) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_client_errors_are_not_retried(status: int) -> None:
    harness = Harness(lambda request: httpx.Response(status, text=f"secret detail {KEY}"))
    with pytest.raises(ModelUnavailable) as caught:
        await harness.model.complete(MESSAGES, max_tokens=5)
    assert len(harness.requests) == 1 and harness.sleeps == []
    assert KEY not in str(caught.value) and "secret detail" not in str(caught.value)


@pytest.mark.anyio
async def test_a_timeout_is_reported_as_a_timeout_and_not_retried() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    harness = Harness(slow)
    with pytest.raises(ModelTimeout):
        await harness.model.complete(MESSAGES, max_tokens=5)
    assert len(harness.requests) == 1


@pytest.mark.anyio
async def test_a_connection_failure_is_retried_then_reported() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    harness = Harness(refuse, retries=1)
    with pytest.raises(ModelUnavailable):
        await harness.model.complete(MESSAGES, max_tokens=5)
    assert len(harness.requests) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 5}}]},
    ],
)
async def test_an_unexpected_reply_shape_is_an_error(payload: dict[str, object]) -> None:
    harness = Harness(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ModelUnavailable):
        await harness.model.complete(MESSAGES, max_tokens=5)


@pytest.mark.anyio
async def test_stream_yields_fragments_in_order_and_asks_for_streaming() -> None:
    harness = Harness(lambda request: httpx.Response(200, content=sse("Hel", "lo ", "[1]")))
    fragments = [f async for f in harness.model.stream(MESSAGES, max_tokens=5)]
    assert fragments == ["Hel", "lo ", "[1]"]
    assert json.loads(harness.requests[0].content)["stream"] is True


@pytest.mark.anyio
async def test_stream_skips_comments_empty_deltas_and_stops_at_done() -> None:
    body = (
        b": keep-alive\n\n"
        b'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n'
        + sse("a", "b")
        + b'data: {"choices": [{"delta": {"content": "after done"}}]}\n\n'
    )
    harness = Harness(lambda request: httpx.Response(200, content=body))
    assert [f async for f in harness.model.stream(MESSAGES, max_tokens=5)] == ["a", "b"]


@pytest.mark.anyio
async def test_stream_retries_before_the_first_text_only() -> None:
    answers = iter([httpx.Response(502), httpx.Response(200, content=sse("ok"))])
    harness = Harness(lambda request: next(answers))
    assert [f async for f in harness.model.stream(MESSAGES, max_tokens=5)] == ["ok"]
    assert len(harness.requests) == 2


@pytest.mark.anyio
async def test_stream_errors_do_not_leak_the_response_body() -> None:
    harness = Harness(lambda request: httpx.Response(401, text=f"bad key {KEY}"))
    with pytest.raises(ModelUnavailable) as caught:
        [f async for f in harness.model.stream(MESSAGES, max_tokens=5)]
    assert KEY not in str(caught.value)


@pytest.mark.anyio
async def test_a_malformed_stream_line_is_an_error() -> None:
    harness = Harness(lambda request: httpx.Response(200, content=b"data: {not json}\n\n"))
    with pytest.raises(ModelUnavailable):
        [f async for f in harness.model.stream(MESSAGES, max_tokens=5)]


class _Tracked(httpx.AsyncByteStream):
    closed = False

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield sse("one ", done=False)
        yield sse("two ", done=False)
        yield sse("three", done=True)

    async def aclose(self) -> None:
        _Tracked.closed = True


@pytest.mark.anyio
async def test_closing_the_stream_closes_the_provider_response() -> None:
    _Tracked.closed = False
    harness = Harness(lambda request: httpx.Response(200, stream=_Tracked()))
    stream = harness.model.stream(MESSAGES, max_tokens=5)
    assert await anext(stream) == "one "
    await stream.aclose()
    assert _Tracked.closed


@pytest.mark.anyio
async def test_the_fake_model_extracts_the_best_sentence_with_its_number() -> None:
    user = (
        "Passages:\n"
        '<passage n="1" source="a.md" location="page 1">\nThe canteen opens at noon.\n</passage>\n'
        '<passage n="2" source="b.md" location="page 1">\n'
        "Staff may carry over five leave days. Other text.\n</passage>\n\n"
        "Question: how many leave days can staff carry over?"
    )
    model = FakeChatModel()
    messages = [ChatMessage("system", "rules"), ChatMessage("user", user)]
    assert (
        await model.complete(messages, max_tokens=50) == "Staff may carry over five leave days. [2]"
    )
    streamed = "".join([f async for f in model.stream(messages, max_tokens=50)])
    assert streamed.strip() == "Staff may carry over five leave days. [2]"


@pytest.mark.anyio
async def test_the_fake_model_declines_without_a_matching_passage() -> None:
    user = (
        'Passages:\n<passage n="1" source="a.md" location="page 1">\nThe canteen opens.\n</passage>'
        "\n\nQuestion: quantum chromodynamics?"
    )
    reply_text = await FakeChatModel().complete(
        [ChatMessage("system", "rules"), ChatMessage("user", user)], max_tokens=5
    )
    assert reply_text == "INSUFFICIENT_EVIDENCE"
