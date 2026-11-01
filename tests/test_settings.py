import json

import pytest
from pydantic import ValidationError

from eka.config import Settings
from eka.security.auth import digest_key

DB_URL = "postgresql+psycopg://eka:s3cretpw@127.0.0.1:5432/eka"
KEYS_JSON = json.dumps({"alice": {"sha256": digest_key("k").hex(), "role": "user"}})


def _local(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "local",
        "database_url": DB_URL,
        "auth_mode": "api_key",
        "api_keys": {"alice": {"sha256": digest_key("k").hex(), "role": "user"}},
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_settings_read_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("EKA_LOG_JSON", "true")
    monkeypatch.setenv("EKA_ENVIRONMENT", "test")
    settings = Settings(_env_file=None)
    assert settings.log_level == "DEBUG"
    assert settings.log_json is True


def test_settings_reject_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKA_ENVIRONMENT", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_keys_are_parsed_from_a_json_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKA_ENVIRONMENT", "local")
    monkeypatch.setenv("EKA_DATABASE_URL", DB_URL)
    monkeypatch.setenv("EKA_AUTH_MODE", "api_key")
    monkeypatch.setenv("EKA_API_KEYS", KEYS_JSON)
    settings = Settings(_env_file=None)
    assert set(settings.api_keys) == {"alice"}
    assert settings.api_keys["alice"].role == "user"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database_url": None}, "EKA_DATABASE_URL is required"),
        ({"auth_mode": None}, "EKA_AUTH_MODE is required"),
        ({"api_keys": {}}, "EKA_API_KEYS must list at least one key"),
        ({"auth_mode": "gateway"}, "not available yet"),
    ],
)
def test_startup_fails_when_half_configured_outside_test(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _local(**overrides)


def test_test_environment_may_omit_everything() -> None:
    settings = Settings(_env_file=None, environment="test")
    assert settings.database_url is None
    assert settings.auth_mode is None
    assert settings.api_keys == {}


def test_user_ids_must_match_the_pattern_and_are_not_echoed() -> None:
    digest = digest_key("k").hex()
    with pytest.raises(ValidationError) as caught:
        _local(api_keys={"not a valid id!": {"sha256": digest, "role": "user"}})
    assert "do not match" in str(caught.value)
    assert "not a valid id!" not in str(caught.value)


@pytest.mark.parametrize("digest", ["", "abc", "z" * 64, "a" * 63, "a" * 65])
def test_digest_must_be_64_hex_characters(digest: str) -> None:
    with pytest.raises(ValidationError):
        _local(api_keys={"alice": {"sha256": digest, "role": "user"}})


def test_role_must_be_known() -> None:
    with pytest.raises(ValidationError):
        _local(api_keys={"alice": {"sha256": digest_key("k").hex(), "role": "superuser"}})


def test_database_url_must_use_the_psycopg_driver_and_the_error_hides_the_password() -> None:
    with pytest.raises(ValidationError, match="must start with postgresql\\+psycopg://") as caught:
        _local(database_url="postgresql://eka:hunter2pw@127.0.0.1/eka")
    assert "hunter2pw" not in str(caught.value)


def test_repr_hides_the_database_password_and_key_digests() -> None:
    text = repr(_local())
    assert "s3cretpw" not in text
    assert digest_key("k").hex() not in text
