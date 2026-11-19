# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Chat on a real database: persistence, cascade, append-only messages, and row-level security
on the three tables added by migration 0002. The chat model is the fake extractive one."""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from eka.adapters.db.engine import Database
from eka.config import ApiKeyEntry
from eka.domain.models import Role
from eka.main import create_app
from eka.security.auth import digest_key
from tests.fakes import FakeEmbedder
from tests.helpers import ADMIN_KEY, USER_ID, USER_KEY, api_keys, make_settings, ready_ok
from tests.integration.helpers import admin_engine, count, run_async
from tests.integration.test_search_database import seed

_SELECTOR = {"loop_factory": asyncio.SelectorEventLoop}
BOB_KEY = "test-bob-key-0003"
LEAVE = "Staff may carry over five unused leave days into the next year."


@pytest.fixture
def client(isolated_url: str) -> Iterator[TestClient]:
    engine = admin_engine(isolated_url)
    seed(engine, USER_ID, "leave.md", [LEAVE, "The canteen opens at noon."])
    keys = {**api_keys(), "bob": ApiKeyEntry(sha256=digest_key(BOB_KEY).hex(), role=Role.USER)}
    app = create_app(
        make_settings(database_url=isolated_url, api_keys=keys, refusal_min_cosine=0.3),
        readiness_check=ready_ok,
        embedder=FakeEmbedder(),
    )
    with TestClient(app, backend_options=_SELECTOR, raise_server_exceptions=False) as test_client:
        test_client.database_url = isolated_url  # type: ignore[attr-defined]
        yield test_client


def ask(client: TestClient, key: str = USER_KEY, **body: Any) -> dict[str, Any]:
    payload = {"question": "carry over unused leave days", **body}
    response = client.post("/api/v1/chat", headers={"X-API-Key": key}, json=payload)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_an_answer_is_stored_with_citations_and_a_usage_event(client: TestClient) -> None:
    answer = ask(client)
    assert answer["verified"] and answer["citations"][0]["filename"] == "leave.md"
    assert "[1]" in answer["answer"]

    detail = client.get(
        f"/api/v1/conversations/{answer['conversation_id']}", headers={"X-API-Key": USER_KEY}
    ).json()
    assistant = detail["messages"][1]
    assert detail["messages"][0]["content"] == "carry over unused leave days"
    assert assistant["citations"] == answer["citations"]  # the JSON round trip is lossless

    engine = admin_engine(client.database_url)  # type: ignore[attr-defined]
    with engine.connect() as connection:
        usage = connection.execute(
            text("SELECT owner_id, mode, model, refused, retrieved, latency_ms FROM usage_events")
        ).all()
    assert len(usage) == 1
    assert tuple(usage[0])[:5] == (USER_ID, "verified", "fake-extractive", False, 2)
    assert usage[0].latency_ms >= 0


def test_a_streamed_answer_ends_with_the_same_stored_result(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers={"X-API-Key": USER_KEY},
        json={"question": "carry over unused leave days", "stream": True, "mode": "fast"},
    ) as response:
        text_body = "".join(response.iter_text())
    done = [
        json.loads(block.split("data: ", 1)[1])
        for block in text_body.split("\n\n")
        if block.startswith("event: done")
    ]
    assert len(done) == 1 and done[0]["verified"]
    detail = client.get(
        f"/api/v1/conversations/{done[0]['conversation_id']}", headers={"X-API-Key": USER_KEY}
    ).json()
    assert detail["messages"][1]["content"] == done[0]["answer"]


def test_deleting_a_conversation_removes_messages_and_keeps_usage_without_the_link(
    client: TestClient,
) -> None:
    answer = ask(client)
    response = client.delete(
        f"/api/v1/conversations/{answer['conversation_id']}", headers={"X-API-Key": USER_KEY}
    )
    assert response.status_code == 204
    engine = admin_engine(client.database_url)  # type: ignore[attr-defined]
    assert count(engine, "messages") == 0
    assert count(engine, "conversations") == 0
    assert count(engine, "usage_events") == 1
    assert count(engine, "usage_events", "conversation_id IS NULL") == 1


def test_another_user_cannot_see_or_continue_a_conversation(client: TestClient) -> None:
    answer = ask(client)
    headers = {"X-API-Key": BOB_KEY}
    url = f"/api/v1/conversations/{answer['conversation_id']}"
    assert client.get(url, headers=headers).status_code == 404
    assert client.delete(url, headers=headers).status_code == 404
    assert client.get("/api/v1/conversations", headers=headers).json()["items"] == []
    continued = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"question": "anything", "conversation_id": answer["conversation_id"]},
    )
    assert continued.status_code == 404
    assert client.get(url, headers={"X-API-Key": USER_KEY}).status_code == 200  # still intact


def test_a_user_without_documents_gets_a_refusal_and_no_model_call(client: TestClient) -> None:
    answer = ask(client, key=BOB_KEY)
    assert answer["refused"] and answer["refusal_reason"] == "no_passages"
    assert answer["citations"] == []


def _query_as(url: str, owner: str, role: Role, sql: str) -> list[Any]:
    async def scenario() -> list[Any]:
        database = Database(url)
        try:
            async with database.session_for(owner, role) as session:
                return list((await session.execute(text(sql))).all())
        finally:
            await database.dispose()

    return run_async(scenario)


def test_row_level_security_isolates_the_three_new_tables(client: TestClient) -> None:
    ask(client)
    url = client.database_url  # type: ignore[attr-defined]
    for table in ("conversations", "messages", "usage_events"):
        assert len(_query_as(url, "bob", Role.USER, f"SELECT 1 FROM {table}")) == 0, table
        assert len(_query_as(url, USER_ID, Role.USER, f"SELECT 1 FROM {table}")) >= 1, table


def test_admins_read_usage_events_but_not_conversations_or_messages(client: TestClient) -> None:
    ask(client)
    url = client.database_url  # type: ignore[attr-defined]
    assert len(_query_as(url, "root", Role.ADMIN, "SELECT 1 FROM usage_events")) == 1
    assert _query_as(url, "root", Role.ADMIN, "SELECT 1 FROM conversations") == []
    assert _query_as(url, "root", Role.ADMIN, "SELECT 1 FROM messages") == []
    assert ADMIN_KEY  # the admin key exists in the fixture's key set


def test_messages_are_append_only_for_the_api_role(client: TestClient) -> None:
    ask(client)
    url = client.database_url  # type: ignore[attr-defined]
    for statement in ("UPDATE messages SET content = 'edited'", "DELETE FROM messages"):
        with pytest.raises(DBAPIError, match="permission denied"):
            _query_as(url, USER_ID, Role.USER, statement)


def test_a_session_without_an_owner_sees_nothing(client: TestClient) -> None:
    ask(client)
    engine = admin_engine(client.database_url)  # type: ignore[attr-defined]
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE eka_api"))
        for table in ("conversations", "messages", "usage_events"):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_messages_come_back_in_the_order_they_were_written(client: TestClient) -> None:
    """Both messages of a turn are written in one transaction, so their timestamps are equal.
    Ordering by a random id would swap them about half the time; 20 turns make that certain."""
    for _ in range(20):
        answer = ask(client)
        detail = client.get(
            f"/api/v1/conversations/{answer['conversation_id']}", headers={"X-API-Key": USER_KEY}
        ).json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_history_is_oldest_first_and_limited_to_the_most_recent(client: TestClient) -> None:
    first = ask(client)
    conversation_id = first["conversation_id"]
    for _ in range(3):
        ask(client, conversation_id=conversation_id)
    detail = client.get(
        f"/api/v1/conversations/{conversation_id}", headers={"X-API-Key": USER_KEY}
    ).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 4
