"""Code and text loader: blocks of lines, locator ``{"type": "lines", "path": f, "start": a,
"end": b}`` (1-based, inclusive). No parser dependency (ADR-029): boundaries come from small
heuristics, and anything the heuristic cannot decide falls back to plain blank-line blocks.

* ``.java``: blank lines at brace depth 0 or 1 separate members (methods, fields, nested types),
  so a method with blank lines inside is never cut. Strings, comments and text blocks are skipped
  while counting braces.
* ``.md``: a heading starts a new block (outside code fences).
* everything else: blank-line blocks.

Neighbouring blocks are merged up to ``TARGET_LINES`` so tiny members (getters) do not become
tiny chunks; a block longer than that stays alone and the chunker splits it by lines.
"""

from typing import Literal

from eka.domain.errors import UNSUPPORTED_ENCODING, PermanentIngestionError
from eka.domain.models import Segment
from eka.ingestion.sniff import extension_of

TARGET_LINES = 40
_PROSE_EXTENSIONS = {".md", ".txt"}

Block = tuple[int, int]  # 0-based inclusive line range


def _java_depths(lines: list[str]) -> list[int]:
    """Brace depth at the start of each line, ignoring braces in strings and comments."""
    depths: list[int] = []
    depth = 0
    in_block_comment = False
    in_text_block = False
    for line in lines:
        depths.append(depth)
        i, n = 0, len(line)
        while i < n:
            if in_block_comment:
                end = line.find("*/", i)
                if end < 0:
                    break
                in_block_comment, i = False, end + 2
                continue
            if in_text_block:
                end = line.find('"""', i)
                if end < 0:
                    break
                in_text_block, i = False, end + 3
                continue
            char = line[i]
            if char == "/" and line.startswith("//", i):
                break
            if char == "/" and line.startswith("/*", i):
                in_block_comment, i = True, i + 2
            elif char == '"' and line.startswith('"""', i):
                in_text_block, i = True, i + 3
            elif char in "\"'":
                j = i + 1
                while j < n and line[j] != char:
                    j += 2 if line[j] == "\\" else 1
                i = j + 1
            else:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth = max(0, depth - 1)
                i += 1
    return depths


def _blank_line_blocks(lines: list[str], depths: list[int] | None) -> list[Block]:
    blocks: list[Block] = []
    start: int | None = None
    last = 0
    for index, line in enumerate(lines):
        blank = not line.strip()
        can_cut = blank and (depths is None or depths[index] <= 1)
        if can_cut:
            if start is not None:
                blocks.append((start, last))
                start = None
        elif not blank:
            if start is None:
                start = index
            last = index
    if start is not None:
        blocks.append((start, last))
    return blocks


def _markdown_blocks(lines: list[str]) -> list[Block]:
    starts = [0]
    in_fence = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("#") and index > 0:
            starts.append(index)
    blocks: list[Block] = []
    for position, begin in enumerate(starts):
        end = (starts[position + 1] if position + 1 < len(starts) else len(lines)) - 1
        while begin <= end and not lines[begin].strip():
            begin += 1
        while end >= begin and not lines[end].strip():
            end -= 1
        if begin <= end:
            blocks.append((begin, end))
    return blocks


def _merge(blocks: list[Block]) -> list[Block]:
    merged: list[Block] = []
    current: Block | None = None
    for start, end in blocks:
        if end - start + 1 > TARGET_LINES:
            if current is not None:
                merged.append(current)
                current = None
            merged.append((start, end))
        elif current is None:
            current = (start, end)
        elif end - current[0] + 1 <= TARGET_LINES:
            current = (current[0], end)
        else:
            merged.append(current)
            current = (start, end)
    if current is not None:
        merged.append(current)
    return merged


def load_text(data: bytes, filename: str) -> list[Segment]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PermanentIngestionError(UNSUPPORTED_ENCODING) from None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    extension = extension_of(filename)
    if extension == ".md":
        blocks = _markdown_blocks(lines)
    elif extension == ".java":
        blocks = _blank_line_blocks(lines, _java_depths(lines))
    else:
        blocks = _blank_line_blocks(lines, None)
    unit: Literal["prose", "lines"] = "prose" if extension in _PROSE_EXTENSIONS else "lines"
    return [
        Segment(
            "\n".join(lines[start : end + 1]),
            {"type": "lines", "path": filename, "start": start + 1, "end": end + 1},
            unit,
        )
        for start, end in _merge(blocks)
    ]
