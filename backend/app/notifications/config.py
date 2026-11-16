from dataclasses import dataclass
from typing import ClassVar

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    name: ClassVar[str] = "smtp"

    host: str | None
    port: int
    username: str | None
    password: str | None
    start_tls: bool
    use_tls: bool


@dataclass(frozen=True, slots=True)
class BrevoConfig:
    name: ClassVar[str] = "brevo"

    api_key: str | None


@dataclass(frozen=True, slots=True)
class MailgunConfig:
    name: ClassVar[str] = "mailgun"

    api_key: str | None
    domain: str | None
    api_url: str


@dataclass(frozen=True, slots=True)
class MailtrapConfig:
    name: ClassVar[str] = "mailtrap"

    api_token: str | None


ProviderConfig = SmtpConfig | BrevoConfig | MailgunConfig | MailtrapConfig


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    enabled: bool
    provider: ProviderConfig
    sender_email: str
    sender_name: str
    recipients: tuple[str, ...]
    timeout_seconds: float

    @property
    def provider_name(self) -> str:
        return self.provider.name


def _provider_from_env(settings: Settings) -> ProviderConfig:
    if settings.email_provider == "brevo":
        return BrevoConfig(
            api_key=(
                settings.brevo_api_key.get_secret_value()
                if settings.brevo_api_key is not None
                else None
            )
        )
    if settings.email_provider == "mailgun":
        return MailgunConfig(
            api_key=(
                settings.mailgun_api_key.get_secret_value()
                if settings.mailgun_api_key is not None
                else None
            ),
            domain=settings.mailgun_domain,
            api_url=settings.mailgun_api_url,
        )
    if settings.email_provider == "mailtrap":
        return MailtrapConfig(
            api_token=(
                settings.mailtrap_api_token.get_secret_value()
                if settings.mailtrap_api_token is not None
                else None
            )
        )
    return SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=(
            settings.smtp_password.get_secret_value()
            if settings.smtp_password is not None
            else None
        ),
        start_tls=settings.smtp_starttls,
        use_tls=settings.smtp_ssl,
    )


def config_from_env(settings: Settings) -> NotificationConfig | None:
    """Map the environment into a notification config without validating details.

    Provider-detail validation belongs to ``build_transport`` so the database and
    environment paths share one set of checks.
    """
    if settings.email_from_address is None or not settings.notification_recipients:
        return None
    return NotificationConfig(
        enabled=settings.email_notifications_enabled,
        provider=_provider_from_env(settings),
        sender_email=str(settings.email_from_address),
        sender_name=settings.email_from_name.strip() or "Uptime Monitor",
        recipients=tuple(str(recipient) for recipient in settings.notification_recipients),
        timeout_seconds=settings.notification_timeout_seconds,
    )
