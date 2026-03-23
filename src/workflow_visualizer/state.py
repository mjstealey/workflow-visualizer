"""Pegasus job state mapping and UML-style color definitions."""
from __future__ import annotations

from typing import Dict, Optional


# Map raw Pegasus jobstate -> simplified display category
STATE_MAP: Dict[str, str] = {
    "POST_SCRIPT_SUCCESS": "SUCCESS",
    "JOB_SUCCESS": "SUCCESS",
    "POST_SCRIPT_FAILURE": "FAILED",
    "POST_SCRIPT_FAILED": "FAILED",
    "JOB_FAILURE": "FAILED",
    "JOB_FAILED": "FAILED",
    "EXECUTE": "RUNNING",
    "SUBMIT": "QUEUED",
    "PRE_SCRIPT_STARTED": "PRE",
    "PRE_SCRIPT_SUCCESS": "PRE",
    "POST_SCRIPT_STARTED": "POST",
    "POST_SCRIPT_TERMINATED": "POST",
    "JOB_TERMINATED": "DONE",
    "JOB_HELD": "HELD",
    "JOB_EVICTED": "HELD",
}

# UML state machine color scheme: {fill, stroke}
STATE_COLORS: Dict[str, Dict[str, str]] = {
    "UNSUBMITTED": {"fill": "#e0e0e0", "stroke": "#999999"},
    "QUEUED":      {"fill": "#fff3cd", "stroke": "#ffc107"},
    "PRE":         {"fill": "#cce5ff", "stroke": "#4a90d9"},
    "RUNNING":     {"fill": "#d1ecf1", "stroke": "#17a2b8"},
    "POST":        {"fill": "#cce5ff", "stroke": "#4a90d9"},
    "DONE":        {"fill": "#d4edda", "stroke": "#28a745"},
    "SUCCESS":     {"fill": "#d4edda", "stroke": "#28a745"},
    "FAILED":      {"fill": "#f8d7da", "stroke": "#dc3545"},
    "HELD":        {"fill": "#e8d5f5", "stroke": "#9b59b6"},
    "UNKNOWN":     {"fill": "#e0e0e0", "stroke": "#999999"},
}

# Job type labels for display
JOB_TYPE_LABEL: Dict[str, str] = {
    "compute": "compute",
    "stage-in-tx": "stage-in",
    "stage-out-tx": "stage-out",
    "create-dir": "dir-create",
    "stage-worker": "stage-worker",
    "cleanup": "cleanup",
    "registration": "register",
    "chmod": "chmod",
}


def display_state(raw_state: Optional[str]) -> str:
    """Convert a raw Pegasus job state to a display category."""
    if raw_state is None:
        return "UNSUBMITTED"
    return STATE_MAP.get(raw_state, raw_state)


def state_color(display_st: str) -> Dict[str, str]:
    """Get the fill/stroke colors for a display state."""
    return STATE_COLORS.get(display_st, STATE_COLORS["UNKNOWN"])


def fmt_duration(seconds: Optional[float]) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds is None or seconds < 0:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def fmt_timestamp(ts: Optional[float]) -> str:
    """Format a Unix timestamp as HH:MM:SS."""
    if ts is None:
        return "-"
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def fmt_memory(kb: Optional[int]) -> str:
    """Format memory in KB to a human-readable string."""
    if kb is None or kb < 0:
        return "-"
    if kb < 1024:
        return f"{kb} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    return f"{gb:.2f} GB"
