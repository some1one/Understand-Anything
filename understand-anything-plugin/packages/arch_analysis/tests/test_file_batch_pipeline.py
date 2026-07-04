"""Tests for the deterministic file-analyzer batch pipeline.

Covers prepare_file_analysis_batch, seed_file_batch_graph,
finalize_file_batch_output, and validate_structure_output.
"""

from __future__ import annotations

import copy
import json

from arch_analysis.finalize_file_batch_output import split_into_parts, validate_draft
from arch_analysis.prepare_file_analysis_batch import build_batch_payloads
from arch_analysis.seed_file_batch_graph import build_seed
from arch_analysis.validate_structure_output import check_structure_output
from arch_analysis.schema import (
    validate_file_analysis_context,
    validate_structure_input,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _context():
    return {
        "projectRoot": "/proj",
        "batchIndex": 7,
        "batchFiles": [
            {"path": "src/a.ts", "language": "typescript", "sizeLines": 40, "fileCategory": "code"},
            {"path": "tsconfig.json", "language": "json", "sizeLines": 10, "fileCategory": "config"},
            {"path": "Dockerfile", "language": "dockerfile", "sizeLines": 12, "fileCategory": "infra"},
        ],
        "batchImportData": {"src/a.ts": ["src/b.ts"]},
        "neighborMap": {
            "src/a.ts": [{"path": "src/b.ts", "batchIndex": 2, "symbols": ["helper"]}]
        },
    }


def _extract_results():
    return {
        "scriptCompleted": True,
        "filesAnalyzed": 3,
        "filesSkipped": [],
        "results": [
            {
                "path": "src/a.ts",
                "language": "typescript",
                "fileCategory": "code",
                "totalLines": 40,
                "nonEmptyLines": 30,
                "functions": [
                    {"name": "run", "startLine": 1, "endLine": 20, "params": []},
                    {"name": "tiny", "startLine": 22, "endLine": 23, "params": []},
                ],
                "classes": [
                    {"name": "App", "startLine": 25, "endLine": 39, "methods": ["a", "b"], "properties": []}
                ],
                "exports": [{"name": "run", "line": 1, "isDefault": False}],
                "metrics": {"importCount": 1, "exportCount": 1, "functionCount": 2, "classCount": 1},
            },
            {"path": "tsconfig.json", "fileCategory": "config", "totalLines": 10, "nonEmptyLines": 10, "metrics": {}},
            {"path": "Dockerfile", "fileCategory": "infra", "totalLines": 12, "nonEmptyLines": 10, "metrics": {}},
        ],
    }


def _draft_from_seed(seed):
    """Build a valid LLM draft by enriching seed nodes with summary/complexity/tags."""
    draft = copy.deepcopy(seed)
    draft.pop("batchIndex", None)
    for n in draft["nodes"]:
        n["summary"] = f"Summary for {n['id']}."
        n["complexity"] = "simple"
        n.setdefault("tags", [])
        # keep the deterministic tags, add a semantic one
        n["tags"] = list(n["tags"]) + ["semantic"]
    return draft


# ── prepare_file_analysis_batch ──────────────────────────────────────────────


def test_prepare_builds_valid_input_and_context():
    batch = {
        "batchIndex": 7,
        "files": _context()["batchFiles"],
        "batchImportData": {"src/a.ts": ["src/b.ts"]},
        "neighborMap": {"src/a.ts": [{"path": "src/b.ts", "batchIndex": 2, "symbols": ["helper"]}]},
    }
    structure_input, context = build_batch_payloads("/proj", batch)
    validate_structure_input(structure_input)
    validate_file_analysis_context(context)
    assert context["batchIndex"] == 7
    assert structure_input["batchImportData"] == {"src/a.ts": ["src/b.ts"]}


# ── seed_file_batch_graph ─────────────────────────────────────────────────────


def test_seed_creates_file_function_class_nodes_and_edges():
    seed = build_seed(_context(), _extract_results())
    ids = {n["id"] for n in seed["nodes"]}
    assert "file:src/a.ts" in ids
    assert "config:tsconfig.json" in ids
    assert "service:Dockerfile" in ids
    assert "function:src/a.ts:run" in ids  # 20 lines AND exported
    assert "class:src/a.ts:App" in ids  # 2 methods
    assert "function:src/a.ts:tiny" not in ids  # trivial, not exported

    edge_keys = {(e["source"], e["target"], e["type"]) for e in seed["edges"]}
    assert ("file:src/a.ts", "file:src/b.ts", "imports") in edge_keys
    assert ("file:src/a.ts", "function:src/a.ts:run", "contains") in edge_keys
    assert ("file:src/a.ts", "function:src/a.ts:run", "exports") in edge_keys
    assert ("file:src/a.ts", "class:src/a.ts:App", "contains") in edge_keys


def test_seed_tags_include_deterministic_infra_tags():
    seed = build_seed(_context(), _extract_results())
    docker = next(n for n in seed["nodes"] if n["id"] == "service:Dockerfile")
    assert "containerization" in docker["tags"]


def test_seed_nodes_are_valid_draft_metadata():
    seed = build_seed(_context(), _extract_results())
    for node in seed["nodes"]:
        assert node["summary"]
        assert node["complexity"] in {"simple", "moderate", "complex"}
        assert len(node["tags"]) >= 3


# ── finalize_file_batch_output: validation ───────────────────────────────────


def test_finalize_accepts_valid_draft():
    ctx = _context()
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)
    assert validate_draft(ctx, seed, draft) == []


def test_finalize_fails_on_missing_import_edge():
    ctx = _context()
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)
    draft["edges"] = [e for e in draft["edges"] if e["type"] != "imports"]
    issues = validate_draft(ctx, seed, draft)
    assert any("missing imports edge" in i for i in issues)


def test_finalize_fails_on_deleted_seed_tag():
    ctx = _context()
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)
    docker = next(n for n in draft["nodes"] if n["id"] == "service:Dockerfile")
    docker["tags"] = ["semantic"]  # dropped the deterministic infra tags
    issues = validate_draft(ctx, seed, draft)
    assert any("missing required tag" in i for i in issues)


def test_finalize_fails_on_deleted_deterministic_edge():
    ctx = _context()
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)
    draft["edges"] = [
        e
        for e in draft["edges"]
        if not (e["source"] == "file:src/a.ts" and e["target"] == "class:src/a.ts:App" and e["type"] == "contains")
    ]
    issues = validate_draft(ctx, seed, draft)
    assert any("seeded contains edge" in i for i in issues)


def test_finalize_fails_on_invalid_cross_batch_ref():
    ctx = _context()
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)
    draft["edges"].append(
        {
            "source": "file:src/a.ts",
            "target": "function:src/elsewhere.ts:mystery",
            "type": "calls",
            "direction": "forward",
            "weight": 0.8,
        }
    )
    issues = validate_draft(ctx, seed, draft)
    assert any("allowed cross-batch reference" in i for i in issues)


def test_finalize_allows_neighbor_symbol_ref():
    ctx = _context()
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)
    draft["edges"].append(
        {
            "source": "file:src/a.ts",
            "target": "function:src/b.ts:helper",  # from neighborMap symbols
            "type": "calls",
            "direction": "forward",
            "weight": 0.8,
        }
    )
    assert validate_draft(ctx, seed, draft) == []


def test_finalize_fails_on_spurious_import():
    ctx = _context()
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)
    draft["edges"].append(
        {
            "source": "file:src/a.ts",
            "target": "file:src/b.ts",
            "type": "imports",
            "direction": "forward",
            "weight": 0.7,
        }
    )  # this one is legit (already required) so add a genuinely spurious one instead
    draft["nodes"].append(
        {"id": "file:src/c.ts", "type": "file", "name": "c.ts", "filePath": "src/c.ts",
         "summary": "c", "complexity": "simple", "tags": ["x"]}
    )
    draft["edges"].append(
        {"source": "file:src/c.ts", "target": "file:src/d.ts", "type": "imports",
         "direction": "forward", "weight": 0.7}
    )
    # src/c.ts isn't a batch import-data key, so it's not flagged as spurious;
    # add a spurious edge from a batch file instead.
    draft["edges"].append(
        {"source": "file:src/a.ts", "target": "file:src/zzz.ts", "type": "imports",
         "direction": "forward", "weight": 0.7}
    )
    draft["nodes"].append(
        {"id": "file:src/zzz.ts", "type": "file", "name": "zzz.ts", "filePath": "src/zzz.ts",
         "summary": "z", "complexity": "simple", "tags": ["x"]}
    )
    issues = validate_draft(ctx, seed, draft)
    assert any("spurious imports edge" in i for i in issues)


# ── finalize_file_batch_output: splitting + writing ──────────────────────────


def test_split_single_part_under_thresholds():
    nodes = [{"id": f"file:f{i}.ts", "filePath": f"f{i}.ts"} for i in range(3)]
    edges = []
    parts = split_into_parts(nodes, edges, [f"f{i}.ts" for i in range(3)])
    assert len(parts) == 1


def test_split_multi_part_over_node_threshold():
    files = [f"f{i}.ts" for i in range(80)]
    nodes = [{"id": f"file:{f}", "filePath": f} for f in files]
    edges = [{"source": f"file:{files[0]}", "target": f"file:{files[1]}", "type": "imports"}]
    parts = split_into_parts(nodes, edges, files)
    assert len(parts) == 2
    total = sum(len(p["nodes"]) for p in parts)
    assert total == 80


def test_finalize_cli_writes_batch_file(tmp_path):
    from arch_analysis.finalize_file_batch_output import main

    project_root = tmp_path
    ctx = _context()
    ctx["projectRoot"] = str(project_root)
    seed = build_seed(ctx, _extract_results())
    draft = _draft_from_seed(seed)

    ctx_path = tmp_path / "context.json"
    seed_path = tmp_path / "seed.json"
    draft_path = tmp_path / "draft.json"
    ctx_path.write_text(json.dumps(ctx))
    seed_path.write_text(json.dumps(seed))
    draft_path.write_text(json.dumps(draft))

    rc = main([str(project_root), str(ctx_path), str(seed_path), str(draft_path)])
    assert rc == 0
    out = project_root / ".understand-anything" / "intermediate" / "batch-7.json"
    assert out.exists()
    written = json.loads(out.read_text())
    assert {n["id"] for n in written["nodes"]} == {n["id"] for n in draft["nodes"]}


def test_finalize_cli_accepts_seed_as_draft(tmp_path):
    from arch_analysis.finalize_file_batch_output import main

    project_root = tmp_path
    ctx = _context()
    ctx["projectRoot"] = str(project_root)
    seed = build_seed(ctx, _extract_results())

    ctx_path = tmp_path / "context.json"
    seed_path = tmp_path / "seed.json"
    ctx_path.write_text(json.dumps(ctx))
    seed_path.write_text(json.dumps(seed))

    rc = main([str(project_root), str(ctx_path), str(seed_path), str(seed_path)])
    assert rc == 0
    out = project_root / ".understand-anything" / "intermediate" / "batch-7.json"
    written = json.loads(out.read_text())
    assert {n["id"] for n in written["nodes"]} == {n["id"] for n in seed["nodes"]}


# ── validate_structure_output ────────────────────────────────────────────────


def _structure_input():
    return {
        "projectRoot": "/proj",
        "batchFiles": [
            {"path": "src/a.ts", "language": "typescript", "sizeLines": 40, "fileCategory": "code"},
            {"path": "src/b.ts", "language": "typescript", "sizeLines": 10, "fileCategory": "code"},
        ],
        "batchImportData": {},
    }


def _structure_output():
    return {
        "scriptCompleted": True,
        "filesAnalyzed": 2,
        "filesSkipped": [],
        "results": [
            {"path": "src/a.ts", "totalLines": 40, "nonEmptyLines": 30, "metrics": {"functionCount": 1}},
            {"path": "src/b.ts", "totalLines": 10, "nonEmptyLines": 8, "metrics": {}},
        ],
    }


def test_structure_output_valid():
    assert check_structure_output(_structure_input(), _structure_output()) == []


def test_structure_output_duplicate_paths():
    out = _structure_output()
    out["results"].append(out["results"][0])
    out["filesAnalyzed"] = 3
    issues = check_structure_output(_structure_input(), out)
    assert any("duplicate result" in i for i in issues)


def test_structure_output_missing_batch_file():
    out = _structure_output()
    out["results"] = out["results"][:1]
    out["filesAnalyzed"] = 1
    issues = check_structure_output(_structure_input(), out)
    assert any("missing from results" in i for i in issues)


def test_structure_output_bad_files_analyzed():
    out = _structure_output()
    out["filesAnalyzed"] = 99
    issues = check_structure_output(_structure_input(), out)
    assert any("does not match the number of results" in i for i in issues)


def test_structure_output_malformed_metrics():
    out = _structure_output()
    out["results"][0]["metrics"] = {"functionCount": "lots"}
    issues = check_structure_output(_structure_input(), out)
    assert any("malformed metric" in i for i in issues)
