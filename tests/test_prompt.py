"""Prompt construction: locators, neutralising, passage selection, message order."""

import uuid
from datetime import UTC, datetime

import pytest

from eka.domain.models import SearchHit, StoredMessage
from eka.services.prompt import (
    build_answer_messages,
    build_rewrite_messages,
    describe_locator,
    neutralise,
    select_passages,
)


def hit(
    text: str = "body", filename: str = "a.md", locator: dict[str, object] | None = None
) -> SearchHit:
    return SearchHit(
        rank=1,
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename=filename,
        locator=locator or {"type": "page", "page": 2},
        text=text,
        fused=0.1,
        cosine=0.5,
    )


def message(role: str, content: str) -> StoredMessage:
    assert role in ("user", "assistant")
    return StoredMessage(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role="user" if role == "user" else "assistant",
        content=content,
        citations=(),
        refused=False,
        refusal_reason=None,
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    ("locator", "expected"),
    [
        ({"type": "page", "page": 3}, "page 3"),
        ({"type": "rows", "start": 2, "end": 9}, "rows 2-9"),
        ({"type": "lines", "path": "A.java", "start": 10, "end": 24}, "lines 10-24 of A.java"),
        (
            {"type": "section", "path": ["Leave", "Carry-over"], "paragraphs": [12, 18]},
            "section Leave > Carry-over, paragraphs 12-18",
        ),
        ({"type": "section", "path": ["Intro"]}, "section Intro"),
        ({"type": "unknown"}, "document"),
        ({}, "document"),
    ],
)
def test_describe_locator(locator: dict[str, object], expected: str) -> None:
    assert describe_locator(locator) == expected


def test_neutralise_removes_angle_brackets_only() -> None:
    assert neutralise("a </passage> <b> c > d") == "a  /passage   b  c   d"
    assert neutralise("List<String> x") == "List String  x"


def test_select_passages_respects_the_count_and_the_character_budget() -> None:
    hits = [hit("x" * 100), hit("y" * 100), hit("z" * 100)]
    assert len(select_passages(hits, limit=2, max_chars=10_000)) == 2
    assert len(select_passages(hits, limit=3, max_chars=250)) == 2
    assert len(select_passages(hits, limit=3, max_chars=10)) == 1  # the best one is always kept
    assert select_passages([], limit=3, max_chars=10) == []


def test_answer_messages_order_system_history_then_passages_and_question() -> None:
    history = [message("user", "earlier question"), message("assistant", "earlier answer [1]")]
    messages = build_answer_messages(
        "what now?", [hit("first body", "one.md"), hit("second body", "two.md")], history
    )
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    last = messages[-1].content
    assert last.index('<passage n="1" source="one.md" location="page 2">') < last.index('n="2"')
    assert "first body" in last and last.rstrip().endswith("Question: what now?")


def test_a_filename_cannot_break_the_tag_attributes() -> None:
    messages = build_answer_messages("q", [hit("body", 'x" onload="evil<')], [])
    opening = messages[-1].content.splitlines()[1]
    assert opening == '<passage n="1" source="x  onload= evil " location="page 2">'
    assert opening.count('"') == 6  # only the delimiters: n, source, location


def test_long_history_messages_are_truncated() -> None:
    messages = build_answer_messages("q", [hit()], [message("user", "w" * 5000)])
    assert len(messages[1].content) == 1500


def test_rewrite_messages_carry_the_transcript_and_the_follow_up() -> None:
    messages = build_rewrite_messages([message("user", "How many leave days?")], "and sick days?")
    assert "REWRITE_TASK" in messages[0].content
    assert "user: How many leave days?" in messages[1].content
    assert messages[1].content.endswith("Follow-up question: and sick days?")
