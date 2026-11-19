# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Cross-encoder reranking with fastembed (ONNX). The model loads on first use, so a deployment
that leaves reranking off never downloads it."""

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastembed.rerank.cross_encoder import TextCrossEncoder


class FastEmbedReranker:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self._cache_dir = cache_dir
        self._model: Any = None
        self._lock = threading.Lock()

    def _loaded(self) -> Any:
        with self._lock:
            if self._model is None:
                self._model = TextCrossEncoder(
                    model_name=self.model_name, cache_dir=str(self._cache_dir)
                )
            return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in self._loaded().rerank(query, list(passages))]
