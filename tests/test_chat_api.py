"""The chat endpoints over HTTP, with the real app, real authentication and in-memory ports."""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator, Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

import eka.api.chat as chat_module
from eka.domain.answering import REFUSAL_TEXT
from eka.domain.errors import ModelTimeout, ModelUnavailable
from eka.domain.models import ChatMessage
from eka.main import create_app
from tests.helpers import USER_KEY, make_settings, ready_ok
from tests.test_answering import GOOD, World

HEADERS = {"X-API-Key": USER_KEY}
QUESTION = "carry over unused leave days"


def make_client(world: World) -> TestClient:
    app = create_app(make_settings(), readiness_check=ready_ok, answer_service=world.service)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def world() -> Iterator[World]:
    from tests.fakes import ScriptedChatModel

    yield World(ScriptedChatModel([GOOD]))


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if not lines:
            continue
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


def post_stream(client: TestClient, **body: Any) -> tuple[int, str, str]:
    payload = {"question": QUESTION, "stream": True, **body}
    with client.stream("POST", "/api/v1/chat", headers=HEADERS, json=payload) as response:
        text = "".join(response.iter_text())
        return response.status_code, response.headers.get("content-type", ""), text


# --- JSON ---------------------------------------------------------------------------------------


def test_a_json_answer_has_the_documented_shape(world: World) -> None:
    with make_client(world) as client:
        response = client.post("/api/v1/chat", headers=HEADERS, json={"question": QUESTION})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {
        "conversation_id",
        "message_id",
        "answer",
        "citations",
        "refused",
        "refusal_reason",
        "mode",
        "verified",
    }
    assert body["answer"] == GOOD and body["mode"] == "verified" and body["verified"] is True
    assert body["citations"][0]["filename"] == "leave.md"
    assert body["citations"][0]["locator"] == {"type": "page", "page": 1}


def test_conversations_can_be_continued_listed_read_and_deleted(world: World) -> None:
    with make_client(world) as client:
        first = client.post("/api/v1/chat", headers=HEADERS, json={"question": QUESTION}).json()
        conversation_id = first["conversation_id"]
        again = client.post(
            "/api/v1/chat",
            headers=HEADERS,
            json={"question": QUESTION, "conversation_id": conversation_id},
        ).json()
        assert again["conversation_id"] == conversation_id

        listed = client.get("/api/v1/conversations", headers=HEADERS).json()
        assert [c["id"] for c in listed["items"]] == [conversation_id]

        detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=HEADERS).json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
        assert detail["messages"][1]["citations"][0]["filename"] == "leave.md"

        assert (
            client.delete(f"/api/v1/conversations/{conversation_id}", headers=HEADERS).status_code
            == 204
        )
        gone = client.get(f"/api/v1/conversations/{conversation_id}", headers=HEADERS)
        assert gone.status_code == 404 and gone.json()["type"] == "urn:eka:problem:not-found"


def test_an_unknown_conversation_is_a_404_problem_in_both_modes(world: World) -> None:
    body = {"question": QUESTION, "conversation_id": str(uuid.uuid4())}
    with make_client(world) as client:
        plain = client.post("/api/v1/chat", headers=HEADERS, json=body)
        streamed = client.post("/api/v1/chat", headers=HEADERS, json={**body, "stream": True})
    for response in (plain, streamed):
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "body",
    [
        {"question": ""},
        {"question": "x" * 1001},
        {"question": "ok", "top_k": 0},
        {"question": "ok", "top_k": 11},
        {"question": "ok", "mode": "turbo"},
        {"question": "ok", "conversation_id": "not-a-uuid"},
        {},
    ],
)
def test_invalid_requests_are_422_and_never_reach_the_model(
    world: World, body: dict[str, Any]
) -> None:
    with make_client(world) as client:
        response = client.post("/api/v1/chat", headers=HEADERS, json=body)
    assert response.status_code == 422
    assert world.model.stream_calls == []
    assert "input" not in json.dumps(response.json())  # the submitted value is not echoed


def test_model_failures_map_to_502_and_504_problems() -> None:
    from tests.fakes import ScriptedChatModel

    for error, status in (
        (ModelUnavailable("provider-secret-detail"), 502),
        (ModelTimeout("provider-secret-detail"), 504),
    ):
        world = World(ScriptedChatModel(stream_error=error))
        with make_client(world) as client:
            response = client.post("/api/v1/chat", headers=HEADERS, json={"question": QUESTION})
        assert response.status_code == status
        assert response.headers["content-type"].startswith("application/problem+json")
        assert "provider-secret-detail" not in response.text
        assert world.repo.conversations == {}


# --- streaming ----------------------------------------------------------------------------------


def test_a_stream_is_server_sent_events_in_the_documented_order(world: World) -> None:
    with make_client(world) as client:
        status, content_type, text = post_stream(client)
    assert status == 200 and content_type.startswith("text/event-stream")
    events = parse_sse(text)
    kinds = [name for name, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and set(kinds[1:-1]) == {"token"}
    assert events[0][1]["mode"] == "verified"
    assert "".join(data["text"] for name, data in events if name == "token") == GOOD
    done = events[-1][1]
    assert done["verified"] and done["citations"][0]["filename"] == "leave.md"


def test_fast_mode_marks_tokens_provisional(world: World) -> None:
    with make_client(world) as client:
        _, _, text = post_stream(client, mode="fast")
    tokens = [data for name, data in parse_sse(text) if name == "token"]
    assert len(tokens) > 3 and all(t["provisional"] for t in tokens)


def test_a_failure_after_the_stream_started_is_an_error_event(world: World) -> None:
    from tests.fakes import ScriptedChatModel

    failing = World(ScriptedChatModel(stream_error=ModelUnavailable("provider said no")))
    with make_client(failing) as client:
        status, _, text = post_stream(client)
    assert status == 200  # headers were already sent
    events = parse_sse(text)
    assert [name for name, _ in events] == ["meta", "error"]
    assert events[1][1]["status"] == 502 and events[1][1]["type"].endswith("model-unavailable")
    assert "provider said no" not in text
    assert failing.repo.conversations == {}


class _SlowFirstToken:
    """A model that waits before its first fragment, so the stream is idle for a while."""

    model_name = "slow"

    async def complete(self, messages: Sequence[ChatMessage], *, max_tokens: int) -> str:
        return GOOD

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        await asyncio.sleep(0.25)
        for word in GOOD.split(" "):
            yield word + " "


def test_idle_streams_send_heartbeat_comments(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_module, "HEARTBEAT_SECONDS", 0.05)
    slow = World(_SlowFirstToken())  # type: ignore[arg-type]
    with make_client(slow) as client:
        _, _, text = post_stream(client, mode="fast")
    assert text.count(": heartbeat") >= 2
    events = parse_sse(text)  # heartbeats are comments: they do not disturb the events
    assert events[0][0] == "meta" and events[-1][0] == "done"


def test_a_refusal_is_still_a_complete_stream(world: World) -> None:
    with make_client(world) as client:
        _, _, text = post_stream(client, question="zebra giraffe quantum")
    events = parse_sse(text)
    assert [name for name, _ in events] == ["meta", "token", "done"]
    assert events[1][1] == {"text": REFUSAL_TEXT, "provisional": False}
    assert events[2][1]["refused"] is True and events[2][1]["refusal_reason"] == "weak_evidence"
    assert world.model.stream_calls == []
