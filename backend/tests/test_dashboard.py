from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.db.models import Incident, MonitorCheck


@pytest.fixture
async def viewer(create_user):
    return await create_user(
        email="dashboard-viewer@example.com",
        password="viewer-password",
        role="viewer",
    )


async def test_summary_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/summary")

    assert response.status_code == 401


async def test_summary_kpis_uptime_and_average_latency(
    client: AsyncClient,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    up_one = await create_monitor(name="Up One", current_status="UP")
    up_two = await create_monitor(name="Up Two", current_status="UP")
    await create_monitor(name="Down One", current_status="DOWN")
    await create_monitor(name="Pending One", current_status="PENDING")
    await create_monitor(name="Paused One", current_status="UP", is_active=False)

    now = datetime.now(UTC)
    session.add_all(
        [
            MonitorCheck(
                monitor_id=up_one.id,
                status="UP",
                status_code=200,
                response_time_ms=100,
                checked_at=now - timedelta(minutes=10),
            ),
            MonitorCheck(
                monitor_id=up_one.id,
                status="UP",
                status_code=200,
                response_time_ms=200,
                checked_at=now - timedelta(minutes=20),
            ),
            MonitorCheck(
                monitor_id=up_two.id,
                status="UP",
                status_code=200,
                response_time_ms=300,
                checked_at=now - timedelta(minutes=30),
            ),
            MonitorCheck(
                monitor_id=up_two.id,
                status="DOWN",
                status_code=503,
                response_time_ms=500,
                checked_at=now - timedelta(minutes=40),
            ),
        ],
    )
    await session.commit()
    await login(viewer.email, "viewer-password")

    response = await client.get("/api/v1/dashboard/summary?range=24h")

    assert response.status_code == 200
    body = response.json()
    assert body["total_monitors"] == 5
    assert body["active_monitors"] == 4
    assert body["paused_monitors"] == 1
    assert body["up_count"] == 2
    assert body["down_count"] == 1
    assert body["pending_count"] == 1
    assert body["overall_uptime"] == 75.0
    assert body["avg_response_time_ms"] == 275.0
    assert body["latency_series"]
    assert len(body["monitors"]) == 5


@pytest.mark.parametrize("time_range", ["1h", "24h", "7d", "30d"])
async def test_summary_supports_every_range(
    client: AsyncClient,
    viewer,
    create_monitor,
    session,
    login,
    time_range: str,
) -> None:
    monitor = await create_monitor(current_status="UP")
    now = datetime.now(UTC)
    session.add_all(
        [
            MonitorCheck(
                monitor_id=monitor.id,
                status="UP",
                status_code=200,
                response_time_ms=100,
                checked_at=now - timedelta(minutes=30),
            ),
            MonitorCheck(
                monitor_id=monitor.id,
                status="DOWN",
                status_code=503,
                response_time_ms=200,
                checked_at=now - timedelta(days=2),
            ),
        ],
    )
    await session.commit()
    await login(viewer.email, "viewer-password")

    response = await client.get(f"/api/v1/dashboard/summary?range={time_range}")

    assert response.status_code == 200
    body = response.json()
    assert body["latency_series"]
    if time_range in {"1h", "24h"}:
        assert body["overall_uptime"] == 100.0
        assert body["avg_response_time_ms"] == 100.0
    else:
        assert body["overall_uptime"] == 50.0
        assert body["avg_response_time_ms"] == 150.0


async def test_summary_includes_recent_status_strips(
    client: AsyncClient,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(name="Strip Monitor", current_status="UP")
    now = datetime.now(UTC)
    for index in range(25):
        status = "UP" if index % 2 == 0 else "DOWN"
        session.add(
            MonitorCheck(
                monitor_id=monitor.id,
                status=status,
                status_code=200 if status == "UP" else 503,
                response_time_ms=10,
                checked_at=now - timedelta(minutes=index),
            ),
        )
    await session.commit()
    await login(viewer.email, "viewer-password")

    body = (await client.get("/api/v1/dashboard/summary?range=24h")).json()

    strip = next(item for item in body["monitors"] if item["id"] == str(monitor.id))
    assert len(strip["recent_statuses"]) == 20
    assert strip["recent_statuses"][-1] == "UP"
    assert strip["recent_statuses"][0] == "DOWN"


async def test_summary_status_strips_are_partitioned_per_monitor(
    client: AsyncClient,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    first = await create_monitor(name="First Strip", current_status="UP")
    second = await create_monitor(name="Second Strip", current_status="DOWN")
    now = datetime.now(UTC)
    for index in range(20):
        checked_at = now - timedelta(minutes=index)
        session.add(
            MonitorCheck(
                monitor_id=first.id,
                status="UP",
                status_code=200,
                response_time_ms=10,
                checked_at=checked_at,
            ),
        )
        session.add(
            MonitorCheck(
                monitor_id=second.id,
                status="DOWN",
                status_code=503,
                response_time_ms=20,
                checked_at=checked_at,
            ),
        )
    await session.commit()
    await login(viewer.email, "viewer-password")

    body = (await client.get("/api/v1/dashboard/summary?range=24h")).json()

    strips = {item["id"]: item for item in body["monitors"]}
    assert strips[str(first.id)]["recent_statuses"] == ["UP"] * 20
    assert strips[str(second.id)]["recent_statuses"] == ["DOWN"] * 20


async def test_summary_lists_active_and_recently_resolved_incidents(
    client: AsyncClient,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(name="Incident Monitor")
    now = datetime.now(UTC)
    session.add_all(
        [
            Incident(
                monitor_id=monitor.id,
                started_at=now - timedelta(hours=1),
                cause="Connection timeout after 10s",
            ),
            Incident(
                monitor_id=monitor.id,
                started_at=now - timedelta(hours=3),
                resolved_at=now - timedelta(hours=2),
                cause="Expected 200, got 502",
            ),
        ],
    )
    await session.commit()
    await login(viewer.email, "viewer-password")

    body = (await client.get("/api/v1/dashboard/summary?range=24h")).json()

    incidents = body["incidents"]
    assert len(incidents) == 2
    active = next(incident for incident in incidents if incident["resolved_at"] is None)
    resolved = next(incident for incident in incidents if incident["resolved_at"] is not None)
    assert active["monitor_name"] == "Incident Monitor"
    assert active["cause"] == "Connection timeout after 10s"
    assert abs(active["duration_seconds"] - 3600) <= 5
    assert abs(resolved["duration_seconds"] - 3600) <= 5


async def test_summary_includes_incident_that_started_before_the_range(
    client: AsyncClient,
    viewer,
    create_monitor,
    session,
    login,
) -> None:
    monitor = await create_monitor(name="Long Incident")
    now = datetime.now(UTC)
    session.add(
        Incident(
            monitor_id=monitor.id,
            started_at=now - timedelta(days=2),
            resolved_at=now - timedelta(hours=1),
            cause="Extended outage",
        ),
    )
    await session.commit()
    await login(viewer.email, "viewer-password")

    body = (await client.get("/api/v1/dashboard/summary?range=24h")).json()

    assert [incident["cause"] for incident in body["incidents"]] == ["Extended outage"]
    assert abs(body["incidents"][0]["duration_seconds"] - (86400 * 2 - 3600)) <= 5


async def test_summary_on_empty_database(client: AsyncClient, viewer, login) -> None:
    await login(viewer.email, "viewer-password")

    response = await client.get("/api/v1/dashboard/summary?range=24h")

    assert response.status_code == 200
    body = response.json()
    assert body["total_monitors"] == 0
    assert body["overall_uptime"] is None
    assert body["avg_response_time_ms"] is None
    assert body["latency_series"] == []
    assert body["monitors"] == []
    assert body["incidents"] == []


async def test_summary_rejects_unknown_range(client: AsyncClient, viewer, login) -> None:
    await login(viewer.email, "viewer-password")

    response = await client.get("/api/v1/dashboard/summary?range=2h")

    assert response.status_code == 422
