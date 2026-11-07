"""A deterministic chat model that needs no network and no key (TDD 4.7, decision D-5).

It reads the numbered passages in the prompt, picks the sentence that shares the most words with
the question, and answers with that sentence and its passage number. It is a development and test
stand-in, not a language model: it cannot paraphrase or combine passages.
"""

import asyncio
import re
from collections.abc import AsyncGenerator, Sequence

from eka.domain.answering import INSUFFICIENT_EVIDENCE, REWRITE_MARKER
from eka.domain.models import ChatMessage

_PASSAGE = re.compile(r'<passage n="(\d+)"[^>]*>\n(.*?)\n</passage>', re.DOTALL)
_QUESTION = re.compile(r"^Question: (.*)$", re.MULTILINE)
_FOLLOW_UP = re.compile(r"^Follow-up question: (.*)$", re.MULTILINE)
_WORD = re.compile(r"[a-z0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    ]
)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


class FakeChatModel:
    model_name = "fake-extractive"

    def _reply(self, messages: Sequence[ChatMessage]) -> str:
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if REWRITE_MARKER in system:
            match = _FOLLOW_UP.search(user)
            return match.group(1).strip() if match else user.strip()
        question = _QUESTION.search(user)
        wanted = _words(question.group(1)) if question else set()
        best: tuple[int, str, str] = (0, "", "")
        for number, body in _PASSAGE.findall(user):
            for sentence in _SENTENCE.split(body):
                score = len(wanted & _words(sentence))
                if score > best[0]:
                    best = (score, sentence.strip(), number)
        if best[0] == 0:
            return INSUFFICIENT_EVIDENCE
        return f"{best[1]} [{best[2]}]"

    async def complete(self, messages: Sequence[ChatMessage], *, max_tokens: int) -> str:
        return self._reply(messages)

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        for word in self._reply(messages).split(" "):
            await asyncio.sleep(0)
            yield word + " "
