"""Anywidget-based Pegasus workflow visualizer for Jupyter notebooks."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import anywidget
import traitlets

from .controls import WorkflowControls
from .events import EventConsumer, RemoteEventConsumer
from .parser import WorkflowGraph
from .state import STATE_COLORS

_HERE = Path(__file__).parent


class WorkflowVisualizerWidget(anywidget.AnyWidget):
    """Interactive DAG visualization of a Pegasus workflow.

    Parameters
    ----------
    workflow_path : str or Path, optional
        Path to a Pegasus workflow.yml file for graph structure.
    jsonl_path : str or Path, optional
        Path to a workflow-events.jsonl file for live state updates.
    remote_spec : str, optional
        SSH remote spec (user@host:/path/to/workflow-events.jsonl).
    submit_dir : str or Path, optional
        Pegasus submit directory for lifecycle controls.
    poll_interval : float
        Seconds between JSONL polls (default: 2.0).
    ssh_config : str, optional
        Path to SSH config file for remote mode.
    ssh_identity : str, optional
        Path to SSH identity file for remote mode.
    show_files : bool
        Whether to show data file nodes in the DAG (default: False).
    """

    _esm = _HERE / "static" / "widget.js"
    _css = _HERE / "static" / "widget.css"

    # Synced traitlets
    graph_data = traitlets.Dict({}).tag(sync=True)
    job_states = traitlets.Dict({}).tag(sync=True)
    event_log = traitlets.List([]).tag(sync=True)
    workflow_state = traitlets.Unicode("UNKNOWN").tag(sync=True)
    state_colors = traitlets.Dict(STATE_COLORS).tag(sync=True)
    show_files = traitlets.Bool(False).tag(sync=True)
    workflow_info = traitlets.Dict({}).tag(sync=True)
    status_message = traitlets.Unicode("").tag(sync=True)
    source_mode = traitlets.Unicode("STATIC").tag(sync=True)
    source_detail = traitlets.Unicode("").tag(sync=True)

    def __init__(
        self,
        workflow_path: Optional[str | Path] = None,
        jsonl_path: Optional[str | Path] = None,
        remote_spec: Optional[str] = None,
        submit_dir: Optional[str | Path] = None,
        poll_interval: float = 2.0,
        ssh_config: Optional[str] = None,
        ssh_identity: Optional[str] = None,
        show_files: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self._poll_interval = poll_interval
        self._polling = False
        self._poll_thread: Optional[threading.Thread] = None
        self._consumer: Optional[EventConsumer | RemoteEventConsumer] = None
        self._controls = WorkflowControls(submit_dir)

        self.show_files = show_files

        # Set up event consumer and source mode (before parsing workflow.yml,
        # since SSH mode needs the consumer to fetch the remote file)
        graph: Optional[WorkflowGraph] = None
        if remote_spec:
            self._consumer = RemoteEventConsumer(
                remote_spec,
                ssh_config=ssh_config,
                ssh_identity=ssh_identity,
            )
            self.source_mode = "SSH"
            self.source_detail = self._consumer._host

            # In SSH mode, workflow_path refers to the remote host
            if workflow_path:
                try:
                    local_yml = self._consumer.fetch_file(str(workflow_path))
                    graph = WorkflowGraph.from_yaml(local_yml)
                except Exception as exc:
                    # Show full error — truncation happens in the UI
                    self.status_message = str(exc)

            if graph:
                self._consumer.build_id_map(graph.nodes)
        elif jsonl_path:
            # Local mode: workflow_path is a local file
            if workflow_path:
                graph = WorkflowGraph.from_yaml(workflow_path)
            self._consumer = EventConsumer(jsonl_path)
            if graph:
                self._consumer.build_id_map(graph.nodes)
            self.source_mode = "LIVE"
            self.source_detail = str(jsonl_path)
        elif workflow_path:
            # Static mode: just parse a local workflow.yml, no events
            graph = WorkflowGraph.from_yaml(workflow_path)

        # Populate graph_data and workflow_info from parsed graph
        if graph:
            self.graph_data = graph.to_dict()
            info: Dict[str, Any] = {}
            if graph.metadata.get("name"):
                info["dax_label"] = graph.metadata["name"]
            if graph.metadata.get("pegasus_version"):
                info["planner_version"] = graph.metadata["pegasus_version"]
            self.workflow_info = info

        # Handle custom messages from the frontend
        self.on_msg(self._on_custom_msg)

        # Auto-start polling if we have a consumer
        if self._consumer:
            self.start_polling()

    def start_polling(self) -> None:
        """Start background thread to poll for JSONL updates."""
        if self._polling or self._consumer is None:
            return
        self._polling = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True
        )
        self._poll_thread.start()

    def stop_polling(self) -> None:
        """Stop the background polling thread."""
        self._polling = False

    def _poll_loop(self) -> None:
        """Background loop that polls the event consumer."""
        while self._polling:
            try:
                if isinstance(self._consumer, RemoteEventConsumer):
                    changed = self._consumer.sync()
                elif isinstance(self._consumer, EventConsumer):
                    changed = self._consumer.poll()
                else:
                    break

                if changed:
                    self._sync_state()

                if self._consumer.is_complete:
                    self._sync_state()
                    break
            except Exception as exc:
                self.status_message = f"Poll error: {exc}"

            time.sleep(self._poll_interval)

        self._polling = False

    def _sync_state(self) -> None:
        """Sync consumer state to widget traitlets."""
        if self._consumer is None:
            return
        self.job_states = self._consumer.job_states
        self.event_log = self._consumer.event_log[:100]  # cap at 100 entries
        self.workflow_state = self._consumer.workflow_state

        # Merge consumer workflow_info into existing info (preserves parser-seeded fields)
        consumer_info = self._consumer.workflow_info
        if consumer_info:
            merged = dict(self.workflow_info)
            merged.update(consumer_info)
            self.workflow_info = merged

        # If no graph_data was set from workflow.yml, build from events
        if not self.graph_data and hasattr(self._consumer, '_job_state'):
            consumer = self._consumer
            if isinstance(consumer, RemoteEventConsumer):
                consumer = consumer._consumer
            graph = WorkflowGraph.from_events(consumer._job_state)
            self.graph_data = graph.to_dict()

    def _on_custom_msg(self, widget: Any, content: Dict[str, Any], buffers: Any) -> None:
        """Handle custom messages from the frontend (control buttons)."""
        action = content.get("action")
        if not action:
            return

        result: Dict[str, str] = {}
        if action == "plan":
            dax = content.get("dax_file", "")
            result = self._controls.plan(dax)
        elif action == "run":
            result = self._controls.run(content.get("submit_dir"))
        elif action == "stop":
            result = self._controls.stop(content.get("submit_dir"))
        elif action == "resume":
            result = self._controls.resume(content.get("submit_dir"))
        elif action == "monitor_start":
            result = self._controls.monitor_start(content.get("submit_dir"))
        elif action == "monitor_stop":
            result = self._controls.monitor_stop(content.get("submit_dir"))
        elif action == "set_jsonl_path":
            path = content.get("path", "")
            if path:
                self._consumer = EventConsumer(path)
                if self.graph_data:
                    self._consumer.build_id_map(
                        self.graph_data.get("nodes", [])
                    )
                self.source_mode = "LIVE"
                self.source_detail = path
                self.start_polling()
                result = {"status": "ok", "stdout": f"Monitoring {path}", "stderr": ""}
        elif action == "set_workflow_path":
            path = content.get("path", "")
            if path:
                try:
                    graph = WorkflowGraph.from_yaml(path)
                    self.graph_data = graph.to_dict()
                    if self._consumer:
                        self._consumer.build_id_map(graph.nodes)
                    result = {"status": "ok", "stdout": f"Loaded {path}", "stderr": ""}
                except Exception as exc:
                    result = {"status": "error", "stdout": "", "stderr": str(exc)}

        if result:
            status = result.get("status", "")
            if status == "error":
                self.status_message = result.get("stderr", "Error")
            else:
                self.status_message = result.get("stdout", "OK").strip()[:200]

        self.send({"type": "action_result", "action": action, "result": result})

    def close(self) -> None:
        """Clean up resources on widget close."""
        self.stop_polling()
        if isinstance(self._consumer, RemoteEventConsumer):
            self._consumer.cleanup()
        super().close()
