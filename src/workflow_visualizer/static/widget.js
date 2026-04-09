// Pegasus Workflow Visualizer — D3 + dagre frontend (ESM)
import * as d3 from "https://esm.sh/d3@7";
import dagre from "https://esm.sh/dagre@0.8.5";

// ── State color defaults (overridden by model.get("state_colors")) ──────────
const DEFAULT_COLORS = {
  UNSUBMITTED: { fill: "#e0e0e0", stroke: "#999999" },
  QUEUED:      { fill: "#fff3cd", stroke: "#ffc107" },
  PRE:         { fill: "#cce5ff", stroke: "#4a90d9" },
  RUNNING:     { fill: "#d1ecf1", stroke: "#17a2b8" },
  POST:        { fill: "#cce5ff", stroke: "#4a90d9" },
  DONE:        { fill: "#d4edda", stroke: "#28a745" },
  SUCCESS:     { fill: "#d4edda", stroke: "#28a745" },
  FAILED:      { fill: "#f8d7da", stroke: "#dc3545" },
  HELD:        { fill: "#e8d5f5", stroke: "#9b59b6" },
  UNKNOWN:     { fill: "#e0e0e0", stroke: "#999999" },
};

const LEGEND_STATES = ["UNSUBMITTED", "QUEUED", "RUNNING", "SUCCESS", "FAILED", "HELD"];

// ── Helpers ─────────────────────────────────────────────────────────────────

function getColor(state, colors) {
  return colors[state] || colors["UNKNOWN"] || DEFAULT_COLORS["UNKNOWN"];
}

function isCompute(node) {
  const td = node.type_desc || "";
  return td === "" || td === "compute";
}

function shortLabel(node) {
  return node.nodeLabel || node.id || "";
}

// ── Build dagre graph ───────────────────────────────────────────────────────

function buildDagreGraph(graphData, showFiles) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", ranksep: 60, nodesep: 40, marginx: 30, marginy: 30 });
  g.setDefaultEdgeLabel(() => ({}));

  const nodes = graphData.nodes || [];
  const edges = graphData.edges || [];
  const fileMeta = (graphData.metadata && graphData.metadata.file_meta) || {};

  for (const node of nodes) {
    if (!isCompute(node)) continue;
    g.setNode(node.id, { label: shortLabel(node), width: 150, height: 40, data: node });
  }

  // When showing files, replace direct job edges with job->file->job edges
  if (!showFiles) {
    for (const edge of edges) {
      if (g.hasNode(edge.source) && g.hasNode(edge.target)) {
        g.setEdge(edge.source, edge.target);
      }
    }
  }

  if (showFiles) {
    const fileNodes = new Set();
    for (const node of nodes) {
      if (!g.hasNode(node.id)) continue;
      for (const lfn of (node.outputs || [])) {
        if (!fileNodes.has(lfn)) {
          const meta = fileMeta[lfn] || { lfn };
          const label = lfn.length > 20 ? "..." + lfn.slice(-18) : lfn;
          g.setNode("file:" + lfn, { label, width: 130, height: 26, data: { _isFile: true, lfn, ...meta } });
          fileNodes.add(lfn);
        }
        g.setEdge(node.id, "file:" + lfn);
      }
      for (const lfn of (node.inputs || [])) {
        if (!fileNodes.has(lfn)) {
          const meta = fileMeta[lfn] || { lfn };
          const label = lfn.length > 20 ? "..." + lfn.slice(-18) : lfn;
          g.setNode("file:" + lfn, { label, width: 130, height: 26, data: { _isFile: true, lfn, ...meta } });
          fileNodes.add(lfn);
        }
        g.setEdge("file:" + lfn, node.id);
      }
    }
  }

  dagre.layout(g);
  return g;
}

// ── Render DAG ──────────────────────────────────────────────────────────────

function renderDAG(container, g, colors, jobStates, tooltip) {
  const svg = container.select("svg g.dag-content");

  // Arrowhead marker
  const defs = container.select("svg defs");
  defs.selectAll("marker").remove();
  defs.append("marker")
    .attr("id", "wfviz-arrowhead")
    .attr("viewBox", "0 0 10 10")
    .attr("refX", 9)
    .attr("refY", 5)
    .attr("markerWidth", 8)
    .attr("markerHeight", 8)
    .attr("orient", "auto-start-reverse")
    .append("path")
    .attr("d", "M 0 0 L 10 5 L 0 10 z")
    .attr("fill", "#94a3b8");

  // ── Edges ──
  const edgeData = g.edges().map(e => {
    const edgeObj = g.edge(e);
    return { source: e.v, target: e.w, points: edgeObj.points };
  });

  const line = d3.line().x(d => d.x).y(d => d.y).curve(d3.curveBasis);

  const edgeSel = svg.selectAll(".wfviz-edge").data(edgeData, d => `${d.source}->${d.target}`);
  edgeSel.exit().remove();
  const edgeEnter = edgeSel.enter().append("path").attr("class", "wfviz-edge");
  edgeSel.merge(edgeEnter)
    .attr("d", d => line(d.points))
    .attr("marker-end", "url(#wfviz-arrowhead)");

  // ── Nodes ──
  const nodeData = g.nodes().map(id => {
    const n = g.node(id);
    return { id, ...n };
  });

  // Separate file nodes from job nodes
  const jobNodeData = nodeData.filter(d => !d.data._isFile);
  const fileNodeData = nodeData.filter(d => d.data._isFile);

  // ── Job nodes ──
  const nodeSel = svg.selectAll(".wfviz-node").data(jobNodeData, d => d.id);
  nodeSel.exit().remove();

  const nodeEnter = nodeSel.enter().append("g").attr("class", "wfviz-node");
  nodeEnter.append("rect");
  nodeEnter.append("text").attr("class", "wfviz-node-label");
  nodeEnter.append("text").attr("class", "wfviz-node-state-badge");

  const nodeAll = nodeSel.merge(nodeEnter);

  nodeAll.each(function(d) {
    const el = d3.select(this);

    // Determine state
    const js = jobStates[d.id];
    const state = js ? js.state : "UNSUBMITTED";
    const c = getColor(state, colors);

    el.attr("transform", `translate(${d.x - d.width/2}, ${d.y - d.height/2})`);

    el.select("rect")
      .attr("width", d.width)
      .attr("height", d.height)
      .attr("fill", c.fill)
      .attr("stroke", c.stroke);

    el.select(".wfviz-node-label")
      .attr("x", d.width / 2)
      .attr("y", d.height / 2 - 2)
      .text(d.label);

    // State badge
    el.select(".wfviz-node-state-badge")
      .attr("x", d.width / 2)
      .attr("y", d.height - 4)
      .text(state !== "UNSUBMITTED" ? state : "");

    // Pulse class
    el.classed("wfviz-running", state === "RUNNING");

    // Tooltip events
    el.on("mouseenter", function(event) {
      showTooltip(tooltip, event, d, jobStates[d.id]);
    }).on("mousemove", function(event) {
      moveTooltip(tooltip, event);
    }).on("mouseleave", function() {
      hideTooltip(tooltip);
    });
  });

  // ── File nodes ──
  const fileSel = svg.selectAll(".wfviz-node-file").data(fileNodeData, d => d.id);
  fileSel.exit().remove();

  const fileEnter = fileSel.enter().append("g").attr("class", "wfviz-node-file");
  fileEnter.append("ellipse");
  fileEnter.append("text").attr("class", "wfviz-node-label");

  const fileAll = fileSel.merge(fileEnter);

  fileAll.each(function(d) {
    const el = d3.select(this);
    el.attr("transform", `translate(${d.x}, ${d.y})`);

    el.select("ellipse")
      .attr("rx", d.width / 2)
      .attr("ry", d.height / 2);

    el.select(".wfviz-node-label")
      .attr("x", 0)
      .attr("y", 0)
      .text(d.label);

    // Tooltip for file nodes
    el.on("mouseenter", function(event) {
      showFileTooltip(tooltip, event, d.data);
    }).on("mousemove", function(event) {
      moveTooltip(tooltip, event);
    }).on("mouseleave", function() {
      hideTooltip(tooltip);
    });
  });
}

// ── Tooltip ─────────────────────────────────────────────────────────────────

function showTooltip(tooltip, event, node, jobState) {
  let html = `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Name</span><span class="wfviz-tooltip-val">${node.label}</span></div>`;
  html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">ID</span><span class="wfviz-tooltip-val">${node.id}</span></div>`;

  if (node.data) {
    const d = node.data;
    if (d.type_desc) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Type</span><span class="wfviz-tooltip-val">${d.type_desc || "compute"}</span></div>`;
    if (d.inputs && d.inputs.length) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Inputs</span><span class="wfviz-tooltip-val">${d.inputs.join(", ")}</span></div>`;
    if (d.outputs && d.outputs.length) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Outputs</span><span class="wfviz-tooltip-val">${d.outputs.join(", ")}</span></div>`;
  }

  if (jobState) {
    html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">State</span><span class="wfviz-tooltip-val">${jobState.state}</span></div>`;
    if (jobState.exec_job_id) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Exec ID</span><span class="wfviz-tooltip-val">${jobState.exec_job_id}</span></div>`;
    if (jobState.transformation) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Transform</span><span class="wfviz-tooltip-val">${jobState.transformation}</span></div>`;
    if (jobState.task_argv) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Args</span><span class="wfviz-tooltip-val wfviz-tooltip-mono">${jobState.task_argv}</span></div>`;
    if (jobState.exitcode !== null && jobState.exitcode !== undefined) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Exit</span><span class="wfviz-tooltip-val">${jobState.exitcode}</span></div>`;
    if (jobState.duration) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Duration</span><span class="wfviz-tooltip-val">${jobState.duration}</span></div>`;
    if (jobState.maxrss_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Peak RSS</span><span class="wfviz-tooltip-val">${jobState.maxrss_fmt}</span></div>`;
    if (jobState.site) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Site</span><span class="wfviz-tooltip-val">${jobState.site}</span></div>`;
    // Resource requests
    const resParts = [];
    if (jobState.request_cpus) resParts.push(`${jobState.request_cpus} CPU`);
    if (jobState.request_memory) resParts.push(`${jobState.request_memory} MB`);
    if (jobState.request_gpus && jobState.request_gpus > 0) resParts.push(`${jobState.request_gpus} GPU`);
    if (resParts.length) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Requested</span><span class="wfviz-tooltip-val">${resParts.join(", ")}</span></div>`;
    // Timing and CPU
    if (jobState.wall_time) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Wall Time</span><span class="wfviz-tooltip-val">${jobState.wall_time}</span></div>`;
    if (jobState.cpu_time) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">CPU Time</span><span class="wfviz-tooltip-val">${jobState.cpu_time}</span></div>`;
    if (jobState.cpu_efficiency_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">CPU Eff.</span><span class="wfviz-tooltip-val">${jobState.cpu_efficiency_fmt}</span></div>`;
    if (jobState.memory_efficiency_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Mem Eff.</span><span class="wfviz-tooltip-val">${jobState.memory_efficiency_fmt}</span></div>`;
    // Memory and disk
    if (jobState.image_size_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Peak Mem</span><span class="wfviz-tooltip-val">${jobState.image_size_fmt}</span></div>`;
    if (jobState.disk_usage_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Disk</span><span class="wfviz-tooltip-val">${jobState.disk_usage_fmt}</span></div>`;
    // Transfer I/O
    if (jobState.bytes_recvd_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Bytes In</span><span class="wfviz-tooltip-val">${jobState.bytes_recvd_fmt}</span></div>`;
    if (jobState.bytes_sent_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Bytes Out</span><span class="wfviz-tooltip-val">${jobState.bytes_sent_fmt}</span></div>`;
    // Queue and host
    if (jobState.queue_wait && jobState.queue_wait !== "-") html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Q. Wait</span><span class="wfviz-tooltip-val">${jobState.queue_wait}</span></div>`;
    if (jobState.remote_host) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Host</span><span class="wfviz-tooltip-val wfviz-tooltip-mono">${jobState.remote_host}</span></div>`;
    if (jobState.num_job_starts != null && jobState.num_job_starts > 1) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Restarts</span><span class="wfviz-tooltip-val">${jobState.num_job_starts}</span></div>`;
    if (jobState.maxrss_fmt) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Peak RSS</span><span class="wfviz-tooltip-val">${jobState.maxrss_fmt}</span></div>`;
    if (jobState.stdout_file) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Stdout</span><span class="wfviz-tooltip-val wfviz-tooltip-mono">${jobState.stdout_file}</span></div>`;
    if (jobState.stderr_file) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Stderr</span><span class="wfviz-tooltip-val wfviz-tooltip-mono">${jobState.stderr_file}</span></div>`;
    if (jobState.hold_reason) html += `<div class="wfviz-tooltip-row wfviz-tooltip-diag"><span class="wfviz-tooltip-key">Hold</span><span class="wfviz-tooltip-val">${jobState.hold_reason}</span></div>`;
  }

  tooltip.html(html);
  tooltip.classed("visible", true);
  moveTooltip(tooltip, event);
}

function showFileTooltip(tooltip, event, fileMeta) {
  let html = `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">File</span><span class="wfviz-tooltip-val">${fileMeta.lfn || ""}</span></div>`;
  if (fileMeta.type) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Usage</span><span class="wfviz-tooltip-val">${fileMeta.type}</span></div>`;
  if (fileMeta.size !== undefined) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Size</span><span class="wfviz-tooltip-val">${fileMeta.size}</span></div>`;
  if (fileMeta.namespace) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Namespace</span><span class="wfviz-tooltip-val">${fileMeta.namespace}</span></div>`;
  if (fileMeta.version) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Version</span><span class="wfviz-tooltip-val">${fileMeta.version}</span></div>`;
  if (fileMeta.stageOut !== undefined) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Stage Out</span><span class="wfviz-tooltip-val">${fileMeta.stageOut}</span></div>`;
  if (fileMeta.registerReplica !== undefined) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Register</span><span class="wfviz-tooltip-val">${fileMeta.registerReplica}</span></div>`;

  tooltip.html(html);
  tooltip.classed("visible", true);
  moveTooltip(tooltip, event);
}

function moveTooltip(tooltip, event) {
  const node = tooltip.node();
  if (!node) return;
  const rect = node.closest(".wfviz-container")?.getBoundingClientRect();
  if (!rect) return;
  const x = event.clientX - rect.left + 12;
  const y = event.clientY - rect.top + 12;
  tooltip.style("left", x + "px").style("top", y + "px");
}

function hideTooltip(tooltip) {
  tooltip.classed("visible", false);
}

// ── Time formatting helpers ──────────────────────────────────────────────────

function fmtTs(ts) {
  if (ts == null) return "-";
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0, 8);
}

function fmtDur(seconds) {
  if (seconds == null || seconds < 0) return "-";
  if (seconds < 60) return seconds.toFixed(1) + "s";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m < 60) return `${m}m${s.toString().padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h${rm.toString().padStart(2, "0")}m${s.toString().padStart(2, "0")}s`;
}

// ── Event log (hierarchical) ────────────────────────────────────────────────

function buildJobGroups(eventLog) {
  // eventLog arrives most-recent-first; group by job key
  const groupMap = new Map();
  const groupOrder = [];

  for (const ev of eventLog) {
    const key = ev.node_id || ev.exec_job_id || "";
    if (!key) continue;
    if (!groupMap.has(key)) {
      const group = { key, execId: ev.exec_job_id || "", events: [] };
      groupMap.set(key, group);
      groupOrder.push(group);
    }
    groupMap.get(key).events.push(ev);
  }

  // Compute per-group summary and per-transition durations
  for (const group of groupOrder) {
    const evts = group.events; // most-recent-first
    group.currentState = evts[0].state;
    group.holdReason = null;

    // Chronological order for computing transition durations
    const chrono = [...evts].reverse();
    group.transitions = [];
    for (let i = 0; i < chrono.length; i++) {
      const cur = chrono[i];
      const next = chrono[i + 1];
      const start = cur.timestamp;
      const end = next ? next.timestamp : null;
      const dur = (start != null && end != null) ? end - start : null;
      const tr = {
        state: cur.state,
        rawState: cur.raw_state,
        start,
        end,
        duration: dur,
      };
      if (cur.hold_reason) {
        tr.holdReason = cur.hold_reason;
        group.holdReason = cur.hold_reason;  // bubble up to group
      }
      group.transitions.push(tr);
    }
    // Reverse transitions back to most-recent-first for display
    group.transitions.reverse();

    // Summary timing: first event -> last event
    const first = chrono[0];
    const last = chrono[chrono.length - 1];
    group.startTs = first ? first.timestamp : null;
    group.endTs = last ? last.timestamp : null;
    group.totalDuration = (group.startTs != null && group.endTs != null)
      ? group.endTs - group.startTs
      : null;
  }

  // Sort groups: most recently active first
  groupOrder.sort((a, b) => (b.endTs || 0) - (a.endTs || 0));
  return groupOrder;
}

function renderEventLog(panel, eventLog, colors, expandedJobs, jobStates) {
  // Ensure header exists
  let header = panel.select(".wfviz-event-header");
  if (header.empty()) {
    header = panel.append("div").attr("class", "wfviz-event-header").html(
      `<span class="wfviz-event-col wfviz-event-col-name">Job</span>` +
      `<span class="wfviz-event-col">Type</span>` +
      `<span class="wfviz-event-col">State</span>` +
      `<span class="wfviz-event-col">Start</span>` +
      `<span class="wfviz-event-col">End</span>` +
      `<span class="wfviz-event-col">Duration</span>` +
      `<span class="wfviz-event-col">Memory</span>`
    );
  }

  // Store current render data so the click handler can re-render
  const panelNode = panel.node();
  panelNode.__wfviz_eventLog = eventLog;
  panelNode.__wfviz_colors = colors;
  panelNode.__wfviz_jobStates = jobStates;

  // Install a single delegated click handler on the panel (once)
  if (!panelNode.__wfviz_delegated) {
    panelNode.__wfviz_delegated = true;
    panel.on("click", function(event) {
      // Walk up from the click target to find the expandable primary row
      let target = event.target;
      while (target && target !== panelNode) {
        if (target.classList && target.classList.contains("wfviz-event-expandable")) {
          const groupKey = target.dataset.groupKey;
          if (!groupKey) break;
          if (expandedJobs.has(groupKey)) {
            expandedJobs.delete(groupKey);
          } else {
            expandedJobs.add(groupKey);
          }
          // Re-render the event log with updated expand state
          renderEventLog(
            panel,
            panelNode.__wfviz_eventLog,
            panelNode.__wfviz_colors,
            expandedJobs,
            panelNode.__wfviz_jobStates,
          );
          break;
        }
        target = target.parentNode;
      }
    });
  }

  const groups = buildJobGroups(eventLog);

  // Bind groups
  const groupSel = panel.selectAll(".wfviz-event-group")
    .data(groups, d => d.key);
  groupSel.exit().remove();

  const groupEnter = groupSel.enter()
    .append("div").attr("class", "wfviz-event-group");

  // Primary row
  groupEnter.append("div").attr("class", "wfviz-event-primary");

  // Sub-rows container
  groupEnter.append("div").attr("class", "wfviz-event-subs");

  const groupAll = groupSel.merge(groupEnter);

  groupAll.each(function(group) {
    const el = d3.select(this);
    const isExpanded = expandedJobs.has(group.key);
    const hasEvents = group.transitions.length > 0;
    el.classed("expanded", isExpanded);

    // Look up enriched job data from jobStates
    const jd = (jobStates || {})[group.key] || {};
    const typeDesc = group.events[0]?.type_desc || jd.type_desc || "";
    const memFmt = jd.maxrss_fmt || (group.events[0]?.maxrss_fmt) || "-";

    // ── Primary row ──
    const primary = el.select(".wfviz-event-primary");
    const c = getColor(group.currentState, colors);
    const stateStyle = `background:${c.fill};color:${c.stroke};`;

    const chevron = hasEvents
      ? `<span class="wfviz-event-chevron">${isExpanded ? "\u25BE" : "\u25B8"}</span>`
      : `<span class="wfviz-event-chevron-spacer"></span>`;
    const count = group.transitions.length > 1 ? `<span class="wfviz-event-count">${group.transitions.length}</span>` : "";
    const diagIcon = group.holdReason ? `<span class="wfviz-event-diag-icon" title="${group.holdReason.replace(/"/g, '&quot;')}">&#x26A0;</span>` : "";

    primary.html(
      `<span class="wfviz-event-col wfviz-event-col-name" title="${group.execId}">${chevron}${group.key}${count}${diagIcon}</span>` +
      `<span class="wfviz-event-col wfviz-event-col-type">${typeDesc}</span>` +
      `<span class="wfviz-event-col"><span class="wfviz-event-state" style="${stateStyle}">${group.currentState}</span></span>` +
      `<span class="wfviz-event-col">${fmtTs(group.startTs)}</span>` +
      `<span class="wfviz-event-col">${fmtTs(group.endTs)}</span>` +
      `<span class="wfviz-event-col">${fmtDur(group.totalDuration)}</span>` +
      `<span class="wfviz-event-col">${memFmt}</span>`
    );

    primary.classed("wfviz-event-expandable", hasEvents);
    primary.attr("data-group-key", hasEvents ? group.key : null);

    // ── Expanded detail ──
    const subsContainer = el.select(".wfviz-event-subs");
    subsContainer.style("display", isExpanded ? "block" : "none");
    subsContainer.selectAll("*").remove();

    if (isExpanded) {
      // ── Job metadata grid ──
      const meta = [];
      const latest = group.events[0] || {};
      if (latest.node_id) meta.push(["Node ID", latest.node_id]);
      if (jd.transformation || latest.transformation) meta.push(["Transformation", jd.transformation || latest.transformation]);
      if (jd.task_argv || latest.task_argv) meta.push(["Arguments", jd.task_argv || latest.task_argv]);
      if (jd.maxrss != null) {
        meta.push(["Peak RSS", `${jd.maxrss_fmt || jd.maxrss} (${jd.maxrss} KB)`]);
      } else if (latest.maxrss != null) {
        meta.push(["Peak RSS", `${latest.maxrss_fmt || latest.maxrss} (${latest.maxrss} KB)`]);
      }
      if (jd.stdout_file || latest.stdout_file) meta.push(["Stdout", jd.stdout_file || latest.stdout_file]);
      if (jd.stderr_file || latest.stderr_file) meta.push(["Stderr", jd.stderr_file || latest.stderr_file]);
      if (jd.hold_reason || latest.hold_reason) meta.push(["Hold reason", jd.hold_reason || latest.hold_reason]);

      // HTCondor enriched metrics
      if (jd.wall_time) meta.push(["Wall time", jd.wall_time]);
      if (jd.cpu_time) meta.push(["CPU time", jd.cpu_time]);
      if (jd.cpu_efficiency_fmt) meta.push(["CPU efficiency", jd.cpu_efficiency_fmt]);
      if (jd.memory_efficiency_fmt) meta.push(["Memory efficiency", jd.memory_efficiency_fmt]);
      if (jd.image_size_fmt) meta.push(["Peak memory", jd.image_size_fmt]);
      if (jd.disk_usage_fmt) meta.push(["Disk usage", jd.disk_usage_fmt]);
      if (jd.bytes_recvd_fmt) meta.push(["Bytes in", jd.bytes_recvd_fmt]);
      if (jd.bytes_sent_fmt) meta.push(["Bytes out", jd.bytes_sent_fmt]);
      if (jd.queue_wait && jd.queue_wait !== "-") meta.push(["Queue wait", jd.queue_wait]);
      if (jd.remote_host) meta.push(["Remote host", jd.remote_host]);
      // Requested resources
      const resParts = [];
      if (jd.request_cpus) resParts.push(`${jd.request_cpus} CPU`);
      if (jd.request_memory) resParts.push(`${jd.request_memory} MB`);
      if (jd.request_gpus && jd.request_gpus > 0) resParts.push(`${jd.request_gpus} GPU`);
      if (resParts.length) meta.push(["Requested", resParts.join(", ")]);
      if (jd.num_job_starts != null && jd.num_job_starts > 1) meta.push(["Restarts", String(jd.num_job_starts)]);

      if (meta.length > 0) {
        let metaHtml = '<div class="wfviz-event-meta">';
        for (const [k, v] of meta) {
          metaHtml += `<span class="wfviz-event-meta-key">${k}</span>`;
          metaHtml += `<span class="wfviz-event-meta-val">${v}</span>`;
        }
        metaHtml += '</div>';
        subsContainer.append("div").html(metaHtml);
      }

      // ── State history ──
      if (group.transitions.length > 1) {
        subsContainer.append("div")
          .attr("class", "wfviz-event-history-label")
          .text("State history");

        for (const tr of group.transitions) {
          const sc = getColor(tr.state, colors);
          const ss = `background:${sc.fill};color:${sc.stroke};`;
          subsContainer.append("div")
            .attr("class", "wfviz-event-sub")
            .html(
              `<span class="wfviz-event-col wfviz-event-col-name wfviz-event-sub-name">${tr.rawState || tr.state}</span>` +
              `<span class="wfviz-event-col"><span class="wfviz-event-state" style="${ss}">${tr.state}</span></span>` +
              `<span class="wfviz-event-col">${fmtTs(tr.start)}</span>` +
              `<span class="wfviz-event-col">${fmtTs(tr.end)}</span>` +
              `<span class="wfviz-event-col">${fmtDur(tr.duration)}</span>`
            );
          if (tr.holdReason) {
            subsContainer.append("div")
              .attr("class", "wfviz-event-diag")
              .html(`<span class="wfviz-event-diag-text">${tr.holdReason}</span>`);
          }
        }
      }
    }
  });
}

// ── Legend ───────────────────────────────────────────────────────────────────

function renderLegend(legendEl, colors) {
  legendEl.selectAll("*").remove();
  for (const state of LEGEND_STATES) {
    const c = getColor(state, colors);
    const item = legendEl.append("div").attr("class", "wfviz-legend-item");
    item.append("div")
      .attr("class", "wfviz-legend-swatch")
      .style("background", c.fill)
      .style("border-color", c.stroke);
    item.append("span").text(state);
  }
}

// ── Toolbar ─────────────────────────────────────────────────────────────────

const WF_STATE_LABELS = {
  UNKNOWN:              { label: "Idle",       cls: "wfviz-wf-idle" },
  WORKFLOW_STARTED:     { label: "Running",    cls: "wfviz-wf-running" },
  WORKFLOW_TERMINATED:  { label: "Completed",  cls: "wfviz-wf-completed" },
};

const SOURCE_MODE_LABELS = {
  STATIC: { label: "Static",  cls: "wfviz-source-static" },
  LIVE:   { label: "Live",    cls: "wfviz-source-live" },
  SSH:    { label: "SSH",     cls: "wfviz-source-ssh" },
};

function wfButtonRules(wfState) {
  // Returns { plan, run, stop, resume } — true means enabled
  switch (wfState) {
    case "WORKFLOW_STARTED":
      return { plan: false, run: false, stop: true, resume: false };
    case "WORKFLOW_TERMINATED":
      return { plan: true, run: false, stop: false, resume: true };
    default: // UNKNOWN / idle
      return { plan: true, run: true, stop: false, resume: false };
  }
}

function sendWithFeedback(btn, model, payload) {
  btn.classed("wfviz-btn-pending", true).attr("disabled", true);
  model.send(payload);
  setTimeout(() => {
    btn.classed("wfviz-btn-pending", false).attr("disabled", null);
  }, 1500);
}

function buildToolbar(toolbar, model) {
  toolbar.html("");

  const wfState = model.get("workflow_state") || "UNKNOWN";
  const rules = wfButtonRules(wfState);

  // ── Workflow state indicator ──
  const stateInfo = WF_STATE_LABELS[wfState] || WF_STATE_LABELS.UNKNOWN;
  const stateGroup = toolbar.append("div").attr("class", "wfviz-toolbar-group");
  stateGroup.append("span")
    .attr("class", `wfviz-wf-badge ${stateInfo.cls}`)
    .text(stateInfo.label);

  // ── Source mode indicator ──
  const sourceMode = model.get("source_mode") || "STATIC";
  const sourceDetail = model.get("source_detail") || "";
  const sourceInfo = SOURCE_MODE_LABELS[sourceMode] || SOURCE_MODE_LABELS.STATIC;
  const sourceBadge = stateGroup.append("span")
    .attr("class", `wfviz-source-badge ${sourceInfo.cls}`)
    .text(sourceInfo.label);
  if (sourceDetail) {
    sourceBadge.attr("title", sourceDetail);
  }

  // ── Workflow controls ──
  const wfGroup = toolbar.append("div").attr("class", "wfviz-toolbar-group");
  wfGroup.append("span").attr("class", "wfviz-toolbar-label").text("Workflow");

  const actions = [
    { label: "Plan",   action: "plan",   cls: "",                  enabled: rules.plan },
    { label: "Start",  action: "run",    cls: "wfviz-btn-success", enabled: rules.run },
    { label: "Stop",   action: "stop",   cls: "wfviz-btn-danger",  enabled: rules.stop },
    { label: "Resume", action: "resume", cls: "wfviz-btn-success", enabled: rules.resume },
  ];

  for (const a of actions) {
    const btn = wfGroup.append("button")
      .attr("class", `wfviz-btn ${a.cls}`)
      .text(a.label);
    if (!a.enabled) {
      btn.attr("disabled", true).classed("wfviz-btn-disabled", true);
    } else {
      btn.on("click", function() { sendWithFeedback(d3.select(this), model, { action: a.action }); });
    }
  }

  // ── Monitor controls ──
  const monGroup = toolbar.append("div").attr("class", "wfviz-toolbar-group");
  monGroup.append("span").attr("class", "wfviz-toolbar-label").text("Monitor");

  const monStart = monGroup.append("button")
    .attr("class", "wfviz-btn wfviz-btn-success")
    .text("Start");
  monStart.on("click", function() { sendWithFeedback(d3.select(this), model, { action: "monitor_start" }); });

  const monStop = monGroup.append("button")
    .attr("class", "wfviz-btn wfviz-btn-danger")
    .text("Stop");
  monStop.on("click", function() { sendWithFeedback(d3.select(this), model, { action: "monitor_stop" }); });

  // ── Toggles ──
  const toggleGroup = toolbar.append("div").attr("class", "wfviz-toolbar-group");

  const fileToggle = toggleGroup.append("label").attr("class", "wfviz-toggle");
  const fileCheckbox = fileToggle.append("input")
    .attr("type", "checkbox")
    .property("checked", model.get("show_files"));
  fileToggle.append("span").text("Data files");
  fileCheckbox.on("change", function() {
    model.set("show_files", this.checked);
    model.save_changes();
  });

  // ── Status message ──
  const statusMsg = model.get("status_message") || "";
  if (statusMsg) {
    toolbar.append("span")
      .attr("class", "wfviz-status wfviz-status-flash")
      .text(statusMsg);
  }
}

// ── Workflow info bar ────────────────────────────────────────────────────────

function renderInfoBar(infoBar, model) {
  const info = model.get("workflow_info") || {};
  const wfState = model.get("workflow_state") || "UNKNOWN";

  // Hide if no info at all
  const hasContent = info.dax_label || info.wf_uuid || info.user || info.planner_version;
  infoBar.style("display", hasContent ? "flex" : "none");
  if (!hasContent) return;

  infoBar.html("");

  if (info.dax_label) {
    infoBar.append("span").attr("class", "wfviz-info-item")
      .html(`<span class="wfviz-info-key">Workflow</span><span class="wfviz-info-val wfviz-info-label">${info.dax_label}</span>`);
  }

  if (info.wf_uuid) {
    const short = info.wf_uuid.length > 8 ? info.wf_uuid.slice(0, 8) + "\u2026" : info.wf_uuid;
    infoBar.append("span").attr("class", "wfviz-info-item")
      .attr("title", info.wf_uuid)
      .html(`<span class="wfviz-info-key">UUID</span><span class="wfviz-info-val wfviz-info-uuid">${short}</span>`);
  }

  if (info.user) {
    infoBar.append("span").attr("class", "wfviz-info-item")
      .html(`<span class="wfviz-info-key">User</span><span class="wfviz-info-val">${info.user}</span>`);
  }

  if (info.planner_version) {
    infoBar.append("span").attr("class", "wfviz-info-item")
      .html(`<span class="wfviz-info-key">Pegasus</span><span class="wfviz-info-val">${info.planner_version}</span>`);
  }

  if (info.submit_dir) {
    const dirShort = info.submit_dir.length > 50
      ? "\u2026" + info.submit_dir.slice(-48)
      : info.submit_dir;
    infoBar.append("span").attr("class", "wfviz-info-item wfviz-info-dir")
      .attr("title", info.submit_dir)
      .html(`<span class="wfviz-info-key">Dir</span><span class="wfviz-info-val">${dirShort}</span>`);
  }

  // Job summary counts (from workflow_end)
  if (info.total_jobs != null) {
    let summary = `${info.done != null ? info.done : "?"} / ${info.total_jobs}`;
    if (info.failed != null && info.failed > 0) {
      summary += ` <span class="wfviz-info-failed">(${info.failed} failed)</span>`;
    }
    infoBar.append("span").attr("class", "wfviz-info-item")
      .html(`<span class="wfviz-info-key">Jobs</span><span class="wfviz-info-val">${summary}</span>`);
  }

  // Workflow timing (right-aligned)
  if (info.start_time || info.end_time || info.elapsed != null) {
    const startStr = info.start_time ? fmtTs(info.start_time) : "-";
    const endStr = info.end_time ? fmtTs(info.end_time) : "-";
    const dur = info.elapsed != null ? fmtDur(info.elapsed) :
      (info.start_time && info.end_time) ? fmtDur(info.end_time - info.start_time) : "-";
    infoBar.append("span").attr("class", "wfviz-info-item wfviz-info-timing")
      .html(`<span class="wfviz-info-key">Elapsed</span><span class="wfviz-info-val">${startStr} \u2192 ${endStr} (${dur})</span>`);
  }
}

// ── Workflow Synopsis Panel ─────────────────────────────────────────────────

function fmtDuration(s) {
  if (s == null || s < 0) return "-";
  s = Math.round(s);
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m < 60) return sec > 0 ? `${m}m${String(sec).padStart(2, "0")}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const min = m % 60;
  return min > 0 ? `${h}h${String(min).padStart(2, "0")}m` : `${h}h`;
}

function fmtMemKB(kb) {
  if (kb == null || kb < 0) return "-";
  if (kb < 1024) return kb + " KB";
  const mb = kb / 1024;
  if (mb < 1024) return mb.toFixed(1) + " MB";
  return (mb / 1024).toFixed(2) + " GB";
}

function fmtBytesVal(b) {
  if (b == null || b < 0) return "-";
  if (b < 1024) return b + " B";
  const kb = b / 1024;
  if (kb < 1024) return kb.toFixed(1) + " KB";
  const mb = kb / 1024;
  if (mb < 1024) return mb.toFixed(1) + " MB";
  return (mb / 1024).toFixed(2) + " GB";
}

function fmtPct(v) {
  if (v == null) return "-";
  return (v * 100).toFixed(1) + "%";
}

function statHTML(label, value, valueStyle) {
  const vs = valueStyle || "";
  return `<div class="wfviz-stats-item"><div class="wfviz-stats-label">${label}</div><div class="wfviz-stats-value" ${vs}>${value}</div></div>`;
}

function renderWorkflowStats(panel, model) {
  const stats = model.get("workflow_stats") || {};
  const hasData = stats.total_jobs != null;
  panel.style("display", hasData ? "block" : "none");
  if (!hasData) return;

  let html = '<div class="wfviz-stats-title">Workflow Synopsis</div>';

  // Jobs section
  html += '<div class="wfviz-stats-section-label">Jobs</div><div class="wfviz-stats-row">';
  html += statHTML("Total", stats.total_jobs);
  if (stats.compute_jobs != null) html += statHTML("Compute", stats.compute_jobs);
  if (stats.infra_jobs != null) html += statHTML("Infra", stats.infra_jobs);
  if (stats.succeeded != null) {
    const c = stats.succeeded === stats.total_jobs ? 'style="color:#16a34a"' : '';
    html += statHTML("Succeeded", stats.succeeded, c);
  }
  if (stats.failed != null) {
    const c = stats.failed > 0 ? 'style="color:#dc2626"' : '';
    html += statHTML("Failed", stats.failed, c);
  }
  if (stats.held != null && stats.held > 0) {
    html += statHTML("Held", stats.held, 'style="color:#9333ea"');
  }
  html += '</div>';

  // Timing section
  if (stats.wall_time != null || stats.total_compute_time != null) {
    html += '<div class="wfviz-stats-section-label">Timing</div><div class="wfviz-stats-row">';
    if (stats.wall_time != null) html += statHTML("Wall Time", fmtDuration(stats.wall_time));
    if (stats.total_compute_time != null) html += statHTML("Total Compute", fmtDuration(stats.total_compute_time));
    if (stats.parallelism != null) html += statHTML("Parallelism", stats.parallelism.toFixed(2) + "x");
    html += '</div>';
  }

  // Job Duration section
  if (stats.dur_min != null) {
    html += '<div class="wfviz-stats-section-label">Job Duration</div><div class="wfviz-stats-row">';
    html += statHTML("Min", fmtDuration(stats.dur_min));
    if (stats.dur_max != null) html += statHTML("Max", fmtDuration(stats.dur_max));
    if (stats.dur_mean != null) html += statHTML("Mean", fmtDuration(stats.dur_mean));
    if (stats.dur_median != null) html += statHTML("Median", fmtDuration(stats.dur_median));
    if (stats.longest_job_name) html += statHTML("Longest", `<span class="wfviz-stats-name">${stats.longest_job_name}</span>`);
    if (stats.shortest_job_name) html += statHTML("Shortest", `<span class="wfviz-stats-name">${stats.shortest_job_name}</span>`);
    html += '</div>';
  }

  // Memory section
  if (stats.peak_maxrss_kb != null) {
    html += '<div class="wfviz-stats-section-label">Memory</div><div class="wfviz-stats-row">';
    html += statHTML("Peak RSS", fmtMemKB(stats.peak_maxrss_kb));
    if (stats.peak_maxrss_job) html += statHTML("Peak Job", `<span class="wfviz-stats-name">${stats.peak_maxrss_job}</span>`);
    if (stats.mean_maxrss_kb != null) html += statHTML("Mean RSS", fmtMemKB(Math.round(stats.mean_maxrss_kb)));
    html += '</div>';
  }

  // Efficiency section
  if (stats.cpu_eff_mean != null || stats.mem_eff_mean != null) {
    html += '<div class="wfviz-stats-section-label">Efficiency</div><div class="wfviz-stats-row">';
    if (stats.cpu_eff_mean != null) html += statHTML("CPU Eff (mean)", fmtPct(stats.cpu_eff_mean));
    if (stats.cpu_eff_min != null && stats.cpu_eff_max != null) html += statHTML("CPU Eff (range)", fmtPct(stats.cpu_eff_min) + " – " + fmtPct(stats.cpu_eff_max));
    if (stats.mem_eff_mean != null) html += statHTML("Mem Eff (mean)", fmtPct(stats.mem_eff_mean));
    html += '</div>';
  }

  // Resources section
  if (stats.cpu_seconds != null || stats.hosts) {
    html += '<div class="wfviz-stats-section-label">Resources</div><div class="wfviz-stats-row">';
    if (stats.cpu_seconds != null) html += statHTML("CPU Seconds", fmtDuration(stats.cpu_seconds));
    if (stats.transfer_bytes != null) html += statHTML("Data Transfer", fmtBytesVal(stats.transfer_bytes));
    if (stats.pool_machines != null) html += statHTML("Pool Machines", stats.pool_machines);
    if (stats.pool_total_cpus != null) html += statHTML("Pool CPUs", stats.pool_total_cpus);
    if (stats.pool_total_gpus != null && stats.pool_total_gpus > 0) html += statHTML("Pool GPUs", stats.pool_total_gpus);
    if (stats.hosts && stats.hosts.length) html += statHTML("Hosts", `<span class="wfviz-stats-name">${stats.hosts.join(", ")}</span>`);
    html += '</div>';
  }

  panel.html(html);
}

// ── Pool Resources Panel ───────────────────────────────────────────────────

function fmtMemMB(mb) {
  if (mb == null || mb < 0) return "-";
  if (mb < 1024) return mb + " MB";
  return (mb / 1024).toFixed(1) + " GB";
}

function renderPoolStatus(panel, model) {
  const pool = model.get("pool_status") || {};
  const hasData = pool.total_slots || pool.total_cpus || pool.machines;
  panel.style("display", hasData ? "flex" : "none");
  if (!hasData) return;

  panel.html("");

  panel.append("span").attr("class", "wfviz-pool-title").text("Pool Resources");

  if (pool.machines != null) {
    panel.append("span").attr("class", "wfviz-pool-stat")
      .html(`<span class="wfviz-pool-label">Machines</span><span class="wfviz-pool-value">${pool.machines}</span>`);
  }

  if (pool.total_slots) {
    const claimed = pool.claimed_slots || 0;
    panel.append("span").attr("class", "wfviz-pool-stat")
      .html(`<span class="wfviz-pool-label">Slots</span><span class="wfviz-pool-value">${claimed}/${pool.total_slots} <small>claimed</small></span>`);
  }

  if (pool.total_cpus) {
    const idle = pool.idle_cpus || 0;
    panel.append("span").attr("class", "wfviz-pool-stat")
      .html(`<span class="wfviz-pool-label">CPUs</span><span class="wfviz-pool-value">${idle}/${pool.total_cpus} <small>idle</small></span>`);
  }

  if (pool.total_memory_mb != null) {
    panel.append("span").attr("class", "wfviz-pool-stat")
      .html(`<span class="wfviz-pool-label">Memory</span><span class="wfviz-pool-value">${fmtMemMB(pool.idle_memory_mb)} / ${fmtMemMB(pool.total_memory_mb)} <small>idle</small></span>`);
  }

  if (pool.total_gpus && pool.total_gpus > 0) {
    const idleGpus = pool.idle_gpus || 0;
    panel.append("span").attr("class", "wfviz-pool-stat")
      .html(`<span class="wfviz-pool-label">GPUs</span><span class="wfviz-pool-value">${idleGpus}/${pool.total_gpus} <small>idle</small></span>`);
  }

  if (pool.load_avg != null) {
    panel.append("span").attr("class", "wfviz-pool-stat")
      .html(`<span class="wfviz-pool-label">Load</span><span class="wfviz-pool-value">${pool.load_avg.toFixed(1)}</span>`);
  }

  if (pool.os_arch) {
    panel.append("span").attr("class", "wfviz-pool-stat")
      .html(`<span class="wfviz-pool-label">Platform</span><span class="wfviz-pool-value">${pool.os_arch}</span>`);
  }
}

// ── Diagnostics Panel ──────────────────────────────────────────────────────

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function renderDiagnostics(panel, model) {
  const diag = model.get("diagnostics") || {};
  const holds = diag.holds || [];
  const failures = diag.failures || [];
  const idle = diag.idle;
  const stallState = diag.stall_state || "ok";
  const has = diag.available || diag.active || holds.length || failures.length || idle || stallState === "stalled";
  panel.style("display", has ? "block" : "none");
  if (!has) return;

  const badgeColor = stallState === "stalled" ? "#dc2626"
    : stallState === "suspect" ? "#d97706" : "#16a34a";
  const badgeLabel = stallState === "stalled" ? "STALLED"
    : stallState === "suspect" ? "Suspect" : "Healthy";

  let html = '<div class="wfviz-diag-header">'
    + '<span class="wfviz-diag-title">Diagnostics</span>'
    + `<span class="wfviz-diag-badge" style="background:${badgeColor}">${badgeLabel}</span>`;
  if (diag.active) {
    html += '<span class="wfviz-diag-sub">monitor --diagnose engine active</span>';
  }
  html += '</div>';

  if (stallState === "stalled" && diag.stall_reason) {
    html += `<div class="wfviz-diag-stall"><b>Stall reason:</b> ${escapeHtml(diag.stall_reason)}</div>`;
  }

  if (idle) {
    html += '<div class="wfviz-diag-section">Idle Diagnosis</div>';
    const headBits = [];
    if (idle.idle_job_count != null) headBits.push(`${idle.idle_job_count} idle jobs`);
    if (idle.pool_total_cpus != null) headBits.push(`pool: ${idle.pool_idle_cpus}/${idle.pool_total_cpus} CPUs idle`);
    if (headBits.length) html += `<div class="wfviz-diag-line">${escapeHtml(headBits.join(" — "))}</div>`;
    (idle.findings || []).slice(0, 6).forEach(f => {
      html += `<div class="wfviz-diag-line">• ${escapeHtml(f)}</div>`;
    });
    (idle.suggestions || []).slice(0, 6).forEach(s => {
      html += `<div class="wfviz-diag-line wfviz-diag-suggest">→ ${escapeHtml(s)}</div>`;
    });
  }

  function entries(label, color, items) {
    if (!items || !items.length) return "";
    let h = `<div class="wfviz-diag-section" style="color:${color}">${label} (${items.length})</div>`;
    items.slice(-5).forEach(it => {
      h += '<details class="wfviz-diag-entry"><summary>'
        + `<b>${escapeHtml(it.job_name || "")}</b> — ${escapeHtml(it.summary || "")}</summary>`;
      if (it.reason) h += `<div class="wfviz-diag-reason">${escapeHtml(it.reason)}</div>`;
      (it.suggestions || []).slice(0, 5).forEach(s => {
        h += `<div class="wfviz-diag-line wfviz-diag-suggest">→ ${escapeHtml(s)}</div>`;
      });
      h += '</details>';
    });
    return h;
  }
  html += entries("Held Jobs", "#9333ea", holds);
  html += entries("Failed Jobs", "#dc2626", failures);

  if (!idle && !holds.length && !failures.length && stallState !== "stalled") {
    html += '<div class="wfviz-diag-line" style="color:#64748b">No issues detected. Engine is monitoring.</div>';
  }

  panel.html(html);
}

// ── Placeholder (no workflow loaded) ────────────────────────────────────────

function showPlaceholder(viewport, model) {
  viewport.selectAll("*").remove();
  const ph = viewport.append("div").attr("class", "wfviz-placeholder");
  ph.append("div").attr("class", "wfviz-placeholder-icon").text("\u2b22");
  ph.append("div").attr("class", "wfviz-placeholder-text").text("No workflow loaded");

  const row = ph.append("div").style("display", "flex").style("gap", "8px").style("align-items", "center");
  const input = row.append("input")
    .attr("class", "wfviz-file-input")
    .attr("type", "text")
    .attr("placeholder", "Enter path to workflow.yml...");
  row.append("button")
    .attr("class", "wfviz-btn wfviz-btn-success")
    .text("Load")
    .on("click", () => {
      const path = input.property("value").trim();
      if (path) model.send({ action: "set_workflow_path", path });
    });
}

// ── Main render function ────────────────────────────────────────────────────

function render({ model, el }) {
  const container = d3.select(el);
  container.html("");
  container.classed("wfviz-container", true);

  // Toolbar
  const toolbar = container.append("div").attr("class", "wfviz-toolbar");
  buildToolbar(toolbar, model);

  // Workflow info bar
  const infoBar = container.append("div").attr("class", "wfviz-info-bar");
  renderInfoBar(infoBar, model);

  // DAG viewport
  const viewport = container.append("div").attr("class", "wfviz-dag-viewport");

  // Tooltip
  const tooltip = container.append("div").attr("class", "wfviz-tooltip");

  // Pool resources panel
  const poolPanel = container.append("div").attr("class", "wfviz-pool-panel");
  renderPoolStatus(poolPanel, model);

  // Diagnostics panel (workflow-monitor --diagnose sidecar)
  const diagPanel = container.append("div").attr("class", "wfviz-diag-panel");
  renderDiagnostics(diagPanel, model);

  // Workflow synopsis panel
  const statsPanel = container.append("div").attr("class", "wfviz-stats-panel");
  renderWorkflowStats(statsPanel, model);

  // Event log panel
  const eventPanel = container.append("div").attr("class", "wfviz-event-panel");

  // State
  let currentZoom = d3.zoomIdentity;
  let zoomInitialized = false;
  let currentZoomBehavior = null;
  let currentDagreGraph = null;
  const expandedJobs = new Set();

  function update() {
    const graphData = model.get("graph_data");
    const jobStates = model.get("job_states") || {};
    const eventLog = model.get("event_log") || [];
    const colors = model.get("state_colors") || DEFAULT_COLORS;
    const showFiles = model.get("show_files");

    // Update toolbar, info bar, pool panel, and stats panel
    buildToolbar(toolbar, model);
    renderInfoBar(infoBar, model);
    renderPoolStatus(poolPanel, model);
    renderDiagnostics(diagPanel, model);
    renderWorkflowStats(statsPanel, model);

    // If no graph data, show placeholder
    if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
      showPlaceholder(viewport, model);
      return;
    }

    // Build layout
    const g = buildDagreGraph(graphData, showFiles);
    currentDagreGraph = g;
    const graphMeta = g.graph();

    // Ensure SVG exists
    let svg = viewport.select("svg");
    if (svg.empty()) {
      viewport.selectAll("*").remove();
      svg = viewport.append("svg");
      svg.append("defs");
      svg.append("g").attr("class", "dag-content");

      // Zoom controls — use functions to access current zoom/graph state
      const zoomControls = viewport.append("div").attr("class", "wfviz-zoom-controls");
      zoomControls.append("button").attr("class", "wfviz-zoom-btn").text("+")
        .on("click", () => { if (currentZoomBehavior) svg.transition().duration(300).call(currentZoomBehavior.scaleBy, 1.3); });
      zoomControls.append("button").attr("class", "wfviz-zoom-btn").text("\u2013")
        .on("click", () => { if (currentZoomBehavior) svg.transition().duration(300).call(currentZoomBehavior.scaleBy, 0.7); });
      zoomControls.append("button").attr("class", "wfviz-zoom-btn").text("\u25ce")
        .on("click", () => { if (currentZoomBehavior && currentDagreGraph) fitToView(svg, currentDagreGraph, currentZoomBehavior); });

      // Legend
      const legend = viewport.append("div").attr("class", "wfviz-legend");
      renderLegend(d3.select(legend.node()), colors);
    }

    // Set up zoom behavior (once, reuse across updates)
    if (!currentZoomBehavior) {
      currentZoomBehavior = d3.zoom()
        .scaleExtent([0.1, 4])
        .on("zoom", (event) => {
          svg.select("g.dag-content").attr("transform", event.transform);
          currentZoom = event.transform;
        });
      svg.call(currentZoomBehavior);
    }

    // Fit to view only on first render
    if (!zoomInitialized && graphMeta.width && graphMeta.height) {
      fitToView(svg, g, currentZoomBehavior);
      zoomInitialized = true;
    }

    // Render DAG
    renderDAG(container, g, colors, jobStates, tooltip);

    // Render event log
    renderEventLog(eventPanel, eventLog, colors, expandedJobs, jobStates);
  }

  function fitToView(svg, g, zoom) {
    const graphMeta = g.graph();
    const vw = viewport.node().clientWidth || 800;
    const vh = viewport.node().clientHeight || 500;
    const gw = graphMeta.width || 400;
    const gh = graphMeta.height || 300;
    const scale = Math.min(vw / (gw + 60), vh / (gh + 60), 1.5);
    const tx = (vw - gw * scale) / 2;
    const ty = (gh * scale < vh) ? (vh - gh * scale) / 2 : 20;
    const t = d3.zoomIdentity.translate(tx, ty).scale(scale);
    svg.transition().duration(500).call(zoom.transform, t);
    currentZoom = t;
  }

  // Initial render
  update();

  // Watch for model changes
  model.on("change:graph_data", update);
  model.on("change:job_states", update);
  model.on("change:event_log", update);
  model.on("change:workflow_state", update);
  model.on("change:workflow_info", update);
  model.on("change:show_files", update);
  model.on("change:status_message", update);
  model.on("change:source_mode", update);
  model.on("change:source_detail", update);
  model.on("change:pool_status", update);
  model.on("change:workflow_stats", update);
  model.on("change:diagnostics", update);
}

export default { render };
