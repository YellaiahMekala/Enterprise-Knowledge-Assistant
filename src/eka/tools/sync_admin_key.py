"""Keep the Prometheus admin key file and its digest in ``.env`` consistent.

Prometheus scrapes the core with the plain admin key in ``monitoring/secrets/admin_key``. The core
only knows the SHA-256 digest of that key, in the admin entry of ``EKA_API_KEYS`` in ``.env``.
Two files edited by hand drift apart (the scrape then fails with 401), so this tool derives one
from the other:

    python -m eka.tools.sync_admin_key --check    (prints match or mismatch; exit 1 on mismatch)
    python -m eka.tools.sync_admin_key --sync     (writes the file's digest into .env)
    python -m eka.tools.sync_admin_key --rotate   (new random key into the file, digest into .env)

The key and the digests are never printed.
"""

import argparse
import json
import re
import secrets
import sys
from pathlib import Path

from eka.security.auth import digest_key

_LINE = re.compile(r"^EKA_API_KEYS=(.*)$", re.MULTILINE)


def _read_entries(env_text: str) -> tuple[re.Match[str], dict[str, dict[str, str]]]:
    match = _LINE.search(env_text)
    if match is None:
        raise ValueError("EKA_API_KEYS is not set in the env file")
    return match, json.loads(match.group(1).strip().strip("'\""))


def _admin_ids(entries: dict[str, dict[str, str]]) -> list[str]:
    return [user_id for user_id, entry in entries.items() if entry.get("role") == "admin"]


def _read_key(path: Path) -> str:
    return path.read_text(encoding="utf-8").rstrip("\r\n")


def check(env_file: Path, key_file: Path) -> bool:
    _, entries = _read_entries(env_file.read_text(encoding="utf-8"))
    digest = digest_key(_read_key(key_file)).hex()
    return any(entries[user_id].get("sha256") == digest for user_id in _admin_ids(entries))


def write_digest(env_file: Path, key: str) -> None:
    text = env_file.read_text(encoding="utf-8")
    match, entries = _read_entries(text)
    admins = _admin_ids(entries)
    if len(admins) != 1:
        raise ValueError(f"expected exactly one admin entry in EKA_API_KEYS, found {len(admins)}")
    entries[admins[0]]["sha256"] = digest_key(key).hex()
    line = "EKA_API_KEYS='" + json.dumps(entries) + "'"
    env_file.write_text(text[: match.start()] + line + text[match.end() :], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eka.tools.sync_admin_key", description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--sync", action="store_true")
    mode.add_argument("--rotate", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--key-file", type=Path, default=Path("monitoring/secrets/admin_key"))
    args = parser.parse_args(argv)

    try:
        if args.check:
            ok = check(args.env_file, args.key_file)
            print("match" if ok else "mismatch")
            return 0 if ok else 1
        if args.rotate:
            args.key_file.parent.mkdir(parents=True, exist_ok=True)
            args.key_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        write_digest(args.env_file, _read_key(args.key_file))
    except (OSError, ValueError) as exc:
        print(f"sync_admin_key: {exc}", file=sys.stderr)
        return 2
    print("synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
