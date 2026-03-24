"""Anywidget-based Pegasus workflow visualizer for Jupyter notebooks."""
from __future__ import annotations

import html
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

# ── Pure-Python DAG layout → SVG ────────────────────────────────────────────


def _topo_layers(
    node_ids: List[str],
    adj: Dict[str, List[str]],
    in_deg: Dict[str, int],
) -> List[List[str]]:
    """Assign nodes to layers via a Kahn-style topological sort."""
    layers: List[List[str]] = []
    remaining = dict(in_deg)
    while True:
        layer = [n for n in node_ids if remaining.get(n, 0) == 0 and n in remaining]
        if not layer:
            break
        layers.append(layer)
        for n in layer:
            del remaining[n]
            for child in adj.get(n, []):
                if child in remaining:
                    remaining[child] -= 1
    return layers


def _render_dag_svg(
    graph_data: Dict[str, Any],
    job_states: Dict[str, str],
    state_colors: Dict[str, Dict[str, str]],
    show_files: bool,
) -> str:
    """Lay out a DAG and return a self-contained SVG string (no JS).

    Uses ``viewBox`` so the SVG auto-scales to fit the notebook output area.
    Wide layers are wrapped into sub-rows to avoid horizontal overflow.
    """
    nodes_raw: List[Dict[str, Any]] = graph_data.get("nodes", [])
    edges_raw: List[Dict[str, Any]] = graph_data.get("edges", [])

    if not nodes_raw:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
            'viewBox="0 0 400 60" style="max-width:400px">'
            '<text x="200" y="30" text-anchor="middle" font-family="system-ui,sans-serif" '
            'font-size="14" fill="#64748b">No workflow data loaded</text></svg>'
        )

    # Filter to compute nodes only (unless show_files is True)
    node_map: Dict[str, Dict[str, Any]] = {}
    for n in nodes_raw:
        td = n.get("type_desc", "")
        if td == "" or td == "compute":
            node_map[n["id"]] = n

    # Build adjacency and in-degree for compute-to-compute edges
    adj: Dict[str, List[str]] = {nid: [] for nid in node_map}
    in_deg: Dict[str, int] = {nid: 0 for nid in node_map}
    for e in edges_raw:
        s, t = e["source"], e["target"]
        if s in node_map and t in node_map:
            adj[s].append(t)
            in_deg[t] = in_deg.get(t, 0) + 1

    # Layout parameters
    NODE_W, NODE_H = 150, 40
    H_GAP, V_GAP = 40, 60
    MARGIN = 30
    MAX_COLS = 5  # wrap layers wider than this into sub-rows

    # Assign layers
    layers = _topo_layers(list(node_map.keys()), adj, in_deg)

    # Handle nodes not reached by topo sort (cycles or isolates)
    placed = {n for layer in layers for n in layer}
    orphans = [nid for nid in node_map if nid not in placed]
    if orphans:
        layers.append(orphans)

    # Wrap wide layers into sub-rows (e.g. 10 nodes → 2 rows of 5)
    wrapped_layers: List[List[str]] = []
    layer_group: Dict[int, List[int]] = {}  # original layer idx → list of wrapped idxs
    for orig_idx, layer in enumerate(layers):
        group_idxs = []
        for i in range(0, len(layer), MAX_COLS):
            group_idxs.append(len(wrapped_layers))
            wrapped_layers.append(layer[i : i + MAX_COLS])
        layer_group[orig_idx] = group_idxs

    # Compute positions (center of each node)
    pos: Dict[str, tuple] = {}
    max_layer_w = 0
    for layer in wrapped_layers:
        lw = len(layer) * NODE_W + (len(layer) - 1) * H_GAP
        if lw > max_layer_w:
            max_layer_w = lw

    for li, layer in enumerate(wrapped_layers):
        lw = len(layer) * NODE_W + (len(layer) - 1) * H_GAP
        x_offset = MARGIN + (max_layer_w - lw) / 2
        cy = MARGIN + li * (NODE_H + V_GAP) + NODE_H / 2
        for ni, nid in enumerate(layer):
            cx = x_offset + ni * (NODE_W + H_GAP) + NODE_W / 2
            pos[nid] = (cx, cy)

    svg_w = max(max_layer_w + 2 * MARGIN, 400)
    svg_h = len(wrapped_layers) * (NODE_H + V_GAP) - V_GAP + 2 * MARGIN
    # Reserve space for legend
    legend_h = 28
    total_h = svg_h + legend_h

    default_color = {"fill": "#e0f2fe", "stroke": "#0284c7"}
    unknown_color = {"fill": "#e0e0e0", "stroke": "#999999"}

    # Use viewBox so SVG auto-scales to fit the container width
    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" viewBox="0 0 {svg_w} {total_h}" '
        f'style="max-width:{svg_w}px;font-family:system-ui,-apple-system,sans-serif;'
        f'background:#fff;border:1px solid #e2e8f0;border-radius:8px">'
    )

    # Arrowhead marker
    parts.append(
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="8" markerHeight="8" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 Z" fill="#94a3b8"/></marker></defs>'
    )

    # Edges
    for e in edges_raw:
        s, t = e["source"], e["target"]
        if s in pos and t in pos:
            sx, sy = pos[s]
            tx, ty = pos[t]
            # Start at bottom of source, end at top of target
            y1 = sy + NODE_H / 2
            y2 = ty - NODE_H / 2
            if abs(y2 - y1) < 1:
                parts.append(
                    f'<line x1="{sx}" y1="{y1}" x2="{tx}" y2="{y2}" '
                    f'stroke="#94a3b8" stroke-width="1.5" marker-end="url(#ah)"/>'
                )
            else:
                my = (y1 + y2) / 2
                parts.append(
                    f'<path d="M{sx},{y1} C{sx},{my} {tx},{my} {tx},{y2}" '
                    f'fill="none" stroke="#94a3b8" stroke-width="1.5" '
                    f'marker-end="url(#ah)"/>'
                )

    # Nodes
    for nid, (cx, cy) in pos.items():
        state = job_states.get(nid, "UNSUBMITTED")
        color = state_colors.get(state, default_color)
        x = cx - NODE_W / 2
        y = cy - NODE_H / 2
        label = html.escape(node_map[nid].get("nodeLabel", nid))
        if len(label) > 20:
            label = label[:18] + "\u2026"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" '
            f'rx="6" ry="6" fill="{color["fill"]}" stroke="{color["stroke"]}" '
            f'stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{cx}" y="{cy}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="12" fill="#1e293b">'
            f'{label}</text>'
        )

    # Legend
    legend_states = ["UNSUBMITTED", "QUEUED", "RUNNING", "SUCCESS", "FAILED", "HELD"]
    lx = MARGIN
    ly = svg_h + 4
    for st in legend_states:
        c = state_colors.get(st, unknown_color)
        parts.append(
            f'<rect x="{lx}" y="{ly}" width="10" height="10" rx="2" '
            f'fill="{c["fill"]}" stroke="{c["stroke"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{lx + 14}" y="{ly + 9}" font-size="10" fill="#475569">'
            f'{st}</text>'
        )
        lx += 14 + len(st) * 6.5 + 12

    parts.append("</svg>")
    return "\n".join(parts)


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

    def _repr_mimebundle_(self, **kwargs: Any) -> Dict[str, Any]:
        """Choose the best display representation for the current environment.

        Tries the anywidget widget-view MIME type first.  If the comm channel
        is unavailable (e.g. classic Notebook on ACCESS Open OnDemand), falls
        back to a pure SVG rendering computed entirely server-side in Python —
        no JavaScript required, so it survives classic Notebook's HTML sanitizer.
        """
        try:
            bundle = super()._repr_mimebundle_(**kwargs)
            if bundle and "application/vnd.jupyter.widget-view+json" in bundle:
                return bundle
        except Exception:
            pass
        return {"text/html": self._repr_html_()}

    def _repr_html_(self) -> str:
        """Pure SVG fallback for environments where anywidget ESM fails.

        Computes a layered DAG layout entirely in Python and emits inline SVG.
        No JavaScript, no external imports — works in untrusted classic Notebook.
        """
        return _render_dag_svg(
            self.graph_data,
            dict(self.job_states),
            dict(self.state_colors),
            self.show_files,
        )

    def close(self) -> None:
        """Clean up resources on widget close."""
        self.stop_polling()
        if isinstance(self._consumer, RemoteEventConsumer):
            self._consumer.cleanup()
        super().close()
