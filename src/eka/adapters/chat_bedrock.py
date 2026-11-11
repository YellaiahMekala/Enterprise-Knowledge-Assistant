"""Chat model adapter for Amazon Bedrock through the Converse API (ADR-006, ADR-034).

Converse gives one request shape for every model on Bedrock, so changing the model is a setting.
Credentials come from boto3's normal chain (environment, shared config, or the task or instance
role); no key is stored in this project's settings. boto3 is synchronous, so calls run in worker
threads. Timeouts are reported as ``ModelTimeout``, everything else as ``ModelUnavailable``, and
provider error bodies are never returned to callers.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError

from eka.domain.errors import ModelTimeout, ModelUnavailable
from eka.domain.models import ChatMessage

logger = logging.getLogger(__name__)

_END = object()


class BedrockChat:
    def __init__(
        self,
        *,
        model_id: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        timeout_seconds: float = 60.0,
        retries: int = 2,
        client: Any = None,
    ) -> None:
        self.model_name = model_id
        self._client = client or boto3.client(
            "bedrock-runtime",
            region_name=region,
            endpoint_url=endpoint_url,
            config=Config(
                read_timeout=timeout_seconds,
                connect_timeout=min(5.0, timeout_seconds),
                retries={"max_attempts": retries + 1, "mode": "standard"},
            ),
        )

    def _request(self, messages: Sequence[ChatMessage], max_tokens: int) -> dict[str, Any]:
        """Converse wants system text apart from the turns, and turns that alternate user and
        assistant starting with a user turn. Consecutive turns by one role are merged."""
        system = [{"text": m.content} for m in messages if m.role == "system"]
        turns: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            if turns and turns[-1]["role"] == message.role:
                turns[-1]["content"].append({"text": message.content})
            else:
                turns.append({"role": message.role, "content": [{"text": message.content}]})
        if not turns or turns[0]["role"] != "user":
            raise ModelUnavailable("a chat request needs a first user message")
        request: dict[str, Any] = {
            "modelId": self.model_name,
            "messages": turns,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
        }
        if system:
            request["system"] = system
        return request

    async def complete(self, messages: Sequence[ChatMessage], *, max_tokens: int) -> str:
        request = self._request(messages, max_tokens)
        try:
            response = await asyncio.to_thread(self._client.converse, **request)
        except Exception as error:
            raise _translate(error) from error
        try:
            parts = response["output"]["message"]["content"]
            text = "".join(part["text"] for part in parts if "text" in part)
        except (KeyError, TypeError) as error:
            raise ModelUnavailable("chat model returned an unexpected reply") from error
        return text

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        request = self._request(messages, max_tokens)
        try:
            response = await asyncio.to_thread(self._client.converse_stream, **request)
        except Exception as error:
            raise _translate(error) from error
        events = iter(response["stream"])
        try:
            while True:
                event: Any = await asyncio.to_thread(next, events, _END)
                if event is _END:
                    return
                delta = event.get("contentBlockDelta", {}).get("delta", {})
                text = delta.get("text")
                if isinstance(text, str) and text:
                    yield text
        except (BotoCoreError, ClientError) as error:
            raise _translate(error) from error
        finally:
            close = getattr(response["stream"], "close", None)
            if close is not None:
                close()  # ends the request to the provider when the caller stops early


def _translate(error: Exception) -> Exception:
    if isinstance(error, ReadTimeoutError):
        return ModelTimeout("chat model timed out")
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", ""))
        logger.warning("bedrock returned %s", code)
        if code == "ModelTimeoutException":
            return ModelTimeout("chat model timed out")
        return ModelUnavailable("chat model rejected the request")
    if isinstance(error, BotoCoreError):
        logger.warning("bedrock call failed: %s", type(error).__name__)
        return ModelUnavailable("chat model request failed")
    if isinstance(error, ModelUnavailable | ModelTimeout):
        return error
    logger.warning("bedrock call failed: %s", type(error).__name__)
    return ModelUnavailable("chat model request failed")
