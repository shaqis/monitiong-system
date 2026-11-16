from typing import Literal

from pydantic import BaseModel

NotificationProviderValue = Literal["smtp", "brevo", "mailgun", "mailtrap"]


class NotificationSettingsResponse(BaseModel):
    enabled: bool
    provider: NotificationProviderValue
    configured: bool
    from_address: str | None
    from_name: str
    recipients: list[str]
    timeout_seconds: float
    smtp_host: str | None
    smtp_port: int
    smtp_starttls: bool
    smtp_ssl: bool
    smtp_username_set: bool
    mailgun_domain: str | None
    provider_credentials_set: bool
