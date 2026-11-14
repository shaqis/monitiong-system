import pytest

from app.worker.state import MonitorState, apply_probe_result


@pytest.mark.parametrize(
    ("status", "failures", "open_incident"),
    [
        ("UP", 0, False),
        ("UP", 0, True),
        ("PENDING", 0, False),
        ("DEGRADED", 1, False),
        ("DOWN", 2, True),
        ("DOWN", 7, True),
    ],
)
def test_success_sets_up_resets_failures_and_resolves(
    status: str,
    failures: int,
    open_incident: bool,
) -> None:
    transition = apply_probe_result(
        MonitorState(status, failures, open_incident),
        ok=True,
    )

    assert transition.current_status == "UP"
    assert transition.consecutive_failures == 0
    assert transition.retry_in_seconds is None
    assert transition.open_incident is False
    assert transition.resolve_incident is open_incident


@pytest.mark.parametrize("status", ["UP", "PENDING"])
def test_first_failure_is_degraded_with_five_second_retry(status: str) -> None:
    transition = apply_probe_result(
        MonitorState(status, 0, False),
        ok=False,
    )

    assert transition.current_status == "DEGRADED"
    assert transition.consecutive_failures == 1
    assert transition.retry_in_seconds == 5
    assert transition.open_incident is False
    assert transition.resolve_incident is False


def test_second_failure_sets_down_and_opens_one_incident() -> None:
    transition = apply_probe_result(
        MonitorState("DEGRADED", 1, False),
        ok=False,
    )

    assert transition.current_status == "DOWN"
    assert transition.consecutive_failures == 2
    assert transition.retry_in_seconds is None
    assert transition.open_incident is True
    assert transition.resolve_incident is False


def test_further_failures_do_not_open_another_incident() -> None:
    transition = apply_probe_result(
        MonitorState("DOWN", 4, True),
        ok=False,
    )

    assert transition.current_status == "DOWN"
    assert transition.consecutive_failures == 5
    assert transition.open_incident is False


def test_second_failure_still_opens_incident_without_open_row() -> None:
    transition = apply_probe_result(
        MonitorState("DOWN", 3, False),
        ok=False,
    )

    assert transition.open_incident is True
