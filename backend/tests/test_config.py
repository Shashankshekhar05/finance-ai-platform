"""Configuration validation: required values fail fast, defaults sane."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

_DEV_JWT = "test-only-secret-that-is-long-enough-123456"


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=None, jwt_secret_key=_DEV_JWT)  # type: ignore[arg-type]


def test_invalid_database_url_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="not-a-url", jwt_secret_key=_DEV_JWT)


def test_sane_defaults() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg2://u:p@localhost:5432/db",
        jwt_secret_key=_DEV_JWT,
    )
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.app_name == "finance-dashboard"
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 60


def test_jwt_secret_is_required_and_strong() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, database_url="postgresql+psycopg2://u:p@localhost:5432/db"
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg2://u:p@localhost:5432/db",
            jwt_secret_key="too-short",
        )


def test_app_settings_load_from_environment() -> None:
    # The dev/test environment provides DATABASE_URL + JWT_SECRET_KEY.
    try:
        settings = get_settings()
    except ValidationError:
        pytest.skip("auth settings not configured in this environment")
    assert str(settings.database_url).startswith("postgresql")
    assert len(settings.jwt_secret_key) >= 32
