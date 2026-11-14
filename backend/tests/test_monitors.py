import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.models import Incident, Monitor, MonitorCheck
from app.main import app
from app.worker.checker import CheckRunner
from app.worker.prober import ProbeResult
from app.worker.scheduler import Scheduler


@pytest.fixture
async def admin(create_user):
    return await create_user(
        email="admin@example.com",
        password="admin-password",
        role="admin",
    )


@pytest.fixture
async def viewer(create_user):
    return await create_user(
        email="viewer@example.com",
        password="viewer-password",
        role="viewer",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create(client, token: str, **overrides) -> dict:
    payload = {
        "name": "Example Monitor",
        "url": "https://example.com",
    }
    payload.update(overrides)
    response = await client.post("/api/v1/monitors", json=payload, headers=_auth(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _add_checks(
    session, monitor_id: UUID, rows: list[tuple[str, datetime, int | None]]
) -> None:
    for status, checked_at, response_time_ms in rows:
        session.add(
            MonitorCheck(
                monitor_id=monitor_id,
                status=status,
                status_code=200 if status == "UP" else 503,
                response_time_ms=response_time_ms,
                checked_at=checked_at,
            ),
        )
    await session.commit()


async def test_list_requires_authentication(client) -> None:
    response = await client.get("/api/v1/monitors")

    assert response.status_code == 401


async def test_viewer_reads_but_cannot_mutate(
    client,
    admin,
    viewer,
    create_monitor,
    login,
) -> None:
    monitor = await create_monitor(current_status="UP")
    admin_token = await login(admin.email, "admin-password")
    viewer_token = await login(viewer.email, "viewer-password")

    assert (await client.get("/api/v1/monitors", headers=_auth(viewer_token))).status_code == 200
    assert (
        await client.get(f"/api/v1/monitors/{monitor.id}", headers=_auth(viewer_token))
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/monitors/{monitor.id}/checks", headers=_auth(viewer_token))
    ).status_code == 200
    assert (
        await client.get("/api/v1/dashboard/summary", headers=_auth(viewer_token))
    ).status_code == 200

    payload = {"name": "Blocked", "url": "https://blocked.example.com"}
    assert (
        await client.post("/api/v1/monitors", json=payload, headers=_auth(viewer_token))
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/monitors/{monitor.id}",
            json={"name": "Blocked"},
            headers=_auth(viewer_token),
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/monitors/{monitor.id}",
            headers=_auth(viewer_token),
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/monitors/{monitor.id}/check-now",
            headers=_auth(viewer_token),
        )
    ).status_code == 403
    assert (await client.get("/api/v1/monitors", headers=_auth(admin_token))).status_code == 200


async def test_admin_creates_monitor_with_defaults(client, admin, login) -> None:
    token = await login(admin.email, "admin-password")

    body = await _create(client, token)

    assert body["name"] == "Example Monitor"
    assert body["url"] == "https://example.com"
    assert body["http_method"] == "GET"
    assert body["interval_seconds"] == 60
    assert body["timeout_seconds"] == 10
    assert body["expected_status_code"] == 200
    assert body["keyword"] is None
    assert body["check_ssl"] is True
    assert body["is_active"] is True
    assert body["current_status"] == "PENDING"
    assert body["consecutive_failures"] == 0
    assert body["ssl_days_remaining"] is None
    assert body["last_checked_at"] is None
    assert body["created_by"] == str(admin.id)


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "ftp://example.com"},
        {"url": "not-a-url"},
        {"url": "https://"},
        {"http_method": "POST"},
        {"interval_seconds": 120},
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"expected_status_code": 99},
        {"expected_status_code": 600},
        {"keyword": "k" * 256},
        {"name": ""},
    ],
)
async def test_create_validates_input(client, admin, login, overrides) -> None:
    token = await login(admin.email, "admin-password")

    response = await client.post(
        "/api/v1/monitors",
        json={"name": "Invalid", "url": "https://example.com", **overrides},
        headers=_auth(token),
    )

    assert response.status_code == 422


async def test_head_with_keyword_is_accepted(client, admin, login) -> None:
    token = await login(admin.email, "admin-password")

    body = await _create(
        client,
        token,
        http_method="HEAD",
        keyword="ready",
    )

    assert body["http_method"] == "HEAD"
    assert body["keyword"] == "ready"


async def test_list_search_and_status_filters(
    client,
    viewer,
    create_monitor,
    login,
) -> None:
    await create_monitor(
        name="Alpha Portal",
        url="https://alpha.example.com",
        current_status="UP",
    )
    await create_monitor(
        name="Beta API",
        url="https://beta.example.com",
        current_status="DOWN",
    )
    await create_monitor(
        name="Gamma Degraded",
        url="https://gamma.example.com",
        current_status="DEGRADED",
    )
    await create_monitor(
        name="Delta Pending",
        url="https://delta.example.com",
        current_status="PENDING",
    )
    await create_monitor(
        name="Paused Alpha",
        url="https://paused.example.com",
        current_status="UP",
        is_active=False,
    )
    token = await login(viewer.email, "viewer-password")

    by_name = await client.get(
        "/api/v1/monitors",
        params={"search": "alpha"},
        headers=_auth(token),
    )
    by_url = await client.get(
        "/api/v1/monitors",
        params={"search": "beta.example"},
        headers=_auth(token),
    )
    all_monitors = await client.get("/api/v1/monitors?status=all", headers=_auth(token))
    up = await client.get("/api/v1/monitors?status=up", headers=_auth(token))
    down = await client.get("/api/v1/monitors?status=down", headers=_auth(token))
    paused = await client.get("/api/v1/monitors?status=paused", headers=_auth(token))
    invalid = await client.get("/api/v1/monitors?status=unknown", headers=_auth(token))

    assert {item["name"] for item in by_name.json()} == {"Alpha Portal", "Paused Alpha"}
    assert [item["name"] for item in by_url.json()] == ["Beta API"]
    assert all_monitors.json()
    assert {item["name"] for item in up.json()} == {"Alpha Portal"}
    assert {item["name"] for item in down.json()} == {"Beta API", "Gamma Degraded"}
    assert {item["name"] for item in paused.json()} == {"Paused Alpha"}
    assert invalid.status_code == 422


async def test_list_returns_uptime_latency_and_ssl(
    client,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(ssl_days_remaining=30)
    now = datetime.now(UTC)
    await _add_checks(
        session,
        monitor.id,
        [
            ("UP", now - timedelta(hours=1), 100),
            ("UP", now - timedelta(hours=2), 200),
            ("DOWN", now - timedelta(hours=3), 300),
            ("UP", now - timedelta(hours=25), 50),
        ],
    )
    token = await login(viewer.email, "viewer-password")

    response = await client.get("/api/v1/monitors", headers=_auth(token))

    item = next(item for item in response.json() if item["id"] == str(monitor.id))
    assert item["uptime_24h"] == 66.67
    assert item["last_response_time_ms"] == 100
    assert item["ssl_days_remaining"] == 30


async def test_list_uptime_and_latency_use_each_monitors_own_checks(
    client,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    first = await create_monitor(name="First Monitor")
    second = await create_monitor(name="Second Monitor")
    now = datetime.now(UTC)
    await _add_checks(
        session,
        first.id,
        [
            ("UP", now - timedelta(minutes=1), 100),
            ("DOWN", now - timedelta(minutes=2), 900),
            ("UP", now - timedelta(hours=25), 50),
        ],
    )
    await _add_checks(
        session,
        second.id,
        [
            ("DOWN", now - timedelta(minutes=1), 200),
            ("DOWN", now - timedelta(minutes=2), 800),
            ("DOWN", now - timedelta(hours=25), 60),
        ],
    )
    token = await login(viewer.email, "viewer-password")

    response = await client.get("/api/v1/monitors", headers=_auth(token))

    items = {item["id"]: item for item in response.json()}
    assert items[str(first.id)]["uptime_24h"] == 50.0
    assert items[str(second.id)]["uptime_24h"] == 0.0
    assert items[str(first.id)]["last_response_time_ms"] == 100
    assert items[str(second.id)]["last_response_time_ms"] == 200


async def test_detail_returns_all_three_uptime_windows(
    client,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor()
    now = datetime.now(UTC)
    await _add_checks(
        session,
        monitor.id,
        [
            ("DOWN", now - timedelta(hours=2), 500),
            ("UP", now - timedelta(days=3), 200),
            ("UP", now - timedelta(days=20), 300),
        ],
    )
    token = await login(viewer.email, "viewer-password")

    response = await client.get(f"/api/v1/monitors/{monitor.id}", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["uptime_24h"] == 0.0
    assert body["uptime_7d"] == 50.0
    assert body["uptime_30d"] == 66.67
    assert body["last_response_time_ms"] == 500


async def test_detail_returns_monitor_scoped_recent_incidents(
    client,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    first = await create_monitor(name="First Monitor")
    second = await create_monitor(name="Second Monitor")
    now = datetime.now(UTC)
    active = Incident(
        monitor_id=first.id,
        started_at=now - timedelta(hours=3),
        cause="Expected 200, got 503",
    )
    recently_resolved = Incident(
        monitor_id=first.id,
        started_at=now - timedelta(days=2),
        resolved_at=now - timedelta(days=1, hours=20),
        cause="Connection timed out",
    )
    old_resolved = Incident(
        monitor_id=first.id,
        started_at=now - timedelta(days=40),
        resolved_at=now - timedelta(days=39),
        cause="DNS resolution failed",
    )
    other_monitor = Incident(
        monitor_id=second.id,
        started_at=now - timedelta(hours=1),
        cause="Unexpected status 500",
    )
    session.add_all([active, recently_resolved, old_resolved, other_monitor])
    await session.commit()
    token = await login(viewer.email, "viewer-password")

    response = await client.get(f"/api/v1/monitors/{first.id}", headers=_auth(token))

    assert response.status_code == 200
    incidents = response.json()["recent_incidents"]
    assert [incident["id"] for incident in incidents] == [
        str(active.id),
        str(recently_resolved.id),
    ]
    assert incidents[0]["resolved_at"] is None
    assert incidents[0]["duration_seconds"] >= 3 * 3600
    assert incidents[1]["resolved_at"] is not None
    assert incidents[1]["duration_seconds"] == 4 * 3600
    assert str(old_resolved.id) not in {incident["id"] for incident in incidents}
    assert str(other_monitor.id) not in {incident["id"] for incident in incidents}


async def test_patch_keyword_omitted_keeps_and_null_clears(
    client,
    admin,
    login,
) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token, keyword="hello")

    renamed = await client.patch(
        f"/api/v1/monitors/{created['id']}",
        json={"name": "Renamed"},
        headers=_auth(token),
    )
    cleared = await client.patch(
        f"/api/v1/monitors/{created['id']}",
        json={"keyword": None},
        headers=_auth(token),
    )

    assert renamed.json()["keyword"] == "hello"
    assert cleared.json()["keyword"] is None


async def test_patch_target_change_resets_state_and_resolves_incident(
    client,
    admin,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(
        current_status="DOWN",
        consecutive_failures=3,
        last_checked_at=datetime.now(UTC),
    )
    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        cause="Expected 200, got 503",
    )
    session.add(incident)
    await session.commit()
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/monitors/{monitor.id}",
        json={"url": "https://new.example.com"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_status"] == "PENDING"
    assert body["consecutive_failures"] == 0
    assert body["last_checked_at"] is None

    await session.refresh(incident)
    assert incident.resolved_at is not None


async def test_patch_non_target_change_keeps_state(
    client,
    admin,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(
        current_status="DOWN",
        consecutive_failures=2,
        last_checked_at=datetime.now(UTC),
    )
    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        cause="Expected 200, got 503",
    )
    session.add(incident)
    await session.commit()
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/monitors/{monitor.id}",
        json={"timeout_seconds": 20, "check_ssl": False, "interval_seconds": 300},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_status"] == "DOWN"
    assert body["consecutive_failures"] == 2
    assert body["last_checked_at"] is not None

    await session.refresh(incident)
    assert incident.resolved_at is None


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"url": "ftp://example.com"},
        {"interval_seconds": 120},
        {"timeout_seconds": 31},
        {"expected_status_code": 600},
        {"keyword": "k" * 256},
    ],
)
async def test_patch_validates_merged_result(client, admin, login, payload) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token)

    response = await client.patch(
        f"/api/v1/monitors/{created['id']}",
        json=payload,
        headers=_auth(token),
    )

    assert response.status_code == 422


async def test_unknown_monitors_return_not_found(client, admin, login) -> None:
    token = await login(admin.email, "admin-password")
    missing = uuid4()

    assert (await client.get(f"/api/v1/monitors/{missing}", headers=_auth(token))).status_code == (
        404
    )
    assert (
        await client.patch(
            f"/api/v1/monitors/{missing}",
            json={"name": "Missing"},
            headers=_auth(token),
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/monitors/{missing}", headers=_auth(token))
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/monitors/{missing}/check-now", headers=_auth(token))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/monitors/{missing}/checks", headers=_auth(token))
    ).status_code == 404


async def test_delete_cascades_checks(
    client,
    admin,
    session,
    session_factory,
    login,
) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token)
    monitor_id = UUID(created["id"])
    session.add(
        MonitorCheck(
            monitor_id=monitor_id,
            status="UP",
            status_code=200,
            response_time_ms=10,
            checked_at=datetime.now(UTC),
        ),
    )
    await session.commit()

    response = await client.delete(f"/api/v1/monitors/{monitor_id}", headers=_auth(token))

    assert response.status_code == 204
    assert (
        await client.get(f"/api/v1/monitors/{monitor_id}", headers=_auth(token))
    ).status_code == (404)
    async with session_factory() as check_session:
        remaining = await check_session.scalar(
            select(func.count())
            .select_from(MonitorCheck)
            .where(MonitorCheck.monitor_id == monitor_id),
        )
    assert remaining == 0
    async with session_factory() as check_session:
        stored = await check_session.get(Monitor, monitor_id)
    assert stored is None


async def test_check_now_creates_check(client, admin, session_factory, login) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token)

    response = await client.post(
        f"/api/v1/monitors/{created['id']}/check-now",
        headers=_auth(token),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "UP"
    assert body["status_code"] == 200
    assert body["response_time_ms"] == 10

    detail = await client.get(f"/api/v1/monitors/{created['id']}", headers=_auth(token))
    assert detail.json()["current_status"] == "UP"
    assert detail.json()["last_checked_at"] is not None

    history = await client.get(
        f"/api/v1/monitors/{created['id']}/checks?range=1h",
        headers=_auth(token),
    )
    assert history.json()["total"] == 1


async def test_check_now_on_paused_monitor_returns_conflict(
    client,
    admin,
    login,
) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token)
    await client.patch(
        f"/api/v1/monitors/{created['id']}",
        json={"is_active": False},
        headers=_auth(token),
    )

    response = await client.post(
        f"/api/v1/monitors/{created['id']}/check-now",
        headers=_auth(token),
    )

    assert response.status_code == 409


async def test_check_now_while_in_flight_returns_conflict(
    client,
    admin,
    session_factory,
    login,
) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token)

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_prober(target, **_kwargs) -> ProbeResult:
        started.set()
        await release.wait()
        return ProbeResult(
            ok=True,
            status_code=200,
            response_time_ms=10,
            keyword_matched=None,
            error_message=None,
            ssl_days_remaining=None,
        )

    runner = CheckRunner(session_factory, blocking_prober)
    app.state.check_runner = runner

    task = asyncio.create_task(runner.run(UUID(created["id"])))
    await started.wait()

    response = await client.post(
        f"/api/v1/monitors/{created['id']}/check-now",
        headers=_auth(token),
    )

    release.set()
    await task

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("url", "https://changed.example.com"),
        ("http_method", "HEAD"),
        ("expected_status_code", 204),
        ("keyword", "changed"),
    ],
)
async def test_check_now_discards_result_when_target_changes_mid_probe(
    client,
    admin,
    session,
    session_factory,
    login,
    field,
    value,
) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token)
    monitor_id = UUID(created["id"])

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_prober(target, **_kwargs) -> ProbeResult:
        started.set()
        await release.wait()
        return ProbeResult(
            ok=True,
            status_code=200,
            response_time_ms=10,
            keyword_matched=None,
            error_message=None,
            ssl_days_remaining=None,
        )

    app.state.check_runner = CheckRunner(session_factory, blocking_prober)

    request = asyncio.create_task(
        client.post(
            f"/api/v1/monitors/{monitor_id}/check-now",
            headers=_auth(token),
        ),
    )
    await started.wait()

    monitor = await session.get(Monitor, monitor_id)
    assert monitor is not None
    setattr(monitor, field, value)
    await session.commit()

    release.set()
    response = await request

    assert response.status_code == 409
    assert response.json()["detail"] == "Monitor changed during check"

    async with session_factory() as check_session:
        checks = await check_session.scalar(
            select(func.count())
            .select_from(MonitorCheck)
            .where(MonitorCheck.monitor_id == monitor_id),
        )
        stored = await check_session.get(Monitor, monitor_id)
    assert checks == 0
    assert stored is not None
    assert stored.current_status == "PENDING"
    assert stored.last_checked_at is None


async def test_check_history_ranges_and_pagination(
    client,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor()
    now = datetime.now(UTC)
    await _add_checks(
        session,
        monitor.id,
        [
            ("UP", now - timedelta(minutes=30), 100),
            ("DOWN", now - timedelta(hours=5), 200),
            ("UP", now - timedelta(days=3), 300),
            ("UP", now - timedelta(days=20), 400),
        ],
    )
    token = await login(viewer.email, "viewer-password")

    one_hour = await client.get(
        f"/api/v1/monitors/{monitor.id}/checks",
        params={"range": "1h"},
        headers=_auth(token),
    )
    day = await client.get(
        f"/api/v1/monitors/{monitor.id}/checks",
        params={"range": "24h"},
        headers=_auth(token),
    )
    week = await client.get(
        f"/api/v1/monitors/{monitor.id}/checks",
        params={"range": "7d"},
        headers=_auth(token),
    )
    month = await client.get(
        f"/api/v1/monitors/{monitor.id}/checks",
        params={"range": "30d"},
        headers=_auth(token),
    )
    paged = await client.get(
        f"/api/v1/monitors/{monitor.id}/checks",
        params={"range": "30d", "limit": 2, "offset": 2},
        headers=_auth(token),
    )
    invalid_range = await client.get(
        f"/api/v1/monitors/{monitor.id}/checks",
        params={"range": "2h"},
        headers=_auth(token),
    )
    invalid_limit = await client.get(
        f"/api/v1/monitors/{monitor.id}/checks",
        params={"range": "30d", "limit": 501},
        headers=_auth(token),
    )

    assert one_hour.json()["total"] == 1
    assert day.json()["total"] == 2
    assert week.json()["total"] == 3
    assert month.json()["total"] == 4
    assert month.json()["series"]
    assert one_hour.json()["series"]
    assert len(paged.json()["items"]) == 2
    assert paged.json()["total"] == 4
    assert paged.json()["limit"] == 2
    assert paged.json()["offset"] == 2
    assert invalid_range.status_code == 422
    assert invalid_limit.status_code == 422


async def test_list_handles_whitespace_search(client, viewer, create_monitor, login) -> None:
    await create_monitor(name="Whitespace Monitor")
    token = await login(viewer.email, "viewer-password")

    response = await client.get(
        "/api/v1/monitors",
        params={"search": "   "},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_create_normalizes_an_uppercase_url_scheme(
    client,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.post(
        "/api/v1/monitors",
        json={"name": "Uppercase Scheme", "url": "HTTPS://Example.COM/health"},
    )

    assert response.status_code == 201
    assert response.json()["url"] == "https://Example.COM/health"


async def test_pausing_a_monitor_resolves_its_open_incident(
    client,
    admin,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(current_status="DOWN", consecutive_failures=2)
    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        cause="Connection failed",
    )
    session.add(incident)
    await session.commit()
    await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/monitors/{monitor.id}",
        json={"is_active": False},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    await session.refresh(incident)
    assert incident.resolved_at is not None


async def _failing_prober(target, **_kwargs) -> ProbeResult:
    return ProbeResult(
        ok=False,
        status_code=503,
        response_time_ms=25,
        keyword_matched=None,
        error_message="Expected 200, got 503",
        ssl_days_remaining=None,
    )


async def test_check_now_unknown_monitor_does_not_keep_a_lock(
    client,
    admin,
    login,
) -> None:
    token = await login(admin.email, "admin-password")
    missing = uuid4()

    response = await client.post(
        f"/api/v1/monitors/{missing}/check-now",
        headers=_auth(token),
    )

    assert response.status_code == 404
    assert missing not in app.state.check_runner._locks


async def test_check_now_paused_monitor_does_not_keep_a_lock(
    client,
    admin,
    login,
) -> None:
    token = await login(admin.email, "admin-password")
    created = await _create(client, token)
    await client.patch(
        f"/api/v1/monitors/{created['id']}",
        json={"is_active": False},
        headers=_auth(token),
    )

    response = await client.post(
        f"/api/v1/monitors/{created['id']}/check-now",
        headers=_auth(token),
    )

    assert response.status_code == 409
    assert UUID(created["id"]) not in app.state.check_runner._locks


async def test_check_now_racing_a_scheduled_tick_records_one_check(
    client,
    admin,
    create_monitor,
    session_factory,
    test_settings,
    login,
) -> None:
    monitor = await create_monitor(name="racing")
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_prober(target, **_kwargs) -> ProbeResult:
        started.set()
        await release.wait()
        return ProbeResult(
            ok=True,
            status_code=200,
            response_time_ms=10,
            keyword_matched=None,
            error_message=None,
            ssl_days_remaining=None,
        )

    runner = CheckRunner(session_factory, gated_prober)
    app.state.check_runner = runner
    scheduler = Scheduler(runner, session_factory, test_settings)
    token = await login(admin.email, "admin-password")

    tick = asyncio.create_task(scheduler.run_once())
    await started.wait()

    response = await asyncio.wait_for(
        client.post(f"/api/v1/monitors/{monitor.id}/check-now", headers=_auth(token)),
        timeout=5,
    )

    release.set()
    checked = await tick

    assert response.status_code == 409
    assert checked == 1
    async with session_factory() as check_session:
        total = await check_session.scalar(
            select(func.count())
            .select_from(MonitorCheck)
            .where(MonitorCheck.monitor_id == monitor.id)
        )
    assert total == 1


async def test_patch_name_only_keeps_the_cycle_when_the_stored_url_needs_normalization(
    client,
    admin,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(
        url="https://example.com/path?",
        current_status="DOWN",
        consecutive_failures=2,
        last_checked_at=datetime.now(UTC),
    )
    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        cause="Expected 200, got 503",
    )
    session.add(incident)
    await session.commit()
    token = await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/monitors/{monitor.id}",
        json={"name": "Renamed"},
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["current_status"] == "DOWN"
    assert body["consecutive_failures"] == 2
    assert body["last_checked_at"] is not None
    await session.refresh(incident)
    assert incident.resolved_at is None


async def test_resume_after_pause_needs_two_strikes_again(
    client,
    admin,
    create_monitor,
    session,
    session_factory,
    login,
) -> None:
    monitor = await create_monitor(current_status="DOWN", consecutive_failures=2)
    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        cause="Connection failed",
    )
    session.add(incident)
    await session.commit()
    token = await login(admin.email, "admin-password")

    paused = await client.patch(
        f"/api/v1/monitors/{monitor.id}",
        json={"is_active": False},
        headers=_auth(token),
    )

    assert paused.status_code == 200
    assert paused.json()["consecutive_failures"] == 0

    app.state.check_runner = CheckRunner(session_factory, _failing_prober)
    resumed = await client.patch(
        f"/api/v1/monitors/{monitor.id}",
        json={"is_active": True},
        headers=_auth(token),
    )
    assert resumed.status_code == 200

    check = await client.post(
        f"/api/v1/monitors/{monitor.id}/check-now",
        headers=_auth(token),
    )
    assert check.status_code == 201

    detail = await client.get(f"/api/v1/monitors/{monitor.id}", headers=_auth(token))
    assert detail.json()["current_status"] == "DEGRADED"
    assert detail.json()["consecutive_failures"] == 1
    async with session_factory() as incident_session:
        open_incidents = await incident_session.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.monitor_id == monitor.id, Incident.resolved_at.is_(None))
        )
    assert open_incidents == 0


async def test_create_preserves_url_path_query_fragment_and_userinfo(
    client,
    admin,
    login,
) -> None:
    token = await login(admin.email, "admin-password")

    created = await _create(
        client,
        token,
        url="HTTPS://user:pass@example.com:8443/a/b?x=1&y=2#frag",
    )

    assert created["url"] == "https://user:pass@example.com:8443/a/b?x=1&y=2#frag"
