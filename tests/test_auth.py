# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
import hmac
import io

import pytest

from eka.config import ApiKeyEntry
from eka.domain.models import Role
from eka.security.auth import MAX_KEY_LENGTH, ApiKeyAuthenticator, Principal, digest_key
from eka.tools import hash_key


def _authenticator() -> ApiKeyAuthenticator:
    return ApiKeyAuthenticator(
        {
            "alice": ApiKeyEntry(sha256=digest_key("alice-key").hex(), role=Role.USER),
            "bob": ApiKeyEntry(sha256=digest_key("bob-key").hex(), role=Role.USER),
            "root": ApiKeyEntry(sha256=digest_key("root-key").hex(), role=Role.ADMIN),
        }
    )


def test_matching_key_returns_the_principal() -> None:
    assert _authenticator().authenticate("bob-key") == Principal("bob", Role.USER)


def test_role_comes_from_the_matching_entry() -> None:
    assert _authenticator().authenticate("root-key") == Principal("root", Role.ADMIN)


@pytest.mark.parametrize(
    "presented",
    [None, "", "wrong", "alice-key ", " alice-key", "ALICE-KEY", "alice-ke", "alice-keyy"],
)
def test_misses_and_near_misses_are_rejected(presented: str | None) -> None:
    assert _authenticator().authenticate(presented) is None


def test_over_long_key_is_rejected_without_hashing_it() -> None:
    assert _authenticator().authenticate("a" * (MAX_KEY_LENGTH + 1)) is None


def test_every_entry_is_compared_even_after_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real = hmac.compare_digest

    def counting(a: bytes, b: bytes) -> bool:
        nonlocal calls
        calls += 1
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", counting)
    # "alice-key" matches the first of three entries; a short-circuiting loop would stop at 1.
    assert _authenticator().authenticate("alice-key") is not None
    assert calls == 3


def test_an_empty_configuration_rejects_everything() -> None:
    assert ApiKeyAuthenticator({}).authenticate("anything") is None


def test_hash_key_reads_stdin_and_prints_the_digest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("my-key\n"))
    assert hash_key.main([]) == 0
    assert capsys.readouterr().out.strip() == digest_key("my-key").hex()


def test_hash_key_rejects_empty_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert hash_key.main([]) == 2
    assert "No key" in capsys.readouterr().err


def test_hash_key_generate_prints_a_key_that_matches_its_digest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert hash_key.main(["--generate"]) == 0
    lines = dict(line.split(":", 1) for line in capsys.readouterr().out.strip().splitlines())
    assert digest_key(lines["key"].strip()).hex() == lines["sha256"].strip()
