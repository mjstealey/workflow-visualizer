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

    # Build compute node map
    node_map: Dict[str, Dict[str, Any]] = {}
    for n in nodes_raw:
        td = n.get("type_desc", "")
        if td == "" or td == "compute":
            node_map[n["id"]] = n

    # Track which node IDs are file nodes (for rendering style)
    file_node_ids: set = set()

    # Layout parameters
    NODE_W, NODE_H = 150, 40
    FILE_W, FILE_H = 130, 26
    H_GAP, V_GAP = 40, 60
    MARGIN = 30
    MAX_COLS = 5  # wrap layers wider than this into sub-rows

    if show_files:
        # Insert file nodes between compute nodes via input/output LFNs.
        # producer: lfn → compute node id that outputs it
        # consumer: lfn → list of compute node ids that input it
        producers: Dict[str, str] = {}
        consumers: Dict[str, List[str]] = {}
        for nid, n in node_map.items():
            for lfn in n.get("outputs", []):
                producers[lfn] = nid
            for lfn in n.get("inputs", []):
                consumers.setdefault(lfn, []).append(nid)

        # Create file nodes and edges through them
        adj: Dict[str, List[str]] = {nid: [] for nid in node_map}
        in_deg: Dict[str, int] = {nid: 0 for nid in node_map}
        for lfn in set(list(producers.keys()) + list(consumers.keys())):
            fid = "file:" + lfn
            lbl = lfn if len(lfn) <= 20 else "\u2026" + lfn[-18:]
            node_map[fid] = {"id": fid, "nodeLabel": lbl, "_isFile": True}
            file_node_ids.add(fid)
            adj[fid] = []
            in_deg[fid] = 0
            # producer → file
            if lfn in producers:
                adj[producers[lfn]].append(fid)
                in_deg[fid] += 1
            # file → consumers
            for cid in consumers.get(lfn, []):
                adj[fid].append(cid)
                in_deg[cid] = in_deg.get(cid, 0) + 1
    else:
        # Direct compute-to-compute edges
        adj = {nid: [] for nid in node_map}
        in_deg = {nid: 0 for nid in node_map}
        for e in edges_raw:
            s, t = e["source"], e["target"]
            if s in node_map and t in node_map:
                adj[s].append(t)
                in_deg[t] = in_deg.get(t, 0) + 1

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

    # Build edges list for rendering (from adjacency, since show_files rewires edges)
    render_edges: List[tuple] = []
    for s, targets in adj.items():
        for t in targets:
            if s in pos and t in pos:
                render_edges.append((s, t))

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
    for s, t in render_edges:
        sx, sy = pos[s]
        tx, ty = pos[t]
        sh = FILE_H if s in file_node_ids else NODE_H
        th = FILE_H if t in file_node_ids else NODE_H
        y1 = sy + sh / 2
        y2 = ty - th / 2
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
    file_color = {"fill": "#f8fafc", "stroke": "#94a3b8"}
    for nid, (cx, cy) in pos.items():
        is_file = nid in file_node_ids
        if is_file:
            nw, nh, rx = FILE_W, FILE_H, 2
            color = file_color
            font_size = 10
        else:
            nw, nh, rx = NODE_W, NODE_H, 6
            js = job_states.get(nid, "UNSUBMITTED")
            # job_states values may be dicts (from EventConsumer) or strings
            state = js["state"] if isinstance(js, dict) else js
            color = state_colors.get(state, default_color)
            font_size = 12
        x = cx - nw / 2
        y = cy - nh / 2
        label = html.escape(node_map[nid].get("nodeLabel", nid))
        if len(label) > 20:
            label = label[:18] + "\u2026"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{nw}" height="{nh}" '
            f'rx="{rx}" ry="{rx}" fill="{color["fill"]}" stroke="{color["stroke"]}" '
            f'stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{cx}" y="{cy}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="{font_size}" fill="#1e293b">'
            f'{label}</text>'
        )

    # Legend
    legend_states = ["UNSUBMITTED", "QUEUED", "PRE", "RUNNING", "POST", "SUCCESS", "FAILED", "HELD"]
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


def _render_event_table(event_log: List[Dict[str, Any]], max_rows: int = 20) -> str:
    """Render the event log as an HTML table (most recent first)."""
    if not event_log:
        return ""

    rows = event_log[:max_rows]
    # State badge colors (inline, no CSS classes needed)
    badge_colors = {
        "SUCCESS": ("#d4edda", "#28a745"),
        "FAILED": ("#f8d7da", "#dc3545"),
        "RUNNING": ("#d1ecf1", "#17a2b8"),
        "QUEUED": ("#fff3cd", "#ffc107"),
        "HELD": ("#e8d5f5", "#9b59b6"),
        "PRE": ("#cce5ff", "#4a90d9"),
        "POST": ("#cce5ff", "#4a90d9"),
        "DONE": ("#d4edda", "#28a745"),
    }

    parts = [
        '<table style="width:100%;border-collapse:collapse;font-family:system-ui,sans-serif;'
        'font-size:12px;margin-top:8px">',
        "<thead><tr>",
        '<th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e2e8f0;color:#475569">Job</th>',
        '<th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e2e8f0;color:#475569">Type</th>',
        '<th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e2e8f0;color:#475569">State</th>',
        '<th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e2e8f0;color:#475569">Start</th>',
        '<th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e2e8f0;color:#475569">End</th>',
        '<th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e2e8f0;color:#475569">Duration</th>',
        "</tr></thead><tbody>",
    ]

    for ev in rows:
        state = ev.get("state", "")
        bg, fg = badge_colors.get(state, ("#e0e0e0", "#666"))
        badge = (
            f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;'
            f'background:{bg};color:{fg};font-size:11px;font-weight:600">'
            f'{html.escape(state)}</span>'
        )
        job_id = html.escape(ev.get("exec_job_id", ""))
        type_desc = html.escape(ev.get("type_desc", ""))
        start = html.escape(ev.get("start_time", "-"))
        end = html.escape(ev.get("end_time", "-"))
        dur = html.escape(ev.get("duration", "-"))

        parts.append(
            f'<tr style="border-bottom:1px solid #f1f5f9">'
            f'<td style="padding:3px 8px;white-space:nowrap">{job_id}</td>'
            f'<td style="padding:3px 8px;color:#64748b">{type_desc}</td>'
            f'<td style="padding:3px 8px">{badge}</td>'
            f'<td style="padding:3px 8px;font-variant-numeric:tabular-nums">{start}</td>'
            f'<td style="padding:3px 8px;font-variant-numeric:tabular-nums">{end}</td>'
            f'<td style="padding:3px 8px;font-variant-numeric:tabular-nums">{dur}</td>'
            f"</tr>"
        )

    parts.append("</tbody></table>")
    if len(event_log) > max_rows:
        parts.append(
            f'<div style="font-size:11px;color:#94a3b8;padding:4px 8px">'
            f"Showing {max_rows} of {len(event_log)} events</div>"
        )
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

    def watch(self, interval: Optional[float] = None, show_files: Optional[bool] = None) -> None:
        """Auto-refresh the SVG display until the workflow completes or is interrupted.

        Uses IPython's ``clear_output`` to redraw in-place, giving a pseudo-live
        view of workflow progress in environments where the anywidget comm channel
        is unavailable (e.g. ACCESS classic Notebook).

        Parameters
        ----------
        interval : float, optional
            Seconds between display refreshes.  Defaults to ``poll_interval``
            (the same interval used for event polling).
        show_files : bool, optional
            Show data file nodes.  Defaults to the widget's current ``show_files``.

        Usage::

            w.watch()           # refresh at poll_interval rate
            w.watch(interval=5) # refresh every 5 seconds
        """
        from IPython.display import display, HTML, clear_output

        if show_files is not None:
            self.show_files = show_files
        refresh = interval if interval is not None else self._poll_interval

        # Ensure polling is running
        self.start_polling()

        try:
            while True:
                clear_output(wait=True)
                svg = self._repr_html_()
                # Status line above the SVG
                state = self.workflow_state
                status = self.status_message
                header = f"<b>State:</b> {html.escape(state)}"
                if status:
                    header += f" &mdash; {html.escape(status)}"
                header += (
                    f' <span style="color:#94a3b8;font-size:12px">'
                    f"(refreshing every {refresh}s, Ctrl-C to stop)</span>"
                )
                event_table = _render_event_table(list(self.event_log))
                display(HTML(
                    f'<div style="font-family:system-ui,sans-serif;margin-bottom:6px">'
                    f'{header}</div>{svg}{event_table}'
                ))

                # Stop if workflow reached a terminal state
                if state in ("SUCCESS", "FAILED", "UNKNOWN") and self._consumer and not self._polling:
                    break

                time.sleep(refresh)
        except KeyboardInterrupt:
            pass

    def show(self, show_files: Optional[bool] = None) -> None:
        """Re-render the DAG SVG with different options.

        Parameters
        ----------
        show_files : bool, optional
            Toggle data file nodes on/off.  If omitted, flips the current value.

        Usage::

            w.show()                # toggle show_files
            w.show(show_files=True) # explicitly enable file nodes
        """
        from IPython.display import display, HTML

        if show_files is None:
            self.show_files = not self.show_files
        else:
            self.show_files = show_files
        svg = self._repr_html_()
        event_table = _render_event_table(list(self.event_log))
        display(HTML(f"{svg}{event_table}"))

    def summary(self) -> None:
        """Print a text summary of the workflow graph."""
        nodes = self.graph_data.get("nodes", [])
        edges = self.graph_data.get("edges", [])
        info = self.workflow_info

        compute = [n for n in nodes if n.get("type_desc", "") in ("", "compute")]
        all_inputs: set = set()
        all_outputs: set = set()
        for n in compute:
            all_inputs.update(n.get("inputs", []))
            all_outputs.update(n.get("outputs", []))

        lines = []
        if info.get("dax_label"):
            lines.append(f"Workflow:  {info['dax_label']}")
        if info.get("planner_version"):
            lines.append(f"Pegasus:   {info['planner_version']}")
        lines.append(f"Jobs:      {len(compute)}")
        lines.append(f"Edges:     {len(edges)}")
        lines.append(f"Inputs:    {len(all_inputs - all_outputs)}")
        lines.append(f"Outputs:   {len(all_outputs - all_inputs)}")
        if self.workflow_state != "UNKNOWN":
            lines.append(f"State:     {self.workflow_state}")
        if self.source_mode != "STATIC":
            lines.append(f"Source:    {self.source_mode} ({self.source_detail})")
        print("\n".join(lines))

    def close(self) -> None:
        """Clean up resources on widget close."""
        self.stop_polling()
        if isinstance(self._consumer, RemoteEventConsumer):
            self._consumer.cleanup()
        super().close()
