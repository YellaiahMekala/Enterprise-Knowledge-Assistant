"""Token, cost and first-token accounting (ADR-037, FR-53): adapters read the provider's counts
from recorded payloads, the answer service prices and times them, and metrics never name a user."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from eka.adapters.chat_fake import FakeChatModel
from eka.adapters.chat_openai import OpenAICompatibleChat
from eka.domain.models import ChatMessage, TokenUsage, UsageEvent, UsageRow
from eka.main import create_app
from eka.metrics import Metrics
from eka.services.answering import AnswerSettings, cost_usd
from tests.fakes import ScriptedChatModel
from tests.helpers import ADMIN_KEY, USER_KEY, make_settings, ready_ok
from tests.test_answering import GOOD, World
from tests.test_chat_bedrock import MESSAGES, StubClient, chat, run

# --- adapters, from recorded provider payloads -------------------------------------------------


def _openai(handler: Any) -> OpenAICompatibleChat:
    return OpenAICompatibleChat(
        base_url="https://llm.example/v1",
        api_key="sk-test",
        model="gpt-x",
        timeout_seconds=5,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.anyio
async def test_openai_complete_reads_the_usage_block() -> None:
    body = {
        "choices": [{"message": {"content": "Five days [1]."}}],
        "usage": {"prompt_tokens": 812, "completion_tokens": 9, "total_tokens": 821},
    }
    usage = TokenUsage()
    text = await _openai(lambda r: httpx.Response(200, json=body)).complete(
        MESSAGES, max_tokens=50, usage=usage
    )
    assert text == "Five days [1]."
    assert (usage.prompt_tokens, usage.completion_tokens, usage.calls) == (812, 9, 1)
    assert (usage.provider, usage.model, usage.estimated) == ("openai", "gpt-x", False)


@pytest.mark.anyio
async def test_openai_stream_asks_for_usage_and_reads_the_final_chunk() -> None:
    sent: list[dict[str, Any]] = []
    chunks = [
        {"choices": [{"delta": {"content": "Five "}}]},
        {"choices": [{"delta": {"content": "days [1]."}}]},
        {"choices": [], "usage": {"prompt_tokens": 700, "completion_tokens": 4}},
    ]
    payload = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=payload.encode())

    usage = TokenUsage()
    model = _openai(handler)
    text = "".join([f async for f in model.stream(MESSAGES, max_tokens=50, usage=usage)])
    assert text == "Five days [1]."
    assert sent[0]["stream_options"] == {"include_usage": True}
    assert (usage.prompt_tokens, usage.completion_tokens) == (700, 4)


@pytest.mark.anyio
async def test_openai_without_usage_leaves_the_counter_empty() -> None:
    body = {"choices": [{"message": {"content": "x [1]"}}]}
    usage = TokenUsage()
    await _openai(lambda r: httpx.Response(200, json=body)).complete(
        MESSAGES, max_tokens=5, usage=usage
    )
    assert usage.calls == 0


def test_bedrock_converse_reads_input_and_output_tokens() -> None:
    client = StubClient()
    client.reply = {
        "output": {"message": {"content": [{"text": "Hello [1]"}]}},
        "usage": {"inputTokens": 321, "outputTokens": 12, "totalTokens": 333},
    }
    usage = TokenUsage()
    run(chat(client).complete(MESSAGES, max_tokens=50, usage=usage))
    assert (usage.prompt_tokens, usage.completion_tokens, usage.provider) == (321, 12, "bedrock")


def test_bedrock_stream_reads_the_metadata_event() -> None:
    client = StubClient()
    client.events = [
        {"contentBlockDelta": {"delta": {"text": "Hi [1]"}}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": {"inputTokens": 50, "outputTokens": 3}, "metrics": {}}},
    ]
    usage = TokenUsage()

    async def collect() -> list[str]:
        return [f async for f in chat(client).stream(MESSAGES, max_tokens=50, usage=usage)]

    assert run(collect()) == ["Hi [1]"]
    assert (usage.prompt_tokens, usage.completion_tokens) == (50, 3)


@pytest.mark.anyio
async def test_the_fake_model_estimates_and_says_so() -> None:
    usage = TokenUsage()
    messages = [ChatMessage("user", "x" * 400)]
    await FakeChatModel().complete(messages, max_tokens=50, usage=usage)
    assert usage.prompt_tokens == 100 and usage.estimated and usage.provider == "fake"


# --- pricing -----------------------------------------------------------------------------------


def test_cost_is_empty_without_both_prices() -> None:
    tokens = TokenUsage()
    tokens.add("m", "p", 1_000_000, 500_000)
    assert cost_usd(tokens, AnswerSettings()) is None
    assert cost_usd(tokens, AnswerSettings(price_input_per_1m=0.15)) is None
    priced = AnswerSettings(price_input_per_1m=0.15, price_output_per_1m=0.60)
    assert cost_usd(tokens, priced) == pytest.approx(0.45)
    assert cost_usd(TokenUsage(), priced) is None  # no model call, no cost


# --- the answer service ------------------------------------------------------------------------


class Clock:
    """Each read moves time on by 100 ms, so every measured interval is known exactly."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.1
        return self.now


@pytest.mark.anyio
async def test_an_answer_records_tokens_cost_and_both_first_token_times() -> None:
    seen: list[UsageEvent] = []
    rig = World(
        ScriptedChatModel([GOOD]),
        AnswerSettings(
            min_cosine=0.1, price_input_per_1m=1.0, price_output_per_1m=2.0, default_mode="fast"
        ),
    )
    rig.service._clock = Clock()  # type: ignore[attr-defined]
    rig.service._on_usage = seen.append  # type: ignore[attr-defined]
    await rig.ask()

    (_, event) = rig.repo.usage[-1]
    assert event.provider == "scripted" and event.token_source == "provider"
    assert event.prompt_tokens == 100 and event.completion_tokens == len(GOOD.split())
    assert event.cost_usd == pytest.approx((100 * 1.0 + len(GOOD.split()) * 2.0) / 1_000_000)
    assert event.ttft_ms is not None and event.answer_ttfb_ms is not None
    assert 0 < event.ttft_ms <= event.answer_ttfb_ms <= event.latency_ms
    assert seen == [event]


@pytest.mark.anyio
async def test_verified_mode_releases_text_later_than_the_first_fragment() -> None:
    rig = World(ScriptedChatModel([GOOD]))
    rig.service._clock = Clock()  # type: ignore[attr-defined]
    await rig.ask(mode="verified")
    (_, event) = rig.repo.usage[-1]
    assert event.ttft_ms is not None and event.answer_ttfb_ms is not None
    assert event.answer_ttfb_ms > event.ttft_ms  # the whole reply is checked before release
    assert event.cost_usd is None  # no price configured


@pytest.mark.anyio
async def test_a_refusal_without_a_model_call_has_no_tokens() -> None:
    rig = World(ScriptedChatModel([GOOD]), AnswerSettings(min_cosine=0.99))
    await rig.ask()
    (_, event) = rig.repo.usage[-1]
    assert event.refused and event.prompt_tokens is None and event.token_source is None
    assert event.ttft_ms is None and event.answer_ttfb_ms is not None


@pytest.mark.anyio
async def test_a_failing_observer_does_not_break_the_answer() -> None:
    rig = World(ScriptedChatModel([GOOD]))

    def broken(_: UsageEvent) -> None:
        raise RuntimeError("metrics down")

    rig.service._on_usage = broken  # type: ignore[attr-defined]
    events = await rig.ask()
    assert events[-1].type == "done"


# --- metrics -----------------------------------------------------------------------------------


def _event(**changes: Any) -> UsageEvent:
    base: dict[str, Any] = {
        "conversation_id": None,
        "mode": "verified",
        "model": "gpt-x",
        "refused": False,
        "retrieved": 5,
        "top_cosine": 0.8,
        "prompt_chars": 4000,
        "completion_chars": 80,
        "latency_ms": 2100,
        "provider": "openai",
        "prompt_tokens": 900,
        "completion_tokens": 30,
        "token_source": "provider",
        "cost_usd": 0.000153,
        "ttft_ms": 700,
        "answer_ttfb_ms": 1900,
    }
    return UsageEvent(**{**base, **changes})


def test_metrics_show_tokens_cost_ttft_and_duration_without_a_user_label() -> None:
    metrics = Metrics()
    metrics.observe_answer(_event())
    metrics.observe_answer(_event(refused=True, prompt_tokens=None, cost_usd=None, ttft_ms=None))
    text = metrics.render().decode()
    assert 'eka_llm_tokens_total{kind="prompt",model="gpt-x",provider="openai"} 900.0' in text
    assert 'eka_llm_cost_usd_total{model="gpt-x",provider="openai"} 0.000153' in text
    assert 'eka_llm_ttft_seconds_count{mode="verified",model="gpt-x",provider="openai"} 1.0' in text
    assert 'outcome="refused"' in text and 'outcome="answered"' in text
    for line in text.splitlines():
        if line.startswith("eka_llm"):
            assert "user" not in line and "owner" not in line


# --- the admin usage report --------------------------------------------------------------------


def _client(rows: list[UsageRow], calls: list[tuple[Any, ...]]) -> TestClient:
    app = create_app(make_settings(), readiness_check=ready_ok)

    async def report(owner: str, group_by: str, start: datetime, end: datetime) -> list[UsageRow]:
        calls.append((owner, group_by, start, end))
        return rows

    app.state.usage_report = report
    return TestClient(app)


ROW = UsageRow("2026-11-12", 3, 1, 2700, 90, 0.00046, 1800, 2400, 650, 900)


def test_usage_report_is_for_admins_only_and_has_no_text() -> None:
    calls: list[tuple[Any, ...]] = []
    client = _client([ROW], calls)
    assert client.get("/api/v1/admin/usage").status_code == 401
    assert client.get("/api/v1/admin/usage", headers={"X-API-Key": USER_KEY}).status_code == 403
    response = client.get(
        "/api/v1/admin/usage?group_by=day&from=2026-11-01T00:00:00Z&to=2026-11-13T00:00:00Z",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["group_by"] == "day" and body["rows"][0]["prompt_tokens"] == 2700
    assert set(body["rows"][0]) == {
        "key", "requests", "refused", "prompt_tokens", "completion_tokens", "cost_usd",
        "latency_p50_ms", "latency_p95_ms", "ttft_p50_ms", "ttft_p95_ms",
    }  # fmt: skip
    assert calls[0][1:] == (
        "day",
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 13, tzinfo=UTC),
    )


def test_usage_report_rejects_a_reversed_or_too_long_window() -> None:
    client = _client([], [])
    headers = {"X-API-Key": ADMIN_KEY}
    reversed_window = "/api/v1/admin/usage?from=2026-11-12T00:00:00Z&to=2026-11-01T00:00:00Z"
    assert client.get(reversed_window, headers=headers).status_code == 400
    too_long = "/api/v1/admin/usage?from=2026-01-01T00:00:00Z&to=2026-11-01T00:00:00Z"
    assert client.get(too_long, headers=headers).status_code == 400
    assert client.get("/api/v1/admin/usage?group_by=team", headers=headers).status_code == 422


def test_an_empty_price_setting_means_no_price() -> None:
    from tests.helpers import make_settings as settings_with

    settings = settings_with(chat_price_input_per_1m="", chat_price_output_per_1m="")
    assert settings.chat_price_input_per_1m is None and settings.chat_price_output_per_1m is None
