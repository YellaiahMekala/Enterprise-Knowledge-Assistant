# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""DOCX loader: one segment per heading section, in body order, tables flattened row by row.

DOCX has no fixed pages (BRD R4), so the locator is the heading path plus the paragraph range
(1-based indexes of body blocks, so a reader can find the text in Word):
``{"type": "section", "path": ["Leave", "Carry-over"], "paragraphs": [12, 18]}``.
"""

import io
import re
from dataclasses import dataclass, field

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from eka.domain.errors import CORRUPT, PermanentIngestionError
from eka.domain.models import Segment

_HEADING = re.compile(r"^(Heading|Title)\s*(\d*)$", re.IGNORECASE)


@dataclass
class _Section:
    path: list[str]
    lines: list[str] = field(default_factory=list)
    first: int = 0
    last: int = 0

    def add(self, text: str, index: int) -> None:
        if not self.lines:
            self.first = index
        self.lines.append(text)
        self.last = index


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    name = style.name if style is not None and style.name else ""
    match = _HEADING.match(name)
    if not match:
        return None
    if match.group(1).lower() == "title":
        return 0
    return int(match.group(2) or 1)


def _table_rows(table: Table) -> list[str]:
    rows = []
    for row in table.rows:
        cells = []
        seen: set[int] = set()
        for cell in row.cells:
            if id(cell._tc) in seen:  # merged cells repeat
                continue
            seen.add(id(cell._tc))
            cells.append(cell.text.strip())
        line = " | ".join(c for c in cells if c)
        if line:
            rows.append(line)
    return rows


def load_docx(data: bytes) -> list[Segment]:
    try:
        document = Document(io.BytesIO(data))
        children = list(document.element.body.iterchildren())
    except Exception as error:
        raise PermanentIngestionError(CORRUPT) from error

    stack: list[tuple[int, str]] = []
    current = _Section(path=[])
    sections: list[_Section] = []
    index = 0

    def flush() -> None:
        nonlocal current
        if current.lines:
            sections.append(current)

    try:
        for child in children:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                index += 1
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if not text:
                    continue
                level = _heading_level(paragraph)
                if level is not None:
                    flush()
                    stack = [(lv, t) for lv, t in stack if lv < level] + [(level, text)]
                    current = _Section(path=[t for _, t in stack])
                current.add(text, index)
            elif tag == "tbl":
                table = Table(child, document)
                for line in _table_rows(table):
                    index += 1
                    current.add(line, index)
    except PermanentIngestionError:
        raise
    except Exception as error:
        raise PermanentIngestionError(CORRUPT) from error
    flush()

    return [
        Segment(
            "\n\n".join(section.lines),
            {
                "type": "section",
                "path": section.path,
                "paragraphs": [section.first, section.last],
            },
        )
        for section in sections
    ]
