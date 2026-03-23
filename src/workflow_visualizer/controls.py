"""Subprocess wrappers for Pegasus and workflow-monitor CLI commands."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Optional


class WorkflowControls:
    """Execute Pegasus workflow lifecycle commands."""

    def __init__(self, submit_dir: Optional[str | Path] = None) -> None:
        self._submit_dir = Path(submit_dir) if submit_dir else None

    def _run(self, cmd: list[str], cwd: Optional[Path] = None) -> Dict[str, str]:
        """Run a command and return {status, stdout, stderr}."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(cwd) if cwd else None,
            )
            return {
                "status": "ok" if result.returncode == 0 else "error",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": str(result.returncode),
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "stdout": "",
                "stderr": f"Command not found: {cmd[0]}",
                "returncode": "-1",
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "stdout": "",
                "stderr": "Command timed out",
                "returncode": "-1",
            }

    def plan(self, dax_file: str, **kwargs: str) -> Dict[str, str]:
        """Run pegasus-plan on the given DAX file."""
        cmd = ["pegasus-plan", dax_file]
        for k, v in kwargs.items():
            cmd.extend([f"--{k}", v])
        return self._run(cmd)

    def run(self, submit_dir: Optional[str] = None) -> Dict[str, str]:
        """Run pegasus-run on the submit directory."""
        sd = submit_dir or (str(self._submit_dir) if self._submit_dir else None)
        if not sd:
            return {"status": "error", "stdout": "", "stderr": "No submit_dir specified", "returncode": "-1"}
        return self._run(["pegasus-run", sd])

    def stop(self, submit_dir: Optional[str] = None) -> Dict[str, str]:
        """Run pegasus-remove to stop the workflow."""
        sd = submit_dir or (str(self._submit_dir) if self._submit_dir else None)
        if not sd:
            return {"status": "error", "stdout": "", "stderr": "No submit_dir specified", "returncode": "-1"}
        return self._run(["pegasus-remove", sd])

    def resume(self, submit_dir: Optional[str] = None) -> Dict[str, str]:
        """Run pegasus-run to resume the workflow."""
        sd = submit_dir or (str(self._submit_dir) if self._submit_dir else None)
        if not sd:
            return {"status": "error", "stdout": "", "stderr": "No submit_dir specified", "returncode": "-1"}
        return self._run(["pegasus-run", sd])

    def monitor_start(self, submit_dir: Optional[str] = None) -> Dict[str, str]:
        """Start the workflow-monitor server."""
        sd = submit_dir or (str(self._submit_dir) if self._submit_dir else None)
        if not sd:
            return {"status": "error", "stdout": "", "stderr": "No submit_dir specified", "returncode": "-1"}
        return self._run(["workflow-monitor", "--serve", sd])

    def monitor_stop(self, submit_dir: Optional[str] = None) -> Dict[str, str]:
        """Stop the workflow-monitor server."""
        sd = submit_dir or (str(self._submit_dir) if self._submit_dir else None)
        if not sd:
            return {"status": "error", "stdout": "", "stderr": "No submit_dir specified", "returncode": "-1"}
        return self._run(["workflow-monitor", "--stop-server", sd])
