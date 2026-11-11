"""Chat endpoints: ask a question, read and delete conversations (TDD 6.1, 6.3, ADR-031).

``POST /api/v1/chat`` returns JSON, or a server-sent event stream when ``stream`` is true.
Stream events, each ``event: <name>`` then ``data: <json>``:

* ``meta``: ``conversation_id`` and ``mode``;
* ``token``: ``text`` and ``provisional`` (true only in fast mode);
* ``replace``: ``text``; fast mode only, when the streamed text failed verification;
* ``done``: the final answer, ``citations``, ``refused``, ``refusal_reason``, ``verified``;
* ``error``: ``status``, ``type``, ``detail``; the stream ends after it.

A line starting with ``:`` is a heartbeat and carries no data.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from eka.api.deps import AnswerServices, CurrentPrincipal
from eka.api.schemas import NOT_FOUND_RESPONSE, UNAUTHORIZED_RESPONSE
from eka.domain.errors import EkaError, ModelTimeout, ModelUnavailable, NotFound, Unavailable
from eka.domain.models import Conversation, StoredMessage
from eka.services.answering import AnswerEvent, collect_final
from eka.services.retrieval import MAX_QUERY_CHARS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])

HEARTBEAT_SECONDS = 15.0

_CHAT_ERRORS: dict[int | str, dict[str, object]] = {
    **UNAUTHORIZED_RESPONSE,
    **NOT_FOUND_RESPONSE,
    502: {"description": "The language model could not answer."},
    504: {"description": "The language model timed out."},
}


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    conversation_id: UUID | None = Field(
        default=None, description="Continue this conversation; omit to start a new one."
    )
    top_k: int = Field(default=5, ge=1, le=10, description="Passages to retrieve.")
    mode: Literal["verified", "fast"] | None = Field(
        default=None,
        description="verified releases text after its citations are checked; fast streams at once.",
    )
    stream: bool = Field(default=False, description="Return text/event-stream instead of JSON.")


class CitationOut(BaseModel):
    index: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    locator: dict[str, Any]
    quote: str
    kind: Literal["document", "web"] = Field(
        default="document", description="web: a page fetched by the web fallback (ADR-030)."
    )
    source_url: str | None = None
    fetched_at: datetime | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    citations: list[CitationOut]
    refused: bool
    refusal_reason: str | None
    mode: Literal["verified", "fast"]
    verified: bool
    web_fallback: bool = Field(
        default=False, description="The answer used pages fetched by the web fallback (ADR-030)."
    )


class MessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationOut]
    refused: bool
    refusal_reason: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, message: StoredMessage) -> "MessageOut":
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            citations=[
                CitationOut(
                    index=c.index,
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    filename=c.filename,
                    locator=dict(c.locator),
                    quote=c.quote,
                    kind=c.kind,
                    source_url=c.source_url,
                    fetched_at=c.fetched_at,
                )
                for c in message.citations
            ],
            refused=message.refused,
            refusal_reason=message.refusal_reason,
            created_at=message.created_at,
        )


class ConversationOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationOut":
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationList(BaseModel):
    items: list[ConversationOut]
    limit: int
    offset: int


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_event(error: BaseException) -> str:
    if isinstance(error, ModelTimeout):
        status, slug, detail = 504, "model-timeout", "The language model took too long to answer."
    elif isinstance(error, ModelUnavailable):
        status, slug, detail = 502, "model-unavailable", "The language model could not answer."
    elif isinstance(error, NotFound):
        status, slug, detail = 404, "not-found", "No such resource."
    elif isinstance(error, Unavailable):
        status, slug, detail = 503, "unavailable", "A required service is unavailable."
    else:
        logger.error("unhandled error while streaming an answer", exc_info=error)
        status, slug, detail = 500, "internal", "An unexpected error occurred."
    return _sse("error", {"status": status, "type": f"urn:eka:problem:{slug}", "detail": detail})


async def _event_stream(
    first: AnswerEvent, events: AsyncGenerator[AnswerEvent, None], heartbeat: float
) -> AsyncIterator[str]:
    """Format events as SSE. A heartbeat comment is sent whenever the next event takes longer
    than ``heartbeat`` seconds. If the client goes away this generator is cancelled and the
    answer generator is closed, which closes the request to the language model."""
    yield _sse(first.type, first.data)
    pending: asyncio.Task[AnswerEvent] | None = None

    async def next_event() -> AnswerEvent:
        return await events.__anext__()

    try:
        while True:
            pending = asyncio.create_task(next_event())
            while True:
                finished, _ = await asyncio.wait({pending}, timeout=heartbeat)
                if finished:
                    break
                yield ": heartbeat\n\n"
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            except (EkaError, Exception) as error:
                yield _error_event(error)
                return
            pending = None
            yield _sse(event.type, event.data)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pending
        with contextlib.suppress(Exception):
            await events.aclose()


@router.post("/chat", response_model=ChatResponse, responses=_CHAT_ERRORS)
async def chat(body: ChatRequest, principal: CurrentPrincipal, answers: AnswerServices) -> Response:
    """Ask a question about the caller's documents. The answer cites the passages it used; when
    the evidence is weak or the citations cannot be verified the answer says so instead."""
    events = answers.ask(
        principal.user_id,
        principal.role,
        body.question,
        conversation_id=body.conversation_id,
        top_k=body.top_k,
        mode=body.mode,
    )
    if not body.stream:
        final = await collect_final(events)
        payload = ChatResponse.model_validate(final)
        return Response(payload.model_dump_json(), media_type="application/json")

    try:
        first = await events.__anext__()  # errors before the first event are ordinary responses
    except BaseException:
        await events.aclose()
        raise
    return StreamingResponse(
        _event_stream(first, events, HEARTBEAT_SECONDS),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=ConversationList, responses=UNAUTHORIZED_RESPONSE)
async def list_conversations(
    principal: CurrentPrincipal,
    answers: AnswerServices,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ConversationList:
    items = await answers.list_conversations(
        principal.user_id, principal.role, limit=limit, offset=offset
    )
    return ConversationList(
        items=[ConversationOut.from_domain(c) for c in items], limit=limit, offset=offset
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    responses={**UNAUTHORIZED_RESPONSE, **NOT_FOUND_RESPONSE},
)
async def get_conversation(
    conversation_id: UUID, principal: CurrentPrincipal, answers: AnswerServices
) -> ConversationDetail:
    conversation, messages = await answers.get_conversation(
        principal.user_id, principal.role, conversation_id
    )
    return ConversationDetail(
        **ConversationOut.from_domain(conversation).model_dump(),
        messages=[MessageOut.from_domain(m) for m in messages],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    responses={**UNAUTHORIZED_RESPONSE, **NOT_FOUND_RESPONSE},
)
async def delete_conversation(
    conversation_id: UUID, principal: CurrentPrincipal, answers: AnswerServices
) -> Response:
    await answers.delete_conversation(principal.user_id, principal.role, conversation_id)
    return Response(status_code=204)
