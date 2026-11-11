"""Typed settings, read from EKA_* environment variables or a local .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

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
    # Required outside environment=test. "gateway" trusts only tokens minted by the edge.
    auth_mode: Literal["api_key", "gateway"] | None = None
    gateway_jwks_url: str | None = None
    gateway_issuer: str = "eka-edge"
    gateway_audience: str = "eka-core"
    # JSON object: {"<user-id>": {"sha256": "<hex digest>", "role": "user|admin"}}
    api_keys: dict[str, ApiKeyEntry] = Field(default_factory=dict, repr=False)

    # --- storage and ingestion (phase P2) ---
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: Path = Path("./data/files")
    # S3 (or an S3-compatible server such as MinIO). Without keys, boto3 uses its normal credential
    # chain, which is what a task or instance role provides on AWS.
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
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
    # Text put before each search query, not before documents. Empty: experiment E5 found no
    # gain from the BGE instruction prefix on the evaluation set (eval/reports/e5_*.md).
    embedding_query_prefix: str = Field(default="", max_length=200)
    # Starting values, replaced by the results of experiment E1 (TDD 4.11). 510 = 512 - 2.
    chunk_tokens: int = Field(default=256, ge=16, le=510)
    chunk_overlap_tokens: int = Field(default=32, ge=0)
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    worker_max_attempts: int = Field(default=3, ge=1)
    worker_stale_claim_minutes: int = Field(default=10, ge=1)
    parse_timeout_seconds: float = Field(default=120.0, gt=0)
    retrieval_candidates: int = Field(default=30, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1)
    # Cross-encoder reranking of the top fused candidates. Off unless a model is named; see the
    # E3 result in the README before turning it on.
    reranker_model: str | None = None
    reranker_top: int = Field(default=20, ge=2, le=100)
    # Owners with at most this many chunks are searched exactly.
    exact_search_max_chunks: int = Field(default=20_000, ge=0)
    # Spike S-2 recall@10 (3 runs): 0.64-0.69 at 100, 0.85-0.96 at 200, 1.00 at 400.
    hnsw_ef_search: int = Field(default=400, ge=1, le=1000)

    # Chat model. "fake" answers by extracting a sentence from the retrieved passages and needs
    # no key or network; "openai" calls any OpenAI-compatible /chat/completions endpoint.
    chat_provider: Literal["fake", "openai", "bedrock"] = "fake"
    chat_base_url: str = "https://api.openai.com/v1"
    chat_model: str | None = None  # required for openai (model name) and bedrock (model id)
    bedrock_region: str | None = None  # bedrock uses the AWS credential chain, no key here
    # Empty for real AWS. Set only to point the Bedrock adapter at a local stand-in
    # (python -m eka.tools.bedrock_stub) so the full boto3 path can be tested without an account.
    bedrock_endpoint_url: str | None = None
    chat_api_key: SecretStr | None = None  # required when chat_provider="openai"
    chat_timeout_seconds: float = Field(default=60.0, gt=0)
    chat_retries: int = Field(default=2, ge=0, le=5)
    answer_mode: Literal["verified", "fast"] = "verified"
    # 0.50: no answerable question refused on either evaluation set, 20% (main) and 30%
    # (handbook) of unanswerable ones refused before the model is called. 0.55 wrongly refused
    # q31 (best cosine 0.526) in the live run. Sweep: eval/reports/e5_none.md.
    refusal_min_cosine: float = Field(default=0.50, ge=0.0, le=1.0)
    context_passages: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=12_000, ge=500)
    history_messages: int = Field(default=6, ge=0, le=50)
    max_output_tokens: int = Field(default=600, ge=16, le=4000)

    # --- web fallback (ADR-030), off by default ---
    # Exact host names, e.g. ["docs.python.org"]; no wildcards. Entry URLs must be on them.
    web_fallback_enabled: bool = False
    web_allowed_hosts: tuple[str, ...] = ()
    web_entry_urls: tuple[str, ...] = ()
    web_refresh_hours: int = Field(default=24, ge=1)
    web_fetch_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    web_max_page_kb: int = Field(default=2048, ge=16, le=10_240)
    web_ingest_wait_seconds: float = Field(default=30.0, gt=0, le=120)

    @model_validator(mode="after")
    def _web_fallback_is_fully_configured(self) -> Self:
        if not self.web_fallback_enabled:
            return self
        hosts = {host.strip().lower() for host in self.web_allowed_hosts}
        if not hosts or any(not h or "*" in h or "/" in h or ":" in h for h in hosts):
            raise ValueError("EKA_WEB_ALLOWED_HOSTS must list exact host names")
        if not self.web_entry_urls or len(self.web_entry_urls) > 10:
            raise ValueError("EKA_WEB_ENTRY_URLS must list 1 to 10 URLs")
        for url in self.web_entry_urls:
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.username or (parts.hostname or "") not in hosts:
                raise ValueError("each EKA_WEB_ENTRY_URLS entry must be https on an allowed host")
        if ".md" not in self.allowed_text_extensions:
            raise ValueError("the web fallback stores pages as .md; keep it in the allowed types")
        return self

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

    @field_validator(
        "s3_bucket",
        "s3_region",
        "s3_endpoint_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        "reranker_model",
        "bedrock_region",
        "bedrock_endpoint_url",
        mode="before",
    )
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _s3_needs_a_bucket_and_whole_keys(self) -> Self:
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("EKA_S3_BUCKET is required when EKA_STORAGE_BACKEND=s3")
        if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
            raise ValueError(
                "set both EKA_S3_ACCESS_KEY_ID and EKA_S3_SECRET_ACCESS_KEY, or neither"
            )
        return self

    @model_validator(mode="after")
    def _live_chat_needs_a_model_and_a_key(self) -> Self:
        if self.chat_provider == "openai" and (
            self.chat_model is None or self.chat_api_key is None
        ):
            raise ValueError(
                "EKA_CHAT_MODEL and EKA_CHAT_API_KEY are required for the openai provider"
            )
        if self.chat_provider == "bedrock" and self.chat_model is None:
            raise ValueError("EKA_CHAT_MODEL (the Bedrock model id) is required for bedrock")
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
            if not self.gateway_jwks_url:
                raise ValueError("EKA_GATEWAY_JWKS_URL is required when EKA_AUTH_MODE=gateway")
            return self
        if not self.api_keys:
            raise ValueError("EKA_API_KEYS must list at least one key when EKA_AUTH_MODE=api_key")
        return self


@lru_cache
def get_settings() -> Settings:
    """Read once per process; tests build ``Settings`` directly instead."""
    return Settings()
