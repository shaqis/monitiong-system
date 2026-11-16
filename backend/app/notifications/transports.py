from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Any, Protocol

import aiosmtplib
import httpx

from app.core.config import is_loopback_host
from app.notifications.config import (
    BrevoConfig,
    MailgunConfig,
    MailtrapConfig,
    ProviderConfig,
    SmtpConfig,
)


class NotificationConfigError(ValueError):
    """The selected transport is missing required configuration."""


class EmailTransportError(Exception):
    """A provider rejected or could not accept a message."""

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider} delivery failed: {reason}")


@dataclass(frozen=True, slots=True)
class OutboundEmail:
    sender_email: str
    sender_name: str
    recipients: tuple[str, ...]
    subject: str
    text: str
    html: str


class EmailTransport(Protocol):
    name: str

    async def send(self, message: OutboundEmail) -> None: ...


class _HttpTransport:
    name: str

    def __init__(
        self,
        *,
        timeout_seconds: float,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._http_transport = http_transport

    async def _post(self, url: str, **kwargs: Any) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._http_transport,
            ) as client:
                response = await client.post(url, **kwargs)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise EmailTransportError(self.name, f"HTTP {exc.response.status_code}") from None
        except httpx.RequestError as exc:
            raise EmailTransportError(self.name, type(exc).__name__) from None


class SmtpTransport:
    name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        start_tls: bool,
        use_tls: bool,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._start_tls = start_tls
        self._use_tls = use_tls
        self._timeout_seconds = timeout_seconds

    async def send(self, message: OutboundEmail) -> None:
        mime = MimeMessage()
        mime["From"] = f"{message.sender_name} <{message.sender_email}>"
        mime["To"] = ", ".join(message.recipients)
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")

        try:
            await aiosmtplib.send(
                mime,
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                start_tls=self._start_tls,
                use_tls=self._use_tls,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise EmailTransportError(self.name, type(exc).__name__) from None


class BrevoTransport(_HttpTransport):
    name = "brevo"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, http_transport=http_transport)
        self._api_key = api_key

    async def send(self, message: OutboundEmail) -> None:
        await self._post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": self._api_key, "accept": "application/json"},
            json={
                "sender": {"email": message.sender_email, "name": message.sender_name},
                "to": [{"email": recipient} for recipient in message.recipients],
                "subject": message.subject,
                "textContent": message.text,
                "htmlContent": message.html,
            },
        )


class MailgunTransport(_HttpTransport):
    name = "mailgun"

    def __init__(
        self,
        *,
        api_key: str,
        domain: str,
        api_url: str,
        timeout_seconds: float,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, http_transport=http_transport)
        self._api_key = api_key
        self._domain = domain
        self._api_url = api_url.rstrip("/")

    async def send(self, message: OutboundEmail) -> None:
        form: dict[str, str | list[str]] = {
            "from": f"{message.sender_name} <{message.sender_email}>",
            "to": list(message.recipients),
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        }
        await self._post(
            f"{self._api_url}/{self._domain}/messages",
            auth=("api", self._api_key),
            data=form,
        )


class MailtrapTransport(_HttpTransport):
    name = "mailtrap"

    def __init__(
        self,
        *,
        api_token: str,
        timeout_seconds: float,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, http_transport=http_transport)
        self._api_token = api_token

    async def send(self, message: OutboundEmail) -> None:
        await self._post(
            "https://send.api.mailtrap.io/api/send",
            headers={"Authorization": f"Bearer {self._api_token}"},
            json={
                "from": {"email": message.sender_email, "name": message.sender_name},
                "to": [{"email": recipient} for recipient in message.recipients],
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            },
        )


def build_transport(provider: ProviderConfig, timeout_seconds: float) -> EmailTransport:
    if isinstance(provider, SmtpConfig):
        if provider.host is None:
            raise NotificationConfigError("SMTP_HOST is required when EMAIL_PROVIDER is smtp")
        if provider.start_tls and provider.use_tls:
            raise NotificationConfigError("SMTP_STARTTLS and SMTP_SSL cannot both be true")
        if (provider.username is None) != (provider.password is None):
            raise NotificationConfigError("SMTP_USERNAME and SMTP_PASSWORD must be set together")
        if (
            provider.username is not None
            and not provider.start_tls
            and not provider.use_tls
            and not is_loopback_host(provider.host)
        ):
            raise NotificationConfigError(
                "SMTP_USERNAME requires SMTP_STARTTLS or SMTP_SSL unless "
                "SMTP_HOST is a loopback host"
            )
        return SmtpTransport(
            host=provider.host,
            port=provider.port,
            username=provider.username,
            password=provider.password,
            start_tls=provider.start_tls,
            use_tls=provider.use_tls,
            timeout_seconds=timeout_seconds,
        )

    if isinstance(provider, BrevoConfig):
        if provider.api_key is None:
            raise NotificationConfigError("BREVO_API_KEY is required when EMAIL_PROVIDER is brevo")
        return BrevoTransport(
            api_key=provider.api_key,
            timeout_seconds=timeout_seconds,
        )

    if isinstance(provider, MailgunConfig):
        if provider.api_key is None or provider.domain is None:
            raise NotificationConfigError(
                "MAILGUN_API_KEY and MAILGUN_DOMAIN are required when EMAIL_PROVIDER is mailgun"
            )
        return MailgunTransport(
            api_key=provider.api_key,
            domain=provider.domain,
            api_url=provider.api_url,
            timeout_seconds=timeout_seconds,
        )

    if not isinstance(provider, MailtrapConfig):
        raise NotificationConfigError("Unsupported email provider")

    if provider.api_token is None:
        raise NotificationConfigError(
            "MAILTRAP_API_TOKEN is required when EMAIL_PROVIDER is mailtrap"
        )
    return MailtrapTransport(
        api_token=provider.api_token,
        timeout_seconds=timeout_seconds,
    )
