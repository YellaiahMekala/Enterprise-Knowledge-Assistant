"""A chat model that fails over to the next configured model (ADR-038, FR-54).

* Failover happens only on ``ModelUnavailable`` and ``ModelTimeout`` (the adapters' own retries
  have already run), and only **before the first text fragment**. Once text has been sent the
  stream is never switched, because the user would see two answers spliced together; a later
  failure ends the answer with the usual error.
* Each model has its own circuit breaker. An open breaker skips the model without calling it, so
  during an outage requests stop paying the dead provider's failure time.
* When every model fails or is skipped, the last error is raised, so the API returns the same
  502 or 504 problem document as with a single model.
* Closing the stream closes the stream of whichever model was active.
"""

import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from typing import Protocol

from eka.adapters.breaker import CircuitBreaker, State
from eka.domain.errors import ModelTimeout, ModelUnavailable
from eka.domain.models import ChatMessage, TokenUsage
from eka.ports.chat import ChatModel

logger = logging.getLogger(__name__)

_FAILOVER_ERRORS = (ModelUnavailable, ModelTimeout)


class FallbackObserver(Protocol):
    """Where the chain reports what it did (the Prometheus metrics in the running service)."""

    def llm_call(self, model: str, outcome: str) -> None: ...

    def llm_failover(self, from_model: str, to_model: str, reason: str) -> None: ...

    def llm_breaker_state(self, model: str, state: int) -> None: ...


class _NoObserver:
    def llm_call(self, model: str, outcome: str) -> None:
        pass

    def llm_failover(self, from_model: str, to_model: str, reason: str) -> None:
        pass

    def llm_breaker_state(self, model: str, state: int) -> None:
        pass


def _reason(error: Exception) -> str:
    return "timeout" if isinstance(error, ModelTimeout) else "unavailable"


class FallbackChatModel:
    def __init__(
        self,
        models: Sequence[ChatModel],
        *,
        breakers: Sequence[CircuitBreaker] | None = None,
        observer: FallbackObserver | None = None,
    ) -> None:
        if not models:
            raise ValueError("a fallback chain needs at least one model")
        self._models = list(models)
        self._breakers = list(breakers) if breakers else [CircuitBreaker() for _ in models]
        if len(self._breakers) != len(self._models):
            raise ValueError("one breaker per model")
        self._observer: FallbackObserver = observer or _NoObserver()
        # The primary's name; usage events record the model that actually answered.
        self.model_name = self._models[0].model_name
        for model, breaker in zip(self._models, self._breakers, strict=True):
            self._observer.llm_breaker_state(model.model_name, int(breaker.state))

    @property
    def models(self) -> list[ChatModel]:
        return list(self._models)

    def breaker_states(self) -> dict[str, State]:
        return {m.model_name: b.state for m, b in zip(self._models, self._breakers, strict=True)}

    async def aclose(self) -> None:
        for model in self._models:
            close = getattr(model, "aclose", None)
            if close is not None:
                await close()

    def _record(self, index: int, ok: bool, outcome: str) -> None:
        model, breaker = self._models[index], self._breakers[index]
        breaker.record(ok)
        self._observer.llm_call(model.model_name, outcome)
        self._observer.llm_breaker_state(model.model_name, int(breaker.state))

    def _next_name(self, index: int) -> str:
        return self._models[index + 1].model_name if index + 1 < len(self._models) else "none"

    def _failed(self, index: int, error: Exception) -> None:
        reason = _reason(error)
        self._record(index, False, reason)
        name = self._models[index].model_name
        logger.warning("chat model %s failed (%s); trying the next one", name, reason)
        self._observer.llm_failover(name, self._next_name(index), reason)

    def _skipped(self, index: int) -> None:
        name = self._models[index].model_name
        self._observer.llm_call(name, "skipped")
        self._observer.llm_failover(name, self._next_name(index), "breaker_open")

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> str:
        last: Exception | None = None
        for index, (model, breaker) in enumerate(zip(self._models, self._breakers, strict=True)):
            if not breaker.allow():
                self._skipped(index)
                continue
            try:
                text = await model.complete(messages, max_tokens=max_tokens, usage=usage)
            except _FAILOVER_ERRORS as error:
                self._failed(index, error)
                last = error
                continue
            except BaseException:
                breaker.release()  # cancelled or an unexpected error: no verdict on the model
                raise
            self._record(index, True, "ok")
            return text
        raise last or ModelUnavailable("every chat model is unavailable")

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> AsyncGenerator[str, None]:
        last: Exception | None = None
        for index, (model, breaker) in enumerate(zip(self._models, self._breakers, strict=True)):
            if not breaker.allow():
                self._skipped(index)
                continue
            started = False
            try:
                async with aclosing(
                    model.stream(messages, max_tokens=max_tokens, usage=usage)
                ) as fragments:
                    async for fragment in fragments:
                        started = True
                        yield fragment
            except _FAILOVER_ERRORS as error:
                if started:  # never switch models once text has been sent
                    self._record(index, False, _reason(error))
                    raise
                self._failed(index, error)
                last = error
                continue
            except BaseException:
                breaker.release()  # the client left, or an unexpected error
                raise
            self._record(index, True, "ok")
            return
        raise last or ModelUnavailable("every chat model is unavailable")
