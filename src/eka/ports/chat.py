"""Chat model port (TDD 4.7, ADR-006). Calls are asynchronous and may be cancelled; closing the
generator returned by ``stream`` must stop the request to the provider."""

from collections.abc import AsyncGenerator, Sequence
from typing import Protocol

from eka.domain.models import ChatMessage


class ChatModel(Protocol):
    model_name: str

    async def complete(self, messages: Sequence[ChatMessage], *, max_tokens: int) -> str:
        """The whole reply. Raises ``ModelUnavailable`` or ``ModelTimeout``."""
        ...

    def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        """The reply as text fragments, in order. Raises like ``complete``."""
        ...
