from datetime import UTC, datetime
from html import escape
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from app.notifications.events import IncidentEvent, IncidentOpened, IncidentResolved
from app.notifications.transports import EmailTransport, OutboundEmail


class IncidentNotifier(Protocol):
    async def notify(self, event: IncidentEvent) -> None: ...


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _display_url(url: str) -> str:
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, parts.query, parts.fragment)
    )


def _render_html(title: str, rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f'<tr><th align="left">{escape(label)}</th><td>{escape(value)}</td></tr>'
        for label, value in rows
    )
    return f"<h2>{escape(title)}</h2><table>{body}</table>"


def _render_event(
    event: IncidentEvent,
    *,
    sender_email: str,
    sender_name: str,
    recipients: tuple[str, ...],
) -> OutboundEmail:
    match event:
        case IncidentOpened():
            title = f"Monitor {event.monitor_name} is down"
            rows = [
                ("Monitor", event.monitor_name),
                ("URL", _display_url(event.monitor_url)),
                ("Cause", event.cause),
                ("Opened", _format_utc(event.opened_at)),
            ]
            subject = f"[DOWN] {event.monitor_name}"
        case IncidentResolved():
            title = f"Monitor {event.monitor_name} recovered"
            rows = [
                ("Monitor", event.monitor_name),
                ("URL", _display_url(event.monitor_url)),
                ("Started", _format_utc(event.started_at)),
                ("Resolved", _format_utc(event.resolved_at)),
                ("Duration", f"{event.duration_seconds} seconds"),
            ]
            subject = f"[UP] {event.monitor_name}"

    text = "\n".join([title, "", *[f"{label}: {value}" for label, value in rows]])
    return OutboundEmail(
        sender_email=sender_email,
        sender_name=sender_name,
        recipients=recipients,
        subject=subject,
        text=text,
        html=_render_html(title, rows),
    )


class NotificationService:
    def __init__(
        self,
        transport: EmailTransport,
        *,
        sender_email: str,
        sender_name: str,
        recipients: tuple[str, ...],
    ) -> None:
        if not recipients:
            raise ValueError("At least one notification recipient is required")
        self._transport = transport
        self._sender_email = sender_email
        self._sender_name = sender_name
        self._recipients = recipients

    async def notify(self, event: IncidentEvent) -> None:
        await self._transport.send(
            _render_event(
                event,
                sender_email=self._sender_email,
                sender_name=self._sender_name,
                recipients=self._recipients,
            )
        )

    async def send_test(self) -> None:
        now = _format_utc(datetime.now(UTC))
        title = f"{self._sender_name} test email"
        text = (
            "This is a test email from your uptime monitor.\n\n"
            f"Sent at: {now}\n"
            f"Provider: {self._transport.name}\n\n"
            "If you received this message, the email transport is configured correctly."
        )
        await self._transport.send(
            OutboundEmail(
                sender_email=self._sender_email,
                sender_name=self._sender_name,
                recipients=self._recipients,
                subject=f"[{self._sender_name}] Test email",
                text=text,
                html=_render_html(
                    title,
                    [("Sent at", now), ("Provider", self._transport.name)],
                ),
            )
        )
