"""Anywidget-based Pegasus workflow visualizer for Jupyter notebooks."""
from __future__ import annotations

import html
import json
import threading
import time
import uuid
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

    def _repr_mimebundle_(self, **kwargs: Any) -> Dict[str, Any]:
        """Choose the best display representation for the current environment.

        Always includes ``text/html`` as a fallback so that environments which
        reject the widget MIME type as untrusted (e.g. classic Jupyter Notebook
        on ACCESS Open OnDemand) can still render the inline DAG visualization.
        """
        bundle: Dict[str, Any] = {"text/html": self._repr_html_()}
        try:
            widget_bundle = super()._repr_mimebundle_(**kwargs)
            if widget_bundle:
                bundle.update(widget_bundle)
        except Exception:
            pass
        return bundle

    def _repr_html_(self) -> str:
        """Inline HTML/SVG fallback for environments where anywidget ESM fails.

        Renders the workflow DAG using D3 and dagre loaded as ES modules from
        esm.sh.  This method is called by Jupyter's display machinery when the
        anywidget comm channel is unavailable (e.g. wrong MIME type behind a
        reverse proxy).
        """
        container_id = f"wfviz-{uuid.uuid4().hex[:12]}"
        graph_json = html.escape(json.dumps(self.graph_data), quote=True)
        job_states_json = html.escape(json.dumps(dict(self.job_states)), quote=True)
        colors_json = html.escape(json.dumps(dict(self.state_colors)), quote=True)
        show_files_js = "true" if self.show_files else "false"

        return f"""\
<div id="{container_id}" style="width:800px;max-width:100%;height:600px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;background:#fff;position:relative;font-family:system-ui,-apple-system,sans-serif">
  <svg width="100%" height="100%"><defs></defs><g class="dag-content"></g></svg>
</div>
<script type="module">
import * as d3 from "https://esm.sh/d3@7";
import dagre from "https://esm.sh/dagre@0.8.5";

const graphData   = JSON.parse({json.dumps(json.dumps(self.graph_data))});
const jobStates   = JSON.parse({json.dumps(json.dumps(dict(self.job_states)))});
const stateColors = JSON.parse({json.dumps(json.dumps(dict(self.state_colors)))});
const showFiles   = {show_files_js};
const containerId = "{container_id}";

const DEFAULT_FILL   = "#e0f2fe";
const DEFAULT_STROKE = "#0284c7";
const UNKNOWN_COLOR  = {{ fill: "#e0e0e0", stroke: "#999999" }};

function getColor(state) {{
  return stateColors[state] || UNKNOWN_COLOR;
}}

// ── Build dagre graph ────────────────────────────────────────────────────
const g = new dagre.graphlib.Graph();
g.setGraph({{ rankdir: "TB", ranksep: 60, nodesep: 40, marginx: 30, marginy: 30 }});
g.setDefaultEdgeLabel(() => ({{}}));

const nodes = graphData.nodes || [];
const edges = graphData.edges || [];
const fileMeta = (graphData.metadata && graphData.metadata.file_meta) || {{}};

for (const node of nodes) {{
  const td = node.type_desc || "";
  if (td !== "" && td !== "compute") continue;
  const label = node.nodeLabel || node.id || "";
  g.setNode(node.id, {{ label, width: 150, height: 40, data: node }});
}}

if (!showFiles) {{
  for (const edge of edges) {{
    if (g.hasNode(edge.source) && g.hasNode(edge.target)) {{
      g.setEdge(edge.source, edge.target);
    }}
  }}
}} else {{
  const fileNodes = new Set();
  for (const node of nodes) {{
    if (!g.hasNode(node.id)) continue;
    for (const lfn of (node.outputs || [])) {{
      if (!fileNodes.has(lfn)) {{
        const meta = fileMeta[lfn] || {{ lfn }};
        const lbl = lfn.length > 20 ? "..." + lfn.slice(-18) : lfn;
        g.setNode("file:" + lfn, {{ label: lbl, width: 130, height: 26, data: {{ _isFile: true, lfn, ...meta }} }});
        fileNodes.add(lfn);
      }}
      g.setEdge(node.id, "file:" + lfn);
    }}
    for (const lfn of (node.inputs || [])) {{
      if (!fileNodes.has(lfn)) {{
        const meta = fileMeta[lfn] || {{ lfn }};
        const lbl = lfn.length > 20 ? "..." + lfn.slice(-18) : lfn;
        g.setNode("file:" + lfn, {{ label: lbl, width: 130, height: 26, data: {{ _isFile: true, lfn, ...meta }} }});
        fileNodes.add(lfn);
      }}
      g.setEdge("file:" + lfn, node.id);
    }}
  }}
}}

dagre.layout(g);

// ── Render (deferred until container has layout dimensions) ──────────────
function renderGraph() {{
  const container = d3.select("#" + containerId);
  if (!container.node()) return;
  const svg = container.select("svg");
  const gContent = svg.select("g.dag-content");
  const defs = svg.select("defs");

  // Arrowhead marker
  defs.append("marker")
    .attr("id", containerId + "-arrow")
    .attr("viewBox", "0 0 10 10")
    .attr("refX", 9).attr("refY", 5)
    .attr("markerWidth", 8).attr("markerHeight", 8)
    .attr("orient", "auto-start-reverse")
    .append("path").attr("d", "M 0 0 L 10 5 L 0 10 z").attr("fill", "#94a3b8");

  // Edges
  const line = d3.line().x(d => d.x).y(d => d.y).curve(d3.curveBasis);
  for (const e of g.edges()) {{
    const edgeObj = g.edge(e);
    gContent.append("path")
      .attr("d", line(edgeObj.points))
      .attr("fill", "none")
      .attr("stroke", "#94a3b8")
      .attr("stroke-width", 1.5)
      .attr("marker-end", `url(#${{containerId}}-arrow)`);
  }}

  // Nodes
  for (const id of g.nodes()) {{
    const n = g.node(id);
    if (!n) continue;
    const isFile = n.data && n.data._isFile;
    const state = jobStates[id] || "UNSUBMITTED";
    const color = isFile
      ? {{ fill: "#f8fafc", stroke: "#94a3b8" }}
      : (stateColors[state] || {{ fill: DEFAULT_FILL, stroke: DEFAULT_STROKE }});

    const nodeG = gContent.append("g")
      .attr("transform", `translate(${{n.x - n.width / 2}},${{n.y - n.height / 2}})`);

    nodeG.append("rect")
      .attr("width", n.width).attr("height", n.height)
      .attr("rx", isFile ? 2 : 6).attr("ry", isFile ? 2 : 6)
      .attr("fill", color.fill).attr("stroke", color.stroke).attr("stroke-width", 1.5);

    if (isFile) {{
      nodeG.append("rect")
        .attr("x", n.width - 12).attr("y", 0)
        .attr("width", 12).attr("height", 10)
        .attr("fill", color.stroke).attr("opacity", 0.25);
    }}

    nodeG.append("text")
      .attr("x", n.width / 2).attr("y", n.height / 2)
      .attr("text-anchor", "middle").attr("dominant-baseline", "central")
      .attr("font-size", isFile ? "10px" : "12px")
      .attr("font-family", "system-ui,-apple-system,sans-serif")
      .attr("fill", "#1e293b")
      .text(n.label);
  }}

  // ── Zoom / pan ─────────────────────────────────────────────────────────
  const zoom = d3.zoom()
    .scaleExtent([0.2, 4])
    .on("zoom", (event) => gContent.attr("transform", event.transform));
  svg.call(zoom);

  // Auto-center using resolved dimensions (fallback to 800x600)
  const gGraph = g.graph();
  const el = container.node();
  const cw = el.clientWidth || 800;
  const ch = el.clientHeight || 600;
  const gw = gGraph.width || 1;
  const gh = gGraph.height || 1;
  const scale = Math.min(cw / gw, ch / gh, 1) * 0.9;
  const tx = (cw - gw * scale) / 2;
  const ty = (ch - gh * scale) / 2;
  svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));

  // ── Legend ──────────────────────────────────────────────────────────────
  const legendStates = ["UNSUBMITTED", "QUEUED", "RUNNING", "SUCCESS", "FAILED", "HELD"];
  const legend = container.append("div")
    .style("position", "absolute").style("top", "8px").style("right", "8px")
    .style("display", "flex").style("gap", "8px").style("flex-wrap", "wrap")
    .style("font-size", "11px").style("color", "#475569");
  for (const st of legendStates) {{
    const c = stateColors[st] || UNKNOWN_COLOR;
    const item = legend.append("div").style("display", "flex").style("align-items", "center").style("gap", "3px");
    item.append("div")
      .style("width", "10px").style("height", "10px").style("border-radius", "2px")
      .style("background", c.fill).style("border", `1px solid ${{c.stroke}}`);
    item.append("span").text(st);
  }}
}}

// Defer rendering — setTimeout gives ES module imports time to resolve
// and ensures the container has final dimensions in the DOM.
setTimeout(renderGraph, 150);
</script>"""

    def close(self) -> None:
        """Clean up resources on widget close."""
        self.stop_polling()
        if isinstance(self._consumer, RemoteEventConsumer):
            self._consumer.cleanup()
        super().close()
