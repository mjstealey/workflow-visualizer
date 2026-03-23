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
- **Real-time state visualization** with UML-style state machine coloring and pulse animations for running jobs
- **Event log display** with most-recent-first ordering (event name, state, timing)
- **Hover tooltips** showing full metadata for job nodes and edges
- **Workflow lifecycle controls** — plan, start, stop, resume via Pegasus CLI
- **Workflow-monitor integration** — start/stop the monitor serve function
- **Remote SSH support** — consume `workflow-events.jsonl` and fetch `workflow.yml` from a remote Pegasus submit node
- **Fallback graph construction** — builds DAG from event data when no `workflow.yml` is available

## Requirements

- Python >= 3.10
- Pegasus WMS 5.1.x
- HTCondor (minicondor for local development)
- JupyterLab >= 4.0

## Installation

```bash
# Clone the repository
git clone https://github.com/mjstealey/workflow-visualizer.git
cd workflow-visualizer

# Install with uv
uv sync

# Or install with pip
pip install -e .

# Install with development dependencies
uv sync --extra dev
```

## Quick Start

### Static DAG from workflow.yml

```python
from workflow_visualizer import WorkflowVisualizerWidget

widget = WorkflowVisualizerWidget(
    workflow_path="path/to/workflow.yml",
)
widget
```

### Live workflow monitoring (local)

```python
from workflow_visualizer import WorkflowVisualizerWidget

widget = WorkflowVisualizerWidget(
    workflow_path="path/to/workflow.yml",
    jsonl_path="path/to/workflow-events.jsonl",
    submit_dir="path/to/submit-dir",
    poll_interval=2.0,
)
widget
```

### Live workflow monitoring (remote via SSH)

When `remote_spec` is provided, both `workflow_path` and the JSONL event file refer to paths **on the remote host**. The widget fetches `workflow.yml` via SSH at startup and then polls the JSONL file incrementally.

```python
from workflow_visualizer import WorkflowVisualizerWidget

widget = WorkflowVisualizerWidget(
    workflow_path="/home/ubuntu/my-workflow/workflow.yml",
    remote_spec="user@host:/home/ubuntu/my-workflow/user/pegasus/wf/run0001/workflow-events.jsonl",
    ssh_config="~/.ssh/config",
    ssh_identity="~/.ssh/id_rsa",
    poll_interval=5.0,
)
widget
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
widget = WorkflowVisualizerWidget(
    workflow_path="/home/ubuntu/my-workflow/workflow.yml",
    remote_spec="pegasus-submit:/home/ubuntu/my-workflow/ubuntu/pegasus/wf/run0001/workflow-events.jsonl",
    ssh_config="~/.ssh/fabric-ssh-config",
    ssh_identity="~/.ssh/my-sliver-key",
    poll_interval=5.0,
)

# Option B: IPv6 address (wrap in brackets)
widget = WorkflowVisualizerWidget(
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

### Dynamic file selection (no paths at init)

```python
from workflow_visualizer import WorkflowVisualizerWidget

widget = WorkflowVisualizerWidget()
widget
```

This shows a dialog allowing you to choose the workflow definition and event files at runtime.

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

When `submit_dir` is provided, the widget exposes control buttons:

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
| Running | Cyan | Job is actively executing (animated pulse) |
| Post-script | Light Blue | Post-script is running |
| Success | Green | Job completed successfully |
| Failed | Red | Job failed |
| Held | Purple | Job is held |

### Polling and Cleanup

Polling starts automatically when a JSONL source is provided and stops when a `workflow_end` event is received. To manually control polling:

```python
widget.start_polling()
widget.stop_polling()
```

Always close the widget when done to clean up resources (especially for remote SSH connections):

```python
widget.close()
```

## Architecture

```
workflow.yml ──→ parser.py ──→ WorkflowGraph (nodes + edges)
  (local or          │
   via SSH)          ▼
workflow-events.jsonl ──→ events.py ──→ EventConsumer ──→ job states + event log
  (local or                                                      │
   via SSH)                                                      ▼
         └──→ RemoteEventConsumer                    widget.py (anywidget)
                 (fetch_file +                            │
                  incremental sync)       ┌───────────────┼─────────────┐
                                          ▼               ▼             ▼
                                    DAG render      Event table    Controls
                                   (state.py)                   (controls.py)
```

### Modules

| Module | Purpose |
|---|---|
| `parser.py` | Parses `workflow.yml` into a graph of nodes and edges |
| `state.py` | Maps Pegasus job states to display categories and UML colors |
| `events.py` | Consumes JSONL event logs (local or SSH) with incremental polling |
| `controls.py` | Subprocess wrappers for Pegasus and workflow-monitor CLI commands |
| `widget.py` | AnyWidget integration — syncs backend state to interactive frontend |

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
