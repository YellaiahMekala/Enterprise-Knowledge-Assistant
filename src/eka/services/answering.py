"""Answering: retrieve, gate, generate, verify citations, store (TDD 4.7, ADR-031).

Order of work for one question, each database step in its own short transaction so no connection
is held while the chat model runs:

1. load the conversation and its recent messages; rewrite a follow-up into a standalone question;
2. retrieve passages; refuse without calling the model when the best cosine is below the gate;
3. generate. In ``verified`` mode the whole reply is checked before any of it is released; in
   ``fast`` mode text streams at once, marked provisional, and a ``replace`` event corrects it if
   the check fails;
4. store the question, the answer with server-resolved citations, and a usage event.

Citations are numbers in the answer text. They are resolved against the passages that were sent,
so the model cannot invent a source: a number outside the sent range makes the answer unverified.
A client that disconnects cancels the generator; nothing is stored for a cancelled answer.
"""

import logging
import re
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, aclosing
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from eka.domain.answering import (
    INSUFFICIENT_EVIDENCE,
    REASON_MODEL_DECLINED,
    REASON_NO_PASSAGES,
    REASON_UNVERIFIED,
    REASON_WEAK_EVIDENCE,
    REFUSAL_TEXT,
    UNVERIFIED_TEXT,
)
from eka.domain.errors import EkaError, NotFound
from eka.domain.models import (
    AnswerMode,
    ChatMessage,
    Citation,
    Conversation,
    Role,
    SearchFilters,
    SearchHit,
    StoredMessage,
    TokenUsage,
    UsageEvent,
)
from eka.ports.chat import ChatModel
from eka.ports.embedder import Embedder
from eka.ports.repositories import ConversationRepository
from eka.services.grounding import misattributed
from eka.services.prompt import build_answer_messages, build_rewrite_messages, select_passages
from eka.services.retrieval import EmbedderProvider, RetrievalService
from eka.services.web_fallback import WebFallback

logger = logging.getLogger(__name__)

_CITATION = re.compile(r"\[(\d{1,3})\]")
_QUOTE_CHARS = 300
_TITLE_CHARS = 60
_RELEASE_PIECE_CHARS = 80
_RETRY_NOTE = (
    "Your previous reply cited a passage that does not exist, cited a passage that does not "
    "contain the statement, or cited none. Answer again, citing for each statement the passage "
    "that contains it, or reply exactly " + INSUFFICIENT_EVIDENCE + "."
)


# (text, citations, refused, refusal reason, verified)
Outcome = tuple[str, tuple[Citation, ...], bool, str | None, bool]


@dataclass(frozen=True, slots=True)
class AnswerSettings:
    default_mode: AnswerMode = "verified"
    min_cosine: float = 0.50
    context_passages: int = 5
    max_context_chars: int = 12_000
    history_messages: int = 6
    max_output_tokens: int = 600
    # US dollars per million tokens; the cost stays empty unless both are set (ADR-037).
    price_input_per_1m: float | None = None
    price_output_per_1m: float | None = None


@dataclass(slots=True)
class _Timing:
    """Seconds on the service clock: first model fragment, and first text sent to the client."""

    first_fragment: float | None = None
    first_text: float | None = None


def cost_usd(tokens: TokenUsage, settings: AnswerSettings) -> float | None:
    if tokens.calls == 0 or settings.price_input_per_1m is None:
        return None
    if settings.price_output_per_1m is None:
        return None
    return round(
        tokens.prompt_tokens * settings.price_input_per_1m / 1_000_000
        + tokens.completion_tokens * settings.price_output_per_1m / 1_000_000,
        6,
    )


@dataclass(frozen=True, slots=True)
class AnswerScope:
    """What one short database transaction offers the service."""

    conversations: ConversationRepository
    retrieval: Callable[[Embedder], RetrievalService]


ScopeFactory = Callable[[str, Role], AbstractAsyncContextManager[AnswerScope]]


@dataclass(frozen=True, slots=True)
class AnswerEvent:
    """``type`` is meta, token, replace or done; ``data`` is the JSON payload of that event."""

    type: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    cited: tuple[int, ...]
    declined: bool
    misattributed: tuple[int, ...] = ()


def verify(text: str, passage_count: int, passages: Sequence[str] = ()) -> Verdict:
    """Check a reply. It is valid when it cites at least one passage, only passages that were
    sent, and (when ``passages`` is given) no citation that another passage clearly supports
    better (``grounding.misattributed``). The "insufficient evidence" sentinel is a decline."""
    stripped = text.strip()
    if stripped.rstrip(".") == INSUFFICIENT_EVIDENCE:
        return Verdict(ok=False, cited=(), declined=True)
    cited: list[int] = []
    for match in _CITATION.finditer(stripped):
        number = int(match.group(1))
        if number not in cited:
            cited.append(number)
    ok = bool(cited) and all(1 <= n <= passage_count for n in cited)
    wrong = misattributed(stripped, passages) if ok and passages else ()
    return Verdict(ok=ok and not wrong, cited=tuple(cited), declined=False, misattributed=wrong)


def _citation(index: int, hit: SearchHit) -> Citation:
    return Citation(
        index=index,
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        filename=hit.filename,
        locator=hit.locator,
        quote=hit.text[:_QUOTE_CHARS],
        source_url=hit.source_url,
        fetched_at=hit.fetched_at,
    )


def citation_payload(citation: Citation) -> dict[str, Any]:
    return {
        "index": citation.index,
        "chunk_id": str(citation.chunk_id),
        "document_id": str(citation.document_id),
        "filename": citation.filename,
        "locator": dict(citation.locator),
        "quote": citation.quote,
        "kind": citation.kind,
        "source_url": citation.source_url,
        "fetched_at": citation.fetched_at.isoformat() if citation.fetched_at else None,
    }


def _title(question: str) -> str:
    collapsed = " ".join(question.split())
    return collapsed[:_TITLE_CHARS] or "Conversation"


class AnswerService:
    def __init__(
        self,
        scope: ScopeFactory,
        model: ChatModel,
        embedder: EmbedderProvider,
        settings: AnswerSettings,
        *,
        clock: Callable[[], float] = time.monotonic,
        web: WebFallback | None = None,
        on_usage: Callable[[UsageEvent], None] | None = None,
    ) -> None:
        self._on_usage = on_usage
        self._scope = scope
        self._web = web
        self._model = model
        self._embedder = embedder
        self._settings = settings
        self._clock = clock

    # --- conversations ---------------------------------------------------------------------

    async def list_conversations(
        self, owner_id: str, role: Role, *, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        async with self._scope(owner_id, role) as scope:
            return await scope.conversations.list_by_owner(owner_id, limit=limit, offset=offset)

    async def get_conversation(
        self, owner_id: str, role: Role, conversation_id: UUID
    ) -> tuple[Conversation, list[StoredMessage]]:
        async with self._scope(owner_id, role) as scope:
            conversation = await scope.conversations.get(owner_id, conversation_id)
            if conversation is None:
                raise NotFound()
            return conversation, await scope.conversations.messages(owner_id, conversation_id)

    async def delete_conversation(self, owner_id: str, role: Role, conversation_id: UUID) -> None:
        async with self._scope(owner_id, role) as scope:
            if not await scope.conversations.delete(owner_id, conversation_id):
                raise NotFound()

    # --- asking ----------------------------------------------------------------------------

    async def ask(
        self,
        owner_id: str,
        role: Role,
        question: str,
        *,
        conversation_id: UUID | None = None,
        top_k: int = 5,
        mode: AnswerMode | None = None,
    ) -> AsyncGenerator[AnswerEvent, None]:
        mode = mode or self._settings.default_mode
        started = self._clock()
        conversation, history, created = await self._open_conversation(
            owner_id, role, question, conversation_id
        )
        try:
            # aclosing: when this generator is closed (a client left), the nested one is closed
            # at once, which in turn closes the request to the language model.
            async with aclosing(
                self._answer(owner_id, role, question, conversation, history, top_k, mode, started)
            ) as events:
                async for event in events:
                    yield event
        except BaseException:
            if created:
                await self._discard(owner_id, role, conversation.id)
            raise

    async def _open_conversation(
        self, owner_id: str, role: Role, question: str, conversation_id: UUID | None
    ) -> tuple[Conversation, list[StoredMessage], bool]:
        async with self._scope(owner_id, role) as scope:
            if conversation_id is None:
                conversation = await scope.conversations.create(owner_id, _title(question))
                return conversation, [], True
            existing = await scope.conversations.get(owner_id, conversation_id)
            if existing is None:
                raise NotFound()
            recent = await scope.conversations.messages(
                owner_id, conversation_id, limit=self._settings.history_messages
            )
            return existing, recent, False

    async def _discard(self, owner_id: str, role: Role, conversation_id: UUID) -> None:
        """Remove a conversation created for an answer that never completed."""
        try:
            async with self._scope(owner_id, role) as scope:
                await scope.conversations.delete(owner_id, conversation_id)
        except Exception:
            logger.warning("could not remove unfinished conversation", exc_info=True)

    async def _answer(
        self,
        owner_id: str,
        role: Role,
        question: str,
        conversation: Conversation,
        history: list[StoredMessage],
        top_k: int,
        mode: AnswerMode,
        started: float,
    ) -> AsyncGenerator[AnswerEvent, None]:
        yield AnswerEvent("meta", {"conversation_id": str(conversation.id), "mode": mode})
        tokens = TokenUsage()
        timing = _Timing()

        standalone = await self._standalone(question, history, tokens)
        embedder = await self._embedder()
        async with self._scope(owner_id, role) as scope:
            hits = await scope.retrieval(embedder).search(
                owner_id, standalone, top_k=top_k, filters=SearchFilters()
            )
        best = max((h.cosine for h in hits), default=None)

        web_used = False
        if self._web is not None and (best is None or best < self._settings.min_cosine):
            web_ids = await self._web.refresh(owner_id, role)
            if web_ids:
                async with self._scope(owner_id, role) as scope:
                    hits = await scope.retrieval(embedder).search(
                        owner_id,
                        standalone,
                        top_k=top_k,
                        filters=SearchFilters(document_ids=web_ids),
                    )
                best = max((h.cosine for h in hits), default=None)
                web_used = True

        generated = False
        result: Outcome | None
        if not hits:
            result = (REFUSAL_TEXT, (), True, REASON_NO_PASSAGES, True)
        elif best is not None and best < self._settings.min_cosine:
            result = (REFUSAL_TEXT, (), True, REASON_WEAK_EVIDENCE, True)
        else:
            generated = True
            passages = select_passages(
                hits,
                limit=self._settings.context_passages,
                max_chars=self._settings.max_context_chars,
            )
            messages = build_answer_messages(standalone, passages, history)
            result = None
            async with aclosing(
                self._generate(messages, passages, mode, tokens, timing)
            ) as generated_events:
                async for event, final in generated_events:
                    if event is not None:
                        if timing.first_text is None and event.type in ("token", "replace"):
                            timing.first_text = self._clock()
                        yield event
                    if final is not None:
                        result = final
            assert result is not None

        text, citations, refused, reason, verified = result
        if refused and not (generated and mode == "fast"):
            # Nothing was streamed for this text yet (fast mode already sent a replace event).
            if timing.first_text is None:
                timing.first_text = self._clock()
            yield AnswerEvent("token", {"text": text, "provisional": False})
        usage = UsageEvent(
            conversation_id=conversation.id,
            mode=mode,
            model=tokens.model or self._model.model_name,
            refused=refused,
            retrieved=len(hits),
            top_cosine=best,
            prompt_chars=len(standalone) + sum(len(h.text) for h in hits),
            completion_chars=len(text),
            latency_ms=_ms(self._clock() - started),
            provider=tokens.provider,
            prompt_tokens=tokens.prompt_tokens if tokens.calls else None,
            completion_tokens=tokens.completion_tokens if tokens.calls else None,
            token_source=("estimated" if tokens.estimated else "provider")
            if tokens.calls
            else None,
            cost_usd=cost_usd(tokens, self._settings),
            ttft_ms=_ms(timing.first_fragment - started) if timing.first_fragment else None,
            answer_ttfb_ms=_ms(timing.first_text - started) if timing.first_text else None,
        )
        completion = await self._persist(
            owner_id,
            role,
            conversation,
            question,
            text,
            citations,
            refused,
            reason,
            usage=usage,
        )
        if self._on_usage is not None:
            try:
                self._on_usage(usage)
            except Exception:
                logger.warning("usage observer failed", exc_info=True)
        yield AnswerEvent(
            "done",
            {
                "conversation_id": str(conversation.id),
                "message_id": str(completion.id),
                "answer": text,
                "citations": [citation_payload(c) for c in citations],
                "refused": refused,
                "refusal_reason": reason,
                "mode": mode,
                "verified": verified,
                "web_fallback": web_used,
            },
        )

    # --- steps -----------------------------------------------------------------------------

    async def _standalone(
        self, question: str, history: list[StoredMessage], tokens: TokenUsage
    ) -> str:
        """Rewrite a follow-up into a standalone question. Falls back to the original text."""
        if not history:
            return question
        try:
            rewritten = await self._model.complete(
                build_rewrite_messages(history, question), max_tokens=120, usage=tokens
            )
        except EkaError:
            logger.warning("question rewrite failed; using the original question", exc_info=True)
            return question
        rewritten = " ".join(rewritten.split())
        return rewritten[:1000] if rewritten else question

    async def _generate(
        self,
        messages: list[ChatMessage],
        passages: list[SearchHit],
        mode: AnswerMode,
        tokens: TokenUsage,
        timing: _Timing,
    ) -> AsyncGenerator[tuple[AnswerEvent | None, Outcome | None], None]:
        """Yield ``(event, None)`` while generating and ``(None, result)`` once at the end."""
        max_tokens = self._settings.max_output_tokens
        parts: list[str] = []
        stream_of = self._model.stream(messages, max_tokens=max_tokens, usage=tokens)
        async with aclosing(stream_of) as stream:
            async for fragment in stream:
                if timing.first_fragment is None:
                    timing.first_fragment = self._clock()
                parts.append(fragment)
                if mode == "fast":
                    yield AnswerEvent("token", {"text": fragment, "provisional": True}), None
        text = "".join(parts).strip()
        verdict = verify(text, len(passages), [p.text for p in passages])

        if not verdict.ok and not verdict.declined and mode == "verified":
            retry = [*messages, ChatMessage("assistant", text), ChatMessage("user", _RETRY_NOTE)]
            text = (await self._model.complete(retry, max_tokens=max_tokens, usage=tokens)).strip()
            verdict = verify(text, len(passages), [p.text for p in passages])

        if verdict.ok:
            citations = tuple(_citation(n, passages[n - 1]) for n in verdict.cited)
            if mode == "verified":
                for start in range(0, len(text), _RELEASE_PIECE_CHARS):
                    piece = text[start : start + _RELEASE_PIECE_CHARS]
                    yield AnswerEvent("token", {"text": piece, "provisional": False}), None
            yield None, (text, citations, False, None, True)
            return

        if verdict.misattributed:
            logger.info("answer cited passages that do not support it: %s", verdict.misattributed)
        reason = REASON_MODEL_DECLINED if verdict.declined else REASON_UNVERIFIED
        replacement = REFUSAL_TEXT if verdict.declined else UNVERIFIED_TEXT
        if mode == "fast":
            yield AnswerEvent("replace", {"text": replacement}), None
        yield None, (replacement, (), True, reason, True)

    async def _persist(
        self,
        owner_id: str,
        role: Role,
        conversation: Conversation,
        question: str,
        text: str,
        citations: tuple[Citation, ...],
        refused: bool,
        reason: str | None,
        *,
        usage: UsageEvent,
    ) -> StoredMessage:
        async with self._scope(owner_id, role) as scope:
            repo = scope.conversations
            await repo.add_message(owner_id, conversation.id, role="user", content=question)
            stored = await repo.add_message(
                owner_id,
                conversation.id,
                role="assistant",
                content=text,
                citations=citations,
                refused=refused,
                refusal_reason=reason,
            )
            await repo.record_usage(owner_id, usage)
            return stored


def _ms(seconds: float) -> int:
    return int(seconds * 1000)


async def collect_final(events: AsyncIterator[AnswerEvent]) -> dict[str, Any]:
    """Run ``events`` to the end and return the payload of the ``done`` event."""
    final: dict[str, Any] | None = None
    async for event in events:
        if event.type == "done":
            final = event.data
    if final is None:  # pragma: no cover - ask() always ends with done or raises
        raise RuntimeError("answer ended without a result")
    return final
