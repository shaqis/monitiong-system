from dataclasses import dataclass

STATUS_UP = "UP"
STATUS_DOWN = "DOWN"
STATUS_DEGRADED = "DEGRADED"
STATUS_PENDING = "PENDING"

INCIDENT_OPEN_FAILURE_COUNT = 2


@dataclass(frozen=True, slots=True)
class MonitorState:
    consecutive_failures: int
    has_open_incident: bool


@dataclass(frozen=True, slots=True)
class Transition:
    current_status: str
    consecutive_failures: int
    open_incident: bool
    resolve_incident: bool


def apply_probe_result(state: MonitorState, ok: bool) -> Transition:
    """Pure reducer for the two-strike rule in PRD section 6.5.

    The retry delay is owned by ``SCHEDULER_RETRY_SECONDS``. The reducer only
    decides status and incident transitions.
    """
    if ok:
        return Transition(
            current_status=STATUS_UP,
            consecutive_failures=0,
            open_incident=False,
            resolve_incident=state.has_open_incident,
        )

    failures = state.consecutive_failures + 1
    if failures < INCIDENT_OPEN_FAILURE_COUNT:
        return Transition(
            current_status=STATUS_DEGRADED,
            consecutive_failures=failures,
            open_incident=False,
            resolve_incident=False,
        )

    return Transition(
        current_status=STATUS_DOWN,
        consecutive_failures=failures,
        open_incident=not state.has_open_incident,
        resolve_incident=False,
    )
