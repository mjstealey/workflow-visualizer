"""Parse a Pegasus workflow.yml into a graph structure for visualization."""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


# Auxiliary (data-management) job name prefixes Pegasus injects during planning.
# These are typically not interesting to view individually.
_AUX_PREFIXES: Tuple[str, ...] = (
    "stage_in_",
    "stage_out_",
    "stage_worker_",
    "register_",
    "clean_up_",
    "cleanup_",
    "create_dir_",
    "chmod_",
)

# Trailing instance markers Pegasus appends when generating exec_job_ids.
# Stripped to recover the bare transformation name for grouping.
_ID_SUFFIX_RE = re.compile(r"_ID\d+$")
_NUM_SUFFIX_RE = re.compile(r"(?:_\d+){1,3}$")


def _strip_instance_suffix(name: str) -> str:
    """Reduce an exec-job name to its base transformation.

    Examples:
        mProject_ID0000327          -> mProject
        stage_in_remote_local_2_0   -> stage_in_remote_local
        merge_mDiffFit_PID2_xyz     -> merge_mDiffFit_PID2
        clean_up_local_level_3_0    -> clean_up_local_level
    """
    if not name:
        return name
    s = _ID_SUFFIX_RE.sub("", name)
    s = _NUM_SUFFIX_RE.sub("", s)
    return s


def _aux_prefix(name: str) -> Optional[str]:
    """Return the auxiliary-job category for ``name``, or None if not aux."""
    for p in _AUX_PREFIXES:
        if name.startswith(p):
            return p.rstrip("_")
    return None


def _topo_levels(node_ids: List[str], parents: Dict[str, set]) -> Dict[str, int]:
    """Assign each node its longest-path depth from a source. Robust to cycles
    (any unresolved nodes get the next level)."""
    level: Dict[str, int] = {}
    remaining = set(node_ids)
    current = 0
    while remaining:
        ready = [n for n in remaining if not (parents.get(n, set()) & remaining)]
        if not ready:
            ready = list(remaining)  # break cycles deterministically
        for n in ready:
            level[n] = current
            remaining.discard(n)
        current += 1
    return level


def _build_adjacency(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
) -> Tuple[Dict[str, set], Dict[str, set]]:
    parents: Dict[str, set] = defaultdict(set)
    children: Dict[str, set] = defaultdict(set)
    node_ids = {n["id"] for n in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in node_ids and t in node_ids:
            children[s].add(t)
            parents[t].add(s)
    return parents, children


def collapse_aux_jobs(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
    min_group: int = 2,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Fold Pegasus auxiliary jobs (stage_in/out, register, clean_up, ...)
    by (topological level, prefix) into single super-nodes.

    Compute jobs are passed through unchanged. Returns new (nodes, edges).
    """
    if not nodes:
        return nodes, edges

    parents, _children = _build_adjacency(nodes, edges)
    node_ids = [n["id"] for n in nodes]
    level = _topo_levels(node_ids, parents)

    # Bucket aux jobs by (level, prefix); leave compute jobs untouched.
    by_id = {n["id"]: n for n in nodes}
    buckets: Dict[Tuple[int, str], List[str]] = defaultdict(list)
    keep_ids: List[str] = []
    for n in nodes:
        nid = n["id"]
        prefix = _aux_prefix(n.get("name", ""))
        if prefix is None:
            keep_ids.append(nid)
            continue
        buckets[(level[nid], prefix)].append(nid)

    member_to_group: Dict[str, str] = {}
    new_nodes: List[Dict[str, Any]] = [by_id[i] for i in keep_ids]

    for (lvl, prefix), members in buckets.items():
        if len(members) < min_group:
            new_nodes.extend(by_id[m] for m in members)
            continue
        gid = f"auxgroup:{prefix}:L{lvl}"
        ins, outs = _union_io(by_id, members)
        new_nodes.append({
            "id": gid,
            "name": prefix,
            "nodeLabel": f"{prefix} ×{len(members)}",
            "type": "job",
            # type_desc must be "compute" so the JS frontend's isCompute()
            # filter renders the group node. _groupKind=="aux" is the marker
            # that survives for tooltip styling.
            "type_desc": "compute",
            "_isGroup": True,
            "_groupKind": "aux",
            "_members": list(members),
            "arguments": [],
            "inputs": ins,
            "outputs": outs,
            "profiles": {},
        })
        for m in members:
            member_to_group[m] = gid

    new_edges = _rewire_edges(edges, member_to_group)
    return new_nodes, new_edges


def collapse_siblings(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
    min_group: int = 3,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Fold isomorphic siblings — nodes with the same transformation name AND
    the same parent set AND the same child set — into one super-node.

    Returns new (nodes, edges).
    """
    if not nodes:
        return nodes, edges

    parents, children = _build_adjacency(nodes, edges)
    by_id = {n["id"]: n for n in nodes}

    groups: Dict[Tuple[str, frozenset, frozenset], List[str]] = defaultdict(list)
    for n in nodes:
        nid = n["id"]
        tname = _strip_instance_suffix(n.get("name", "") or n.get("id", ""))
        key = (tname, frozenset(parents.get(nid, set())),
               frozenset(children.get(nid, set())))
        groups[key].append(nid)

    member_to_group: Dict[str, str] = {}
    new_nodes: List[Dict[str, Any]] = []

    for (tname, ps, cs), members in groups.items():
        if len(members) < min_group:
            new_nodes.extend(by_id[m] for m in members)
            continue
        digest = f"{abs(hash((ps, cs))) & 0xfffffff:07x}"
        gid = f"jobgroup:{tname}:{digest}"
        first = by_id[members[0]]
        ins, outs = _union_io(by_id, members)
        new_nodes.append({
            "id": gid,
            "name": tname,
            "nodeLabel": f"{tname} ×{len(members)}",
            "type": first.get("type", "job"),
            "type_desc": first.get("type_desc", "compute"),
            "_isGroup": True,
            "_groupKind": "siblings",
            "_members": list(members),
            "arguments": [],
            "inputs": ins,
            "outputs": outs,
            "profiles": {},
        })
        for m in members:
            member_to_group[m] = gid

    new_edges = _rewire_edges(edges, member_to_group)
    return new_nodes, new_edges


def _union_io(
    by_id: Dict[str, Dict[str, Any]],
    members: List[str],
) -> Tuple[List[str], List[str]]:
    """Aggregate the inputs/outputs of a group's members.

    Files produced *and* consumed inside the group are dropped from both
    sides — they're internal to the group and shouldn't appear as edges.
    """
    out_set: set = set()
    in_set: set = set()
    for m in members:
        n = by_id.get(m, {})
        out_set.update(n.get("outputs", []) or [])
        in_set.update(n.get("inputs", []) or [])
    internal = out_set & in_set
    return sorted(in_set - internal), sorted(out_set - internal)


def _rewire_edges(
    edges: List[Dict[str, str]],
    member_to_group: Dict[str, str],
) -> List[Dict[str, str]]:
    """Remap edges through ``member_to_group``, dropping self-loops and dupes."""
    seen: set = set()
    out: List[Dict[str, str]] = []
    for e in edges:
        s = member_to_group.get(e["source"], e["source"])
        t = member_to_group.get(e["target"], e["target"])
        if s == t:
            continue
        key = (s, t)
        if key in seen:
            continue
        seen.add(key)
        out.append({"source": s, "target": t})
    return out


def collapse_by_level(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
    min_group: int = 4,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Looser fallback: fold nodes sharing the same transformation name on the
    same topological level. Catches "fan-out" patterns where siblings have
    *overlapping but not identical* parent/child sets (typical for Montage's
    mDiffFit layer, where 360 jobs each connect to 2 of the 48 mProjects).

    Skips already-collapsed group nodes and aux-prefixed jobs.
    """
    if not nodes:
        return nodes, edges

    parents, _ = _build_adjacency(nodes, edges)
    by_id = {n["id"]: n for n in nodes}
    level = _topo_levels([n["id"] for n in nodes], parents)

    groups: Dict[Tuple[str, int], List[str]] = defaultdict(list)
    for n in nodes:
        if n.get("_isGroup"):
            continue
        name = n.get("name", "")
        if _aux_prefix(name) is not None:
            continue
        tname = _strip_instance_suffix(name or n.get("id", ""))
        groups[(tname, level[n["id"]])].append(n["id"])

    member_to_group: Dict[str, str] = {}
    new_nodes: List[Dict[str, Any]] = []
    grouped_ids: set = set()

    for (tname, lvl), members in groups.items():
        if len(members) < min_group:
            continue
        gid = f"jobgroup:{tname}:L{lvl}"
        first = by_id[members[0]]
        ins, outs = _union_io(by_id, members)
        new_nodes.append({
            "id": gid,
            "name": tname,
            "nodeLabel": f"{tname} ×{len(members)}",
            "type": first.get("type", "job"),
            "type_desc": first.get("type_desc", "compute"),
            "_isGroup": True,
            "_groupKind": "level",
            "_members": list(members),
            "arguments": [],
            "inputs": ins,
            "outputs": outs,
            "profiles": {},
        })
        for m in members:
            member_to_group[m] = gid
            grouped_ids.add(m)

    new_nodes.extend(n for n in nodes if n["id"] not in grouped_ids)
    new_edges = _rewire_edges(edges, member_to_group)
    return new_nodes, new_edges


def collapse_graph(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
    min_group: int = 3,
    level_min_group: int = 4,
    strict_only: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Full collapse pass: aux-jobs first (so sibling-iso isn't fooled by
    plumbing), then strict sibling-isomorphism, then a looser per-level
    transformation grouping for what remains.

    Set ``strict_only=True`` to skip the looser per-level pass and preserve
    structural differences between siblings exactly.
    """
    nodes, edges = collapse_aux_jobs(nodes, edges, min_group=min(2, min_group))
    nodes, edges = collapse_siblings(nodes, edges, min_group=min_group)
    if not strict_only:
        nodes, edges = collapse_by_level(nodes, edges, min_group=level_min_group)
    return nodes, edges


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

            # Build a display label: prefer explicit nodeLabel, then name,
            # then id.  If name is shared by multiple jobs, disambiguate
            # with a short argument hint.
            label = job.get("nodeLabel", "")
            jid = job.get("id", "")
            jname = job.get("name", "")
            if not label or label == jid:
                label = jname or jid
            nodes.append({
                "id": jid,
                "name": jname,
                "nodeLabel": label,
                "type": job.get("type", "job"),
                "arguments": job.get("arguments", []),
                "inputs": inputs,
                "outputs": outputs,
                "profiles": job.get("profiles", {}),
            })

        # Disambiguate duplicate labels with argument hints
        label_counts: Dict[str, int] = {}
        for n in nodes:
            label_counts[n["nodeLabel"]] = label_counts.get(n["nodeLabel"], 0) + 1
        for n in nodes:
            if label_counts.get(n["nodeLabel"], 1) > 1:
                # Try to extract a distinguishing argument hint
                args = n.get("arguments", [])
                hint = ""
                for i, a in enumerate(args):
                    if isinstance(a, str) and a.startswith("--type") and i + 1 < len(args):
                        hint = str(args[i + 1])
                        break
                if not hint and args:
                    # Use the suffix of the id as a fallback
                    hint = n["id"].split("ID")[-1].lstrip("0") or n["id"][-4:]
                if hint:
                    n["nodeLabel"] = f"{n['nodeLabel']} ({hint})"

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
