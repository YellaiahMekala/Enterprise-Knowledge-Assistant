# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Token and cost accounting on a real database (migration 0004, ADR-037): the usage event keeps
the counts, cost and first-token times; the admin report sums them by user and by day."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from eka.config import ApiKeyEntry
from eka.domain.models import Role
from eka.main import create_app
from eka.security.auth import digest_key
from tests.fakes import FakeEmbedder
from tests.helpers import ADMIN_KEY, USER_ID, USER_KEY, api_keys, make_settings, ready_ok
from tests.integration.helpers import admin_engine
from tests.integration.test_conversations_database import _SELECTOR, BOB_KEY, LEAVE, ask
from tests.integration.test_search_database import seed


def _app(url: str, **settings: object) -> TestClient:
    keys = {**api_keys(), "bob": ApiKeyEntry(sha256=digest_key(BOB_KEY).hex(), role=Role.USER)}
    app = create_app(
        make_settings(database_url=url, api_keys=keys, refusal_min_cosine=0.3, **settings),
        readiness_check=ready_ok,
        embedder=FakeEmbedder(),
    )
    return TestClient(app, backend_options=_SELECTOR, raise_server_exceptions=False)


@pytest.fixture
def priced(isolated_url: str) -> Iterator[TestClient]:
    engine = admin_engine(isolated_url)
    seed(engine, USER_ID, "leave.md", [LEAVE, "The canteen opens at noon."])
    seed(engine, "bob", "leave.md", [LEAVE])
    with _app(isolated_url, chat_price_input_per_1m=0.15, chat_price_output_per_1m=0.60) as client:
        client.database_url = isolated_url  # type: ignore[attr-defined]
        yield client


def test_a_usage_event_stores_tokens_cost_and_first_token_times(priced: TestClient) -> None:
    ask(priced)
    engine = admin_engine(priced.database_url)  # type: ignore[attr-defined]
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT provider, prompt_tokens, completion_tokens, token_source, cost_usd, "
                "ttft_ms, answer_ttfb_ms, latency_ms FROM usage_events"
            )
        ).one()
    assert row.provider == "fake" and row.token_source == "estimated"
    assert row.prompt_tokens > 0 and row.completion_tokens > 0
    expected = (row.prompt_tokens * 0.15 + row.completion_tokens * 0.60) / 1_000_000
    assert float(row.cost_usd) == pytest.approx(expected, abs=1e-6)
    assert 0 <= row.ttft_ms <= row.answer_ttfb_ms <= row.latency_ms


def test_without_prices_the_cost_is_empty(isolated_url: str) -> None:
    seed(admin_engine(isolated_url), USER_ID, "leave.md", [LEAVE])
    with _app(isolated_url) as client:
        ask(client)
    with admin_engine(isolated_url).connect() as connection:
        row = connection.execute(text("SELECT prompt_tokens, cost_usd FROM usage_events")).one()
    assert row.prompt_tokens > 0 and row.cost_usd is None


def test_the_admin_report_sums_two_users_and_two_days(priced: TestClient) -> None:
    ask(priced)
    ask(priced)
    ask(priced, key=BOB_KEY)
    engine = admin_engine(priced.database_url)  # type: ignore[attr-defined]
    with engine.begin() as connection:  # move one of alice's answers to the day before
        connection.execute(
            text(
                "UPDATE usage_events SET created_at = created_at - interval '1 day' "
                "WHERE id = (SELECT id FROM usage_events WHERE owner_id = :o "
                "ORDER BY created_at LIMIT 1)"
            ),
            {"o": USER_ID},
        )
        totals = connection.execute(
            text("SELECT sum(prompt_tokens) AS p, count(*) AS n FROM usage_events")
        ).one()

    admin = {"X-API-Key": ADMIN_KEY}
    by_user = priced.get("/api/v1/admin/usage?group_by=user", headers=admin).json()["rows"]
    requests = {row["key"]: row["requests"] for row in by_user}
    assert requests == {USER_ID: 2, "bob": 1}
    assert sum(row["prompt_tokens"] for row in by_user) == totals.p
    assert all(row["cost_usd"] > 0 and row["latency_p95_ms"] is not None for row in by_user)

    by_day = priced.get("/api/v1/admin/usage?group_by=day", headers=admin).json()["rows"]
    assert len(by_day) == 2 and sorted(r["requests"] for r in by_day) == [1, 2]
    assert sum(r["requests"] for r in by_day) == totals.n

    assert priced.get("/api/v1/admin/usage", headers={"X-API-Key": USER_KEY}).status_code == 403


def test_events_from_before_token_counting_report_unknown_not_zero(priced: TestClient) -> None:
    ask(priced)
    engine = admin_engine(priced.database_url)  # type: ignore[attr-defined]
    with engine.begin() as connection:  # what a row written before migration 0004 looks like
        connection.execute(text("UPDATE usage_events SET prompt_tokens = NULL, "
                                "completion_tokens = NULL, cost_usd = NULL"))  # fmt: skip
    rows = priced.get("/api/v1/admin/usage?group_by=user", headers={"X-API-Key": ADMIN_KEY}).json()[
        "rows"
    ]
    assert rows[0]["requests"] == 1
    assert rows[0]["prompt_tokens"] is None and rows[0]["cost_usd"] is None


def test_the_admin_document_counts_cover_every_owner(priced: TestClient) -> None:
    admin = {"X-API-Key": ADMIN_KEY}
    body = priced.get("/api/v1/admin/documents", headers=admin).json()
    assert body == {
        "total": 2,
        "by_status": {"pending": 0, "processing": 0, "ready": 2, "failed": 0},
    }  # alice's and bob's documents, seeded as ready
    user = priced.get("/api/v1/admin/documents", headers={"X-API-Key": USER_KEY})
    assert user.status_code == 403
