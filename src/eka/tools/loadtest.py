# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Small closed-loop load generator: N virtual users each send requests back to back.

    python -m eka.tools.loadtest --url http://localhost:8000 --key $KEY --scenario search \
        --users 20 --seconds 30

Prints one JSON document: throughput, latency percentiles and a count per status code. Latency
is measured by the client, so it includes the network and this process's own scheduling.
"""

import argparse
import asyncio
import json
import math
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

QUESTIONS = [
    "How many days of annual leave do employees get?",
    "What is the process for reporting a security incident?",
    "Who approves travel expenses?",
    "How are passwords supposed to be stored?",
]


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile of an already sorted list."""
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(p / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


@dataclass
class Result:
    latencies: list[float] = field(default_factory=list)
    statuses: Counter[str] = field(default_factory=Counter)

    def record(self, seconds: float, status: str) -> None:
        self.latencies.append(seconds)
        self.statuses[status] += 1

    def summary(self, elapsed: float) -> dict[str, Any]:
        ordered = sorted(self.latencies)
        total = len(ordered)
        failed = sum(count for status, count in self.statuses.items() if not status.startswith("2"))
        return {
            "requests": total,
            "seconds": round(elapsed, 2),
            "requests_per_second": round(total / elapsed, 1) if elapsed else 0.0,
            "error_rate": round(failed / total, 4) if total else 0.0,
            "latency_ms": {
                "p50": round(percentile(ordered, 50) * 1000, 1),
                "p95": round(percentile(ordered, 95) * 1000, 1),
                "p99": round(percentile(ordered, 99) * 1000, 1),
                "max": round(ordered[-1] * 1000, 1) if ordered else 0.0,
            },
            "statuses": dict(self.statuses),
        }


Request = Callable[[int], tuple[str, str, dict[str, Any] | None]]

SCENARIOS: dict[str, Request] = {
    "me": lambda i: ("GET", "/api/v1/me", None),
    "search": lambda i: (
        "POST",
        "/api/v1/search",
        {"query": QUESTIONS[i % len(QUESTIONS)], "top_k": 5},
    ),
    "chat": lambda i: (
        "POST",
        "/api/v1/chat",
        {"question": QUESTIONS[i % len(QUESTIONS)], "top_k": 5},
    ),
}


async def _user(
    client: httpx.AsyncClient, scenario: Request, deadline: float, result: Result, offset: int
) -> None:
    count = offset
    while time.monotonic() < deadline:
        method, path, body = scenario(count)
        count += 1
        started = time.perf_counter()
        try:
            response = await client.request(method, path, json=body)
            status = str(response.status_code)
        except httpx.TimeoutException:
            status = "timeout"
        except httpx.HTTPError:
            status = "connection_error"
        result.record(time.perf_counter() - started, status)


async def run(
    url: str,
    key: str,
    scenario: str,
    users: int,
    seconds: float,
    timeout: float = 60.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    result = Result()
    limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
    async with httpx.AsyncClient(
        base_url=url,
        headers={"X-API-Key": key},
        timeout=timeout,
        limits=limits,
        transport=transport,
    ) as client:
        started = time.monotonic()
        deadline = started + seconds
        await asyncio.gather(
            *(_user(client, SCENARIOS[scenario], deadline, result, n) for n in range(users))
        )
        elapsed = time.monotonic() - started
    return result.summary(elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument(
        "--key", required=True, help="API key (kept out of the command history by using $KEY)"
    )
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="search")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run(args.url, args.key, args.scenario, args.users, args.seconds)), indent=2
        )
    )


if __name__ == "__main__":
    main()
