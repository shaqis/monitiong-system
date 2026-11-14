from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BCRYPT_MAX_PASSWORD_BYTES = 72
MIN_ADMIN_PASSWORD_LENGTH = 12
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


def _is_loopback_origin(origin: str) -> bool:
    host = urlparse(origin).hostname
    if host is None:
        return False
    return host in LOOPBACK_HOSTS or host.endswith(".localhost")


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

    @field_validator("first_admin_password")
    @classmethod
    def validate_first_admin_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError("FIRST_ADMIN_PASSWORD must be at most 72 bytes")
        if len(value) < MIN_ADMIN_PASSWORD_LENGTH:
            raise ValueError(
                f"FIRST_ADMIN_PASSWORD must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters"
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
        # Anything reachable over a network needs the Secure attribute.
        if not self.cookie_secure and not all(
            _is_loopback_origin(origin) for origin in self.cors_origins
        ):
            raise ValueError(
                "COOKIE_SECURE must be true unless every CORS_ORIGINS entry is a loopback origin"
            )
        return self

    @model_validator(mode="after")
    def validate_pool_covers_checks(self) -> "Settings":
        if self.db_pool_size + self.db_max_overflow < self.max_concurrent_checks:
            raise ValueError(
                "DB_POOL_SIZE + DB_MAX_OVERFLOW must be at least MAX_CONCURRENT_CHECKS"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
