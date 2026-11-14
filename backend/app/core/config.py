from functools import lru_cache

from pydantic import EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BCRYPT_MAX_PASSWORD_BYTES = 72


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str
    first_admin_email: EmailStr
    first_admin_password: str
    first_admin_name: str
    cors_origins: list[str] = ["http://localhost:3000"]
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    auth_cookie_name: str = "access_token"
    cookie_secure: bool = False
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
        return value

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
