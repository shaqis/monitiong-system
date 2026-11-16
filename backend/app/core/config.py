import json
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BCRYPT_MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 12
MIN_JWT_SECRET_LENGTH = 32

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

PLACEHOLDER_ADMIN_PASSWORDS = frozenset(
    {
        "change-me-now",
        "changeme",
        "replace-me",
        "your-password-here",
    }
)
PLACEHOLDER_JWT_SECRETS = frozenset(
    {
        "local-dev-jwt-secret-at-least-32-bytes",
        "change-me-now",
        "replace-me",
        "your-secret-here",
    }
)

JwtAlgorithm = Literal["HS256", "HS384", "HS512"]
EmailProvider = Literal["smtp", "brevo", "mailgun", "mailtrap"]


def is_loopback_host(host: str) -> bool:
    return host in LOOPBACK_HOSTS or host.endswith(".localhost")


def _is_loopback_origin(origin: str) -> bool:
    host = urlparse(origin).hostname
    return host is not None and is_loopback_host(host)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str
    first_admin_email: EmailStr
    first_admin_password: str
    first_admin_name: str
    cors_origins: list[str] = ["http://localhost:3000"]
    jwt_secret: str
    jwt_algorithm: JwtAlgorithm = "HS256"
    jwt_expire_minutes: int = 60
    auth_cookie_name: str = "access_token"
    cookie_secure: bool = True
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = Field(default=10, ge=1)
    scheduler_retry_seconds: int = Field(default=5, ge=1)
    max_concurrent_checks: int = Field(default=20, ge=1)
    probe_user_agent: str = "UptimeMonitor/1.0"
    ssl_inspect_timeout_seconds: float = Field(default=5.0, gt=0)
    db_pool_size: int = Field(default=20, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    email_notifications_enabled: bool = False
    email_provider: EmailProvider = "smtp"
    email_from_address: EmailStr | None = None
    email_from_name: str = "Uptime Monitor"
    notification_recipients: Annotated[list[EmailStr], NoDecode] = Field(default_factory=list)
    notification_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    brevo_api_key: SecretStr | None = None
    mailgun_api_key: SecretStr | None = None
    mailgun_domain: str | None = None
    mailgun_api_url: str = "https://api.mailgun.net/v3"
    mailtrap_api_token: SecretStr | None = None

    @field_validator("first_admin_password")
    @classmethod
    def validate_first_admin_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError("FIRST_ADMIN_PASSWORD must be at most 72 bytes")
        if len(value) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"FIRST_ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        if value.strip().lower() in PLACEHOLDER_ADMIN_PASSWORDS:
            raise ValueError("FIRST_ADMIN_PASSWORD must not be a documented placeholder")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if len(value.encode("utf-8")) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} bytes")
        if value.strip().lower() in PLACEHOLDER_JWT_SECRETS:
            raise ValueError("JWT_SECRET must not be a documented placeholder")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: list[str]) -> list[str]:
        # Credentialed requests make a wildcard origin reflect the caller's
        # Origin, so the browser would accept authenticated cross-site reads.
        if any(origin.strip() == "*" for origin in value):
            raise ValueError(
                "CORS_ORIGINS must not contain the wildcard '*' while credentials are allowed"
            )
        return value

    @model_validator(mode="after")
    def validate_cookie_secure(self) -> "Settings":
        # A plaintext cookie is acceptable only against a loopback frontend.
        # An empty origin list matches the reverse-proxy shape and gets no
        # exemption: all([]) is true, so it would otherwise skip the check.
        loopback_only = bool(self.cors_origins) and all(
            _is_loopback_origin(origin) for origin in self.cors_origins
        )
        if not self.cookie_secure and not loopback_only:
            raise ValueError(
                "COOKIE_SECURE must be true unless CORS_ORIGINS lists at least one "
                "loopback origin and no other origin"
            )
        return self

    @model_validator(mode="after")
    def validate_pool_covers_checks(self) -> "Settings":
        if self.db_pool_size + self.db_max_overflow < self.max_concurrent_checks:
            raise ValueError(
                "DB_POOL_SIZE + DB_MAX_OVERFLOW must be at least MAX_CONCURRENT_CHECKS"
            )
        return self

    @field_validator(
        "email_from_address",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "brevo_api_key",
        "mailgun_api_key",
        "mailgun_domain",
        "mailtrap_api_token",
        mode="before",
    )
    @classmethod
    def blank_email_values_are_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("notification_recipients", mode="before")
    @classmethod
    def parse_notification_recipients(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            if not value.strip():
                return []
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                raise ValueError(
                    "NOTIFICATION_RECIPIENTS must be a JSON list of email addresses"
                ) from None
        return value

    @model_validator(mode="after")
    def validate_email_notifications(self) -> "Settings":
        if not self.email_notifications_enabled:
            return self
        if self.email_from_address is None:
            raise ValueError(
                "EMAIL_FROM_ADDRESS is required when EMAIL_NOTIFICATIONS_ENABLED is true"
            )
        if not self.email_from_name.strip():
            raise ValueError("EMAIL_FROM_NAME must not be blank")
        if not self.notification_recipients:
            raise ValueError(
                "NOTIFICATION_RECIPIENTS must list at least one address when "
                "EMAIL_NOTIFICATIONS_ENABLED is true"
            )
        if self.email_provider == "smtp":
            if self.smtp_host is None:
                raise ValueError("SMTP_HOST is required when EMAIL_PROVIDER is smtp")
            if self.smtp_starttls and self.smtp_ssl:
                raise ValueError("SMTP_STARTTLS and SMTP_SSL cannot both be true")
            if (self.smtp_username is None) != (self.smtp_password is None):
                raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be set together")
            if (
                self.smtp_username is not None
                and not self.smtp_starttls
                and not self.smtp_ssl
                and not is_loopback_host(self.smtp_host)
            ):
                raise ValueError(
                    "SMTP_USERNAME requires SMTP_STARTTLS or SMTP_SSL unless "
                    "SMTP_HOST is a loopback host"
                )
        elif self.email_provider == "brevo":
            if self.brevo_api_key is None:
                raise ValueError("BREVO_API_KEY is required when EMAIL_PROVIDER is brevo")
        elif self.email_provider == "mailgun":
            if self.mailgun_api_key is None or self.mailgun_domain is None:
                raise ValueError(
                    "MAILGUN_API_KEY and MAILGUN_DOMAIN are required when EMAIL_PROVIDER is mailgun"
                )
        elif self.email_provider == "mailtrap":
            if self.mailtrap_api_token is None:
                raise ValueError("MAILTRAP_API_TOKEN is required when EMAIL_PROVIDER is mailtrap")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
