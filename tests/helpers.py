# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Shared test helpers (importable as ``tests.helpers``)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from eka.config import ApiKeyEntry, Settings
from eka.domain.models import Role
from eka.logging_config import ContextFilter
from eka.security.auth import digest_key

USER_KEY = "test-user-key-0001"
ADMIN_KEY = "test-admin-key-0002"
USER_ID = "alice"
ADMIN_ID = "root"


def api_keys() -> dict[str, ApiKeyEntry]:
    return {
        USER_ID: ApiKeyEntry(sha256=digest_key(USER_KEY).hex(), role=Role.USER),
        ADMIN_ID: ApiKeyEntry(sha256=digest_key(ADMIN_KEY).hex(), role=Role.ADMIN),
    }


def make_settings(**overrides: Any) -> Settings:
    """Valid settings for tests: environment ``test``, API-key auth with two known callers.
    ``_env_file=None`` keeps a developer's real .env out of the tests."""
    values: dict[str, Any] = {
        "environment": "test",
        "ready_requires_embedder": False,  # tests that need it turn it on
        "auth_mode": "api_key",
        "api_keys": api_keys(),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def ready_ok() -> None:
    """A readiness check that always passes (stands in for the database)."""


@contextmanager
def capture_logs(name: str = "eka") -> Iterator[list[logging.LogRecord]]:
    """Collect records from logger ``name`` and its children, with request context attached.

    Attached directly to the named logger because ``create_app`` reconfigures the root logger,
    which would detach pytest's own capture handler.
    """
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect()
    handler.addFilter(ContextFilter())
    logger = logging.getLogger(name)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
