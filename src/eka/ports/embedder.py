"""Embedding port (TDD 4.5, ADR-005). The calls are synchronous and CPU-bound; async callers
run them in a worker thread."""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimension: int

    def count_tokens(self, text: str) -> int:
        """Tokens the model would see for ``text`` (without the two special tokens). The chunker
        uses this so chunk sizes are exact. May report at most the model's input limit."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One L2-normalised vector per text, in order."""
        ...

    def embed_query(self, text: str) -> list[float]: ...
