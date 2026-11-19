# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Bedrock chat adapter against a stub client: request shape, streaming, errors, settings."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

from eka.adapters.chat_bedrock import BedrockChat
from eka.domain.errors import ModelTimeout, ModelUnavailable
from eka.domain.models import ChatMessage
from tests.helpers import make_settings

T = TypeVar("T")
MODEL = "anthropic.claude-3-haiku-20240307-v1:0"


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


class StubStream:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.closed = False

    def __iter__(self) -> Any:
        return iter(self._events)

    def close(self) -> None:
        self.closed = True


class StubClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply: dict[str, Any] = {"output": {"message": {"content": [{"text": "Hello [1]"}]}}}
        self.events: list[dict[str, Any]] = []
        self.stream_handle: StubStream | None = None
        self.error: Exception | None = None

    def converse(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.reply

    def converse_stream(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if self.error:
            raise self.error
        self.stream_handle = StubStream(self.events)
        return {"stream": self.stream_handle}


def chat(client: StubClient) -> BedrockChat:
    return BedrockChat(model_id=MODEL, client=client)


MESSAGES = [
    ChatMessage("system", "Answer from the passages."),
    ChatMessage("user", "How many days of leave?"),
]


def test_complete_sends_system_text_apart_from_the_turns() -> None:
    client = StubClient()

    text = run(chat(client).complete(MESSAGES, max_tokens=200))

    assert text == "Hello [1]"
    request = client.requests[0]
    assert request["modelId"] == MODEL
    assert request["system"] == [{"text": "Answer from the passages."}]
    assert request["messages"] == [
        {"role": "user", "content": [{"text": "How many days of leave?"}]}
    ]
    assert request["inferenceConfig"] == {"maxTokens": 200, "temperature": 0}


def test_consecutive_turns_by_one_role_are_merged() -> None:
    client = StubClient()
    messages = [
        ChatMessage("user", "first"),
        ChatMessage("user", "second"),
        ChatMessage("assistant", "reply"),
        ChatMessage("user", "third"),
    ]

    run(chat(client).complete(messages, max_tokens=50))

    turns = client.requests[0]["messages"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == [{"text": "first"}, {"text": "second"}]


def test_a_request_without_a_first_user_message_is_refused_before_any_call() -> None:
    client = StubClient()

    with pytest.raises(ModelUnavailable):
        run(chat(client).complete([ChatMessage("assistant", "hi")], max_tokens=50))
    assert client.requests == []


def test_stream_yields_the_text_deltas_in_order_and_closes_the_stream() -> None:
    client = StubClient()
    client.events = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": "24 days"}}},
        {"contentBlockDelta": {"delta": {"text": " [1]"}}},
        {"metadata": {"usage": {"inputTokens": 10}}},
    ]

    async def collect() -> list[str]:
        return [fragment async for fragment in chat(client).stream(MESSAGES, max_tokens=50)]

    assert run(collect()) == ["24 days", " [1]"]
    assert client.stream_handle is not None and client.stream_handle.closed


def test_closing_the_stream_early_still_closes_the_provider_stream() -> None:
    client = StubClient()
    client.events = [{"contentBlockDelta": {"delta": {"text": f"t{i}"}}} for i in range(5)]

    async def take_one() -> str:
        generator = chat(client).stream(MESSAGES, max_tokens=50)
        first = await anext(generator)
        await generator.aclose()
        return first

    assert run(take_one()) == "t0"
    assert client.stream_handle is not None and client.stream_handle.closed


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ReadTimeoutError(endpoint_url="https://bedrock"), ModelTimeout),
        (ClientError({"Error": {"Code": "ModelTimeoutException"}}, "Converse"), ModelTimeout),
        (ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse"), ModelUnavailable),
        (ClientError({"Error": {"Code": "AccessDeniedException"}}, "Converse"), ModelUnavailable),
        (EndpointConnectionError(endpoint_url="https://bedrock"), ModelUnavailable),
    ],
)
def test_provider_errors_become_the_ports_two_error_types(
    error: Exception, expected: type[Exception]
) -> None:
    client = StubClient()
    client.error = error

    with pytest.raises(expected):
        run(chat(client).complete(MESSAGES, max_tokens=50))

    async def consume() -> None:
        async for _ in chat(client).stream(MESSAGES, max_tokens=50):
            pass

    with pytest.raises(expected):
        run(consume())


def test_an_unexpected_reply_shape_is_unavailable() -> None:
    client = StubClient()
    client.reply = {"output": {}}

    with pytest.raises(ModelUnavailable):
        run(chat(client).complete(MESSAGES, max_tokens=50))


def test_the_error_message_does_not_carry_the_provider_body() -> None:
    client = StubClient()
    client.error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "secret arn:aws:iam::123"}},
        "Converse",
    )

    with pytest.raises(ModelUnavailable) as caught:
        run(chat(client).complete(MESSAGES, max_tokens=50))
    assert "arn:aws" not in str(caught.value)


def test_bedrock_needs_a_model_id_and_no_key() -> None:
    with pytest.raises(ValueError, match="Bedrock model id"):
        make_settings(chat_provider="bedrock")
    settings = make_settings(chat_provider="bedrock", chat_model=MODEL, bedrock_region="")
    assert settings.chat_api_key is None and settings.bedrock_region is None
