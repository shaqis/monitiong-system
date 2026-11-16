import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.models import Incident, NotificationSettings
from app.main import app
from app.notifications.config import NotificationConfig, config_from_env
from app.notifications.events import IncidentOpened, IncidentResolved
from app.notifications.secrets import decrypt_secret
from app.notifications.service import (
    DatabaseNotifier,
    NotificationService,
)
from app.notifications.settings_store import save_notification_config
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
from app.schemas.notification import NotificationSettingsUpdate
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
        "email_notifications_enabled": False,
        "email_from_address": "alerts@example.com",
        "notification_recipients": ["ops@example.com"],
    }
    values.update(overrides)
    return Settings(**values)


def _config(**overrides) -> NotificationConfig:
    config = config_from_env(_settings(**overrides))
    assert config is not None
    return config


def _transport(**overrides):
    config = _config(**overrides)
    return build_transport(config.provider, config.timeout_seconds)


def test_build_transport_selects_each_provider() -> None:
    assert isinstance(_transport(smtp_host="smtp.example.com"), SmtpTransport)
    assert isinstance(
        _transport(email_provider="brevo", brevo_api_key="brevo-key"),
        BrevoTransport,
    )
    assert isinstance(
        _transport(
            email_provider="mailgun",
            mailgun_api_key="mailgun-key",
            mailgun_domain="mg.example.com",
        ),
        MailgunTransport,
    )
    assert isinstance(
        _transport(email_provider="mailtrap", mailtrap_api_token="token"),
        MailtrapTransport,
    )


def test_build_transport_reports_missing_provider_config() -> None:
    with pytest.raises(NotificationConfigError):
        _transport(email_provider="brevo")


def test_build_transport_rejects_cleartext_smtp_auth_on_remote_host() -> None:
    with pytest.raises(NotificationConfigError):
        _transport(
            smtp_host="smtp.example.com",
            smtp_username="smtp-user",
            smtp_password="smtp-password",
            smtp_starttls=False,
            smtp_ssl=False,
        )


def test_build_transport_allows_cleartext_smtp_auth_on_loopback() -> None:
    transport = _transport(
        smtp_host="localhost",
        smtp_username="smtp-user",
        smtp_password="smtp-password",
        smtp_starttls=False,
        smtp_ssl=False,
    )

    assert isinstance(transport, SmtpTransport)


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


async def test_event_rendering_strips_url_credentials() -> None:
    event = IncidentOpened(
        monitor_id=uuid4(),
        monitor_name="Production",
        monitor_url="https://user:pass@example.com/health",
        cause="Expected 200, got 503",
        opened_at=datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
    )
    transport = RecordingTransport()

    await _service(transport).notify(event)

    message = transport.messages[0]
    assert "user:pass" not in message.text
    assert "user:pass" not in message.html
    assert "https://example.com/health" in message.text


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

    async with session_factory() as session:
        incident = await session.scalar(select(Incident).where(Incident.monitor_id == monitor.id))
    assert incident is not None
    assert opened.opened_at == incident.started_at
    assert resolved.started_at == incident.started_at
    assert resolved.resolved_at == incident.resolved_at
    assert resolved.duration_seconds == int(
        (resolved.resolved_at - incident.started_at).total_seconds()
    )


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


async def test_notification_send_does_not_hold_the_check_slot(
    session_factory,
    create_monitor,
) -> None:
    incident_monitor = await create_monitor(
        name="Incident",
        url="https://incident.example/",
    )
    other_monitor = await create_monitor(name="Other", url="https://other.example/")
    notify_started = asyncio.Event()
    release_notification = asyncio.Event()
    other_probed = asyncio.Event()

    class Prober:
        async def __call__(self, target, **_kwargs) -> ProbeResult:
            if target.url == incident_monitor.url:
                return _failure()
            other_probed.set()
            return _success()

    class SlowNotifier:
        async def notify(self, event) -> None:
            notify_started.set()
            await release_notification.wait()

    runner = CheckRunner(
        session_factory,
        Prober(),
        max_concurrent_checks=1,
        notifier=SlowNotifier(),
    )

    await runner.run(incident_monitor.id)
    incident_task = asyncio.create_task(runner.run(incident_monitor.id))
    await asyncio.wait_for(notify_started.wait(), timeout=1)

    other_task = asyncio.create_task(runner.run(other_monitor.id))
    await asyncio.wait_for(other_probed.wait(), timeout=1)

    release_notification.set()
    await asyncio.gather(incident_task, other_task)


async def test_notification_send_has_a_hard_timeout(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()

    class HangingNotifier:
        async def notify(self, event) -> None:
            await asyncio.sleep(5)

    runner = CheckRunner(
        session_factory,
        SequenceProber([_failure(), _failure()]),
        notifier=HangingNotifier(),
        notification_timeout_seconds=0.05,
    )

    await runner.run(monitor.id)
    check = await asyncio.wait_for(runner.run(monitor.id), timeout=1)

    assert check.status == "DOWN"


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


async def test_settings_endpoint_returns_safe_configuration(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")
    configured = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/uptime",
        first_admin_email="admin@example.com",
        first_admin_password="test-admin-password",
        first_admin_name="Admin",
        jwt_secret="test-secret-that-is-long-enough-for-hs512-signing-and-at-least-32-bytes",
        email_notifications_enabled=True,
        email_provider="brevo",
        email_from_address="alerts@example.com",
        notification_recipients=["ops@example.com"],
        brevo_api_key="super-secret-key",
    )
    app.dependency_overrides[get_settings] = lambda: configured
    app.state.notifier = _service(RecordingTransport())

    response = await client.get(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["provider"] == "brevo"
    assert body["configured"] is True
    assert body["from_address"] == "alerts@example.com"
    assert body["recipients"] == ["ops@example.com"]
    assert body["provider_credentials_set"] is True
    assert "super-secret-key" not in response.text


async def test_settings_endpoint_rejects_viewer(client, create_user, login) -> None:
    viewer = await create_user(email="viewer@example.com", password="viewer-password")
    token = await login(viewer.email, "viewer-password")

    response = await client.get(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def _wiring_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/uptime",
        first_admin_email="admin@example.com",
        first_admin_password="test-admin-password",
        first_admin_name="Admin",
        jwt_secret="test-secret-that-is-long-enough-for-hs512-signing-and-at-least-32-bytes",
        scheduler_enabled=False,
        email_from_address="alerts@example.com",
        notification_recipients=["ops@example.com"],
        smtp_host="smtp.example.com",
    )


def test_lifespan_always_wires_the_database_notifier(monkeypatch) -> None:
    settings = _wiring_settings()

    @asynccontextmanager
    async def fake_session():
        yield object()

    async def fake_seed(session, settings) -> None:
        pass

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.SessionLocal", fake_session)
    monkeypatch.setattr("app.main.seed_first_admin", fake_seed)
    app.state.notifier = None

    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        assert isinstance(app.state.notifier, DatabaseNotifier)
        assert app.state.check_runner._notifier is app.state.notifier

    app.state.notifier = None


async def test_settings_patch_saves_and_get_reads_the_database(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")
    headers = {"Authorization": f"Bearer {token}"}

    saved = await client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={
            "enabled": True,
            "provider": "smtp",
            "from_address": "alerts@example.com",
            "from_name": "Stored Alerts",
            "recipients": ["ops@example.com", "oncall@example.com"],
            "timeout_seconds": 15,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_starttls": True,
            "smtp_ssl": False,
            "smtp_username": "smtp-user",
            "smtp_password": "super-secret-smtp-password",
        },
    )

    assert saved.status_code == 200, saved.text
    saved_body = saved.json()
    assert saved_body["source"] == "database"
    assert saved_body["configured"] is True
    assert saved_body["enabled"] is True
    assert saved_body["provider"] == "smtp"
    assert saved_body["recipients"] == ["ops@example.com", "oncall@example.com"]
    assert saved_body["smtp_username"] == "smtp-user"
    assert saved_body["smtp_password_set"] is True
    assert saved_body["from_name"] == "Stored Alerts"
    assert saved_body["timeout_seconds"] == 15
    assert "super-secret-smtp-password" not in saved.text

    fetched = await client.get("/api/v1/notifications/settings", headers=headers)

    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["source"] == "database"
    assert body["enabled"] is True
    assert body["recipients"] == ["ops@example.com", "oncall@example.com"]
    assert body["smtp_password_set"] is True
    assert "super-secret-smtp-password" not in fetched.text


async def test_smtp_password_is_encrypted_at_rest(
    client,
    create_user,
    login,
    session_factory,
    test_settings,
) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "smtp",
            "from_address": "alerts@example.com",
            "recipients": ["ops@example.com"],
            "smtp_host": "smtp.example.com",
            "smtp_username": "smtp-user",
            "smtp_password": "super-secret-smtp-password",
        },
    )

    assert response.status_code == 200, response.text
    async with session_factory() as session:
        row = await session.get(NotificationSettings, 1)

    assert row is not None
    assert row.smtp_password_encrypted is not None
    assert row.smtp_password_encrypted != "super-secret-smtp-password"
    assert "super-secret-smtp-password" not in row.smtp_password_encrypted
    assert (
        decrypt_secret(row.smtp_password_encrypted, jwt_secret=test_settings.jwt_secret)
        == "super-secret-smtp-password"
    )


async def test_settings_patch_saves_mailgun_configuration(
    client,
    create_user,
    login,
    session_factory,
    test_settings,
) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "enabled": True,
            "provider": "mailgun",
            "from_address": "alerts@example.com",
            "recipients": ["ops@example.com"],
            "mailgun_api_key": "super-secret-mailgun-key",
            "mailgun_domain": "mg.example.com",
            "mailgun_api_url": "https://api.eu.mailgun.net/v3",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["provider"] == "mailgun"
    assert body["mailgun_api_key_set"] is True
    assert body["mailgun_domain"] == "mg.example.com"
    assert body["mailgun_api_url"] == "https://api.eu.mailgun.net/v3"
    assert "super-secret-mailgun-key" not in response.text

    async with session_factory() as session:
        row = await session.get(NotificationSettings, 1)
    assert row is not None
    assert row.mailgun_api_key_encrypted is not None
    assert row.mailgun_api_key_encrypted != "super-secret-mailgun-key"
    assert "super-secret-mailgun-key" not in row.mailgun_api_key_encrypted
    assert (
        decrypt_secret(row.mailgun_api_key_encrypted, jwt_secret=test_settings.jwt_secret)
        == "super-secret-mailgun-key"
    )
    assert row.mailgun_domain == "mg.example.com"
    assert row.mailgun_api_url == "https://api.eu.mailgun.net/v3"


async def test_settings_patch_saves_mailtrap_configuration(
    client,
    create_user,
    login,
    session_factory,
    test_settings,
) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "enabled": True,
            "provider": "mailtrap",
            "from_address": "alerts@example.com",
            "recipients": ["ops@example.com"],
            "mailtrap_api_token": "super-secret-mailtrap-token",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["provider"] == "mailtrap"
    assert body["mailtrap_api_token_set"] is True
    assert "super-secret-mailtrap-token" not in response.text

    async with session_factory() as session:
        row = await session.get(NotificationSettings, 1)
    assert row is not None
    assert row.mailtrap_api_token_encrypted is not None
    assert row.mailtrap_api_token_encrypted != "super-secret-mailtrap-token"
    assert "super-secret-mailtrap-token" not in row.mailtrap_api_token_encrypted
    assert (
        decrypt_secret(row.mailtrap_api_token_encrypted, jwt_secret=test_settings.jwt_secret)
        == "super-secret-mailtrap-token"
    )


async def test_settings_patch_rejects_mailgun_without_a_domain(
    client,
    create_user,
    login,
) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "mailgun",
            "from_address": "alerts@example.com",
            "recipients": ["ops@example.com"],
            "mailgun_api_key": "super-secret-mailgun-key",
        },
    )

    assert response.status_code == 422
    assert "super-secret-mailgun-key" not in response.text


async def test_settings_patch_rejects_a_plain_http_mailgun_api_url(
    client,
    create_user,
    login,
) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "mailgun",
            "from_address": "alerts@example.com",
            "recipients": ["ops@example.com"],
            "mailgun_api_key": "super-secret-mailgun-key",
            "mailgun_domain": "mg.example.com",
            "mailgun_api_url": "http://api.mailgun.net/v3",
        },
    )

    assert response.status_code == 422
    assert "super-secret-mailgun-key" not in response.text


async def test_patch_without_a_password_keeps_the_stored_secret(
    client,
    create_user,
    login,
    session_factory,
) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={
            "provider": "smtp",
            "from_address": "alerts@example.com",
            "recipients": ["ops@example.com"],
            "smtp_host": "smtp.example.com",
            "smtp_username": "smtp-user",
            "smtp_password": "super-secret-smtp-password",
        },
    )
    assert first.status_code == 200, first.text
    async with session_factory() as session:
        stored_before = (await session.get(NotificationSettings, 1)).smtp_password_encrypted

    second = await client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={"from_name": "Renamed Alerts"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["smtp_password_set"] is True

    async with session_factory() as session:
        kept = await session.get(NotificationSettings, 1)
    assert kept is not None
    assert kept.smtp_password_encrypted == stored_before
    assert kept.from_name == "Renamed Alerts"

    cleared = await client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={"smtp_username": ""},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["smtp_username"] is None
    assert cleared.json()["smtp_password_set"] is False

    async with session_factory() as session:
        after_clear = await session.get(NotificationSettings, 1)
    assert after_clear is not None
    assert after_clear.smtp_password_encrypted is None
    assert after_clear.smtp_username is None


async def test_settings_patch_rejects_viewer(client, create_user, login) -> None:
    viewer = await create_user(email="viewer@example.com", password="viewer-password")
    token = await login(viewer.email, "viewer-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )

    assert response.status_code == 403


async def test_settings_patch_rejects_remote_cleartext_smtp_auth(
    client,
    create_user,
    login,
) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "smtp",
            "from_address": "alerts@example.com",
            "recipients": ["ops@example.com"],
            "smtp_host": "smtp.example.com",
            "smtp_starttls": False,
            "smtp_ssl": False,
            "smtp_username": "smtp-user",
            "smtp_password": "super-secret-smtp-password",
        },
    )

    assert response.status_code == 422
    assert "super-secret-smtp-password" not in response.text


async def test_settings_patch_rejects_empty_recipients(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "smtp",
            "from_address": "alerts@example.com",
            "recipients": [],
            "smtp_host": "smtp.example.com",
        },
    )

    assert response.status_code == 422


async def test_first_save_requires_provider_details(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )

    assert response.status_code == 422


async def test_settings_get_falls_back_to_environment(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")

    response = await client.get(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "environment"
    assert body["configured"] is False


async def test_settings_get_reports_a_configured_environment(client, create_user, login) -> None:
    admin = await create_user(email="admin@example.com", password="admin-password", role="admin")
    token = await login(admin.email, "admin-password")
    configured = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/uptime",
        first_admin_email="admin@example.com",
        first_admin_password="test-admin-password",
        first_admin_name="Admin",
        jwt_secret="test-secret-that-is-long-enough-for-hs512-signing-and-at-least-32-bytes",
        email_from_address="env@example.com",
        notification_recipients=["env-ops@example.com"],
        smtp_host="smtp.example.com",
    )
    app.dependency_overrides[get_settings] = lambda: configured

    response = await client.get(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "environment"
    assert body["configured"] is True
    assert body["from_address"] == "env@example.com"
    assert body["recipients"] == ["env-ops@example.com"]


async def test_database_notifier_uses_the_saved_config(
    session_factory,
    test_settings,
    monkeypatch,
) -> None:
    transport = RecordingTransport()
    monkeypatch.setattr(
        "app.notifications.service.build_transport",
        lambda provider, timeout_seconds: transport,
    )
    async with session_factory() as session:
        await save_notification_config(
            session,
            test_settings,
            NotificationSettingsUpdate(
                enabled=True,
                provider="smtp",
                from_address="stored@example.com",
                from_name="Stored Alerts",
                recipients=["stored-ops@example.com"],
                smtp_host="smtp.example.com",
            ),
        )
    notifier = DatabaseNotifier(session_factory, test_settings)
    event = IncidentOpened(
        monitor_id=uuid4(),
        monitor_name="Stored",
        monitor_url="https://example.com",
        cause="Expected 200, got 503",
        opened_at=datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
    )

    await notifier.notify(event)

    assert len(transport.messages) == 1
    message = transport.messages[0]
    assert message.recipients == ("stored-ops@example.com",)
    assert message.sender_email == "stored@example.com"
    assert message.sender_name == "Stored Alerts"
    assert "[DOWN] Stored" in message.subject


async def test_database_notifier_stays_silent_when_disabled(
    session_factory,
    test_settings,
    monkeypatch,
) -> None:
    transport = RecordingTransport()
    monkeypatch.setattr(
        "app.notifications.service.build_transport",
        lambda provider, timeout_seconds: transport,
    )
    async with session_factory() as session:
        await save_notification_config(
            session,
            test_settings,
            NotificationSettingsUpdate(
                enabled=False,
                provider="smtp",
                from_address="stored@example.com",
                recipients=["stored-ops@example.com"],
                smtp_host="smtp.example.com",
            ),
        )
    notifier = DatabaseNotifier(session_factory, test_settings)
    event = IncidentOpened(
        monitor_id=uuid4(),
        monitor_name="Stored",
        monitor_url="https://example.com",
        cause="Expected 200, got 503",
        opened_at=datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
    )

    await notifier.notify(event)

    assert transport.messages == []
