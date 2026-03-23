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
    if (jobState.cpu_time) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">CPU Time</span><span class="wfviz-tooltip-val">${jobState.cpu_time}</span></div>`;
    if (jobState.request_cpus) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">CPUs</span><span class="wfviz-tooltip-val">${jobState.request_cpus}</span></div>`;
    if (jobState.request_memory) html += `<div class="wfviz-tooltip-row"><span class="wfviz-tooltip-key">Req. Mem</span><span class="wfviz-tooltip-val">${jobState.request_memory} MB</span></div>`;
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

function renderEventLog(panel, eventLog, colors, expandedJobs) {
  // Ensure header exists
  let header = panel.select(".wfviz-event-header");
  if (header.empty()) {
    header = panel.append("div").attr("class", "wfviz-event-header").html(
      `<span class="wfviz-event-col wfviz-event-col-name">Job</span>` +
      `<span class="wfviz-event-col">State</span>` +
      `<span class="wfviz-event-col">Start</span>` +
      `<span class="wfviz-event-col">End</span>` +
      `<span class="wfviz-event-col">Duration</span>`
    );
  }

  // Store current render data so the click handler can re-render
  const panelNode = panel.node();
  panelNode.__wfviz_eventLog = eventLog;
  panelNode.__wfviz_colors = colors;

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
    const hasSubRows = group.transitions.length > 1;
    el.classed("expanded", isExpanded);

    // ── Primary row ──
    const primary = el.select(".wfviz-event-primary");
    const c = getColor(group.currentState, colors);
    const stateStyle = `background:${c.fill};color:${c.stroke};`;

    const chevron = hasSubRows
      ? `<span class="wfviz-event-chevron">${isExpanded ? "\u25BE" : "\u25B8"}</span>`
      : `<span class="wfviz-event-chevron-spacer"></span>`;
    const count = hasSubRows ? `<span class="wfviz-event-count">${group.transitions.length}</span>` : "";
    const diagIcon = group.holdReason ? `<span class="wfviz-event-diag-icon" title="${group.holdReason.replace(/"/g, '&quot;')}">&#x26A0;</span>` : "";

    primary.html(
      `<span class="wfviz-event-col wfviz-event-col-name" title="${group.execId}">${chevron}${group.key}${count}${diagIcon}</span>` +
      `<span class="wfviz-event-col"><span class="wfviz-event-state" style="${stateStyle}">${group.currentState}</span></span>` +
      `<span class="wfviz-event-col">${fmtTs(group.startTs)}</span>` +
      `<span class="wfviz-event-col">${fmtTs(group.endTs)}</span>` +
      `<span class="wfviz-event-col">${fmtDur(group.totalDuration)}</span>`
    );

    primary.classed("wfviz-event-expandable", hasSubRows);
    primary.attr("data-group-key", hasSubRows ? group.key : null);

    // ── Sub-rows ──
    const subsContainer = el.select(".wfviz-event-subs");
    subsContainer.style("display", isExpanded ? "block" : "none");
    subsContainer.selectAll("*").remove();

    if (isExpanded && hasSubRows) {
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
        // Show hold reason as a diagnostic row below the HELD transition
        if (tr.holdReason) {
          subsContainer.append("div")
            .attr("class", "wfviz-event-diag")
            .html(`<span class="wfviz-event-diag-text">${tr.holdReason}</span>`);
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

    // Update toolbar and info bar
    buildToolbar(toolbar, model);
    renderInfoBar(infoBar, model);

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
    renderEventLog(eventPanel, eventLog, colors, expandedJobs);
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
}

export default { render };
