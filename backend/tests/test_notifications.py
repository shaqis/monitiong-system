import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import Incident
from app.main import app
from app.notifications.events import IncidentOpened, IncidentResolved
from app.notifications.service import NotificationService
from app.notifications.transports import (
    BrevoTransport,
    EmailTransportError,
    MailgunTransport,
    MailtrapTransport,
    NotificationConfigError,
    OutboundEmail,
    SmtpTransport,
    build_transport,
)
from app.worker.checker import CheckRunner
from app.worker.prober import ProbeResult, ProbeTarget

SENDER = "alerts@example.com"
RECIPIENTS = ("ops@example.com",)


def _message() -> OutboundEmail:
    return OutboundEmail(
        sender_email=SENDER,
        sender_name="Uptime Monitor",
        recipients=RECIPIENTS,
        subject="[DOWN] Production",
        text="text body",
        html="<p>html body</p>",
    )


def _service(transport) -> NotificationService:
    return NotificationService(
        transport,
        sender_email=SENDER,
        sender_name="Uptime Monitor",
        recipients=RECIPIENTS,
    )


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/uptime",
        "first_admin_email": "admin@example.com",
        "first_admin_password": "test-admin-password",
        "first_admin_name": "Admin",
        "jwt_secret": "test-secret-that-is-at-least-32-bytes-long",
        "email_from_address": "alerts@example.com",
        "notification_recipients": ["ops@example.com"],
    }
    values.update(overrides)
    return Settings(**values)


def test_build_transport_selects_each_provider() -> None:
    assert isinstance(
        build_transport(_settings(smtp_host="smtp.example.com")),
        SmtpTransport,
    )
    assert isinstance(
        build_transport(_settings(email_provider="brevo", brevo_api_key="brevo-key")),
        BrevoTransport,
    )
    assert isinstance(
        build_transport(
            _settings(
                email_provider="mailgun",
                mailgun_api_key="mailgun-key",
                mailgun_domain="mg.example.com",
            )
        ),
        MailgunTransport,
    )
    assert isinstance(
        build_transport(_settings(email_provider="mailtrap", mailtrap_api_token="token")),
        MailtrapTransport,
    )


def test_build_transport_reports_missing_provider_config() -> None:
    with pytest.raises(NotificationConfigError):
        build_transport(_settings(email_provider="brevo"))


class RecordingTransport:
    name = "fake"

    def __init__(self, error: Exception | None = None) -> None:
        self.messages: list[OutboundEmail] = []
        self.error = error

    async def send(self, message: OutboundEmail) -> None:
        if self.error is not None:
            raise self.error
        self.messages.append(message)


class RecordingNotifier:
    def __init__(self, error: Exception | None = None) -> None:
        self.events = []
        self.error = error

    async def notify(self, event) -> None:
        if self.error is not None:
            raise self.error
        self.events.append(event)


def _failure() -> ProbeResult:
    return ProbeResult(
        ok=False,
        status_code=503,
        response_time_ms=25,
        keyword_matched=None,
        error_message="Expected 200, got 503",
        ssl_days_remaining=None,
    )


def _success() -> ProbeResult:
    return ProbeResult(
        ok=True,
        status_code=200,
        response_time_ms=10,
        keyword_matched=None,
        error_message=None,
        ssl_days_remaining=None,
    )


class SequenceProber:
    def __init__(self, results: list[ProbeResult]) -> None:
        self._results = list(results)

    async def __call__(self, target: ProbeTarget, **_kwargs) -> ProbeResult:
        return self._results.pop(0)


async def test_opened_event_renders_down_message() -> None:
    opened_at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    event = IncidentOpened(
        monitor_id=uuid4(),
        monitor_name="Production",
        monitor_url="https://example.com",
        cause="Expected 200, got 503",
        opened_at=opened_at,
    )
    transport = RecordingTransport()

    await _service(transport).notify(event)

    message = transport.messages[0]
    assert message.subject == "[DOWN] Production"
    assert "Monitor Production is down" in message.text
    assert "Cause: Expected 200, got 503" in message.text
    assert "2026-11-16 12:00:00 UTC" in message.text
    assert "https://example.com" in message.html


async def test_resolved_event_renders_recovery_and_duration() -> None:
    started_at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    event = IncidentResolved(
        monitor_id=uuid4(),
        monitor_name="Production",
        monitor_url="https://example.com",
        started_at=started_at,
        resolved_at=started_at + timedelta(seconds=125),
        duration_seconds=125,
    )
    transport = RecordingTransport()

    await _service(transport).notify(event)

    message = transport.messages[0]
    assert message.subject == "[UP] Production"
    assert "Duration: 125 seconds" in message.text
    assert "Monitor Production recovered" in message.html


async def test_service_requires_at_least_one_recipient() -> None:
    with pytest.raises(ValueError):
        NotificationService(
            RecordingTransport(),
            sender_email=SENDER,
            sender_name="Uptime Monitor",
            recipients=(),
        )


async def test_smtp_transport_sends_multipart_message(monkeypatch) -> None:
    sent: dict[str, object] = {}

    async def fake_send(message, **kwargs) -> None:
        sent["message"] = message
        sent["kwargs"] = kwargs

    monkeypatch.setattr("app.notifications.transports.aiosmtplib.send", fake_send)
    transport = SmtpTransport(
        host="smtp.example.com",
        port=587,
        username="smtp-user",
        password="smtp-password",
        start_tls=True,
        use_tls=False,
        timeout_seconds=5,
    )

    await transport.send(_message())

    mime = sent["message"]
    assert mime["To"] == "ops@example.com"
    assert mime["Subject"] == "[DOWN] Production"
    plain = mime.get_body(preferencelist=("plain",))
    html = mime.get_body(preferencelist=("html",))
    assert plain is not None and plain.get_content().strip() == "text body"
    assert html is not None and html.get_content().strip() == "<p>html body</p>"
    kwargs = sent["kwargs"]
    assert kwargs["hostname"] == "smtp.example.com"
    assert kwargs["port"] == 587
    assert kwargs["username"] == "smtp-user"
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False


def _mock_http(requests: list[httpx.Request], status_code: int = 200):
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code)

    return httpx.MockTransport(handler)


async def test_brevo_transport_posts_expected_payload() -> None:
    requests: list[httpx.Request] = []
    transport = BrevoTransport(
        api_key="brevo-key",
        timeout_seconds=5,
        http_transport=_mock_http(requests),
    )

    await transport.send(_message())

    request = requests[0]
    assert str(request.url) == "https://api.brevo.com/v3/smtp/email"
    assert request.headers["api-key"] == "brevo-key"
    body = json.loads(request.content)
    assert body["sender"] == {"email": SENDER, "name": "Uptime Monitor"}
    assert body["to"] == [{"email": "ops@example.com"}]
    assert body["subject"] == "[DOWN] Production"
    assert body["textContent"] == "text body"
    assert body["htmlContent"] == "<p>html body</p>"


async def test_mailgun_transport_posts_expected_payload() -> None:
    requests: list[httpx.Request] = []
    transport = MailgunTransport(
        api_key="mailgun-key",
        domain="mg.example.com",
        api_url="https://api.mailgun.net/v3",
        timeout_seconds=5,
        http_transport=_mock_http(requests),
    )

    await transport.send(_message())

    request = requests[0]
    assert str(request.url) == "https://api.mailgun.net/v3/mg.example.com/messages"
    assert request.headers["authorization"].startswith("Basic ")
    form = parse_qs(request.content.decode())
    assert form["from"] == ["Uptime Monitor <alerts@example.com>"]
    assert form["to"] == ["ops@example.com"]
    assert form["subject"] == ["[DOWN] Production"]
    assert form["text"] == ["text body"]


async def test_mailtrap_transport_posts_expected_payload() -> None:
    requests: list[httpx.Request] = []
    transport = MailtrapTransport(
        api_token="mailtrap-token",
        timeout_seconds=5,
        http_transport=_mock_http(requests),
    )

    await transport.send(_message())

    request = requests[0]
    assert str(request.url) == "https://send.api.mailtrap.io/api/send"
    assert request.headers["authorization"] == "Bearer mailtrap-token"
    body = json.loads(request.content)
    assert body["from"] == {"email": SENDER, "name": "Uptime Monitor"}
    assert body["to"] == [{"email": "ops@example.com"}]
    assert body["text"] == "text body"


async def test_provider_failure_does_not_leak_credentials() -> None:
    transport = BrevoTransport(
        api_key="super-secret-key",
        timeout_seconds=5,
        http_transport=_mock_http([], status_code=401),
    )

    with pytest.raises(EmailTransportError) as exc_info:
        await transport.send(_message())

    assert exc_info.value.provider == "brevo"
    assert "HTTP 401" in str(exc_info.value)
    assert "super-secret-key" not in str(exc_info.value)


async def test_checker_notifies_once_on_open_and_once_on_resolve(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor(name="Production", url="https://example.com")
    notifier = RecordingNotifier()
    runner = CheckRunner(
        session_factory,
        SequenceProber([_failure(), _failure(), _success()]),
        notifier=notifier,
    )

    await runner.run(monitor.id)
    await runner.run(monitor.id)
    await runner.run(monitor.id)

    assert [type(event) for event in notifier.events] == [IncidentOpened, IncidentResolved]
    opened, resolved = notifier.events
    assert opened.monitor_name == "Production"
    assert opened.cause == "Expected 200, got 503"
    assert resolved.monitor_url == "https://example.com"
    assert resolved.duration_seconds >= 0


async def test_checker_stays_silent_on_first_and_repeat_failures(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    notifier = RecordingNotifier()
    runner = CheckRunner(
        session_factory,
        SequenceProber([_failure(), _failure(), _failure()]),
        notifier=notifier,
    )

    for _ in range(3):
        await runner.run(monitor.id)

    assert [type(event) for event in notifier.events] == [IncidentOpened]


async def test_notification_failure_does_not_block_check_recording(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    notifier = RecordingNotifier(error=RuntimeError("smtp unreachable"))
    runner = CheckRunner(
        session_factory,
        SequenceProber([_failure(), _failure()]),
        notifier=notifier,
    )

    await runner.run(monitor.id)
    check = await runner.run(monitor.id)

    assert check.status == "DOWN"
    async with session_factory() as session:
        incidents = list(
            (await session.scalars(select(Incident).where(Incident.monitor_id == monitor.id))).all()
        )
    assert len(incidents) == 1
    assert incidents[0].resolved_at is None


async def test_test_endpoint_sends_for_admin(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")
    transport = RecordingTransport()
    app.state.notifier = _service(transport)

    response = await client.post(
        "/api/v1/notifications/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204
    assert len(transport.messages) == 1
    assert "Test email" in transport.messages[0].subject


async def test_test_endpoint_rejects_viewer(client, create_user, login) -> None:
    viewer = await create_user(email="viewer@example.com", password="viewer-password")
    token = await login(viewer.email, "viewer-password")
    app.state.notifier = _service(RecordingTransport())

    response = await client.post(
        "/api/v1/notifications/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_test_endpoint_reports_unconfigured(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")
    app.state.notifier = None

    response = await client.post(
        "/api/v1/notifications/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503


async def test_test_endpoint_reports_provider_failure(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")
    app.state.notifier = _service(
        RecordingTransport(error=EmailTransportError("mailtrap", "HTTP 401"))
    )

    response = await client.post(
        "/api/v1/notifications/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    assert "mailtrap" not in response.text
