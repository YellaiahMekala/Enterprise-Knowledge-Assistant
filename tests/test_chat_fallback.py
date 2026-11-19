# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The fallback chain and its per-model breaker (ADR-038, FR-54, AC-26 to AC-28), with scripted
models and an injected clock: no network, no waiting."""

from collections.abc import AsyncGenerator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from eka.adapters.breaker import CircuitBreaker, State
from eka.adapters.chat_fallback import FallbackChatModel
from eka.domain.errors import EkaError, ModelTimeout, ModelUnavailable
from eka.domain.models import ChatMessage, TokenUsage
from eka.main import create_app
from eka.metrics import Metrics
from tests.fakes import ScriptedChatModel
from tests.helpers import USER_KEY, make_settings, ready_ok
from tests.test_answering import GOOD, World

MESSAGES = [ChatMessage("user", "q")]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Flaky:
    """Fails with ``error`` before any text while ``broken``; can also fail after the first word."""

    def __init__(self, name: str, error: EkaError | None = None, *, after_text: bool = False):
        self.model_name = name
        self.error = error
        self.after_text = after_text
        self.calls = 0
        self.closed = 0

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if usage is not None:
            usage.add(self.model_name, "test", 10, 2)
        return f"from {self.model_name} [1]"

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> AsyncGenerator[str, None]:
        self.calls += 1
        try:
            if self.error is not None and not self.after_text:
                raise self.error
            yield "from "
            if self.error is not None:
                raise self.error
            if usage is not None:
                usage.add(self.model_name, "test", 10, 2)
            yield f"{self.model_name} [1]"
        finally:
            self.closed += 1


def chain(*models: Any, clock: Clock | None = None, metrics: Metrics | None = None) -> Any:
    clock = clock or Clock()
    breakers = [CircuitBreaker(clock=clock) for _ in models]
    return FallbackChatModel(models, breakers=breakers, observer=metrics)


async def text_of(model: Any, usage: TokenUsage | None = None) -> str:
    return "".join([f async for f in model.stream(MESSAGES, max_tokens=50, usage=usage)])


# --- failover --------------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("error", [ModelUnavailable("down"), ModelTimeout("slow")])
async def test_failover_on_unavailable_and_timeout_before_any_text(error: EkaError) -> None:
    primary, backup = Flaky("primary", error), Flaky("backup")
    model = chain(primary, backup)
    usage = TokenUsage()
    assert await text_of(model, usage) == "from backup [1]"
    assert await model.complete(MESSAGES, max_tokens=5) == "from backup [1]"
    assert usage.model == "backup"  # the usage event records the model that answered
    assert model.model_name == "primary"


@pytest.mark.anyio
async def test_no_failover_after_the_first_fragment() -> None:
    primary, backup = Flaky("primary", ModelUnavailable("cut"), after_text=True), Flaky("backup")
    model = chain(primary, backup)
    got: list[str] = []
    with pytest.raises(ModelUnavailable):
        async for fragment in model.stream(MESSAGES, max_tokens=5):
            got.append(fragment)
    assert got == ["from "] and backup.calls == 0


@pytest.mark.anyio
async def test_other_errors_are_not_failed_over() -> None:
    class Broken(Flaky):
        async def complete(self, *a: Any, **k: Any) -> str:
            raise ValueError("a bug")

    backup = Flaky("backup")
    with pytest.raises(ValueError):
        await chain(Broken("primary"), backup).complete(MESSAGES, max_tokens=5)
    assert backup.calls == 0


@pytest.mark.anyio
async def test_when_every_model_fails_the_last_error_is_raised() -> None:
    model = chain(Flaky("a", ModelUnavailable("x")), Flaky("b", ModelTimeout("y")))
    with pytest.raises(ModelTimeout):
        await text_of(model)
    with pytest.raises(ModelTimeout):
        await model.complete(MESSAGES, max_tokens=5)


@pytest.mark.anyio
async def test_closing_the_stream_closes_the_active_model() -> None:
    primary, backup = Flaky("primary", ModelUnavailable("down")), Flaky("backup")
    stream = chain(primary, backup).stream(MESSAGES, max_tokens=5)
    assert await stream.__anext__() == "from "
    await stream.aclose()
    assert backup.closed == 1 and primary.closed == 1


# --- the breaker -------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_an_open_breaker_skips_the_primary_and_probes_it_after_30_seconds() -> None:
    clock = Clock()
    metrics = Metrics()
    primary, backup = Flaky("primary", ModelUnavailable("down")), Flaky("backup")
    model = chain(primary, backup, clock=clock, metrics=metrics)

    for _ in range(10):  # minimum calls, all failed: the breaker opens
        await text_of(model)
    assert model.breaker_states()["primary"] is State.OPEN
    assert primary.calls == 10

    await text_of(model)
    assert primary.calls == 10  # skipped without a call

    clock.now += 30
    primary.error = None  # the provider is back
    for _ in range(3):  # three half-open probes succeed
        assert await text_of(model) == "from primary [1]"
    assert model.breaker_states()["primary"] is State.CLOSED

    text = metrics.render().decode()
    assert 'eka_llm_breaker_state{model="primary"} 0.0' in text
    assert 'eka_llm_calls_total{model="primary",outcome="skipped"} 1.0' in text
    assert (
        'eka_llm_failover_total{from_model="primary",reason="unavailable",to_model="backup"} 10.0'
        in text
    )


def test_breaker_states_and_a_failed_probe_reopen() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    for _ in range(9):
        breaker.record(False)
    assert breaker.state is State.CLOSED  # under the minimum of 10 calls
    breaker.record(False)
    assert breaker.state is State.OPEN and not breaker.allow()  # type: ignore[comparison-overlap]
    clock.now = 29.9
    assert breaker.state is State.OPEN
    clock.now = 30
    assert breaker.allow() and breaker.state is State.HALF_OPEN
    breaker.record(False)
    assert breaker.state is State.OPEN


def test_half_open_allows_three_probes_and_a_cancelled_probe_frees_its_slot() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    for _ in range(10):
        breaker.record(False)
    clock.now = 30
    assert [breaker.allow() for _ in range(4)] == [True, True, True, False]
    breaker.release()
    assert breaker.allow()


def test_a_mostly_healthy_model_stays_closed() -> None:
    breaker = CircuitBreaker()
    for i in range(20):
        breaker.record(i % 3 != 0)  # a third of calls fail, under 50%
    assert breaker.state is State.CLOSED


# --- through the answer service and the API ----------------------------------------------------


@pytest.mark.anyio
async def test_an_answer_comes_from_the_fallback_and_its_usage_names_it() -> None:
    backup = ScriptedChatModel([GOOD])
    backup.model_name = "backup-model"
    world = World(chain(Flaky("primary", ModelUnavailable("down")), backup))
    events = await world.ask()
    assert events[-1].data["refused"] is False
    (_, usage) = world.repo.usage[-1]
    assert usage.model == "backup-model"


def test_every_model_failing_gives_the_same_502_as_one_model() -> None:
    model = chain(Flaky("a", ModelUnavailable("x")), Flaky("b", ModelUnavailable("y")))
    world = World(model)
    app = create_app(make_settings(), readiness_check=ready_ok, answer_service=world.service)
    response = TestClient(app).post(
        "/api/v1/chat",
        headers={"X-API-Key": USER_KEY},
        json={"question": "carry over unused leave days"},
    )
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")


# --- settings ----------------------------------------------------------------------------------


def test_settings_build_a_chain_from_the_fallback_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKA_TEST_FALLBACK_KEY", "sk-fallback")
    settings = make_settings(
        chat_fallbacks=[
            {"provider": "openai", "model": "gpt-y", "api_key_env": "EKA_TEST_FALLBACK_KEY"}
        ]
    )
    app = create_app(settings, readiness_check=ready_ok)
    model = app.state.answer_service._model
    assert isinstance(model, FallbackChatModel)
    assert [m.model_name for m in model.models] == ["fake-extractive", "gpt-y"]


@pytest.mark.parametrize(
    ("fallbacks", "message"),
    [
        ([{"provider": "fake", "model": "fake-extractive"}], "same as the primary"),
        ([{"provider": "openai", "model": "gpt-y"}], "api_key_env"),
        ([{"provider": "azure", "model": "m"}], "provider"),
        ([{"provider": "fake", "model": "a"}, {"provider": "fake", "model": "b"}], "at most 1"),
        ([{"provider": "openai", "model": "m", "api_key": "sk-inline"}], "Extra inputs"),
    ],
)
def test_bad_fallback_settings_are_rejected(fallbacks: list[dict[str, str]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_settings(chat_fallbacks=fallbacks)


def test_an_empty_fallback_key_variable_stops_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EKA_TEST_MISSING_KEY", raising=False)
    settings = make_settings(
        chat_fallbacks=[
            {"provider": "openai", "model": "gpt-y", "api_key_env": "EKA_TEST_MISSING_KEY"}
        ]
    )
    with pytest.raises(ValueError, match="EKA_TEST_MISSING_KEY"):
        create_app(settings, readiness_check=ready_ok)
