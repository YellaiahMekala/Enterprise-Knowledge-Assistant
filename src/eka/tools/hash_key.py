"""Print the SHA-256 digest of an API key, for ``EKA_API_KEYS``.

    echo -n "my-key" | python -m eka.tools.hash_key      (key read from standard input)
    python -m eka.tools.hash_key --generate               (new random key; shown once)

The key itself is never stored by the service. Keep it in your own secret store.
"""

import argparse
import secrets
import sys

from eka.security.auth import digest_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eka.tools.hash_key", description=__doc__)
    parser.add_argument("--generate", action="store_true", help="create a random key and show it")
    args = parser.parse_args(argv)

    if args.generate:
        key = secrets.token_urlsafe(32)
        print(f"key:    {key}")
        print(f"sha256: {digest_key(key).hex()}")
        return 0

    key = sys.stdin.read().rstrip("\r\n")
    if not key:
        print("No key on standard input.", file=sys.stderr)
        return 2
    print(digest_key(key).hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
