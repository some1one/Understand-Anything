"""Tests for the Phase 2 layer cross-check validator."""

from __future__ import annotations

import orjson

from arch_analysis.validate_layers import check, main

INPUT = {
    "fileNodes": [
        {"id": "file:a.ts", "type": "file", "filePath": "a.ts"},
        {"id": "file:b.ts", "type": "file", "filePath": "b.ts"},
        {"id": "file:c.ts", "type": "file", "filePath": "c.ts"},
    ]
}


def _layers(*groups):
    """Build 3 well-formed layers, distributing the given node-id groups."""
    base = [
        {"id": "layer:api", "name": "API", "description": "d", "nodeIds": list(groups[0])},
        {"id": "layer:service", "name": "Service", "description": "d", "nodeIds": list(groups[1])},
        {"id": "layer:utility", "name": "Utility", "description": "d", "nodeIds": list(groups[2])},
    ]
    return base


def test_valid_layers_pass():
    layers = _layers(["file:a.ts"], ["file:b.ts"], ["file:c.ts"])
    assert check(INPUT, layers) == []


def test_missing_node_detected():
    layers = _layers(["file:a.ts"], ["file:b.ts"], ["file:b.ts"])  # c missing
    problems = check(INPUT, layers)
    assert any("not assigned" in p for p in problems)


def test_invented_node_detected():
    layers = _layers(["file:a.ts"], ["file:b.ts"], ["file:c.ts", "file:ghost.ts"])
    problems = check(INPUT, layers)
    assert any("invented" in p for p in problems)


def test_duplicate_assignment_detected():
    layers = _layers(["file:a.ts", "file:b.ts"], ["file:b.ts"], ["file:c.ts"])
    problems = check(INPUT, layers)
    assert any("multiple layers" in p for p in problems)


def test_too_few_layers_detected():
    layers = [
        {"id": "layer:all", "name": "All", "description": "d", "nodeIds": ["file:a.ts", "file:b.ts", "file:c.ts"]},
    ]
    problems = check(INPUT, layers)
    assert any("outside the allowed range" in p for p in problems)


def test_bad_id_format_detected():
    layers = _layers(["file:a.ts"], ["file:b.ts"], ["file:c.ts"])
    layers[0]["id"] = "API_LAYER"
    problems = check(INPUT, layers)
    assert any("schema" in p for p in problems)


def test_empty_node_ids_detected():
    layers = _layers(["file:a.ts", "file:b.ts", "file:c.ts"], [], [])
    problems = check(INPUT, layers)
    assert any("schema" in p for p in problems)


def test_cli_pass_and_fail(tmp_path):
    in_path = tmp_path / "in.json"
    ok_path = tmp_path / "ok.json"
    bad_path = tmp_path / "bad.json"
    in_path.write_bytes(orjson.dumps(INPUT))
    ok_path.write_bytes(orjson.dumps(_layers(["file:a.ts"], ["file:b.ts"], ["file:c.ts"])))
    bad_path.write_bytes(orjson.dumps(_layers(["file:a.ts"], ["file:b.ts"], ["file:b.ts"])))

    assert main([str(in_path), str(ok_path)]) == 0
    assert main([str(in_path), str(bad_path)]) == 1
