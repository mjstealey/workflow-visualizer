"""Tests for workflow.yml parser."""
import tempfile
from pathlib import Path

import yaml

from workflow_visualizer.parser import WorkflowGraph


SAMPLE_WORKFLOW = {
    "pegasus": "5.0.4",
    "name": "earthquake",
    "jobs": [
        {
            "type": "job",
            "name": "fetch_earthquake_data",
            "id": "fetch_california",
            "nodeLabel": "fetch_california",
            "arguments": ["--region", "california"],
            "uses": [
                {"lfn": "california_catalog.csv", "type": "output", "stageOut": True},
            ],
        },
        {
            "type": "job",
            "name": "analyze_seismic_patterns",
            "id": "analyze_california",
            "nodeLabel": "analyze_california",
            "arguments": ["--input", "california_catalog.csv"],
            "uses": [
                {"lfn": "california_catalog.csv", "type": "input"},
                {"lfn": "california_patterns.json", "type": "output", "stageOut": True},
            ],
        },
        {
            "type": "job",
            "name": "visualize_earthquakes",
            "id": "visualize_california",
            "nodeLabel": "visualize_california",
            "arguments": ["--input", "california_catalog.csv"],
            "uses": [
                {"lfn": "california_catalog.csv", "type": "input"},
                {"lfn": "california_visualization.png", "type": "output", "stageOut": True},
            ],
        },
    ],
    "jobDependencies": [
        {
            "id": "fetch_california",
            "children": ["analyze_california", "visualize_california"],
        },
    ],
}


def _write_yaml(data: dict) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
    yaml.dump(data, f)
    f.close()
    return Path(f.name)


def test_parse_nodes():
    path = _write_yaml(SAMPLE_WORKFLOW)
    graph = WorkflowGraph.from_yaml(path)

    assert len(graph.nodes) == 3
    ids = {n["id"] for n in graph.nodes}
    assert ids == {"fetch_california", "analyze_california", "visualize_california"}
    path.unlink()


def test_parse_edges():
    path = _write_yaml(SAMPLE_WORKFLOW)
    graph = WorkflowGraph.from_yaml(path)

    assert len(graph.edges) == 2
    sources = {e["source"] for e in graph.edges}
    targets = {e["target"] for e in graph.edges}
    assert sources == {"fetch_california"}
    assert targets == {"analyze_california", "visualize_california"}
    path.unlink()


def test_parse_metadata():
    path = _write_yaml(SAMPLE_WORKFLOW)
    graph = WorkflowGraph.from_yaml(path)

    assert graph.metadata["name"] == "earthquake"
    assert graph.metadata["pegasus_version"] == "5.0.4"
    path.unlink()


def test_node_inputs_outputs():
    path = _write_yaml(SAMPLE_WORKFLOW)
    graph = WorkflowGraph.from_yaml(path)

    fetch = next(n for n in graph.nodes if n["id"] == "fetch_california")
    assert fetch["inputs"] == []
    assert fetch["outputs"] == ["california_catalog.csv"]

    analyze = next(n for n in graph.nodes if n["id"] == "analyze_california")
    assert analyze["inputs"] == ["california_catalog.csv"]
    assert analyze["outputs"] == ["california_patterns.json"]
    path.unlink()


def test_to_dict():
    path = _write_yaml(SAMPLE_WORKFLOW)
    graph = WorkflowGraph.from_yaml(path)
    d = graph.to_dict()

    assert "nodes" in d
    assert "edges" in d
    assert "metadata" in d
    assert len(d["nodes"]) == 3
    path.unlink()


def test_from_events():
    jobs = {
        1: {"exec_job_id": "job_a", "type_desc": "compute"},
        2: {"exec_job_id": "job_b", "type_desc": "stage-in-tx"},
    }
    graph = WorkflowGraph.from_events(jobs)
    assert len(graph.nodes) == 2
    assert graph.edges == []


def test_real_workflow_yml():
    """Test parsing the actual earthquake workflow.yml if available.

    Set EARTHQUAKE_WORKFLOW_YML to the path of a real workflow.yml to run this test.
    """
    import os
    path_str = os.environ.get("EARTHQUAKE_WORKFLOW_YML")
    if not path_str:
        return
    path = Path(path_str)
    if not path.exists():
        return

    graph = WorkflowGraph.from_yaml(path)
    assert len(graph.nodes) > 0
    assert len(graph.edges) > 0
    assert graph.metadata["name"] is not None
