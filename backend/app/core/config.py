from functools import lru_cache

from pydantic import EmailStr, field_validator
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

    @field_validator("first_admin_password")
    @classmethod
    def validate_first_admin_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError("FIRST_ADMIN_PASSWORD must be at most 72 bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
