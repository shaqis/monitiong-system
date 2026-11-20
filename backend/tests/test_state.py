import pytest

from app.worker.state import (
    STATUS_PENDING,
    LifecycleTransition,
    MonitorState,
    apply_probe_result,
    plan_lifecycle_transition,
)


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


@pytest.mark.parametrize(
    ("was_active", "is_active"),
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_plan_lifecycle_transition_target_change_resets_and_clears_last_checked(
    was_active: bool,
    is_active: bool,
) -> None:
    transition = plan_lifecycle_transition(
        was_active=was_active,
        is_active=is_active,
        target_changed=True,
    )

    assert transition == LifecycleTransition(
        current_status=STATUS_PENDING,
        consecutive_failures=0,
        clear_last_checked_at=True,
        resolve_open_incidents=True,
    )


def test_plan_lifecycle_transition_pause_resets_status_and_preserves_last_checked() -> None:
    transition = plan_lifecycle_transition(
        was_active=True,
        is_active=False,
        target_changed=False,
    )

    assert transition == LifecycleTransition(
        current_status=STATUS_PENDING,
        consecutive_failures=0,
        clear_last_checked_at=False,
        resolve_open_incidents=True,
    )


def test_plan_lifecycle_transition_paused_metadata_edit_converges_cleanly() -> None:
    transition = plan_lifecycle_transition(
        was_active=False,
        is_active=False,
        target_changed=False,
    )

    assert transition == LifecycleTransition(
        current_status=STATUS_PENDING,
        consecutive_failures=0,
        clear_last_checked_at=False,
        resolve_open_incidents=True,
    )


def test_plan_lifecycle_transition_resume_resets_status_and_clears_last_checked() -> None:
    transition = plan_lifecycle_transition(
        was_active=False,
        is_active=True,
        target_changed=False,
    )

    assert transition == LifecycleTransition(
        current_status=STATUS_PENDING,
        consecutive_failures=0,
        clear_last_checked_at=True,
        resolve_open_incidents=True,
    )


def test_plan_lifecycle_transition_active_metadata_edit_returns_none() -> None:
    transition = plan_lifecycle_transition(
        was_active=True,
        is_active=True,
        target_changed=False,
    )

    assert transition is None
