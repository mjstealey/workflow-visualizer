"""Parse a Pegasus workflow.yml into a graph structure for visualization."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _build_file_index(jobs: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Build a mapping from logical filename -> list of job ids that use it.

    Returns {lfn: [job_ids_that_produce_it]} for outputs, used to infer
    data-flow edges beyond what jobDependencies declares.
    """
    producers: Dict[str, List[str]] = {}
    for job in jobs:
        job_id = job.get("id", "")
        for use in job.get("uses", []):
            if use.get("type") == "output":
                lfn = use.get("lfn", "")
                if lfn:
                    producers.setdefault(lfn, []).append(job_id)
    return producers


class WorkflowGraph:
    """Parsed workflow graph ready for visualization."""

    def __init__(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
        metadata: Dict[str, Any],
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.metadata = metadata

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WorkflowGraph":
        """Parse a Pegasus workflow.yml file into a WorkflowGraph."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        wf_name = data.get("name", path.stem)
        pegasus_version = data.get("pegasus", "")

        raw_jobs = data.get("jobs", [])
        dependencies = data.get("jobDependencies", [])

        # Build nodes and collect file metadata
        nodes: List[Dict[str, Any]] = []
        file_meta: Dict[str, Dict[str, Any]] = {}
        for job in raw_jobs:
            inputs = []
            outputs = []
            for use in job.get("uses", []):
                lfn = use.get("lfn", "")
                utype = use.get("type", "")
                if utype == "input":
                    inputs.append(lfn)
                elif utype == "output":
                    outputs.append(lfn)
                # Capture per-file metadata
                if lfn and lfn not in file_meta:
                    meta: Dict[str, Any] = {"lfn": lfn, "type": utype}
                    if "size" in use:
                        meta["size"] = use["size"]
                    if use.get("stageOut") is not None:
                        meta["stageOut"] = use["stageOut"]
                    if use.get("registerReplica") is not None:
                        meta["registerReplica"] = use["registerReplica"]
                    if use.get("namespace"):
                        meta["namespace"] = use["namespace"]
                    if use.get("version"):
                        meta["version"] = use["version"]
                    file_meta[lfn] = meta

            nodes.append({
                "id": job.get("id", ""),
                "name": job.get("name", ""),
                "nodeLabel": job.get("nodeLabel", job.get("id", "")),
                "type": job.get("type", "job"),
                "arguments": job.get("arguments", []),
                "inputs": inputs,
                "outputs": outputs,
                "profiles": job.get("profiles", {}),
            })

        # Build edges from jobDependencies
        edges: List[Dict[str, str]] = []
        for dep in dependencies:
            parent_id = dep.get("id", "")
            for child_id in dep.get("children", []):
                edges.append({"source": parent_id, "target": child_id})

        metadata = {
            "name": wf_name,
            "pegasus_version": str(pegasus_version),
            "file_meta": file_meta,
        }

        return cls(nodes=nodes, edges=edges, metadata=metadata)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict for the widget traitlet."""
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "metadata": self.metadata,
        }

    @classmethod
    def from_events(
        cls, jobs: Dict[int, Dict[str, Any]]
    ) -> "WorkflowGraph":
        """Build a graph from JSONL event data when no workflow.yml is available.

        Args:
            jobs: Dict mapping job_id -> {exec_job_id, type_desc, ...}
        """
        nodes: List[Dict[str, Any]] = []
        for jid, js in sorted(jobs.items()):
            nodes.append({
                "id": str(jid),
                "name": js.get("exec_job_id", ""),
                "nodeLabel": js.get("exec_job_id", ""),
                "type": "job",
                "type_desc": js.get("type_desc", "compute"),
                "arguments": [],
                "inputs": [],
                "outputs": [],
                "profiles": {},
            })

        return cls(
            nodes=nodes,
            edges=[],
            metadata={"name": "workflow", "pegasus_version": ""},
        )
