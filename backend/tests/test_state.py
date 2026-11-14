import pytest

from app.worker.state import MonitorState, apply_probe_result


@pytest.mark.parametrize(
    ("failures", "open_incident"),
    [
        (0, False),
        (0, True),
        (1, False),
        (2, True),
        (7, True),
    ],
)
def test_success_sets_up_resets_failures_and_resolves(
    failures: int,
    open_incident: bool,
) -> None:
    transition = apply_probe_result(
        MonitorState(failures, open_incident),
        ok=True,
    )

    assert transition.current_status == "UP"
    assert transition.consecutive_failures == 0
    assert transition.open_incident is False
    assert transition.resolve_incident is open_incident


def test_first_failure_is_degraded_without_an_incident() -> None:
    transition = apply_probe_result(
        MonitorState(0, False),
        ok=False,
    )

    assert transition.current_status == "DEGRADED"
    assert transition.consecutive_failures == 1
    assert transition.open_incident is False
    assert transition.resolve_incident is False


def test_second_failure_sets_down_and_opens_one_incident() -> None:
    transition = apply_probe_result(
        MonitorState(1, False),
        ok=False,
    )

    assert transition.current_status == "DOWN"
    assert transition.consecutive_failures == 2
    assert transition.open_incident is True
    assert transition.resolve_incident is False


def test_further_failures_do_not_open_another_incident() -> None:
    transition = apply_probe_result(
        MonitorState(4, True),
        ok=False,
    )

    assert transition.current_status == "DOWN"
    assert transition.consecutive_failures == 5
    assert transition.open_incident is False


def test_second_failure_still_opens_incident_without_open_row() -> None:
    transition = apply_probe_result(
        MonitorState(3, False),
        ok=False,
    )

    assert transition.open_incident is True
