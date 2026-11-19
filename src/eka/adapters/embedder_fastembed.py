# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Local embeddings with fastembed (ONNX, no PyTorch) (TDD 4.5, ADR-005).

The model is loaded once, at construction, from a cache directory; construction fails if the
model cannot be loaded or its dimension differs from the database column. Vectors come back
L2-normalised, which is what the ``vector_cosine_ops`` index expects.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastembed import TextEmbedding

_BATCH = 32


class FastEmbedEmbedder:
    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        expected_dimension: int,
        *,
        query_prefix: str = "",
    ) -> None:
        # Text put before every query, never before a document (experiment E5). Empty by default.
        self.query_prefix = query_prefix
        model: Any = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
        self._model = model
        self.model_name = model_name
        self.dimension = int(TextEmbedding.get_embedding_size(model_name))
        if self.dimension != expected_dimension:
            raise RuntimeError(
                f"embedding model has {self.dimension} dimensions, "
                f"the database column has {expected_dimension}"
            )
        self._tokenizer = model.model.tokenizer

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(list(texts), batch_size=_BATCH)]

    def embed_query(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._model.query_embed(self.query_prefix + text)))]
