# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Architecture checks (Test Strategy 3.1): the package table in TDD section 3 as a test, and the
isolation rule that every repository method takes ``owner_id`` first (ADR-012)."""

import ast
import inspect
import sys
from pathlib import Path

import pytest

from eka.adapters.db import repositories as db_repositories
from eka.ports import repositories as repository_ports

SRC = Path(__file__).resolve().parents[1] / "src" / "eka"

# Package -> the eka packages it may import. Third-party imports are allowed only where listed
# in THIRD_PARTY_OK (the "vendor SDK" rule). Top-level modules (config, request_context,
# metrics, the package itself) are shared by every layer and are not restricted here.
ALLOWED_EKA = {
    "domain": set(),
    "ports": {"domain"},
    "services": {"domain", "ports", "ingestion"},
    "ingestion": {"domain"},
    "adapters": {"domain", "ports"},
    "security": {"domain"},
    "api": {"services", "domain", "security"},
}
SHARED_TOP_LEVEL = {"config", "request_context", "logging_config", "metrics", "tracing"}
# Packages that may use third-party libraries. domain, ports and services may not.
THIRD_PARTY_OK = {"adapters", "api", "security", "ingestion"}
# Third-party libraries each of those may use is deliberately not narrowed further yet.


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path}:{node.lineno}: use absolute imports"
            found.append((node.lineno, node.module or ""))
    return found


def _modules() -> list[tuple[str, Path]]:
    result = []
    for package in ALLOWED_EKA:
        for path in sorted((SRC / package).rglob("*.py")) if (SRC / package).exists() else []:
            result.append((package, path))
    return result


def test_the_boundary_table_covers_every_package_directory() -> None:
    on_disk = {p.name for p in SRC.iterdir() if p.is_dir() and not p.name.startswith("__")}
    # tools and eval are entry points / test harnesses: free to import across layers.
    unrestricted = {"tools", "eval"}
    assert on_disk - unrestricted <= set(ALLOWED_EKA), (
        f"new package without a boundary rule: {sorted(on_disk - unrestricted - set(ALLOWED_EKA))}"
    )


@pytest.mark.parametrize(("package", "path"), _modules(), ids=lambda v: getattr(v, "name", v))
def test_imports_respect_the_package_boundaries(package: str, path: Path) -> None:
    violations: list[str] = []
    for lineno, module in _imports(path):
        top = module.split(".")[0]
        if top == "eka":
            parts = module.split(".")
            target = parts[1] if len(parts) > 1 else ""
            if target in ALLOWED_EKA and target != package and target not in ALLOWED_EKA[package]:
                violations.append(f"line {lineno}: {package} must not import eka.{target}")
            if target not in ALLOWED_EKA and target not in SHARED_TOP_LEVEL and target:
                violations.append(f"line {lineno}: eka.{target} is not a shared module")
        elif top not in sys.stdlib_module_names and package not in THIRD_PARTY_OK:
            violations.append(f"line {lineno}: {package} must not import third-party '{top}'")
    assert not violations, f"{path.relative_to(SRC)}: " + "; ".join(violations)


def test_domain_imports_nothing_from_the_rest_of_the_app() -> None:
    """domain is the bottom layer: not even the shared top-level modules."""
    for path in (SRC / "domain").rglob("*.py"):
        for lineno, module in _imports(path):
            assert not module.startswith("eka.") or module.startswith("eka.domain"), (
                f"{path.name}:{lineno} imports {module}"
            )


def _public_methods(cls: type) -> list[tuple[str, inspect.Signature]]:
    return [
        (name, inspect.signature(member))
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    ]


def _repository_classes() -> list[type]:
    ports = [
        cls
        for _, cls in inspect.getmembers(repository_ports, inspect.isclass)
        if cls.__module__ == repository_ports.__name__ and cls.__name__.endswith("Repository")
    ]
    adapters = [
        cls
        for _, cls in inspect.getmembers(db_repositories, inspect.isclass)
        if cls.__module__ == db_repositories.__name__ and cls.__name__.endswith("Repository")
    ]
    return ports + adapters


def test_there_are_repositories_to_check() -> None:
    names = {cls.__name__ for cls in _repository_classes()}
    assert {"DocumentRepository", "SqlDocumentRepository"} <= names


def test_every_repository_method_takes_owner_id_first() -> None:
    """A query without an owner must not type-check, so the owner is the first parameter."""
    problems: list[str] = []
    for cls in _repository_classes():
        for name, signature in _public_methods(cls):
            params = [p for p in signature.parameters.values() if p.name != "self"]
            if (
                not params
                or params[0].name != "owner_id"
                or params[0].annotation not in (str, "str")
            ):
                problems.append(f"{cls.__name__}.{name}{signature}")
    assert not problems, "owner_id must be the first (str) parameter: " + "; ".join(problems)


def test_the_adapter_implements_every_port_method() -> None:
    port = {name for name, _ in _public_methods(repository_ports.DocumentRepository)}
    adapter = {name for name, _ in _public_methods(db_repositories.SqlDocumentRepository)}
    assert port <= adapter
    assert adapter <= port, f"adapter has methods the port lacks: {sorted(adapter - port)}"
