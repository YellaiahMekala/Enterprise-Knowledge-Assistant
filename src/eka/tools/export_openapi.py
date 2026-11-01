"""Write or check the committed OpenAPI snapshot, ``docs/openapi.json`` (ADR-019).

    python -m eka.tools.export_openapi            write the snapshot
    python -m eka.tools.export_openapi --check    exit 1 if the code and the snapshot differ

CI runs the check, so a contract change shows up in review as a diff of this file.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eka.api.deps import ReadinessCheck
from eka.config import Settings
from eka.main import create_app

SNAPSHOT_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


async def _never_called() -> None:  # pragma: no cover - the schema is built without serving
    raise AssertionError("readiness is not exercised when exporting the schema")


def build_openapi() -> dict[str, Any]:
    """The schema of an app built with test-environment settings (no database, no keys)."""
    check: ReadinessCheck = _never_called
    app = create_app(Settings(_env_file=None, environment="test"), readiness_check=check)
    schema: dict[str, Any] = app.openapi()
    return schema


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eka.tools.export_openapi", description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args(argv)

    current = render(build_openapi())
    if args.check:
        committed = SNAPSHOT_PATH.read_text(encoding="utf-8") if SNAPSHOT_PATH.exists() else ""
        if committed == current:
            print(f"{SNAPSHOT_PATH.name} is up to date")
            return 0
        print(
            f"{SNAPSHOT_PATH.name} is out of date. Run: python -m eka.tools.export_openapi",
            file=sys.stderr,
        )
        return 1
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(current, encoding="utf-8", newline="\n")
    print(f"wrote {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
