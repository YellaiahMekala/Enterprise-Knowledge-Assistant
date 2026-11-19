# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Chat model port (TDD 4.7, ADR-006). Calls are asynchronous and may be cancelled; closing the
generator returned by ``stream`` must stop the request to the provider."""

from collections.abc import AsyncGenerator, Sequence
from typing import Protocol

from eka.domain.models import ChatMessage, TokenUsage


class ChatModel(Protocol):
    model_name: str

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> str:
        """The whole reply. Raises ``ModelUnavailable`` or ``ModelTimeout``. When ``usage`` is
        given, the adapter adds the call's token counts to it (ADR-037)."""
        ...

    def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int, usage: TokenUsage | None = None
    ) -> AsyncGenerator[str, None]:
        """The reply as text fragments, in order. Raises like ``complete``."""
        ...
