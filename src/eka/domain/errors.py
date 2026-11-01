"""Typed errors. Messages are fixed and safe to show; detail goes to the log, never the client."""


class EkaError(Exception):
    """Base class for errors the API translates into problem+json responses."""


class Unauthorized(EkaError):
    """Missing, malformed or unknown credential."""


class NotFound(EkaError):
    """Unknown id, or an id that belongs to another user (the two are indistinguishable)."""


class Unavailable(EkaError):
    """A required dependency (database, storage) cannot be reached."""
