# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Web page port for the optional web fallback (ADR-030)."""

from typing import Protocol

from eka.domain.models import WebPage


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> WebPage:
        """The page at ``url``; raises ``WebFetchRefused`` for anything the policy forbids."""
        ...
