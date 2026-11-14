import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import MonitorCheck
from app.worker.checker import CheckRunner
from app.worker.prober import ProbeResult, ProbeTarget
from app.worker.scheduler import Scheduler


def _success() -> ProbeResult:
    return ProbeResult(
        ok=True,
        status_code=200,
        response_time_ms=10,
        keyword_matched=None,
        error_message=None,
        ssl_days_remaining=None,
    )


class CountingProber:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, target: ProbeTarget, **_kwargs) -> ProbeResult:
        self.calls += 1
        return _success()


class ExplodingProber:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, target: ProbeTarget, **_kwargs) -> ProbeResult:
        self.calls += 1
        if "explode" in target.url:
            raise RuntimeError("prober exploded")
        return _success()


class TrackingProber:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls = 0

    async def __call__(self, target: ProbeTarget, **_kwargs) -> ProbeResult:
        self.active += 1
        self.calls += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return _success()


async def _check_total(session_factory) -> int:
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(MonitorCheck))
    return total or 0


async def test_run_once_selects_due_monitors_and_first_failure_retries(
    session_factory,
    create_monitor,
    test_settings,
) -> None:
    now = datetime.now(UTC)
    await create_monitor(name="never-checked")
    await create_monitor(name="fresh", last_checked_at=now, interval_seconds=60)
    await create_monitor(
        name="interval-due",
        last_checked_at=now - timedelta(seconds=61),
        interval_seconds=60,
    )
    await create_monitor(
        name="retry-not-yet",
        last_checked_at=now - timedelta(seconds=2),
        consecutive_failures=1,
        interval_seconds=60,
    )
    await create_monitor(
        name="retry-due",
        last_checked_at=now - timedelta(seconds=6),
        consecutive_failures=1,
        interval_seconds=600,
    )
    await create_monitor(name="paused", is_active=False, last_checked_at=None)

    prober = CountingProber()
    runner = CheckRunner(session_factory, prober)
    scheduler = Scheduler(runner, session_factory, test_settings)

    checked = await scheduler.run_once()

    assert checked == 3
    assert prober.calls == 3
    assert await _check_total(session_factory) == 3


async def test_concurrency_is_bounded(
    session_factory,
    create_monitor,
    test_settings,
) -> None:
    for index in range(6):
        await create_monitor(name=f"monitor-{index}")

    prober = TrackingProber()
    runner = CheckRunner(session_factory, prober, max_concurrent_checks=2)
    settings = test_settings.model_copy(update={"max_concurrent_checks": 2})
    scheduler = Scheduler(runner, session_factory, settings)

    checked = await scheduler.run_once()

    assert checked == 6
    assert prober.calls == 6
    assert prober.max_active == 2


async def test_one_failing_check_does_not_stop_the_tick(
    session_factory,
    create_monitor,
    test_settings,
) -> None:
    await create_monitor(name="healthy", url="https://healthy.example.test")
    await create_monitor(name="broken", url="https://explode.example.test")

    prober = ExplodingProber()
    runner = CheckRunner(session_factory, prober)
    scheduler = Scheduler(runner, session_factory, test_settings)

    checked = await scheduler.run_once()

    assert checked == 1
    assert prober.calls == 2
    assert await _check_total(session_factory) == 1


async def test_no_monitors_returns_zero(session_factory, test_settings) -> None:
    runner = CheckRunner(session_factory, CountingProber())
    scheduler = Scheduler(runner, session_factory, test_settings)

    assert await scheduler.run_once() == 0


async def test_loop_wakes_before_the_poll_for_a_retry(
    session_factory,
    create_monitor,
    test_settings,
) -> None:
    await create_monitor(
        consecutive_failures=1,
        last_checked_at=datetime.now(UTC) - timedelta(seconds=4),
    )
    runner = CheckRunner(session_factory, CountingProber())
    scheduler = Scheduler(runner, session_factory, test_settings)

    delay = await scheduler._next_delay()

    assert 0 < delay <= 2.0


async def test_start_and_stop_are_clean(session_factory, test_settings) -> None:
    runner = CheckRunner(session_factory, CountingProber())
    scheduler = Scheduler(runner, session_factory, test_settings)

    scheduler.start()

    assert scheduler.is_running is True

    await asyncio.sleep(0)
    await scheduler.stop()

    assert scheduler.is_running is False
    await scheduler.stop()


async def test_stop_before_start_is_a_noop(session_factory, test_settings) -> None:
    runner = CheckRunner(session_factory, CountingProber())
    scheduler = Scheduler(runner, session_factory, test_settings)

    await scheduler.stop()

    assert scheduler.is_running is False
