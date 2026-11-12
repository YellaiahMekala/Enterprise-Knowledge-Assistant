"""Failover drill (ADR-038): ask questions through the running API and report how long each took
and which chat model answered, read from the core's own metrics.

    python -m eka.tools.failover_drill --base-url http://127.0.0.1:8003 --phase outage --count 12

EKA_RUN_API_KEY is a user's key (asks the questions), EKA_RUN_ADMIN_KEY an admin key (reads
``/api/v1/admin/metrics``). The core is started by the operator with an OpenAI-style primary whose
base URL has nothing listening, and a Bedrock fallback pointed at the local stand-in; the drill
needs no AWS account and makes no paid call. See docs/runbooks.md#ekallmfailoverburst.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
from typing import Any

import httpx

_SAMPLE = re.compile(r"^(eka_llm_\w+)\{([^}]*)\} ([0-9.e+-]+)$")
QUESTION = "How many days of annual leave do staff get?"


def llm_samples(admin: httpx.Client) -> dict[str, float]:
    """``eka_llm_calls_total``, ``eka_llm_failover_total`` and ``eka_llm_breaker_state`` samples,
    keyed by the metric name and its labels."""
    response = admin.get("/api/v1/admin/metrics")
    response.raise_for_status()
    samples: dict[str, float] = {}
    for line in response.text.splitlines():
        match = _SAMPLE.match(line)
        if match and match.group(1) in (
            "eka_llm_calls_total",
            "eka_llm_failover_total",
            "eka_llm_breaker_state",
        ):
            samples[f"{match.group(1)}{{{match.group(2)}}}"] = float(match.group(3))
    return samples


def delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """Counter growth during the phase; gauges (breaker state) as their value at the end."""
    out: dict[str, float] = {}
    for key, value in after.items():
        if key.startswith("eka_llm_breaker_state"):
            out[key] = value
        elif value - before.get(key, 0.0):
            out[key] = value - before.get(key, 0.0)
    return out


def run_phase(user: httpx.Client, admin: httpx.Client, phase: str, count: int) -> dict[str, Any]:
    before = llm_samples(admin)
    seconds: list[float] = []
    statuses: list[int] = []
    for _ in range(count):
        started = time.monotonic()
        response = user.post("/api/v1/chat", json={"question": QUESTION})
        seconds.append(round(time.monotonic() - started, 3))
        statuses.append(response.status_code)
    return {
        "phase": phase,
        "statuses": statuses,
        "seconds": seconds,
        "p50_seconds": statistics.median(seconds) if seconds else None,
        "max_seconds": max(seconds) if seconds else None,
        "metrics": delta(before, llm_samples(admin)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eka.tools.failover_drill", description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--phase", required=True, help="a label for this part of the drill")
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args(argv)
    user_key, admin_key = os.environ.get("EKA_RUN_API_KEY"), os.environ.get("EKA_RUN_ADMIN_KEY")
    if not user_key or not admin_key:
        print("Set EKA_RUN_API_KEY (a user) and EKA_RUN_ADMIN_KEY (an admin).", file=sys.stderr)
        return 2
    with (
        httpx.Client(base_url=args.base_url, headers={"X-API-Key": user_key}, timeout=180) as user,
        httpx.Client(base_url=args.base_url, headers={"X-API-Key": admin_key}, timeout=30) as admin,
    ):
        print(json.dumps(run_phase(user, admin, args.phase, args.count), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
