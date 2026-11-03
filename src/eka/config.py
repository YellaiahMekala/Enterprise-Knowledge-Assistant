"""Typed settings, read from EKA_* environment variables or a local .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from eka.domain.models import ParseLimits, Role, is_valid_user_id

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
    # Which process reads these settings. The worker authenticates nobody, so it is not asked
    # for (and is not given) the API keys.
    component: Literal["api", "worker"] = "api"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    # SQLAlchemy URL, postgresql+psycopg://... A SecretStr keeps the password out of repr().
    database_url: SecretStr | None = None
    # Required outside environment=test. "gateway" arrives with the Java edge (phase P3b).
    auth_mode: Literal["api_key", "gateway"] | None = None
    # JSON object: {"<user-id>": {"sha256": "<hex digest>", "role": "user|admin"}}
    api_keys: dict[str, ApiKeyEntry] = Field(default_factory=dict, repr=False)

    # --- storage and ingestion (phase P2) ---
    storage_backend: Literal["local"] = "local"  # "s3" arrives in phase P9
    storage_local_dir: Path = Path("./data/files")
    max_upload_mb: int = Field(default=20, ge=1, le=200)
    max_pages: int = Field(default=500, ge=1)
    max_csv_rows: int = Field(default=50_000, ge=1)
    max_docs_per_user: int = Field(default=200, ge=1)
    # Code and text files accepted besides PDF, DOCX and CSV (FR-36).
    allowed_text_extensions: tuple[str, ...] = (
        ".java",
        ".md",
        ".txt",
        ".xml",
        ".sql",
        ".properties",
        ".yml",
        ".json",
    )
    max_text_file_kb: int = Field(default=512, ge=1)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384  # must equal the chunks.embedding column (migration 0001)
    embedding_cache_dir: Path = Path("./data/models")
    # Starting values, replaced by the results of experiment E1 (TDD 4.11). 510 = 512 - 2.
    chunk_tokens: int = Field(default=256, ge=16, le=510)
    chunk_overlap_tokens: int = Field(default=32, ge=0)
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    worker_max_attempts: int = Field(default=3, ge=1)
    worker_stale_claim_minutes: int = Field(default=10, ge=1)
    parse_timeout_seconds: float = Field(default=120.0, gt=0)

    @field_validator("allowed_text_extensions")
    @classmethod
    def _extensions_are_well_formed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip().lower() for item in value)
        if any(not item.startswith(".") or len(item) < 2 or "/" in item for item in cleaned):
            raise ValueError("each extension must look like '.java'")
        return cleaned

    @model_validator(mode="after")
    def _overlap_is_smaller_than_chunk(self) -> Self:
        if self.chunk_overlap_tokens >= self.chunk_tokens:
            raise ValueError("EKA_CHUNK_OVERLAP_TOKENS must be smaller than EKA_CHUNK_TOKENS")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def parse_limits(self) -> ParseLimits:
        return ParseLimits(
            max_pages=self.max_pages,
            max_csv_rows=self.max_csv_rows,
            max_text_bytes=self.max_text_file_kb * 1024,
        )

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
        if self.component == "worker":
            return self
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
