"""Tests for understand_core.boundary_stubs."""

from __future__ import annotations

from understand_core.boundary_stubs import add_boundary_stubs, parse_node_id


def _node(nid, **extra):
    return {
        "id": nid,
        "type": "file",
        "name": nid,
        "summary": "s",
        "tags": [],
        "complexity": "simple",
        **extra,
    }


def _edge(src, tgt, etype="imports"):
    return {"source": src, "target": tgt, "type": etype, "weight": 0.7}


def test_parse_file_id():
    assert parse_node_id("file:src/a.ts") == ("file", "src/a.ts", "a.ts")


def test_parse_function_id():
    assert parse_node_id("function:src/a.ts:login") == ("function", "src/a.ts", "login")


def test_parse_no_prefix():
    assert parse_node_id("noprefix") is None


def test_stub_created_for_cross_part_target():
    graph = {
        "nodes": [_node("file:src/api/h.ts")],
        "edges": [_edge("file:src/api/h.ts", "file:src/db/conn.ts")],
    }
    known = {"src/api/h.ts", "src/db/conn.ts"}
    out = add_boundary_stubs(graph, known)
    ids = {n["id"] for n in out["nodes"]}
    assert "file:src/db/conn.ts" in ids
    stub = next(n for n in out["nodes"] if n["id"] == "file:src/db/conn.ts")
    assert stub["stub"] is True
    assert stub["filePath"] == "src/db/conn.ts"
    assert stub["type"] == "file"


def test_no_stub_for_unknown_path():
    graph = {
        "nodes": [_node("file:src/api/h.ts")],
        "edges": [_edge("file:src/api/h.ts", "file:vendor/lib.ts")],
    }
    out = add_boundary_stubs(graph, {"src/api/h.ts"})
    assert {n["id"] for n in out["nodes"]} == {"file:src/api/h.ts"}


def test_no_stub_for_existing_node():
    graph = {
        "nodes": [_node("file:a.ts"), _node("file:b.ts")],
        "edges": [_edge("file:a.ts", "file:b.ts")],
    }
    out = add_boundary_stubs(graph, {"a.ts", "b.ts"})
    assert len(out["nodes"]) == 2


def test_function_stub_falls_back_to_parsed_type():
    graph = {
        "nodes": [_node("file:src/a.ts")],
        "edges": [_edge("file:src/a.ts", "function:src/b.ts:run", "calls")],
    }
    out = add_boundary_stubs(graph, {"src/a.ts", "src/b.ts"})
    stub = next(n for n in out["nodes"] if n["id"] == "function:src/b.ts:run")
    assert stub["type"] == "function"
    assert stub["name"] == "run"


def test_returns_same_object_when_no_stubs():
    graph = {"nodes": [_node("file:a.ts")], "edges": []}
    assert add_boundary_stubs(graph, {"a.ts"}) is graph
