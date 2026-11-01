"""Typed settings, read from EKA_* environment variables or a local .env file."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from eka.domain.models import Role, is_valid_user_id

DATABASE_URL_PREFIX = "postgresql+psycopg://"


class ApiKeyEntry(BaseModel):
    """One configured caller: the SHA-256 digest of its key (never the key) and its role."""

    model_config = ConfigDict(frozen=True)

    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    role: Role = Role.USER


class Settings(BaseSettings):
    # hide_input_in_errors: a startup error must not echo submitted values (API-key digests,
    # a database URL that contains a password) into logs and terminals.
    model_config = SettingsConfigDict(
        env_prefix="EKA_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["local", "test", "prod"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    # SQLAlchemy URL, postgresql+psycopg://... A SecretStr keeps the password out of repr().
    database_url: SecretStr | None = None
    # Required outside environment=test. "gateway" arrives with the Java edge (phase P3b).
    auth_mode: Literal["api_key", "gateway"] | None = None
    # JSON object: {"<user-id>": {"sha256": "<hex digest>", "role": "user|admin"}}
    api_keys: dict[str, ApiKeyEntry] = Field(default_factory=dict, repr=False)

    @field_validator("api_keys")
    @classmethod
    def _user_ids_are_well_formed(cls, value: dict[str, ApiKeyEntry]) -> dict[str, ApiKeyEntry]:
        bad = [user_id for user_id in value if not is_valid_user_id(user_id)]
        if bad:
            # Report the count only: an id typed into the wrong place can be a secret.
            raise ValueError(f"{len(bad)} user id(s) do not match ^[A-Za-z0-9_.-]{{1,36}}$")
        return value

    @field_validator("database_url")
    @classmethod
    def _driver_is_psycopg(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(DATABASE_URL_PREFIX):
            raise ValueError(f"must start with {DATABASE_URL_PREFIX}")
        return value

    @model_validator(mode="after")
    def _fail_fast_outside_tests(self) -> Self:
        """A half-configured service must not start (TDD 4.1). Tests build what they need."""
        if self.environment == "test":
            return self
        if self.database_url is None:
            raise ValueError("EKA_DATABASE_URL is required outside environment=test")
        if self.auth_mode is None:
            raise ValueError("EKA_AUTH_MODE is required outside environment=test")
        if self.auth_mode == "gateway":
            raise ValueError("EKA_AUTH_MODE=gateway is not available yet (phase P3b)")
        if not self.api_keys:
            raise ValueError("EKA_API_KEYS must list at least one key when EKA_AUTH_MODE=api_key")
        return self


@lru_cache
def get_settings() -> Settings:
    """Read once per process; tests build ``Settings`` directly instead."""
    return Settings()
