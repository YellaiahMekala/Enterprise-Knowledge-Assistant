"""Plain data types shared by every layer. No framework, no I/O."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

# One rule for what a user id may look like. The database repeats it as a CHECK constraint.
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,36}$")


def is_valid_user_id(value: str) -> bool:
    return USER_ID_PATTERN.fullmatch(value) is not None


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NewDocument:
    """What the upload path knows before the row exists. The caller chooses the id because
    the storage key (``{owner_id}/{id}``) is derived from it."""

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str


@dataclass(frozen=True, slots=True)
class Document:
    id: UUID
    owner_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str
    status: DocumentStatus
    error_code: str | None
    attempts: int
    page_count: int | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime
