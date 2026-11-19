# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Gateway mode: the core accepts only tokens signed by the edge's key (TDD 4.1)."""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from eka.domain.models import Role
from eka.main import create_app
from eka.security.auth import Principal
from eka.security.gateway import GatewayAuthenticator
from tests.helpers import make_settings, ready_ok

ISSUER = "eka-edge"
AUDIENCE = "eka-core"
_KEY = ec.generate_private_key(ec.SECP256R1())
_OTHER = ec.generate_private_key(ec.SECP256R1())


class _Resolver:
    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        return jwt.PyJWK.from_dict(
            {**jwt.algorithms.ECAlgorithm.to_jwk(_KEY.public_key(), as_dict=True), "kid": "k1"}
        )


def _token(key: Any = _KEY, alg: str = "ES256", **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u1234",
        "role": "user",
        "iat": now,
        "exp": now + 60,
        "rid": "r-1",
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm=alg)


def _auth() -> GatewayAuthenticator:
    return GatewayAuthenticator(_Resolver(), ISSUER, AUDIENCE)


def test_valid_token_yields_principal() -> None:
    assert _auth().authenticate(_token()) == Principal("u1234", Role.USER)
    assert _auth().authenticate(_token(role="admin")) == Principal("u1234", Role.ADMIN)


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "garbage",
        "x" * 5000,
        _token(key=_OTHER),
        _token(iss="someone-else"),
        _token(aud="eka-api"),
        _token(exp=int(time.time()) - 120),
        _token(role="superuser"),
        _token(role=None),
        _token(sub=""),
        _token(sub=None),
        _token(exp=None),
    ],
)
def test_bad_tokens_are_rejected(token: str | None) -> None:
    assert _auth().authenticate(token) is None


def test_hs256_token_is_rejected() -> None:
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "u1",
            "role": "admin",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        "a-shared-secret-that-is-long-enough-123456",
        algorithm="HS256",
    )
    assert _auth().authenticate(forged) is None


def _client() -> TestClient:
    settings = make_settings(auth_mode="gateway", gateway_jwks_url="http://unused/jwks")
    return TestClient(create_app(settings, readiness_check=ready_ok, gateway_authenticator=_auth()))


def test_api_serves_identity_from_the_bearer_token() -> None:
    response = _client().get("/api/v1/me", headers={"Authorization": f"Bearer {_token()}"})
    assert response.status_code == 200
    assert response.json()["user_id"] == "u1234"


def test_api_key_header_is_not_accepted_in_gateway_mode() -> None:
    assert _client().get("/api/v1/me", headers={"X-API-Key": "user-key"}).status_code == 401


def test_missing_or_bad_bearer_is_401() -> None:
    client = _client()
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert (
        client.get("/api/v1/me", headers={"Authorization": f"Basic {_token()}"}).status_code == 401
    )
