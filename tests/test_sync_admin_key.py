# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
import json
from pathlib import Path

import pytest

from eka.security.auth import digest_key
from eka.tools import sync_admin_key


def _env(tmp_path: Path, admin_digest: str) -> Path:
    entries = {
        "u": {"sha256": "a" * 64, "role": "user"},
        "adm": {"sha256": admin_digest, "role": "admin"},
    }
    path = tmp_path / ".env"
    path.write_text(f"A=1\nEKA_API_KEYS='{json.dumps(entries)}'\nB=2\n", encoding="utf-8")
    return path


def test_check_reports_mismatch_then_sync_makes_it_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env, key_file = _env(tmp_path, "0" * 64), tmp_path / "admin_key"
    key_file.write_text("plain-admin-key\n", encoding="utf-8")
    argv = ["--env-file", str(env), "--key-file", str(key_file)]

    assert sync_admin_key.main(["--check", *argv]) == 1
    assert sync_admin_key.main(["--sync", *argv]) == 0
    assert sync_admin_key.main(["--check", *argv]) == 0

    out = capsys.readouterr().out
    assert "plain-admin-key" not in out and digest_key("plain-admin-key").hex() not in out
    text = env.read_text(encoding="utf-8")
    assert text.startswith("A=1\n") and text.endswith("\nB=2\n")
    assert json.loads(text.splitlines()[1].split("=", 1)[1].strip("'"))["u"]["sha256"] == "a" * 64


def test_rotate_writes_a_new_key_and_matching_digest(tmp_path: Path) -> None:
    env, key_file = _env(tmp_path, "0" * 64), tmp_path / "sub" / "admin_key"
    argv = ["--env-file", str(env), "--key-file", str(key_file)]
    assert sync_admin_key.main(["--rotate", *argv]) == 0
    assert sync_admin_key.main(["--check", *argv]) == 0


def test_missing_files_return_2(tmp_path: Path) -> None:
    argv = ["--env-file", str(tmp_path / "none"), "--key-file", str(tmp_path / "none2")]
    assert sync_admin_key.main(["--check", *argv]) == 2
