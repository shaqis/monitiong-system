from app.core.config import Settings
from app.core.security import hash_password, verify_password


def test_settings_accept_explicit_values() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/uptime",
        first_admin_email="admin@example.com",
        first_admin_password="secret",
        first_admin_name="Admin",
    )

    assert settings.database_url.endswith("/uptime")
    assert settings.cors_origins == ["http://localhost:3000"]


def test_password_hash_uses_bcrypt_and_verifies() -> None:
    hashed = hash_password("secret")

    assert hashed.startswith("$2")
    assert verify_password("secret", hashed)
    assert not verify_password("wrong", hashed)
