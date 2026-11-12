"""Chat model adapter for any OpenAI-compatible ``/chat/completions`` endpoint (TDD 4.7, ADR-006).

* Bounded retries with exponential backoff on 429 and 5xx, only before any text was received.
* A request timeout; a timeout is reported as ``ModelTimeout``, anything else as
  ``ModelUnavailable``. Provider response bodies and the key are never logged or returned.
* Closing the stream closes the HTTP response, which ends the request to the provider.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from typing import Any

import httpx

from eka.domain.errors import ModelTimeout, ModelUnavailable
from eka.domain.models import ChatMessage, TokenUsage

logger = logging.getLogger(__name__)

_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_BACKOFF_SECONDS = 0.5


class OpenAICompatibleChat:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        retries: int = 2,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.model_name = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._retries = retries
        self._sleep = sleep
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds))
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _body(
        self, messages: Sequence[ChatMessage], max_tokens: int, stream: bool
    ) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": stream,
            # The last streamed chunk then carries the token counts (ADR-037).
            **({"stream_options": {"include_usage": True}} if stream else {}),
        }

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> str:
        body = self._body(messages, max_tokens, stream=False)
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.post(self._url, json=body, headers=self._headers)
            except httpx.TimeoutException as error:
                raise ModelTimeout("chat model timed out") from error
            except httpx.HTTPError as error:
                if attempt < self._retries:
                    await self._backoff(attempt, type(error).__name__)
                    continue
                raise ModelUnavailable("chat model request failed") from error
            if response.status_code in _RETRYABLE and attempt < self._retries:
                await self._backoff(attempt, str(response.status_code))
                continue
            if response.status_code >= 400:
                logger.warning("chat model returned status %s", response.status_code)
                raise ModelUnavailable("chat model rejected the request")
            content = _content_of(response)
            self._count(_json_or_none(response), usage)
            return content
        raise ModelUnavailable("chat model request failed")  # pragma: no cover

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> AsyncGenerator[str, None]:
        body = self._body(messages, max_tokens, stream=True)
        for attempt in range(self._retries + 1):
            try:
                async with self._client.stream(
                    "POST", self._url, json=body, headers=self._headers
                ) as response:
                    if response.status_code in _RETRYABLE and attempt < self._retries:
                        await self._backoff(attempt, str(response.status_code))
                        continue
                    if response.status_code >= 400:
                        logger.warning("chat model returned status %s", response.status_code)
                        raise ModelUnavailable("chat model rejected the request")
                    async for line in response.aiter_lines():
                        fragment = _fragment_of(line)
                        if fragment is _DONE:
                            return
                        if isinstance(fragment, dict):
                            self._count(fragment, usage)
                        elif fragment:
                            yield str(fragment)
                    return
            except httpx.TimeoutException as error:
                raise ModelTimeout("chat model timed out") from error
            except httpx.HTTPError as error:
                if attempt < self._retries:
                    await self._backoff(attempt, type(error).__name__)
                    continue
                raise ModelUnavailable("chat model request failed") from error

    def _count(self, body: Any, usage: TokenUsage | None) -> None:
        if usage is None or not isinstance(body, dict):
            return
        counts = body.get("usage")
        if not isinstance(counts, dict):
            return
        prompt, completion = counts.get("prompt_tokens"), counts.get("completion_tokens")
        if isinstance(prompt, int) and isinstance(completion, int):
            usage.add(self.model_name, "openai", prompt, completion)

    async def _backoff(self, attempt: int, reason: str) -> None:
        delay = _BACKOFF_SECONDS * (2**attempt)
        logger.warning(
            "chat model attempt %s failed (%s); retrying in %.1fs", attempt + 1, reason, delay
        )
        await self._sleep(delay)


_DONE = object()


def _content_of(response: httpx.Response) -> str:
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ModelUnavailable("chat model returned an unexpected reply") from error
    if not isinstance(content, str):
        raise ModelUnavailable("chat model returned an unexpected reply")
    return content


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _fragment_of(line: str) -> object:
    """The text in one server-sent line, ``_DONE`` for the end marker, the whole chunk (a dict)
    when it is the final usage chunk, or ``""`` to skip."""
    if not line.startswith("data:"):
        return ""
    payload = line[5:].strip()
    if payload == "[DONE]":
        return _DONE
    try:
        chunk = json.loads(payload)
        if isinstance(chunk, dict) and not chunk.get("choices") and "usage" in chunk:
            return chunk
        delta = chunk["choices"][0].get("delta", {})
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise ModelUnavailable("chat model returned an unexpected stream") from error
    content = delta.get("content")
    return content if isinstance(content, str) else ""
