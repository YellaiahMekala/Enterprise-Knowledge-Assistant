# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The child-process parser: result passing, fixed error codes, and the timeout."""

import time

import pytest

from eka.domain.errors import PermanentIngestionError
from eka.domain.models import ParsedDocument, ParseLimits
from eka.ingestion.parse_runner import parse_in_child
from tests.files import make_pdf

LIMITS = ParseLimits(max_pages=50, max_csv_rows=1000, max_text_bytes=100_000)


def run(filename: str, data: bytes, timeout: float = 60.0) -> ParsedDocument:
    return parse_in_child(
        filename,
        None,
        data,
        text_extensions=(".txt",),
        limits=LIMITS,
        timeout_seconds=timeout,
    )


def test_a_good_file_is_parsed_in_the_child_and_returned() -> None:
    parsed = run("a.pdf", make_pdf(["Hello from a child process"]))
    assert parsed.page_count == 1
    assert "Hello from a child" in parsed.segments[0].text


def test_a_permanent_error_comes_back_with_its_fixed_code() -> None:
    with pytest.raises(PermanentIngestionError) as error:
        run("a.pdf", make_pdf(["", ""]))
    assert error.value.code == "no_text"


def test_an_unexpected_parser_crash_is_reported_as_corrupt() -> None:
    # A PDF header followed by junk makes the parser raise something other than our error type.
    with pytest.raises(PermanentIngestionError) as error:
        run("a.pdf", b"%PDF-1.7\n" + b"\xff" * 64)
    assert error.value.code == "corrupt"


def test_a_child_that_takes_too_long_is_killed() -> None:
    started = time.monotonic()
    with pytest.raises(PermanentIngestionError) as error:
        run("a.pdf", make_pdf(["x"]), timeout=0.01)  # starting a process alone takes longer
    assert error.value.code == "too_large"
    assert time.monotonic() - started < 30  # we did not wait for the child to finish by itself
