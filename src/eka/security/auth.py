# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""API-key authentication for the standalone core (TDD 4.1).

Keys are never held: configuration carries SHA-256 digests. A presented key is hashed once and
compared with **every** configured digest in constant time, with no early exit, so response time
does not reveal which entry (if any) was close.
"""

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass

from eka.config import ApiKeyEntry
from eka.domain.models import Role

# Real keys are far shorter; the cap only stops someone making us hash megabytes.
MAX_KEY_LENGTH = 512


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. Identity comes only from the credential, never from a request
    parameter, so a caller cannot ask for another user's data by naming them."""

    user_id: str
    role: Role


def digest_key(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


class ApiKeyAuthenticator:
    def __init__(self, entries: Mapping[str, ApiKeyEntry]) -> None:
        self._entries: tuple[tuple[str, bytes, Role], ...] = tuple(
            (user_id, bytes.fromhex(entry.sha256), entry.role) for user_id, entry in entries.items()
        )

    def authenticate(self, presented: str | None) -> Principal | None:
        if not presented or len(presented) > MAX_KEY_LENGTH:
            return None
        digest = digest_key(presented)
        matched: Principal | None = None
        for user_id, stored, role in self._entries:
            is_match = hmac.compare_digest(stored, digest)  # evaluated for every entry
            if is_match and matched is None:
                matched = Principal(user_id=user_id, role=role)
        return matched
