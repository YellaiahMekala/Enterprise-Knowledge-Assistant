# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""PDF loader: one segment per page, locator ``{"type": "page", "page": n}`` (1-based)."""

import io

from pypdf import PdfReader

from eka.domain.errors import CORRUPT, ENCRYPTED, TOO_LARGE, PermanentIngestionError
from eka.domain.models import ParseLimits, Segment


def load_pdf(data: bytes, limits: ParseLimits) -> tuple[list[Segment], int]:
    """Returns the page segments and the page count. Pages without extractable text are skipped
    (image-only pages: OCR is out of scope); the caller fails the document if none remain."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PermanentIngestionError(ENCRYPTED)
        page_count = len(reader.pages)
    except PermanentIngestionError:
        raise
    except Exception as error:  # pypdf raises many types for damaged files
        raise PermanentIngestionError(CORRUPT) from error
    if page_count == 0:
        raise PermanentIngestionError(CORRUPT)
    if page_count > limits.max_pages:
        raise PermanentIngestionError(TOO_LARGE)

    segments: list[Segment] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as error:
            raise PermanentIngestionError(CORRUPT) from error
        if text.strip():
            segments.append(Segment(text, {"type": "page", "page": number}))
    return segments, page_count
