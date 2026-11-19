# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The worker's composition root: it refuses to start without a database and reads its own
settings (no API keys needed)."""

import asyncio

import pytest

from eka.config import Settings
from eka.worker import run_worker


def test_the_worker_refuses_to_start_without_a_database() -> None:
    settings = Settings(_env_file=None, environment="test", component="worker")
    with pytest.raises(RuntimeError, match="EKA_DATABASE_URL"):
        asyncio.run(run_worker(settings, asyncio.Event()))


def test_the_worker_settings_need_no_api_keys() -> None:
    settings = Settings(
        _env_file=None,
        environment="local",
        component="worker",
        database_url="postgresql+psycopg://eka:pw@127.0.0.1:5432/eka",
    )
    assert settings.api_keys == {} and settings.auth_mode is None
