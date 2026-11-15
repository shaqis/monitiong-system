import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import Incident, Monitor, MonitorCheck
from app.worker.checker import (
    CheckAlreadyRunning,
    CheckRunner,
    MonitorNotFound,
    MonitorPaused,
)
from app.worker.prober import ProbeResult, ProbeTarget


def _failure(
    status_code: int | None = 503,
    error_message: str | None = "Expected 200, got 503",
    response_time_ms: int | None = 25,
) -> ProbeResult:
    return ProbeResult(
        ok=False,
        status_code=status_code,
        response_time_ms=response_time_ms,
        keyword_matched=None,
        error_message=error_message,
        ssl_days_remaining=None,
    )


def _success(ssl_days_remaining: int | None = None) -> ProbeResult:
    return ProbeResult(
        ok=True,
        status_code=200,
        response_time_ms=10,
        keyword_matched=None,
        error_message=None,
        ssl_days_remaining=ssl_days_remaining,
    )


class SequenceProber:
    def __init__(self, results: list[ProbeResult]) -> None:
        self._results = list(results)
        self.targets: list[ProbeTarget] = []

    async def __call__(self, target: ProbeTarget, **_kwargs) -> ProbeResult:
        self.targets.append(target)
        return self._results.pop(0)


async def _stored_monitor(session_factory, monitor_id):
    async with session_factory() as session:
        return await session.get(Monitor, monitor_id)


async def _incidents(session_factory, monitor_id) -> list[Incident]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(Incident)
                    .where(Incident.monitor_id == monitor_id)
                    .order_by(Incident.started_at),
                )
            ).all(),
        )


async def _checks(session_factory, monitor_id) -> list[MonitorCheck]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(MonitorCheck)
                    .where(MonitorCheck.monitor_id == monitor_id)
                    .order_by(MonitorCheck.id),
                )
            ).all(),
        )


async def test_first_failure_records_check_and_degrades(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    prober = SequenceProber([_failure()])
    runner = CheckRunner(session_factory, prober)

    check = await runner.run(monitor.id)

    assert check.status == "DOWN"
    assert check.status_code == 503
    assert check.error_message == "Expected 200, got 503"

    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.current_status == "DEGRADED"
    assert stored.consecutive_failures == 1
    assert stored.last_checked_at is not None
    assert await _incidents(session_factory, monitor.id) == []
    assert len(await _checks(session_factory, monitor.id)) == 1


async def test_second_failure_opens_exactly_one_incident(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    runner = CheckRunner(session_factory, SequenceProber([_failure(), _failure()]))

    await runner.run(monitor.id)
    await runner.run(monitor.id)

    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.current_status == "DOWN"
    assert stored.consecutive_failures == 2

    incidents = await _incidents(session_factory, monitor.id)
    assert len(incidents) == 1
    assert incidents[0].resolved_at is None
    assert incidents[0].cause == "Expected 200, got 503"


async def test_further_failures_do_not_open_another_incident(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    runner = CheckRunner(session_factory, SequenceProber([_failure() for _ in range(4)]))

    for _ in range(4):
        await runner.run(monitor.id)

    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.current_status == "DOWN"
    assert stored.consecutive_failures == 4
    assert len(await _incidents(session_factory, monitor.id)) == 1


async def test_recovery_resets_state_and_resolves_incident(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    runner = CheckRunner(
        session_factory,
        SequenceProber([_failure(), _failure(), _success()]),
    )

    await runner.run(monitor.id)
    await runner.run(monitor.id)
    await runner.run(monitor.id)

    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.current_status == "UP"
    assert stored.consecutive_failures == 0

    incidents = await _incidents(session_factory, monitor.id)
    assert len(incidents) == 1
    assert incidents[0].resolved_at is not None


async def test_recurring_incidents_are_opened_and_resolved_independently(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    runner = CheckRunner(
        session_factory,
        SequenceProber(
            [
                _failure(),
                _failure(),
                _success(),
                _failure(),
                _failure(),
            ]
        ),
    )

    await runner.run(monitor.id)
    await runner.run(monitor.id)
    opened = await _incidents(session_factory, monitor.id)
    assert len(opened) == 1
    first_incident_id = opened[0].id
    assert opened[0].resolved_at is None

    await runner.run(monitor.id)
    resolved = await _incidents(session_factory, monitor.id)
    assert len(resolved) == 1
    assert resolved[0].id == first_incident_id
    assert resolved[0].resolved_at is not None

    await runner.run(monitor.id)
    await runner.run(monitor.id)
    incidents = await _incidents(session_factory, monitor.id)
    assert len(incidents) == 2
    by_id = {incident.id: incident for incident in incidents}
    assert by_id[first_incident_id].resolved_at is not None
    second = next(incident for incident in incidents if incident.id != first_incident_id)
    assert second.resolved_at is None

    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.current_status == "DOWN"
    assert stored.consecutive_failures == 2


async def test_connection_failure_records_null_status_code(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    runner = CheckRunner(
        session_factory,
        SequenceProber(
            [
                _failure(
                    status_code=None,
                    error_message="Connection failed: refused",
                    response_time_ms=None,
                )
            ]
        ),
    )

    check = await runner.run(monitor.id)

    assert check.status == "DOWN"
    assert check.status_code is None
    assert check.response_time_ms is None
    assert check.error_message == "Connection failed: refused"


async def test_concurrent_checks_for_one_monitor_open_one_incident(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()

    class SlowProber:
        def __init__(self) -> None:
            self.started = 0

        async def __call__(self, target: ProbeTarget, **_kwargs) -> ProbeResult:
            self.started += 1
            await asyncio.sleep(0.05)
            return _failure()

    prober = SlowProber()
    runner = CheckRunner(session_factory, prober)

    results = await asyncio.gather(
        runner.run(monitor.id),
        runner.run(monitor.id),
        return_exceptions=True,
    )

    assert prober.started == 1
    assert any(isinstance(result, CheckAlreadyRunning) for result in results)
    assert len(await _checks(session_factory, monitor.id)) == 1
    assert len(await _incidents(session_factory, monitor.id)) == 0
    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.current_status == "DEGRADED"
    assert stored.consecutive_failures == 1


async def test_second_run_is_rejected_while_the_first_waits_for_a_semaphore_slot(
    session_factory,
    create_monitor,
) -> None:
    holder_monitor = await create_monitor(name="holder")
    queued_monitor = await create_monitor(name="queued")
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def blocking_prober(target: ProbeTarget, **_kwargs) -> ProbeResult:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return _success()

    runner = CheckRunner(session_factory, blocking_prober, max_concurrent_checks=1)
    holder = asyncio.create_task(runner.run(holder_monitor.id))
    await started.wait()

    queued = asyncio.create_task(runner.run(queued_monitor.id))
    await asyncio.sleep(0.05)
    third = asyncio.create_task(runner.run(queued_monitor.id))

    try:
        done, _ = await asyncio.wait({third}, timeout=1.0)
        assert done, "a queued run waited for a semaphore slot instead of being rejected"
        with pytest.raises(CheckAlreadyRunning):
            third.result()
    finally:
        release.set()
        await asyncio.gather(holder, queued, third, return_exceptions=True)

    assert calls == 2


async def test_ssl_days_remaining_is_replaced_only_when_present(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor(ssl_days_remaining=42)
    runner = CheckRunner(
        session_factory,
        SequenceProber([_success(ssl_days_remaining=None), _success(ssl_days_remaining=30)]),
    )

    await runner.run(monitor.id)
    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.ssl_days_remaining == 42

    await runner.run(monitor.id)
    stored = await _stored_monitor(session_factory, monitor.id)
    assert stored is not None
    assert stored.ssl_days_remaining == 30


async def test_target_is_built_from_monitor_configuration(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor(
        url="https://status.example.test/health",
        http_method="HEAD",
        timeout_seconds=7,
        expected_status_code=204,
        keyword="ready",
        check_ssl=False,
    )
    prober = SequenceProber([_success()])
    runner = CheckRunner(session_factory, prober)

    await runner.run(monitor.id)

    assert prober.targets == [
        ProbeTarget(
            url="https://status.example.test/health",
            http_method="HEAD",
            timeout_seconds=7,
            expected_status_code=204,
            keyword="ready",
            check_ssl=False,
        ),
    ]


async def test_paused_monitor_raises(session_factory, create_monitor) -> None:
    monitor = await create_monitor(is_active=False)
    runner = CheckRunner(session_factory, SequenceProber([_success()]))

    with pytest.raises(MonitorPaused):
        await runner.run(monitor.id)


async def test_missing_monitor_raises(session_factory) -> None:
    runner = CheckRunner(session_factory, SequenceProber([_success()]))

    with pytest.raises(MonitorNotFound):
        await runner.run(uuid4())


async def test_check_count_is_one_per_run(session_factory, create_monitor) -> None:
    monitor = await create_monitor()
    runner = CheckRunner(session_factory, SequenceProber([_success(), _success()]))

    await runner.run(monitor.id)
    await runner.run(monitor.id)

    async with session_factory() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(MonitorCheck)
            .where(MonitorCheck.monitor_id == monitor.id),
        )
    assert total == 2


async def test_paused_monitor_is_not_checked(session_factory, create_monitor) -> None:
    monitor = await create_monitor(is_active=False)
    runner = CheckRunner(session_factory, SequenceProber([_success()]))

    with pytest.raises(MonitorPaused):
        await runner.run(monitor.id)


async def test_a_second_open_incident_is_rejected(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    now = datetime.now(UTC)

    async with session_factory() as session:
        session.add(Incident(monitor_id=monitor.id, started_at=now, cause="first"))
        await session.commit()
        session.add(Incident(monitor_id=monitor.id, started_at=now, cause="second"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_recovery_resolves_every_open_incident(
    session_factory,
    create_monitor,
    open_incident_index_ddl,
) -> None:
    monitor = await create_monitor(current_status="DOWN", consecutive_failures=2)
    now = datetime.now(UTC)

    async with session_factory() as session:
        # Two open incidents need the partial unique index absent. The finally
        # restores it so later tests still get the arbiter.
        await session.execute(text("DROP INDEX IF EXISTS uq_incidents_open_monitor"))
        session.add_all(
            [
                Incident(
                    monitor_id=monitor.id,
                    started_at=now - timedelta(hours=2),
                    cause="first",
                ),
                Incident(
                    monitor_id=monitor.id,
                    started_at=now - timedelta(hours=1),
                    cause="second",
                ),
            ]
        )
        await session.commit()

    try:
        runner = CheckRunner(session_factory, SequenceProber([_success()]))
        await runner.run(monitor.id)

        incidents = await _incidents(session_factory, monitor.id)
        assert len(incidents) == 2
        assert all(incident.resolved_at is not None for incident in incidents)
    finally:
        async with session_factory() as restore:
            await restore.execute(text("DROP INDEX IF EXISTS uq_incidents_open_monitor"))
            await restore.execute(text(open_incident_index_ddl))
            await restore.commit()


async def test_incident_insert_conflict_keeps_the_check(
    session_factory,
    create_monitor,
) -> None:
    """A writer that opens an incident mid-check must not discard the check.

    The trigger stands in for a concurrent backend replica that inserts the
    open incident after this runner read the incident state, which is the
    window where the partial unique index can reject the insert.
    """
    monitor = await create_monitor(current_status="DEGRADED", consecutive_failures=1)

    async with session_factory() as setup:
        schema = await setup.scalar(text("SELECT quote_ident(current_schema())"))
        assert schema is not None
        await setup.execute(
            text(
                f"""
                CREATE FUNCTION {schema}.open_incident_on_check() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                  INSERT INTO {schema}.incidents (monitor_id, started_at, cause)
                  VALUES (NEW.monitor_id, NEW.checked_at, 'concurrent writer');
                  RETURN NEW;
                END
                $$;
                """
            )
        )
        await setup.execute(
            text(
                f"CREATE TRIGGER open_incident_on_check AFTER INSERT ON {schema}.monitor_checks "
                f"FOR EACH ROW EXECUTE FUNCTION {schema}.open_incident_on_check()"
            )
        )
        await setup.commit()

    runner = CheckRunner(session_factory, SequenceProber([_failure()]))
    try:
        await runner.run(monitor.id)
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                text(f"DROP TRIGGER IF EXISTS open_incident_on_check ON {schema}.monitor_checks")
            )
            await cleanup.execute(
                text(f"DROP FUNCTION IF EXISTS {schema}.open_incident_on_check()")
            )
            await cleanup.commit()

    checks = await _checks(session_factory, monitor.id)
    incidents = await _incidents(session_factory, monitor.id)
    stored = await _stored_monitor(session_factory, monitor.id)

    assert len(checks) == 1
    assert [incident.cause for incident in incidents] == ["concurrent writer"]
    assert incidents[0].resolved_at is None
    assert stored is not None
    assert stored.current_status == "DOWN"
    assert stored.consecutive_failures == 2


async def test_aclose_refuses_new_probe_work(session_factory, create_monitor) -> None:
    class ExecutorProber:
        async def __call__(self, target, **kwargs) -> ProbeResult:
            kwargs["ssl_executor"].submit(lambda: None)
            return _success()

    monitor = await create_monitor()
    runner = CheckRunner(session_factory, ExecutorProber())

    await runner.run(monitor.id)
    runner.aclose()

    with pytest.raises(RuntimeError):
        await runner.run(monitor.id)
