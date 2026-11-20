from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

NotificationProviderValue = Literal["smtp", "brevo", "mailgun", "mailtrap"]
EditableProviderValue = Literal["smtp", "brevo", "mailgun", "mailtrap"]
NotificationSettingsSource = Literal["database", "environment"]


class NotificationSettingsResponse(BaseModel):
    enabled: bool
    provider: NotificationProviderValue
    configured: bool
    source: NotificationSettingsSource
    from_address: str | None
    from_name: str
    recipients: list[str]
    timeout_seconds: float
    smtp_host: str | None
    smtp_port: int
    smtp_starttls: bool
    smtp_ssl: bool
    smtp_username: str | None
    smtp_password_set: bool
    brevo_api_key_set: bool
    mailgun_domain: str | None
    mailgun_api_url: str | None
    mailgun_api_key_set: bool
    mailtrap_api_token_set: bool
    provider_credentials_set: bool
    unreadable_secrets: list[NotificationProviderValue] = Field(default_factory=list)


class NotificationSettingsUpdate(BaseModel):
    enabled: bool | None = None
    provider: EditableProviderValue | None = None
    from_address: EmailStr | None = None
    from_name: str | None = Field(default=None, max_length=120)
    recipients: list[EmailStr] | None = Field(default=None, min_length=1)
    timeout_seconds: float | None = Field(default=None, gt=0, le=60)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_starttls: bool | None = None
    smtp_ssl: bool | None = None
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = None
    brevo_api_key: str | None = None
    mailgun_api_key: str | None = None
    mailgun_domain: str | None = Field(default=None, max_length=255)
    mailgun_api_url: str | None = Field(default=None, max_length=255)
    mailtrap_api_token: str | None = None

    @field_validator(
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "brevo_api_key",
        "mailgun_api_key",
        "mailgun_domain",
        "mailgun_api_url",
        "mailtrap_api_token",
        mode="before",
    )
    @classmethod
    def blank_secrets_and_hosts_are_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("mailgun_api_url")
    @classmethod
    def mailgun_api_url_requires_https(cls, value: str | None) -> str | None:
        # The API key travels in this request, so a stored URL must not downgrade it.
        if value is None:
            return None
        if not value.startswith("https://"):
            raise ValueError("MAILGUN_API_URL must start with https://")
        return value
