# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The failover drill's reading of the metrics (no network)."""

import httpx

from eka.tools.failover_drill import delta, llm_samples, run_phase

METRICS_BEFORE = """# HELP eka_llm_calls_total x
eka_llm_calls_total{model="gpt-x",outcome="unavailable"} 2.0
eka_llm_breaker_state{model="gpt-x"} 0.0
eka_http_requests_total{method="GET",route="/x",status="200"} 9.0
"""
METRICS_AFTER = """eka_llm_calls_total{model="gpt-x",outcome="unavailable"} 5.0
eka_llm_calls_total{model="claude",outcome="ok"} 3.0
eka_llm_failover_total{from_model="gpt-x",reason="unavailable",to_model="claude"} 3.0
eka_llm_breaker_state{model="gpt-x"} 2.0
"""


def _admin(pages: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=pages.pop(0))

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))


def test_only_model_series_are_read_and_counters_become_growth() -> None:
    before = llm_samples(_admin([METRICS_BEFORE]))
    after = llm_samples(_admin([METRICS_AFTER]))
    assert not any(k.startswith("eka_http") for k in before)
    assert delta(before, after) == {
        'eka_llm_calls_total{model="gpt-x",outcome="unavailable"}': 3.0,
        'eka_llm_calls_total{model="claude",outcome="ok"}': 3.0,
        'eka_llm_failover_total{from_model="gpt-x",reason="unavailable",to_model="claude"}': 3.0,
        'eka_llm_breaker_state{model="gpt-x"}': 2.0,
    }


def test_a_phase_reports_statuses_and_timings() -> None:
    user = httpx.Client(
        base_url="http://api", transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    result = run_phase(user, _admin([METRICS_BEFORE, METRICS_AFTER]), "outage", 3)
    assert result["statuses"] == [200, 200, 200] and len(result["seconds"]) == 3
    assert result["metrics"]['eka_llm_calls_total{model="claude",outcome="ok"}'] == 3.0
