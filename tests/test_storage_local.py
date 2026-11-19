# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Local file store: round trip, idempotent delete, and containment of every key."""

import asyncio
import uuid
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import pytest

from eka.adapters.storage_local import LocalFileStore
from eka.domain.errors import Unavailable

T = TypeVar("T")


def key(owner: str = "alice") -> str:
    return f"{owner}/{uuid.uuid4()}"


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def test_put_get_delete_round_trip(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    k = key()
    run(store.put(k, b"hello", "text/plain"))
    assert run(store.get(k)) == b"hello"
    run(store.delete(k))
    with pytest.raises(Unavailable):
        run(store.get(k))


def test_delete_of_a_missing_key_is_not_an_error(tmp_path: Path) -> None:
    run(LocalFileStore(tmp_path).delete(key()))


def test_put_replaces_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    k = key()
    run(store.put(k, b"one", "text/plain"))
    run(store.put(k, b"two", "text/plain"))
    assert run(store.get(k)) == b"two"
    assert [p.name for p in (tmp_path / k.split("/")[0]).iterdir()] == [k.split("/")[1]]


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "alice/../../etc/passwd",
        "alice/not-a-uuid",
        "alice",
        "/abs/olute",
        "alice/" + str(uuid.uuid4()) + "/extra",
        "a b/" + str(uuid.uuid4()),
        "",
    ],
)
def test_malformed_keys_are_refused_for_every_operation(tmp_path: Path, bad: str) -> None:
    store = LocalFileStore(tmp_path)
    for operation in (store.put(bad, b"x", "t"), store.get(bad), store.delete(bad)):
        with pytest.raises(ValueError, match="storage key"):
            run(operation)


def test_an_owner_id_made_of_dots_cannot_climb_out_of_the_root(tmp_path: Path) -> None:
    """``..`` is a legal user id by the id pattern, so containment is checked on the resolved
    path, not on the key's characters."""
    root = tmp_path / "files"
    store = LocalFileStore(root)
    with pytest.raises(ValueError, match="storage key"):
        run(store.put(f"../{uuid.uuid4()}", b"x", "t"))
    with pytest.raises(ValueError, match="storage key"):
        run(store.put(f"{'..'}/{uuid.uuid4()}", b"x", "t"))
    assert not list(tmp_path.glob("*.*"))  # nothing was written next to the root


def test_files_of_different_owners_live_in_different_directories(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    a, b = key("alice"), key("bob")
    run(store.put(a, b"A", "t"))
    run(store.put(b, b"B", "t"))
    assert run(store.get(a)) == b"A" and run(store.get(b)) == b"B"
    assert (tmp_path / "alice").is_dir() and (tmp_path / "bob").is_dir()
