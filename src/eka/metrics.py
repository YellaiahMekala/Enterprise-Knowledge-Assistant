# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from eka.domain.models import UsageEvent

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    """One registry per app instance, so tests that build several apps do not collide."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "eka_http_requests_total",
            "HTTP requests by route template and status",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "eka_http_request_duration_seconds",
            "HTTP request duration by route template",
            ["route"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
            registry=self.registry,
        )

        # Model series (ADR-037). Never labelled by user: one series per user would grow without
        # bound. Per-user figures come from usage_events through the admin usage report.
        self.llm_tokens = Counter(
            "eka_llm_tokens",
            "Chat model tokens by provider, model and kind (prompt or completion)",
            ["provider", "model", "kind"],
            registry=self.registry,
        )
        self.llm_cost = Counter(
            "eka_llm_cost_usd",
            "Chat model cost in US dollars, from configured prices",
            ["provider", "model"],
            registry=self.registry,
        )
        self.llm_ttft = Histogram(
            "eka_llm_ttft_seconds",
            "Request start to the first model fragment",
            ["provider", "model", "mode"],
            buckets=(0.1, 0.25, 0.5, 1, 1.5, 2, 3, 5, 10, 30),
            registry=self.registry,
        )
        self.llm_duration = Histogram(
            "eka_llm_request_duration_seconds",
            "Whole answer duration by outcome (answered or refused)",
            ["provider", "model", "outcome"],
            buckets=(0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
            registry=self.registry,
        )

        # Fallback chain (ADR-038).
        self.llm_calls = Counter(
            "eka_llm_calls",
            "Chat model calls by model and outcome (ok, unavailable, timeout, skipped)",
            ["model", "outcome"],
            registry=self.registry,
        )
        self.llm_failovers = Counter(
            "eka_llm_failover",
            "Moves from one chat model to the next, by reason",
            ["from_model", "to_model", "reason"],
            registry=self.registry,
        )
        self.llm_breaker = Gauge(
            "eka_llm_breaker_state",
            "Circuit breaker per chat model: 0 closed, 1 half-open, 2 open",
            ["model"],
            registry=self.registry,
        )

    def llm_call(self, model: str, outcome: str) -> None:
        self.llm_calls.labels(model, outcome).inc()

    def llm_failover(self, from_model: str, to_model: str, reason: str) -> None:
        self.llm_failovers.labels(from_model, to_model, reason).inc()

    def llm_breaker_state(self, model: str, state: int) -> None:
        self.llm_breaker.labels(model).set(state)

    def observe_answer(self, event: UsageEvent) -> None:
        provider = event.provider or "none"
        model = event.model
        if event.prompt_tokens is not None:
            self.llm_tokens.labels(provider, model, "prompt").inc(event.prompt_tokens)
        if event.completion_tokens is not None:
            self.llm_tokens.labels(provider, model, "completion").inc(event.completion_tokens)
        if event.cost_usd is not None:
            self.llm_cost.labels(provider, model).inc(event.cost_usd)
        if event.ttft_ms is not None:
            self.llm_ttft.labels(provider, model, event.mode).observe(event.ttft_ms / 1000)
        outcome = "refused" if event.refused else "answered"
        self.llm_duration.labels(provider, model, outcome).observe(event.latency_ms / 1000)

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests.labels(method, route, str(status)).inc()
        self.duration.labels(route).observe(seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)
