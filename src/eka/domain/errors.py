"""Typed errors. Messages are fixed and safe to show; detail goes to the log, never the client."""


class EkaError(Exception):
    """Base class for errors the API translates into problem+json responses."""


class Unauthorized(EkaError):
    """Missing, malformed or unknown credential."""


class Forbidden(EkaError):
    """Authenticated, but not allowed to do this."""


class NotFound(EkaError):
    """Unknown id, or an id that belongs to another user (the two are indistinguishable)."""


class Unavailable(EkaError):
    """A required dependency (database, storage) cannot be reached."""


class UnsupportedMedia(EkaError):
    """The upload is not a supported file, or its bytes do not match its name or declared type.
    ``reason`` is a fixed code (safe to show): ``unsupported_type``, ``type_mismatch``,
    ``unsupported_encoding`` or ``invalid_archive``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PayloadTooLarge(EkaError):
    """The upload exceeds the configured size limit."""


class QuotaExceeded(EkaError):
    """The user already holds the maximum number of documents."""


# --- ingestion (worker side) -------------------------------------------------------------------

# Codes stored in documents.error_code and shown to the owner. Fixed strings, no file content.
ENCRYPTED = "encrypted"
NO_TEXT = "no_text"
CORRUPT = "corrupt"
TOO_LARGE = "too_large"
UNSUPPORTED_ENCODING = "unsupported_encoding"
MAX_ATTEMPTS = "max_attempts"


class PermanentIngestionError(EkaError):
    """The file can never be ingested (retrying will not help). ``code`` is one of the constants
    above. Picklable on purpose: parsing runs in a child process and reports through this."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- chat model (phase P4) ----------------------------------------------------------------------


class ModelUnavailable(EkaError):
    """The chat model could not produce a response (provider error, rate limit, bad reply)."""


class ModelTimeout(EkaError):
    """The chat model did not answer within the configured time."""


class WebFetchRefused(Exception):
    """The web fallback did not fetch a page (ADR-030). ``reason`` is a fixed code such as
    ``host_not_allowed``, ``private_address``, ``too_large`` or ``timeout``, safe to log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
