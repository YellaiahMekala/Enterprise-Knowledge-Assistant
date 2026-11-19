# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Text cleaning (TDD 4.3). Pure functions.

Prose is normalised hard (Unicode NFKC, control characters, hyphenation, whitespace). Text that
carries line numbers as its locator (code, notes) is cleaned *line-preservingly*: the number of
lines never changes, so a chunk's line range still matches the original file.
"""

import re
import unicodedata

# Control characters except newline (\n) and tab (\t).
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(?<=\w)-\n(?=\w)")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_RUNS = re.compile(r"\n{3,}")
_SPACE_AROUND_NEWLINE = re.compile(r" ?\n ?")


def clean_prose(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub("", text)
    text = _SPACES.sub(" ", text)
    text = _SPACE_AROUND_NEWLINE.sub("\n", text)
    text = _BLANK_RUNS.sub("\n\n", text)
    return text.strip()


def clean_lines(text: str) -> str:
    """Keep every line (and its indentation); drop control characters and trailing blanks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    return "\n".join(line.rstrip() for line in text.split("\n"))
