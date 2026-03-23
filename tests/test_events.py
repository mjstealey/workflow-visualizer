"""Tests for JSONL event consumer."""
import json
import tempfile
from pathlib import Path

from workflow_visualizer.events import EventConsumer


def _write_events(events: list[dict]) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for ev in events:
        f.write(json.dumps(ev) + "\n")
    f.close()
    return Path(f.name)


SAMPLE_EVENTS = [
    {"event_type": "workflow_start", "timestamp": 1772557974.0, "dax_label": "earthquake", "wf_uuid": "abc-123"},
    {"event_type": "workflow_state", "timestamp": 1772557974.1, "state": "WORKFLOW_STARTED", "status": None, "wf_start": 1772557974.1},
    {"event_type": "jobs_init", "timestamp": 1772557974.2, "total_jobs": 1, "wf_uuid": "abc-123", "jobs": [
        {"job_id": 1, "exec_job_id": "fetch_earthquake_data_fetch_california", "type_desc": "compute",
         "transformation": "fetch_earthquake_data", "task_argv": "--input california_catalog.csv --output california_quakes.json"},
    ]},
    {"event_type": "job_state", "timestamp": 1772557980, "exec_job_id": "fetch_earthquake_data_fetch_california", "type_desc": "compute", "state": "SUBMIT", "job_id": 1, "exitcode": 0, "stdout_file": "00/00/fetch_california.out.000", "stderr_file": "00/00/fetch_california.err.000", "maxrss": 29056},
    {"event_type": "job_state", "timestamp": 1772557985, "exec_job_id": "fetch_earthquake_data_fetch_california", "type_desc": "compute", "state": "EXECUTE", "job_id": 1, "exitcode": 0, "stdout_file": "00/00/fetch_california.out.000", "stderr_file": "00/00/fetch_california.err.000", "maxrss": 29056},
    {"event_type": "job_state", "timestamp": 1772557990, "exec_job_id": "fetch_earthquake_data_fetch_california", "type_desc": "compute", "state": "JOB_TERMINATED", "job_id": 1, "exitcode": 0, "stdout_file": "00/00/fetch_california.out.000", "stderr_file": "00/00/fetch_california.err.000", "maxrss": 45000},
    {"event_type": "job_state", "timestamp": 1772557991, "exec_job_id": "fetch_earthquake_data_fetch_california", "type_desc": "compute", "state": "JOB_SUCCESS", "job_id": 1, "exitcode": 0, "stdout_file": "00/00/fetch_california.out.000", "stderr_file": "00/00/fetch_california.err.000", "maxrss": 45000},
    {"event_type": "job_state", "timestamp": 1772557991, "exec_job_id": "fetch_earthquake_data_fetch_california", "type_desc": "compute", "state": "POST_SCRIPT_STARTED", "job_id": 1},
    {"event_type": "job_state", "timestamp": 1772557995, "exec_job_id": "fetch_earthquake_data_fetch_california", "type_desc": "compute", "state": "POST_SCRIPT_SUCCESS", "job_id": 1},
]


def test_poll_reads_events():
    path = _write_events(SAMPLE_EVENTS)
    consumer = EventConsumer(path)
    changed = consumer.poll()

    assert changed is True
    assert len(consumer.event_log) > 0
    path.unlink()


def test_poll_incremental():
    path = _write_events(SAMPLE_EVENTS[:4])
    consumer = EventConsumer(path)
    consumer.poll()

    initial_count = len(consumer.event_log)

    # Append more events
    with open(path, "a") as f:
        for ev in SAMPLE_EVENTS[4:]:
            f.write(json.dumps(ev) + "\n")

    changed = consumer.poll()
    assert changed is True
    assert len(consumer.event_log) > initial_count
    path.unlink()


def test_job_state_tracking():
    path = _write_events(SAMPLE_EVENTS)
    consumer = EventConsumer(path)
    consumer.poll()

    states = consumer.job_states
    # Job 1 should be in the states (keyed by exec_job_id since no workflow.yml mapping)
    assert len(states) > 0

    # Find the job
    job = states.get("fetch_earthquake_data_fetch_california")
    assert job is not None
    assert job["state"] == "SUCCESS"
    path.unlink()


def test_workflow_state():
    path = _write_events(SAMPLE_EVENTS[:2])
    consumer = EventConsumer(path)
    consumer.poll()

    assert consumer.workflow_state == "WORKFLOW_STARTED"
    path.unlink()


def test_id_mapping():
    path = _write_events(SAMPLE_EVENTS)
    consumer = EventConsumer(path)

    # Build ID map from workflow nodes
    nodes = [
        {"id": "fetch_california", "nodeLabel": "fetch_california", "name": "fetch_earthquake_data"},
    ]
    consumer.build_id_map(nodes)
    consumer.poll()

    states = consumer.job_states
    # Should be keyed by workflow node id now
    assert "fetch_california" in states
    assert states["fetch_california"]["state"] == "SUCCESS"
    path.unlink()


def test_job_state_new_fields():
    """Test that transformation, task_argv, stdout/stderr, maxrss are captured."""
    path = _write_events(SAMPLE_EVENTS)
    consumer = EventConsumer(path)
    consumer.poll()

    states = consumer.job_states
    job = states.get("fetch_earthquake_data_fetch_california")
    assert job is not None
    assert job["transformation"] == "fetch_earthquake_data"
    assert job["task_argv"] == "--input california_catalog.csv --output california_quakes.json"
    assert job["stdout_file"] == "00/00/fetch_california.out.000"
    assert job["stderr_file"] == "00/00/fetch_california.err.000"
    assert job["maxrss"] == 45000
    assert job["maxrss_fmt"] == "43.9 MB"
    path.unlink()


def test_htcondor_poll_resources():
    """Test that resource metrics are extracted from HTCondor ClassAds."""
    events = SAMPLE_EVENTS + [
        {"event_type": "htcondor_poll", "timestamp": 1772557992, "wf_uuid": "abc-123", "jobs": [
            {
                "DAGNodeName": "fetch_earthquake_data_fetch_california",
                "JobStatus": 2,
                "RemoteUserCpu": 3.5,
                "RemoteSysCpu": 0.5,
                "RemoteWallClockTime": 5.0,
                "ImageSize": 50000,
                "DiskUsage": 100000,
                "RequestCpus": 1,
                "RequestMemory": 256,
                "RequestDisk": 500000,
                "pegasus_site": "condorpool",
            },
        ]},
    ]
    path = _write_events(events)
    consumer = EventConsumer(path)
    consumer.poll()

    states = consumer.job_states
    job = states.get("fetch_earthquake_data_fetch_california")
    assert job is not None
    assert job["site"] == "condorpool"
    assert job["cpu_time"] == "4s"
    assert job["wall_time"] == "5s"
    assert job["request_cpus"] == 1
    assert job["request_memory"] == 256
    assert job["request_disk"] == 500000
    path.unlink()


def test_workflow_end():
    events = SAMPLE_EVENTS + [
        {"event_type": "workflow_end", "timestamp": 1772558000, "wf_state": "WORKFLOW_TERMINATED",
         "wf_status": 0, "wf_end": 1772558000, "total_jobs": 35, "done": 35, "failed": 0, "elapsed": 186},
    ]
    path = _write_events(events)
    consumer = EventConsumer(path)
    consumer.poll()

    assert consumer.is_complete is True
    assert consumer.workflow_state == "WORKFLOW_TERMINATED"

    info = consumer.workflow_info
    assert info["total_jobs"] == 35
    assert info["done"] == 35
    assert info["failed"] == 0
    assert info["elapsed"] == 186
    path.unlink()


def test_nonexistent_file():
    consumer = EventConsumer("/tmp/nonexistent_file_abc123.jsonl")
    changed = consumer.poll()
    assert changed is False


def test_event_log_order():
    path = _write_events(SAMPLE_EVENTS)
    consumer = EventConsumer(path)
    consumer.poll()

    log = consumer.event_log
    # Most recent should be first
    assert len(log) > 1
    assert log[0]["raw_state"] == "POST_SCRIPT_SUCCESS"
    path.unlink()


def test_reset():
    path = _write_events(SAMPLE_EVENTS)
    consumer = EventConsumer(path)
    consumer.poll()
    assert len(consumer.job_states) > 0

    consumer.reset()
    assert len(consumer.job_states) == 0
    assert consumer.workflow_state == "UNKNOWN"
    path.unlink()


def test_real_jsonl():
    """Test against an actual JSONL file if available.

    Set WORKFLOW_EVENTS_JSONL and optionally EARTHQUAKE_WORKFLOW_YML
    environment variables to run this test.
    """
    import os
    path_str = os.environ.get("WORKFLOW_EVENTS_JSONL")
    if not path_str:
        return
    path = Path(path_str)
    if not path.exists():
        return

    wf_path_str = os.environ.get("EARTHQUAKE_WORKFLOW_YML")
    consumer = EventConsumer(path)

    if wf_path_str:
        wf_path = Path(wf_path_str)
        if wf_path.exists():
            from workflow_visualizer.parser import WorkflowGraph
            graph = WorkflowGraph.from_yaml(wf_path)
            consumer.build_id_map(graph.nodes)

    consumer.poll()

    states = consumer.job_states
    assert len(states) > 0

    info = consumer.workflow_info
    assert info.get("total_jobs") is not None or len(states) > 0
