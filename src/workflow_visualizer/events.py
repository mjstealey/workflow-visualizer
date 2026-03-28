"""JSONL event consumer for workflow state tracking."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .state import (
    display_state, fmt_timestamp, fmt_duration, fmt_memory, fmt_memory_mb,
    fmt_bytes, fmt_percent, compute_cpu_efficiency, compute_memory_efficiency,
)


class EventConsumer:
    """Poll a local JSONL file for new workflow events.

    Maintains an incremental read position and builds up job state
    and event log suitable for syncing to widget traitlets.
    """

    def __init__(self, jsonl_path: str | Path) -> None:
        self._path = Path(jsonl_path)
        self._processed_lines: int = 0

        # Accumulated state
        self._job_state: Dict[int, Dict[str, Any]] = {}
        self._event_log: List[Dict[str, Any]] = []
        self._wf_state: str = "UNKNOWN"
        self._wf_status: Optional[int] = None
        self._wf_start: Optional[float] = None
        self._wf_end: Optional[float] = None
        self._wf_uuid: Optional[str] = None
        self._wf_label: Optional[str] = None
        self._wf_user: Optional[str] = None
        self._wf_planner: Optional[str] = None
        self._wf_submit_dir: Optional[str] = None
        self._workflow_complete: bool = False

        # Workflow summary from workflow_end
        self._wf_total_jobs: Optional[int] = None
        self._wf_done: Optional[int] = None
        self._wf_failed: Optional[int] = None
        self._wf_elapsed: Optional[float] = None

        # exec_job_id -> workflow.yml node id mapping
        self._id_map: Dict[str, str] = {}

        # Pool status from pool_status events
        self._pool_status: Dict[str, Any] = {}

        # HTCondor history data keyed by DAGNodeName
        self._history: Dict[str, Dict[str, Any]] = {}

    def build_id_map(self, workflow_nodes: List[Dict[str, Any]]) -> None:
        """Build mapping from exec_job_id to workflow.yml node id.

        Strategy: for each exec_job_id, check if any workflow.yml job's
        id or nodeLabel appears as a substring. Compute jobs in the JSONL
        follow the pattern: {transformation_name}_{nodeLabel}
        """
        self._workflow_node_ids = {n["id"]: n for n in workflow_nodes}

    def _match_exec_to_node(self, exec_job_id: str, type_desc: str) -> Optional[str]:
        """Match an exec_job_id to a workflow.yml node id."""
        if not hasattr(self, "_workflow_node_ids"):
            return None

        # Only compute jobs map to workflow.yml nodes
        if type_desc != "compute":
            return None

        for node_id, node in self._workflow_node_ids.items():
            # exec_job_id pattern: {name}_{nodeLabel}
            # e.g. fetch_earthquake_data_fetch_california -> fetch_california
            node_label = node.get("nodeLabel", node_id)
            if node_label and node_label in exec_job_id:
                return node_id

        return None

    def poll(self) -> bool:
        """Read new lines from the JSONL file.

        Returns True if new events were found.
        """
        if not self._path.exists():
            return False

        new_events: List[Dict[str, Any]] = []
        try:
            with open(self._path) as fh:
                total_lines = 0
                for i, line in enumerate(fh):
                    total_lines = i + 1
                    if i < self._processed_lines:
                        continue
                    line = line.strip()
                    if line:
                        try:
                            new_events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                self._processed_lines = total_lines
        except OSError:
            return False

        if not new_events:
            return False

        for ev in new_events:
            self._apply_event(ev)

        return True

    def _apply_event(self, ev: Dict[str, Any]) -> None:
        """Apply a single event to the accumulated state."""
        etype = ev.get("event_type")

        if etype == "workflow_start":
            self._wf_uuid = ev.get("wf_uuid")
            self._wf_label = ev.get("dax_label")
            self._wf_user = ev.get("user")
            self._wf_planner = ev.get("planner_version")
            self._wf_submit_dir = ev.get("submit_dir")
            return

        if etype == "workflow_state":
            self._wf_state = ev.get("state", self._wf_state)
            self._wf_status = ev.get("status")
            if self._wf_state == "WORKFLOW_STARTED" and self._wf_start is None:
                self._wf_start = ev.get("wf_start") or ev.get("timestamp")
            elif self._wf_state == "WORKFLOW_TERMINATED":
                self._wf_end = ev.get("wf_end") or ev.get("timestamp")

        elif etype == "jobs_init":
            for j in ev.get("jobs", []):
                jid = j.get("job_id")
                if jid is not None and jid not in self._job_state:
                    exec_id = j.get("exec_job_id", "")
                    type_desc = j.get("type_desc", "compute")
                    node_id = self._match_exec_to_node(exec_id, type_desc)
                    self._job_state[jid] = {
                        "exec_job_id": exec_id,
                        "type_desc": type_desc,
                        "node_id": node_id,
                        "raw_state": None,
                        "exitcode": None,
                        "site": None,
                        "submit_time": None,
                        "start_time": None,
                        "end_time": None,
                        "transformation": j.get("transformation"),
                        "task_argv": j.get("task_argv"),
                        "stdout_file": None,
                        "stderr_file": None,
                        "maxrss": None,
                    }

        elif etype == "job_state":
            jid = ev.get("job_id")
            if jid is not None:
                if jid not in self._job_state:
                    exec_id = ev.get("exec_job_id", "")
                    type_desc = ev.get("type_desc", "compute")
                    node_id = self._match_exec_to_node(exec_id, type_desc)
                    self._job_state[jid] = {
                        "exec_job_id": exec_id,
                        "type_desc": type_desc,
                        "node_id": node_id,
                        "raw_state": None,
                        "exitcode": None,
                        "site": None,
                        "submit_time": None,
                        "start_time": None,
                        "end_time": None,
                        "transformation": None,
                        "task_argv": None,
                        "stdout_file": None,
                        "stderr_file": None,
                        "maxrss": None,
                    }

                js = self._job_state[jid]
                state = ev.get("state")
                js["raw_state"] = state
                ts = ev.get("timestamp")

                if ev.get("exitcode") is not None:
                    raw_exit = ev["exitcode"]
                    js["exitcode"] = raw_exit >> 8 if raw_exit > 128 else raw_exit

                # Capture stdout/stderr paths and maxrss
                if ev.get("stdout_file"):
                    js["stdout_file"] = ev["stdout_file"]
                if ev.get("stderr_file"):
                    js["stderr_file"] = ev["stderr_file"]
                if ev.get("maxrss") is not None:
                    js["maxrss"] = ev["maxrss"]

                if state == "SUBMIT" and js["submit_time"] is None:
                    js["submit_time"] = ts
                elif state == "EXECUTE" and js["start_time"] is None:
                    js["start_time"] = ts
                elif state in ("JOB_TERMINATED", "JOB_SUCCESS", "JOB_FAILURE"):
                    js["end_time"] = ts

                # Add to event log
                exec_id = ev.get("exec_job_id", js.get("exec_job_id", ""))
                disp = display_state(state)
                duration = None
                if js["start_time"] and js["end_time"]:
                    duration = js["end_time"] - js["start_time"]

                entry: Dict[str, Any] = {
                    "exec_job_id": exec_id,
                    "node_id": js.get("node_id"),
                    "type_desc": ev.get("type_desc", js.get("type_desc", "")),
                    "state": disp,
                    "raw_state": state,
                    "timestamp": ts,
                    "start_time": fmt_timestamp(js["start_time"]),
                    "end_time": fmt_timestamp(js["end_time"]),
                    "duration": fmt_duration(duration),
                }
                if js.get("maxrss") is not None:
                    entry["maxrss"] = js["maxrss"]
                    entry["maxrss_fmt"] = fmt_memory(js["maxrss"])
                if js.get("stdout_file"):
                    entry["stdout_file"] = js["stdout_file"]
                if js.get("stderr_file"):
                    entry["stderr_file"] = js["stderr_file"]
                if js.get("transformation"):
                    entry["transformation"] = js["transformation"]
                if js.get("task_argv"):
                    entry["task_argv"] = js["task_argv"]
                if js.get("hold_reason"):
                    entry["hold_reason"] = js["hold_reason"]
                    entry["hold_reason_code"] = js.get("hold_reason_code")
                self._event_log.append(entry)

        elif etype == "htcondor_poll":
            # Extract diagnostics and resource metrics from HTCondor ClassAds
            for classad in ev.get("jobs", []):
                dag_node = classad.get("DAGNodeName", "")
                if not dag_node:
                    continue
                # Find matching job by exec_job_id
                for jid, js in self._job_state.items():
                    if js["exec_job_id"] == dag_node:
                        hold_reason = classad.get("HoldReason")
                        if hold_reason:
                            js["hold_reason"] = hold_reason
                            js["hold_reason_code"] = classad.get(
                                "HoldReasonCode"
                            )
                        # Resource metrics
                        if classad.get("RemoteWallClockTime") is not None:
                            js["wall_time"] = classad["RemoteWallClockTime"]
                        cpu_user = classad.get("RemoteUserCpu")
                        cpu_sys = classad.get("RemoteSysCpu")
                        if cpu_user is not None or cpu_sys is not None:
                            js["cpu_time"] = (cpu_user or 0) + (cpu_sys or 0)
                        if classad.get("ImageSize") is not None:
                            js["image_size"] = classad["ImageSize"]
                        if classad.get("DiskUsage") is not None:
                            js["disk_usage"] = classad["DiskUsage"]
                        if classad.get("RequestCpus") is not None:
                            js["request_cpus"] = classad["RequestCpus"]
                        if classad.get("RequestMemory") is not None:
                            js["request_memory"] = classad["RequestMemory"]
                        if classad.get("RequestDisk") is not None:
                            js["request_disk"] = classad["RequestDisk"]
                        # Tier 1: additional resource fields
                        if classad.get("RequestGpus") is not None:
                            js["request_gpus"] = classad["RequestGpus"]
                        if classad.get("NumJobStarts") is not None:
                            js["num_job_starts"] = classad["NumJobStarts"]
                        if classad.get("AccountingGroup"):
                            js["accounting_group"] = classad["AccountingGroup"]
                        # Tier 2: file transfer I/O
                        if classad.get("TransferInputSizeMB") is not None:
                            js["transfer_input_mb"] = classad["TransferInputSizeMB"]
                        if classad.get("BytesSent") is not None:
                            js["bytes_sent"] = classad["BytesSent"]
                        if classad.get("BytesRecvd") is not None:
                            js["bytes_recvd"] = classad["BytesRecvd"]
                        # Queue wait time
                        qdate = classad.get("QDate")
                        job_start = classad.get("JobStartDate")
                        if qdate and job_start and job_start > qdate:
                            js["queue_wait"] = job_start - qdate
                        # Remote host
                        remote_host = classad.get("RemoteHost")
                        if remote_host:
                            js["remote_host"] = remote_host
                        # Execution site from Pegasus ClassAd
                        site = classad.get("pegasus_site")
                        if site:
                            js["site"] = site
                        break

        elif etype == "htcondor_history":
            # Tier 3: post-completion metrics from condor_history
            for classad in ev.get("jobs", []):
                dag_node = classad.get("DAGNodeName", "")
                if not dag_node:
                    continue
                # Store raw history data
                self._history[dag_node] = classad
                # Find matching job and enrich with history metrics
                for jid, js in self._job_state.items():
                    if js["exec_job_id"] == dag_node:
                        if classad.get("RemoteWallClockTime") is not None:
                            js["wall_time"] = classad["RemoteWallClockTime"]
                        if classad.get("RemoteUserCpu") is not None:
                            js["remote_user_cpu"] = classad["RemoteUserCpu"]
                        if classad.get("RemoteSysCpu") is not None:
                            js["remote_sys_cpu"] = classad["RemoteSysCpu"]
                        cpu_user = classad.get("RemoteUserCpu")
                        cpu_sys = classad.get("RemoteSysCpu")
                        if cpu_user is not None or cpu_sys is not None:
                            js["cpu_time"] = (cpu_user or 0) + (cpu_sys or 0)
                        if classad.get("CumulativeRemoteUserCpu") is not None:
                            js["cumulative_cpu"] = classad["CumulativeRemoteUserCpu"]
                        if classad.get("ImageSize") is not None:
                            js["image_size"] = classad["ImageSize"]
                        if classad.get("DiskUsage") is not None:
                            js["disk_usage"] = classad["DiskUsage"]
                        if classad.get("LastRemoteHost"):
                            js["remote_host"] = classad["LastRemoteHost"]
                        if classad.get("BytesSent") is not None:
                            js["bytes_sent"] = classad["BytesSent"]
                        if classad.get("BytesRecvd") is not None:
                            js["bytes_recvd"] = classad["BytesRecvd"]
                        if classad.get("ExitCode") is not None:
                            js["exitcode"] = classad["ExitCode"]
                        if classad.get("NumJobStarts") is not None:
                            js["num_job_starts"] = classad["NumJobStarts"]
                        # Resource requests (may not have been seen via poll)
                        if classad.get("RequestCpus") is not None:
                            js["request_cpus"] = classad["RequestCpus"]
                        if classad.get("RequestMemory") is not None:
                            js["request_memory"] = classad["RequestMemory"]
                        if classad.get("RequestDisk") is not None:
                            js["request_disk"] = classad["RequestDisk"]
                        if classad.get("RequestGpus") is not None:
                            js["request_gpus"] = classad["RequestGpus"]
                        # Compute derived metrics
                        js["cpu_efficiency"] = compute_cpu_efficiency(
                            classad.get("RemoteUserCpu"),
                            classad.get("RemoteSysCpu"),
                            classad.get("RemoteWallClockTime"),
                            js.get("request_cpus"),
                        )
                        js["memory_efficiency"] = compute_memory_efficiency(
                            classad.get("ImageSize"),
                            js.get("request_memory"),
                        )
                        break

        elif etype == "pool_status":
            # Tier 4: pool-wide resource visibility
            pool = ev.get("pool", {})
            if pool:
                self._pool_status = pool

        elif etype == "workflow_end":
            self._wf_state = ev.get("wf_state", self._wf_state)
            self._wf_status = ev.get("wf_status", self._wf_status)
            self._workflow_complete = True
            if self._wf_end is None:
                self._wf_end = ev.get("wf_end") or ev.get("timestamp")
            if ev.get("total_jobs") is not None:
                self._wf_total_jobs = ev["total_jobs"]
            if ev.get("done") is not None:
                self._wf_done = ev["done"]
            if ev.get("failed") is not None:
                self._wf_failed = ev["failed"]
            if ev.get("elapsed") is not None:
                self._wf_elapsed = ev["elapsed"]

    @property
    def job_states(self) -> Dict[str, Dict[str, Any]]:
        """Get current job states keyed by node_id (or exec_job_id for auxiliary jobs).

        Returns a dict suitable for syncing to the widget's job_states traitlet.
        """
        result: Dict[str, Dict[str, Any]] = {}
        now = time.time()
        for jid, js in self._job_state.items():
            key = js.get("node_id") or js["exec_job_id"]
            disp = display_state(js["raw_state"])

            duration = None
            if js["start_time"] and js["end_time"]:
                duration = js["end_time"] - js["start_time"]
            elif js["start_time"] and disp == "RUNNING":
                duration = now - js["start_time"]

            result[key] = {
                "job_id": jid,
                "exec_job_id": js["exec_job_id"],
                "type_desc": js["type_desc"],
                "node_id": js.get("node_id"),
                "state": disp,
                "raw_state": js["raw_state"],
                "exitcode": js["exitcode"],
                "submit_time": js["submit_time"],
                "start_time": js["start_time"],
                "end_time": js["end_time"],
                "duration": fmt_duration(duration),
            }
            # Transformation and arguments
            if js.get("transformation"):
                result[key]["transformation"] = js["transformation"]
            if js.get("task_argv"):
                result[key]["task_argv"] = js["task_argv"]
            # Output/error files and peak memory
            if js.get("stdout_file"):
                result[key]["stdout_file"] = js["stdout_file"]
            if js.get("stderr_file"):
                result[key]["stderr_file"] = js["stderr_file"]
            if js.get("maxrss") is not None:
                result[key]["maxrss"] = js["maxrss"]
                result[key]["maxrss_fmt"] = fmt_memory(js["maxrss"])
            # HTCondor resource metrics
            if js.get("site"):
                result[key]["site"] = js["site"]
            if js.get("cpu_time") is not None:
                result[key]["cpu_time"] = fmt_duration(js["cpu_time"])
            if js.get("wall_time") is not None:
                result[key]["wall_time"] = fmt_duration(js["wall_time"])
            if js.get("request_cpus") is not None:
                result[key]["request_cpus"] = js["request_cpus"]
            if js.get("request_memory") is not None:
                result[key]["request_memory"] = js["request_memory"]
            if js.get("request_disk") is not None:
                result[key]["request_disk"] = js["request_disk"]
            # Tier 1 additions
            if js.get("request_gpus") is not None:
                result[key]["request_gpus"] = js["request_gpus"]
            if js.get("num_job_starts") is not None:
                result[key]["num_job_starts"] = js["num_job_starts"]
            if js.get("accounting_group"):
                result[key]["accounting_group"] = js["accounting_group"]
            # Tier 2: transfer I/O
            if js.get("transfer_input_mb") is not None:
                result[key]["transfer_input_mb"] = js["transfer_input_mb"]
            if js.get("bytes_sent") is not None:
                result[key]["bytes_sent"] = js["bytes_sent"]
                result[key]["bytes_sent_fmt"] = fmt_bytes(js["bytes_sent"])
            if js.get("bytes_recvd") is not None:
                result[key]["bytes_recvd"] = js["bytes_recvd"]
                result[key]["bytes_recvd_fmt"] = fmt_bytes(js["bytes_recvd"])
            if js.get("queue_wait") is not None:
                result[key]["queue_wait"] = fmt_duration(js["queue_wait"])
            if js.get("remote_host"):
                result[key]["remote_host"] = js["remote_host"]
            # Tier 3: post-completion
            if js.get("image_size") is not None:
                result[key]["image_size"] = js["image_size"]
                result[key]["image_size_fmt"] = fmt_memory(js["image_size"])
            if js.get("disk_usage") is not None:
                result[key]["disk_usage"] = js["disk_usage"]
                result[key]["disk_usage_fmt"] = fmt_memory(js["disk_usage"])
            if js.get("remote_user_cpu") is not None:
                result[key]["remote_user_cpu"] = fmt_duration(js["remote_user_cpu"])
            if js.get("remote_sys_cpu") is not None:
                result[key]["remote_sys_cpu"] = fmt_duration(js["remote_sys_cpu"])
            if js.get("cumulative_cpu") is not None:
                result[key]["cumulative_cpu"] = fmt_duration(js["cumulative_cpu"])
            # Derived metrics
            if js.get("cpu_efficiency") is not None:
                result[key]["cpu_efficiency"] = js["cpu_efficiency"]
                result[key]["cpu_efficiency_fmt"] = fmt_percent(js["cpu_efficiency"])
            if js.get("memory_efficiency") is not None:
                result[key]["memory_efficiency"] = js["memory_efficiency"]
                result[key]["memory_efficiency_fmt"] = fmt_percent(js["memory_efficiency"])
            if js.get("hold_reason"):
                result[key]["hold_reason"] = js["hold_reason"]
                result[key]["hold_reason_code"] = js.get("hold_reason_code")
        return result

    @property
    def event_log(self) -> List[Dict[str, Any]]:
        """Get the event log, most recent first."""
        return list(reversed(self._event_log))

    @property
    def workflow_state(self) -> str:
        """Current workflow state string."""
        return self._wf_state

    @property
    def is_complete(self) -> bool:
        return self._workflow_complete

    @property
    def pool_status(self) -> Dict[str, Any]:
        """Current HTCondor pool status from pool_status events."""
        return dict(self._pool_status)

    @property
    def workflow_info(self) -> Dict[str, Any]:
        """Workflow metadata extracted from the workflow_start event."""
        info: Dict[str, Any] = {}
        if self._wf_label:
            info["dax_label"] = self._wf_label
        if self._wf_uuid:
            info["wf_uuid"] = self._wf_uuid
        if self._wf_user:
            info["user"] = self._wf_user
        if self._wf_planner:
            info["planner_version"] = self._wf_planner
        if self._wf_submit_dir:
            info["submit_dir"] = self._wf_submit_dir
        if self._wf_start is not None:
            info["start_time"] = self._wf_start
        if self._wf_end is not None:
            info["end_time"] = self._wf_end
        if self._wf_total_jobs is not None:
            info["total_jobs"] = self._wf_total_jobs
        if self._wf_done is not None:
            info["done"] = self._wf_done
        if self._wf_failed is not None:
            info["failed"] = self._wf_failed
        if self._wf_elapsed is not None:
            info["elapsed"] = self._wf_elapsed
        return info

    def reset(self) -> None:
        """Reset all state for a fresh read."""
        self._processed_lines = 0
        self._job_state.clear()
        self._event_log.clear()
        self._wf_state = "UNKNOWN"
        self._wf_status = None
        self._wf_start = None
        self._wf_end = None
        self._wf_uuid = None
        self._wf_label = None
        self._wf_user = None
        self._wf_planner = None
        self._wf_submit_dir = None
        self._workflow_complete = False
        self._wf_total_jobs = None
        self._wf_done = None
        self._wf_failed = None
        self._wf_elapsed = None
        self._pool_status.clear()
        self._history.clear()


class RemoteEventConsumer:
    """Fetch JSONL from a remote server via SSH, then delegate to EventConsumer."""

    def __init__(
        self,
        remote_spec: str,
        ssh_config: Optional[str] = None,
        ssh_identity: Optional[str] = None,
    ) -> None:
        self._host, self._remote_path = self._parse_spec(remote_spec)
        self._ssh_base = self._build_ssh_base(ssh_config, ssh_identity)

        tmpdir = tempfile.mkdtemp(prefix="wfviz-remote-")
        filename = Path(self._remote_path).name
        self._local_path = Path(tmpdir) / filename
        self._tmpdir = tmpdir
        self._remote_offset: int = 0

        self._consumer = EventConsumer(self._local_path)

    @staticmethod
    def _parse_spec(spec: str) -> tuple[str, str]:
        if "[" in spec:
            bracket_close = spec.find("]")
            colon_pos = spec.find(":", bracket_close + 1)
            if colon_pos == -1:
                raise ValueError(f"Invalid remote spec: {spec!r}")
            return spec[:colon_pos], spec[colon_pos + 1:]
        if ":" not in spec:
            raise ValueError(f"Invalid remote spec: {spec!r}")
        host_part, remote_path = spec.split(":", 1)
        return host_part, remote_path

    @staticmethod
    def _build_ssh_base(
        ssh_config: Optional[str] = None,
        ssh_identity: Optional[str] = None,
    ) -> List[str]:
        parts = ["ssh"]
        if ssh_config:
            parts.extend(["-F", str(Path(ssh_config).expanduser())])
        if ssh_identity:
            parts.extend(["-i", str(Path(ssh_identity).expanduser())])
        return parts

    def sync(self) -> bool:
        """Fetch new bytes from remote and poll the local consumer."""
        ssh_host = self._host
        if "@" in ssh_host:
            user, addr = ssh_host.rsplit("@", 1)
            addr = addr.strip("[]")
            ssh_host = f"{user}@{addr}"

        if self._remote_offset > 0:
            remote_cmd = f"tail -c +{self._remote_offset + 1} {self._remote_path}"
            write_mode = "ab"
        else:
            remote_cmd = f"cat {self._remote_path}"
            write_mode = "wb"

        cmd = self._ssh_base + [ssh_host, remote_cmd]
        try:
            with open(self._local_path, write_mode) as fh:
                result = subprocess.run(
                    cmd, stdout=fh, stderr=subprocess.PIPE, timeout=60,
                )
            if result.returncode == 0:
                new_size = self._local_path.stat().st_size
                if new_size < self._remote_offset:
                    # File shrank — reset
                    self._remote_offset = 0
                    self._consumer.reset()
                    return self.sync()
                self._remote_offset = new_size
            else:
                if self._remote_offset > 0:
                    with open(self._local_path, "ab") as fh:
                        fh.truncate(self._remote_offset)
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

        return self._consumer.poll()

    def build_id_map(self, workflow_nodes: List[Dict[str, Any]]) -> None:
        self._consumer.build_id_map(workflow_nodes)

    @property
    def job_states(self) -> Dict[str, Dict[str, Any]]:
        return self._consumer.job_states

    @property
    def event_log(self) -> List[Dict[str, Any]]:
        return self._consumer.event_log

    @property
    def workflow_state(self) -> str:
        return self._consumer.workflow_state

    @property
    def is_complete(self) -> bool:
        return self._consumer.is_complete

    @property
    def pool_status(self) -> Dict[str, Any]:
        return self._consumer.pool_status

    @property
    def workflow_info(self) -> Dict[str, Any]:
        return self._consumer.workflow_info

    def fetch_file(self, remote_path: str) -> Path:
        """Fetch a single file from the remote host via SSH.

        Returns the local Path to the downloaded file.
        Raises ``RuntimeError`` on failure.
        """
        ssh_host = self._host
        if "@" in ssh_host:
            user, addr = ssh_host.rsplit("@", 1)
            addr = addr.strip("[]")
            ssh_host = f"{user}@{addr}"

        local_path = Path(self._tmpdir) / Path(remote_path).name
        cmd = self._ssh_base + [ssh_host, f"cat {remote_path}"]
        try:
            with open(local_path, "wb") as fh:
                result = subprocess.run(
                    cmd, stdout=fh, stderr=subprocess.PIPE, timeout=60,
                )
            if result.returncode != 0:
                stderr = result.stderr.decode(errors="replace").strip()
                raise RuntimeError(
                    f"SSH fetch failed for {remote_path}: {stderr}"
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"SSH fetch timed out for {remote_path}"
            )
        return local_path

    def cleanup(self) -> None:
        import shutil
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except OSError:
            pass
