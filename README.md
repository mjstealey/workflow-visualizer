# Workflow Visualizer

A Pegasus workflow visualizer that runs natively in JupyterHub notebooks, providing interactive DAG rendering, real-time workflow state visualization, and lifecycle controls. Supports local and remote (SSH) event consumption from [workflow-monitor](https://github.com/pegasusai/workflow-monitor).

## Source Modes

The widget toolbar displays a badge indicating the active data source:

| Mode | Badge | Description |
|---|---|---|
| **Static** | `STATIC` (gray) | DAG structure only — no live event feed |
| **Live** | `LIVE` (green, pulsing) | Polling a local `workflow-events.jsonl` file |
| **SSH** | `SSH` (purple, pulsing) | Fetching events from a remote host over SSH |

The mode is set automatically based on the parameters provided at initialization. Hovering over the badge shows the data source path (Live) or remote host (SSH).

## Features

- **Interactive DAG rendering** from Pegasus `workflow.yml` files
- **Pure SVG fallback** — works on classic Jupyter Notebook behind reverse proxies (e.g., ACCESS Open OnDemand) where anywidget cannot load
- **Real-time state visualization** with UML-style state machine coloring for nodes and edges
- **State-aware edges** — edges reflect workflow progress: light gray (pending), cyan (running), dark slate (complete)
- **File data flow** — toggle data file nodes to see inputs/outputs between compute jobs, with automatic grouping for complex workflows
- **File state inference** — data file nodes are colored by their inferred state (pending, staging, available, in use, failed)
- **Workflow header** — displays workflow name, state, job progress (N/M done), elapsed time, and Pegasus version
- **Pool resources panel** — live HTCondor pool status: machines, slots (claimed/idle), CPUs, memory, GPUs, load average, and platform
- **Diagnostics panel** — surfaces stall detection, idle-job analysis, and per-job hold/failure remediation suggestions emitted by `workflow-monitor --diagnose` to the `diagnostics-events.jsonl` sidecar
- **HTCondor job metrics** — resource requests (CPUs, memory, disk, GPUs), queue wait time, restart count, transfer I/O, and accounting group per job
- **Post-completion metrics** — CPU time (user/sys), wall clock time, peak memory, disk usage, transfer bytes, and remote host from `condor_history`
- **Derived efficiency metrics** — CPU efficiency (CPU time / wall time) and memory efficiency (peak usage / requested) per job
- **Event log display** — grouped by job with expandable state history, resource metrics, efficiency indicators, and job metadata
- **Hover tooltips** showing full metadata for job nodes including resource requests, efficiency metrics, transfer I/O, queue wait, and remote host
- **Helper methods** — `show()`, `watch()`, and `summary()` for flexible rendering in SVG fallback mode
- **Workflow lifecycle controls** — plan, start, stop, resume via Pegasus CLI
- **Workflow-monitor integration** — start/stop the monitor serve function
- **Remote SSH support** — consume `workflow-events.jsonl` and fetch `workflow.yml` from a remote Pegasus submit node
- **Fallback graph construction** — builds DAG from event data when no `workflow.yml` is available

## Requirements

- Python >= 3.10
- Pegasus WMS 5.x
- HTCondor (minicondor for local development)
- JupyterLab >= 4.0 or classic Jupyter Notebook

## Installation

```bash
# Clone the repository
git clone https://github.com/pegasusai/workflow-visualizer.git
cd workflow-visualizer

# Install with uv
uv sync

# Or install with pip
pip install -e .

# Install with development dependencies
uv sync --extra dev
```

### Installing a Jupyter Kernel

To make `workflow-visualizer` available as a kernel option in JupyterLab or Jupyter Notebook (including managed environments like ACCESS Open OnDemand), register the project's virtual environment as a Jupyter kernel:

```bash
cd /path/to/workflow-visualizer

# Create the venv and install the package
uv sync

# Install ipykernel into the venv
uv pip install ipykernel

# Register the kernel (--user installs to ~/.local/share/jupyter/kernels/)
uv run python -m ipykernel install --user --name workflow-visualizer --display-name "workflow-visualizer"
```

After registration, restart Jupyter and select **workflow-visualizer** from the kernel dropdown. To verify:

```bash
jupyter kernelspec list
```

To unregister the kernel later:

```bash
jupyter kernelspec remove workflow-visualizer
```

## Quick Start

### Static DAG from workflow.yml

```python
from workflow_visualizer import WorkflowVisualizerWidget

w = WorkflowVisualizerWidget(
    workflow_path="path/to/workflow.yml",
)
w
```

### Live workflow monitoring (local)

```python
from workflow_visualizer import WorkflowVisualizerWidget

w = WorkflowVisualizerWidget(
    workflow_path="path/to/workflow.yml",
    jsonl_path="path/to/workflow-events.jsonl",
    submit_dir="path/to/submit-dir",
    poll_interval=2.0,
)
w
```

### Live workflow monitoring (remote via SSH)

When `remote_spec` is provided, both `workflow_path` and the JSONL event file refer to paths **on the remote host**. The widget fetches `workflow.yml` via SSH at startup and then polls the JSONL file incrementally.

```python
from workflow_visualizer import WorkflowVisualizerWidget

w = WorkflowVisualizerWidget(
    workflow_path="/home/ubuntu/my-workflow/workflow.yml",
    remote_spec="user@host:/home/ubuntu/my-workflow/user/pegasus/wf/run0001/workflow-events.jsonl",
    ssh_config="~/.ssh/config",
    ssh_identity="~/.ssh/id_rsa",
    poll_interval=5.0,
)
w
```

#### Remote monitoring with FABRIC testbed

FABRIC nodes are accessed through a bastion host. Create an SSH config that handles the proxy:

```
# ~/.ssh/fabric-ssh-config

UserKnownHostsFile /dev/null
StrictHostKeyChecking no
ServerAliveInterval 120

Host bastion.fabric-testbed.net
    User <your-fabric-username>
    IdentityFile ~/.ssh/fabric-bastion-key
    ForwardAgent yes

Host pegasus-submit
    User ubuntu
    HostName <submit-node-ipv6>
    ProxyJump bastion.fabric-testbed.net
    IdentityFile ~/.ssh/my-sliver-key
```

Then connect using either the host alias or the IPv6 address directly:

```python
# Option A: SSH config host alias (recommended)
w = WorkflowVisualizerWidget(
    workflow_path="/home/ubuntu/my-workflow/workflow.yml",
    remote_spec="pegasus-submit:/home/ubuntu/my-workflow/ubuntu/pegasus/wf/run0001/workflow-events.jsonl",
    ssh_config="~/.ssh/fabric-ssh-config",
    ssh_identity="~/.ssh/my-sliver-key",
    poll_interval=5.0,
)

# Option B: IPv6 address (wrap in brackets)
w = WorkflowVisualizerWidget(
    workflow_path="/home/ubuntu/my-workflow/workflow.yml",
    remote_spec="ubuntu@[2001:db8::1]:/home/ubuntu/my-workflow/ubuntu/pegasus/wf/run0001/workflow-events.jsonl",
    ssh_config="~/.ssh/fabric-ssh-config",
    ssh_identity="~/.ssh/my-sliver-key",
    poll_interval=5.0,
)
```

> **Note:** Ensure `workflow-monitor` is serving on the remote submit node before connecting:
> ```bash
> ssh pegasus-submit "uv run workflow-monitor --serve /home/ubuntu/my-workflow"
> ```

## ACCESS Pegasus (Open OnDemand)

The ACCESS Pegasus testbed at `pegasus.access-ci.org` runs classic Jupyter Notebook behind a reverse proxy. The anywidget JavaScript frontend cannot load in this environment (the proxy serves `anywidget.js` with the wrong MIME type, and `X-Content-Type-Options: nosniff` blocks execution). The visualizer automatically falls back to a **pure SVG rendering** computed entirely server-side in Python — no JavaScript, no external imports.

### How it works

1. `_repr_mimebundle_()` tries the anywidget comm channel first
2. If the widget MIME type is rejected as untrusted (classic Notebook) or anywidget.js fails to load (reverse proxy), it falls back to `text/html`
3. The HTML fallback is a self-contained SVG with a workflow header, DAG graph, and event log table — all generated in Python
4. Since there is no JavaScript involved, classic Notebook's HTML sanitizer does not strip any content

### Setup on ACCESS Pegasus

```bash
# SSH into the ACCESS Pegasus submit node
ssh mstealey@pegasus.access-ci.org

# Clone and install
cd ~
git clone https://github.com/pegasusai/workflow-visualizer.git
cd workflow-visualizer
uv sync
uv pip install ipykernel
uv run python -m ipykernel install --user --name workflow-visualizer --display-name "workflow-visualizer"
```

Then in the ACCESS JupyterHub:

1. Open or create a notebook
2. Select the **workflow-visualizer** kernel from the kernel dropdown
3. Use the widget as normal — the SVG fallback is automatic

### Helper Methods for SVG Mode

Since the SVG fallback is static (no live comm channel), helper methods provide interactivity:

#### `w.show()` — Re-render with options

```python
w.show()                  # toggle show_files on/off
w.show(show_files=True)   # show data file nodes
w.show(show_files=False)  # hide data file nodes
```

Renders the DAG SVG, workflow header, and event log table inline. Forces a synchronous event poll before rendering so the display is always up-to-date.

#### `w.watch()` — Auto-refresh display

```python
w.watch()                              # refresh at poll_interval rate
w.watch(interval=5)                    # refresh every 5 seconds
w.watch(show_files=True, interval=3)   # with file nodes, every 3 seconds
```

Uses `clear_output` + re-display to provide pseudo-live updates. Shows workflow state, progress, and event log. Auto-stops when the workflow reaches a terminal state. Press **Ctrl-C** (interrupt kernel) to stop manually.

#### `w.summary()` — Text overview

```python
w.summary()
# Workflow:  crophealth
# Pegasus:   5.1.3-dev.0
# Jobs:      2
# Edges:     1
# Inputs:    3
# Outputs:   4
```

### Known Limitations in SVG Mode

- **No interactive zoom/pan** — the SVG scales to fit the cell output width via `viewBox`
- **No live trait updates** — use `w.show()` or `w.watch()` to refresh
- **No interactive controls** — plan/start/stop/resume buttons require the anywidget comm channel
- **Console errors** — anywidget still attempts to load its JS frontend; these errors are harmless and do not affect the SVG rendering

## Usage

### Widget Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workflow_path` | `str` | `None` | Path to Pegasus `workflow.yml` (local path, or remote path when using `remote_spec`) |
| `jsonl_path` | `str` | `None` | Path to local `workflow-events.jsonl` |
| `remote_spec` | `str` | `None` | SSH spec: `user@host:/path/to/workflow-events.jsonl` |
| `submit_dir` | `str` | `None` | Pegasus submit directory (enables lifecycle controls) |
| `poll_interval` | `float` | `2.0` | Seconds between event polls |
| `ssh_config` | `str` | `None` | Path to SSH config file |
| `ssh_identity` | `str` | `None` | Path to SSH identity key |
| `show_files` | `bool` | `False` | Show data file nodes in the DAG (inputs/outputs between jobs) |

### Workflow Controls

When `submit_dir` is provided, the widget exposes control buttons (requires anywidget frontend):

- **Plan** — runs `pegasus-plan` to generate the executable workflow
- **Start** — runs `pegasus-run` to submit the workflow
- **Stop** — runs `pegasus-remove` to halt the workflow
- **Resume** — runs `pegasus-run` to resume a stopped workflow
- **Monitor Start** — starts the `workflow-monitor` serve process
- **Monitor Stop** — stops the `workflow-monitor` serve process

### Job State Colors

The visualizer uses UML-style state machine colors:

| State | Color | Description |
|---|---|---|
| Unsubmitted | Grey | Job has not been submitted |
| Queued | Yellow | Job is queued for execution |
| Pre-script | Light Blue | Pre-script is running |
| Running | Cyan | Job is actively executing (animated pulse in widget mode) |
| Post-script | Light Blue | Post-script is running |
| Success | Green | Job completed successfully |
| Failed | Red | Job failed |
| Held | Purple | Job is held |

### Edge Colors

Edges between nodes reflect the state of the data flow:

| Source State | Target State | Edge Color | Description |
|---|---|---|---|
| SUCCESS | SUCCESS | Dark slate | Both endpoints complete |
| SUCCESS | not done | Dark slate (faded) | Source done, target pending |
| RUNNING | any | Cyan | Data actively flowing |
| FAILED | any | Red | Upstream failure |
| QUEUED | any | Amber | Source queued |
| UNSUBMITTED | any | Light gray | Not yet active |

### Data File Nodes

When `show_files=True`, data file nodes appear between compute jobs showing the data flow. For complex workflows with many files:

- Files sharing the same producer and consumer set are **automatically grouped** into aggregate nodes (e.g., "38 files")
- Hover over aggregate nodes to see sample filenames
- File nodes are color-coded by inferred state: pending (gray), staging (blue), available (green), in use (cyan), failed (red)
- The grouping threshold is 3 files — routes with 3 or fewer files show individual nodes

### Pool Resources Panel

When the workflow-monitor emits `pool_status` events (Tier 4), a Pool Resources panel appears showing live HTCondor pool information:

| Metric | Description |
|---|---|
| Machines | Number of unique machines in the pool |
| Slots | Claimed / total slots |
| CPUs | Idle / total CPU cores |
| Memory | Idle / total memory |
| GPUs | Idle / total GPUs (shown only if GPUs are available) |
| Load Avg | System load average across the pool |
| Platform | Operating system and architecture |

The panel is shown in both anywidget mode (as a bar below the DAG viewport) and SVG fallback mode.

### HTCondor Job Metrics

When the workflow-monitor emits `htcondor_poll` (Tier 1-2), `htcondor_history` (Tier 3), or `pool_status` (Tier 4) events, additional per-job metrics are available in tooltips and the event log:

**Resource Requests (Tier 1):**
- CPU cores, memory, disk, GPUs requested
- Job restart count (preemption/eviction)
- Accounting group

**Transfer I/O (Tier 2):**
- Bytes sent/received during file transfer
- Declared input size
- Queue wait time (time from submission to execution start)

**Post-Completion Metrics (Tier 3):**
- Wall clock time, user CPU time, system CPU time
- Peak memory usage (ImageSize), disk usage
- Remote host that executed the job
- Transfer bytes (final totals)

**Derived Efficiency Metrics:**
- **CPU efficiency** — `(user CPU + sys CPU) / (wall time × requested CPUs)` — indicates how well the job utilized allocated CPU
- **Memory efficiency** — `peak memory / requested memory` — indicates how well the job utilized allocated memory

These metrics appear in:
- **Node tooltips** (hover over a job node in the DAG)
- **Event log detail rows** (click to expand a job in the event log)

### Diagnostics Panel

When the workflow-monitor is launched with the `--diagnose` flag it writes an
additional `diagnostics-events.jsonl` sidecar next to the main event log. The
visualizer auto-detects this file (sibling of `jsonl_path` locally, or fetched
from the same remote directory in SSH mode) and renders a **Diagnostics**
panel containing:

| Section | Source events | Description |
|---|---|---|
| Health badge | `stall_detected` / `stall_resolved` | `Healthy` / `Suspect` / `STALLED` indicator with stall reason |
| Idle Diagnosis | `idle_diagnosis` | Findings, suggestions, and pool capacity context for stalled idle queues |
| Held Jobs | `hold_diagnosis` | Per-job summary, raw HoldReason, and remediation suggestions |
| Failed Jobs | `failure_diagnosis` | Per-job failure summary, reason, and remediation suggestions |

The panel renders identically in both the D3/anywidget mode and the pure-SVG
fallback. To enable diagnostics, start the monitor with `--diagnose`:

```bash
ssh pegasus-submit "uv run workflow-monitor --serve --diagnose /home/ubuntu/my-workflow"
```

Per-job hold/failure diagnoses are also attached to the corresponding entries
in `job_states` (under `diagnosis`) and surfaced in tooltips and event-log
detail rows.

### Polling and Cleanup

Polling starts automatically when a JSONL source is provided and stops when a `workflow_end` event is received. To manually control polling:

```python
w.start_polling()
w.stop_polling()
```

Always close the widget when done to clean up resources (especially for remote SSH connections):

```python
w.close()
```

## Architecture

```
workflow.yml ──→ parser.py ──→ WorkflowGraph (nodes + edges)
  (local or          │
   via SSH)          ▼
workflow-events.jsonl ──→ events.py ──→ EventConsumer ──→ job states + event log
  (local or                  │                           + pool status
   via SSH)                  │                                 │
         └──→ RemoteEventConsumer                    widget.py (anywidget)
                 (fetch_file +                            │
                  incremental sync)       ┌───────────┬───┼─────────┬────────┐
                                          ▼           ▼   ▼         ▼        ▼
                                    DAG render   Pool panel  Event   Controls
                                   (state.py)    (Tier 4)   table  (controls.py)

Event types consumed:
  workflow_start   → workflow metadata
  jobs_init        → job roster
  workflow_state   → workflow lifecycle
  job_state        → per-job state transitions
  htcondor_poll    → live ClassAd metrics (Tier 1-2)
  htcondor_history → post-completion metrics (Tier 3)
  pool_status      → pool resources (Tier 4)
  workflow_end     → final summary

Diagnostics sidecar (workflow-monitor --diagnose):
  diagnostics-events.jsonl
    diag_start / diag_end          → engine lifecycle
    stall_detected / stall_resolved → workflow stall state
    idle_diagnosis                 → idle-job analysis (findings/suggestions)
    hold_diagnosis                 → per-job hold remediation
    failure_diagnosis              → per-job failure remediation
    diag_error                     → engine error report

SVG Fallback Path (classic Notebook / ACCESS):
  widget.py → _render_dag_svg()      → pure SVG (Python-side layout)
            → _render_header()       → workflow info bar (HTML)
            → _render_pool_status()  → pool resources panel (HTML)
            → _render_event_table()  → grouped event log (HTML <details>)
```

### Modules

| Module | Purpose |
|---|---|
| `parser.py` | Parses `workflow.yml` into a graph of nodes and edges |
| `state.py` | Maps Pegasus job states to display categories, UML colors, and formatting helpers |
| `events.py` | Consumes JSONL event logs (local or SSH) with incremental polling; handles `htcondor_poll`, `htcondor_history`, `pool_status`, `workflow_stats`, and the `diagnostics-events.jsonl` sidecar |
| `controls.py` | Subprocess wrappers for Pegasus and workflow-monitor CLI commands |
| `widget.py` | AnyWidget integration with pure SVG fallback for classic Notebook |

## Development

This project uses [just](https://github.com/casey/just) as a task runner. Install it with `brew install just` (macOS) or see the [just installation docs](https://github.com/casey/just#installation).

### Running JupyterLab

Always launch JupyterLab from the project root using the justfile. This ensures JupyterLab uses the project's `.venv` (so all packages, extensions, and the kernel share the same environment) and sets the notebook directory to the project root:

```bash
cd /path/to/workflow-visualizer
just lab
```

This runs `uv run jupyter lab --notebook-dir=.`, which:
- Activates the project's `.venv` via `uv run`
- Roots JupyterLab's file browser at the project directory
- Makes the default kernel the correct one (no manual kernel registration needed)
- Ensures the JupyterLab terminal also uses the project's Python

### Available recipes

```bash
just            # List all available recipes
just install    # Install all dependencies (including dev)
just lab        # Launch JupyterLab rooted at the project directory
just test       # Run the test suite
just test -v    # Run tests with verbose output
just lint       # Run linting (ruff + black)
```

## Demo

A demo notebook is provided at `notebooks/demo.ipynb` showing all four usage modes:

1. **Static** — DAG rendering from a local `workflow.yml`
2. **Live** — DAG with real-time event updates from a local JSONL file
3. **SSH** — Remote workflow monitoring via SSH (with FABRIC testbed example)
4. **Placeholder** — Dynamic file selection at runtime

```bash
just lab
# Then open notebooks/demo.ipynb from the file browser
```

## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
