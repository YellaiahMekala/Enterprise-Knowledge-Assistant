# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Reranker port (ADR-005 style): a second, slower model that re-orders a short candidate list.
Calls are synchronous and CPU-bound; async callers run them in a worker thread."""

from collections.abc import Sequence
from typing import Protocol


class Reranker(Protocol):
    model_name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """One relevance score per passage, in order. Higher is more relevant. The scale is
        model specific and only meaningful within one call."""
        ...
