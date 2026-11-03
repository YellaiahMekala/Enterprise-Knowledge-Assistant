"""CSV loader: groups of rows, locator ``{"type": "rows", "start": a, "end": b}`` (1-based data
rows, header excluded). Each row is rendered ``column=value | column=value`` so the column names
reach the embedding and every chunk carries its own header context."""

import csv
import io
from collections.abc import Iterator

from eka.domain.errors import (
    CORRUPT,
    TOO_LARGE,
    UNSUPPORTED_ENCODING,
    PermanentIngestionError,
)
from eka.domain.models import ParseLimits, Segment

_GROUP_MAX_CHARS = 1_500
_GROUP_MAX_ROWS = 40


def _render(columns: list[str], row: list[str]) -> str:
    cells = [
        f"{name}={value.strip()}"
        for name, value in zip(columns, row + [""] * (len(columns) - len(row)), strict=False)
        if value.strip()
    ]
    return " | ".join(cells)


def _groups(rows: Iterator[tuple[int, str]]) -> Iterator[Segment]:
    lines: list[str] = []
    start = end = 0
    size = 0
    for number, line in rows:
        if not lines:
            start = number
        lines.append(line)
        end = number
        size += len(line) + 1
        if size >= _GROUP_MAX_CHARS or len(lines) >= _GROUP_MAX_ROWS:
            yield Segment("\n".join(lines), {"type": "rows", "start": start, "end": end})
            lines, size = [], 0
    if lines:
        yield Segment("\n".join(lines), {"type": "rows", "start": start, "end": end})


def load_csv(data: bytes, limits: ParseLimits) -> list[Segment]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PermanentIngestionError(UNSUPPORTED_ENCODING) from None
    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        header = next(reader, None)
        if header is None:
            return []
        columns = [name.strip() or f"column_{i + 1}" for i, name in enumerate(header)]
        rendered: list[tuple[int, str]] = []
        for number, row in enumerate(reader, start=1):
            if number > limits.max_csv_rows:
                raise PermanentIngestionError(TOO_LARGE)
            line = _render(columns, row)
            if line:
                rendered.append((number, line))
    except PermanentIngestionError:
        raise
    except csv.Error as error:
        raise PermanentIngestionError(CORRUPT) from error
    return list(_groups(iter(rendered)))
