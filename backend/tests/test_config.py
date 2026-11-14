import pytest
from pydantic import ValidationError

from app.core.config import BCRYPT_MAX_PASSWORD_BYTES, Settings
from app.core.security import hash_password, verify_password


def test_settings_accept_explicit_values(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/uptime",
        first_admin_email="admin@example.com",
        first_admin_password="secret",
        first_admin_name="Admin",
        jwt_secret="test-secret-that-is-at-least-32-bytes-long",
    )

    assert settings.database_url.endswith("/uptime")
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_minutes == 60
    assert settings.cookie_secure is False


def test_settings_reject_long_admin_password() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/uptime",
            first_admin_email="admin@example.com",
            first_admin_password="a" * (BCRYPT_MAX_PASSWORD_BYTES + 1),
            first_admin_name="Admin",
            jwt_secret="test-secret-that-is-at-least-32-bytes-long",
        )


def test_password_hash_uses_bcrypt_and_verifies() -> None:
    hashed = hash_password("secret")

    assert hashed.startswith("$2")
    assert verify_password("secret", hashed)
    assert not verify_password("wrong", hashed)


def test_password_helpers_reject_input_over_bcrypt_limit() -> None:
    long_password = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

    with pytest.raises(ValueError):
        hash_password(long_password)

    assert not verify_password(long_password, "$2b$12$invalid")
