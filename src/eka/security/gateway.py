# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Verification of the internal token minted by the edge.

Only ES256 is accepted; the key is looked up by ``kid`` in the edge's published key set.
Any failure yields ``None``, so the caller answers 401 without saying why.
"""

import logging
from typing import Protocol

import jwt
from jwt import PyJWKClient

from eka.domain.models import Role
from eka.security.auth import Principal

logger = logging.getLogger(__name__)

ALGORITHMS = ["ES256"]
MAX_TOKEN_LENGTH = 4096


class KeyResolver(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> "jwt.PyJWK": ...


class GatewayAuthenticator:
    def __init__(
        self,
        keys: KeyResolver,
        issuer: str,
        audience: str,
        leeway_seconds: int = 5,
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway_seconds

    @classmethod
    def from_jwks_url(cls, url: str, issuer: str, audience: str) -> "GatewayAuthenticator":
        return cls(PyJWKClient(url, cache_keys=True, lifespan=300), issuer, audience)

    def authenticate(self, token: str | None) -> Principal | None:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            role = Role(str(claims.get("role")))
        except (jwt.PyJWTError, ValueError) as error:
            logger.warning("internal token rejected: %s", type(error).__name__)
            return None
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            return None
        return Principal(user_id=subject, role=role)
