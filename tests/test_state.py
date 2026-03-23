"""Tests for state mapping and colors."""
from workflow_visualizer.state import (
    STATE_MAP,
    STATE_COLORS,
    display_state,
    state_color,
    fmt_duration,
    fmt_timestamp,
    fmt_memory,
)


def test_display_state_none():
    assert display_state(None) == "UNSUBMITTED"


def test_display_state_success():
    assert display_state("POST_SCRIPT_SUCCESS") == "SUCCESS"
    assert display_state("JOB_SUCCESS") == "SUCCESS"


def test_display_state_failed():
    assert display_state("JOB_FAILURE") == "FAILED"
    assert display_state("POST_SCRIPT_FAILED") == "FAILED"


def test_display_state_running():
    assert display_state("EXECUTE") == "RUNNING"


def test_display_state_queued():
    assert display_state("SUBMIT") == "QUEUED"


def test_display_state_held():
    assert display_state("JOB_HELD") == "HELD"
    assert display_state("JOB_EVICTED") == "HELD"


def test_display_state_unknown():
    assert display_state("SOMETHING_WEIRD") == "SOMETHING_WEIRD"


def test_state_colors_have_fill_and_stroke():
    for state, colors in STATE_COLORS.items():
        assert "fill" in colors, f"Missing fill for {state}"
        assert "stroke" in colors, f"Missing stroke for {state}"


def test_state_color_known():
    c = state_color("RUNNING")
    assert c["fill"] == "#d1ecf1"
    assert c["stroke"] == "#17a2b8"


def test_state_color_unknown():
    c = state_color("NONEXISTENT")
    assert c == STATE_COLORS["UNKNOWN"]


def test_fmt_duration_none():
    assert fmt_duration(None) == "-"


def test_fmt_duration_seconds():
    assert fmt_duration(45) == "45s"


def test_fmt_duration_minutes():
    assert fmt_duration(125) == "2m05s"


def test_fmt_duration_hours():
    assert fmt_duration(3725) == "1h02m05s"


def test_fmt_timestamp_none():
    assert fmt_timestamp(None) == "-"


def test_fmt_timestamp_valid():
    result = fmt_timestamp(1772557974.0)
    assert ":" in result  # should be HH:MM:SS format
    assert len(result) == 8


def test_fmt_memory_none():
    assert fmt_memory(None) == "-"


def test_fmt_memory_kb():
    assert fmt_memory(512) == "512 KB"


def test_fmt_memory_mb():
    assert fmt_memory(29056) == "28.4 MB"


def test_fmt_memory_gb():
    assert fmt_memory(2097152) == "2.00 GB"
