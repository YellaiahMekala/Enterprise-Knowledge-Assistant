# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Run ``parse_document`` in a child process with a wall-clock timeout (TDD 4.3, 4.9).

A pathological file (a PDF that makes the parser loop, a huge document) must not hang or exhaust
the worker. The child is a fresh ``spawn`` process, so a crash or a kill affects only it. This
function blocks; the worker calls it through ``asyncio.to_thread``.
"""

import multiprocessing
from collections.abc import Collection
from multiprocessing.connection import Connection
from typing import Any

from eka.domain.errors import CORRUPT, TOO_LARGE, PermanentIngestionError
from eka.domain.models import ParsedDocument, ParseLimits
from eka.ingestion.parse import parse_document

_JOIN_SECONDS = 5


def _child(connection: Connection, arguments: dict[str, Any]) -> None:
    try:
        connection.send(("ok", parse_document(**arguments)))
    except PermanentIngestionError as error:
        connection.send(("permanent", error.code))
    except BaseException:  # any other parser failure means this file cannot be read
        connection.send(("permanent", CORRUPT))
    finally:
        connection.close()


def parse_in_child(
    filename: str,
    declared_content_type: str | None,
    data: bytes,
    *,
    text_extensions: Collection[str],
    limits: ParseLimits,
    timeout_seconds: float,
) -> ParsedDocument:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    arguments = {
        "filename": filename,
        "declared_content_type": declared_content_type,
        "data": data,
        "text_extensions": tuple(text_extensions),
        "limits": limits,
    }
    process = context.Process(target=_child, args=(sender, arguments), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout_seconds):
            raise PermanentIngestionError(TOO_LARGE)  # too much work for one file
        try:
            status, payload = receiver.recv()
        except EOFError:  # the child died without answering (killed, out of memory)
            raise PermanentIngestionError(CORRUPT) from None
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(_JOIN_SECONDS)
        if process.is_alive():
            process.kill()
    if status == "ok":
        assert isinstance(payload, ParsedDocument)
        return payload
    raise PermanentIngestionError(str(payload))
