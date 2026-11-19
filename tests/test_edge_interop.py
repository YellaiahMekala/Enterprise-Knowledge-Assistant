# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Tokens minted by the Java edge must verify in the core. The edge test run writes them to
gateway/target/interop (see InteropFixtureTest); without them this module is skipped."""

import json
from pathlib import Path

import jwt
import pytest

from eka.domain.models import Role
from eka.security.auth import Principal
from eka.security.gateway import GatewayAuthenticator

DIR = Path(__file__).parent.parent / "gateway" / "target" / "interop"

pytestmark = pytest.mark.skipif(not DIR.exists(), reason="run the edge tests first")


class _Jwks:
    def __init__(self) -> None:
        self._set = jwt.PyJWKSet.from_dict(json.loads((DIR / "jwks.json").read_text()))

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        kid = jwt.get_unverified_header(token)["kid"]
        return next(key for key in self._set.keys if key.key_id == kid)


def _auth() -> GatewayAuthenticator:
    # The edge's token lives 60 s and the file was written earlier, so only expiry is relaxed.
    return GatewayAuthenticator(_Jwks(), "eka-edge", "eka-core", leeway_seconds=3600)


def test_edge_user_token_is_accepted() -> None:
    token = (DIR / "user.jwt").read_text()
    assert _auth().authenticate(token) == Principal("u0123456789abcdef0123456789abcdef", Role.USER)


def test_edge_admin_token_is_accepted() -> None:
    token = (DIR / "admin.jwt").read_text()
    assert _auth().authenticate(token) == Principal("uffffffffffffffffffffffffffffffff", Role.ADMIN)


def test_wrong_audience_is_refused() -> None:
    strict = GatewayAuthenticator(_Jwks(), "eka-edge", "someone-else", leeway_seconds=3600)
    assert strict.authenticate((DIR / "user.jwt").read_text()) is None
