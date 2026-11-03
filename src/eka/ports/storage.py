"""Raw-file storage port (TDD 4.2, ADR-013)."""

from typing import Protocol


class FileStore(Protocol):
    """Keys are ``{owner_id}/{document_uuid}``. The user's file name never appears in a key."""

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes:
        """The stored bytes; raises ``Unavailable`` if the object cannot be read."""
        ...

    async def delete(self, key: str) -> None:
        """Idempotent: deleting a missing key is not an error."""
        ...
