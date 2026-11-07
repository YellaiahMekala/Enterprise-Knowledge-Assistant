import asyncio

import httpx
import pytest

from eka.tools.loadtest import Result, percentile, run


def test_percentile_uses_nearest_rank() -> None:
    values = [float(n) for n in range(1, 101)]
    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 95.0
    assert percentile(values, 99) == 99.0
    assert percentile(values, 100) == 100.0


def test_percentile_of_nothing_is_zero() -> None:
    assert percentile([], 95) == 0.0


def test_summary_counts_non_2xx_as_errors() -> None:
    result = Result()
    for _ in range(8):
        result.record(0.01, "200")
    result.record(0.5, "503")
    result.record(1.0, "timeout")

    summary = result.summary(elapsed=2.0)

    assert summary["requests"] == 10
    assert summary["requests_per_second"] == 5.0
    assert summary["error_rate"] == 0.2
    assert summary["latency_ms"]["max"] == 1000.0
    assert summary["statuses"] == {"200": 8, "503": 1, "timeout": 1}


def test_run_sends_the_key_and_reports_what_the_server_said() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key"))
        return httpx.Response(200 if len(seen) % 2 else 429, json={})

    summary = asyncio.run(
        run(
            "http://core",
            "k-123",
            "me",
            users=3,
            seconds=0.2,
            transport=httpx.MockTransport(handler),
        )
    )

    assert summary["requests"] > 0
    assert set(seen) == {"k-123"}
    assert set(summary["statuses"]) <= {"200", "429"}


def test_unknown_scenario_is_rejected() -> None:
    with pytest.raises(KeyError):
        asyncio.run(run("http://core", "k", "nope", users=1, seconds=0.1))
