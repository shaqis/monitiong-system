import pytest
from pydantic import ValidationError

from app.core.config import (
    BCRYPT_MAX_PASSWORD_BYTES,
    MIN_JWT_SECRET_LENGTH,
    MIN_PASSWORD_LENGTH,
    Settings,
)
from app.core.security import hash_password, verify_password

STRONG_PASSWORD = "test-admin-password"
STRONG_SECRET = "test-secret-that-is-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch) -> None:
    for key in (
        "CORS_ORIGINS",
        "SCHEDULER_ENABLED",
        "COOKIE_SECURE",
        "JWT_ALGORITHM",
        "JWT_EXPIRE_MINUTES",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "MAX_CONCURRENT_CHECKS",
        "EMAIL_NOTIFICATIONS_ENABLED",
        "EMAIL_PROVIDER",
        "EMAIL_FROM_ADDRESS",
        "EMAIL_FROM_NAME",
        "NOTIFICATION_RECIPIENTS",
        "NOTIFICATION_TIMEOUT_SECONDS",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_STARTTLS",
        "SMTP_SSL",
        "BREVO_API_KEY",
        "MAILGUN_API_KEY",
        "MAILGUN_DOMAIN",
        "MAILGUN_API_URL",
        "MAILTRAP_API_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def build_settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/uptime",
        "first_admin_email": "admin@example.com",
        "first_admin_password": STRONG_PASSWORD,
        "first_admin_name": "Admin",
        "jwt_secret": STRONG_SECRET,
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_accept_explicit_values() -> None:
    settings = build_settings()

    assert settings.database_url.endswith("/uptime")
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_minutes == 60
    assert settings.cookie_secure is True
    assert settings.scheduler_enabled is True
    assert settings.scheduler_poll_seconds == 10
    assert settings.scheduler_retry_seconds == 5
    assert settings.max_concurrent_checks == 20
    assert settings.probe_user_agent == "UptimeMonitor/1.0"
    assert settings.ssl_inspect_timeout_seconds == 5.0
    assert settings.db_pool_size == 20
    assert settings.db_max_overflow == 10


def test_settings_allow_secure_cookie_override() -> None:
    settings = build_settings(cookie_secure=False)

    assert settings.cookie_secure is False


def test_settings_pool_capacity_covers_concurrency() -> None:
    settings = build_settings(
        max_concurrent_checks=25,
        db_pool_size=20,
        db_max_overflow=5,
    )

    assert settings.db_pool_size + settings.db_max_overflow == settings.max_concurrent_checks


def test_settings_reject_pool_smaller_than_concurrency() -> None:
    with pytest.raises(ValidationError):
        build_settings(
            max_concurrent_checks=25,
            db_pool_size=20,
            db_max_overflow=4,
        )


def test_settings_reject_long_admin_password() -> None:
    with pytest.raises(ValidationError):
        build_settings(first_admin_password="a" * (BCRYPT_MAX_PASSWORD_BYTES + 1))


def test_settings_reject_short_admin_password_without_echoing_it() -> None:
    value = "sh0rt"

    with pytest.raises(ValidationError) as exc_info:
        build_settings(first_admin_password=value)

    message = str(exc_info.value)
    assert str(MIN_PASSWORD_LENGTH) in message
    assert value not in message


def test_settings_reject_placeholder_admin_password() -> None:
    value = "change-me-now"

    with pytest.raises(ValidationError) as exc_info:
        build_settings(first_admin_password=value)

    assert "placeholder" in str(exc_info.value)
    assert value not in str(exc_info.value)


def test_settings_reject_short_jwt_secret_without_echoing_it() -> None:
    value = "s" * (MIN_JWT_SECRET_LENGTH - 1)

    with pytest.raises(ValidationError) as exc_info:
        build_settings(jwt_secret=value)

    message = str(exc_info.value)
    assert str(MIN_JWT_SECRET_LENGTH) in message
    assert value not in message


def test_settings_reject_placeholder_jwt_secret() -> None:
    value = "local-dev-jwt-secret-at-least-32-bytes"

    with pytest.raises(ValidationError) as exc_info:
        build_settings(jwt_secret=value)

    assert "placeholder" in str(exc_info.value)
    assert value not in str(exc_info.value)


def test_settings_reject_unsupported_jwt_algorithm() -> None:
    with pytest.raises(ValidationError):
        build_settings(jwt_algorithm="none")


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


def test_verify_password_rejects_malformed_hash() -> None:
    assert not verify_password("secret", "not-a-hash")
    assert not verify_password("secret", "$2b$12$invalid")


def test_settings_reject_wildcard_cors_origin() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(cors_origins=["*"])

    assert "wildcard" in str(exc_info.value)


def test_settings_reject_insecure_cookie_for_public_origin() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(cookie_secure=False, cors_origins=["https://monitor.example.com"])

    assert "COOKIE_SECURE" in str(exc_info.value)


def test_settings_reject_insecure_cookie_without_any_origin() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(cookie_secure=False, cors_origins=[])

    assert "COOKIE_SECURE" in str(exc_info.value)


def test_settings_allow_insecure_cookie_for_loopback_origin() -> None:
    settings = build_settings(cookie_secure=False, cors_origins=["http://127.0.0.1:3000"])

    assert settings.cookie_secure is False


def test_settings_allow_disabled_email_notifications_without_config() -> None:
    settings = build_settings()

    assert settings.email_notifications_enabled is False
    assert settings.email_provider == "smtp"
    assert settings.email_from_address is None
    assert settings.notification_recipients == []


def test_settings_require_email_configuration_when_enabled() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(email_notifications_enabled=True)

    message = str(exc_info.value)
    assert "EMAIL_FROM_ADDRESS" in message


def test_settings_require_recipients_when_email_is_enabled() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(
            email_notifications_enabled=True,
            email_from_address="alerts@example.com",
            smtp_host="smtp.example.com",
        )

    assert "NOTIFICATION_RECIPIENTS" in str(exc_info.value)


def test_settings_require_provider_credentials_when_enabled() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(
            email_notifications_enabled=True,
            email_provider="brevo",
            email_from_address="alerts@example.com",
            notification_recipients=["ops@example.com"],
        )

    assert "BREVO_API_KEY" in str(exc_info.value)


def test_settings_require_smtp_username_and_password_together() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(
            email_notifications_enabled=True,
            email_from_address="alerts@example.com",
            notification_recipients=["ops@example.com"],
            smtp_host="smtp.example.com",
            smtp_username="smtp-user",
        )

    assert "SMTP_USERNAME" in str(exc_info.value)


def test_settings_reject_starttls_and_implicit_tls_together() -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(
            email_notifications_enabled=True,
            email_from_address="alerts@example.com",
            notification_recipients=["ops@example.com"],
            smtp_host="smtp.example.com",
            smtp_starttls=True,
            smtp_ssl=True,
        )

    assert "SMTP_STARTTLS" in str(exc_info.value)


def test_settings_accept_complete_smtp_configuration() -> None:
    settings = build_settings(
        email_notifications_enabled=True,
        email_from_address="alerts@example.com",
        notification_recipients=["ops@example.com"],
        smtp_host="smtp.example.com",
        smtp_username="smtp-user",
        smtp_password="smtp-password",
    )

    assert settings.email_from_address == "alerts@example.com"
    assert settings.notification_recipients == ["ops@example.com"]


def test_settings_hide_email_secrets_in_repr() -> None:
    settings = build_settings(
        email_provider="brevo",
        brevo_api_key="super-secret-key",
        smtp_password="super-secret-password",
    )

    representation = repr(settings)
    assert "super-secret-key" not in representation
    assert "super-secret-password" not in representation


def test_settings_treat_blank_optional_email_values_as_unset() -> None:
    settings = build_settings(
        email_from_address="",
        smtp_host="",
        smtp_password="",
        mailgun_api_key="",
    )

    assert settings.email_from_address is None
    assert settings.smtp_host is None
    assert settings.smtp_password is None
    assert settings.mailgun_api_key is None
