"""Tests for arch_analysis.compute_batches (networkx Louvain batching)."""

from __future__ import annotations

import json

import pytest

from arch_analysis.compute_batches import (
    build_non_code_batches,
    compute_batches,
    count_based_assignment,
    merge_small_batches,
    run_louvain,
)


def _code(path):
    return {"path": path, "language": "typescript", "sizeLines": 10, "fileCategory": "code"}


def _noncode(path, category="config", language="yaml"):
    return {"path": path, "language": language, "sizeLines": 5, "fileCategory": category}


def _write_scan(tmp_path, files, import_map):
    root = tmp_path / "proj"
    (root / ".understand-anything" / "intermediate").mkdir(parents=True)
    for f in files:
        abs_path = root / f["path"]
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(f"export const {f['path'].replace('/', '_').replace('.', '_')} = 1;\n")
    scan = {"files": files, "importMap": import_map}
    return root, scan


def test_basic_louvain_batches(tmp_path):
    files = [_code(f"src/a{i}.ts") for i in range(6)]
    # Two clusters: a0-a2 mutually import, a3-a5 mutually import.
    import_map = {
        "src/a0.ts": ["src/a1.ts", "src/a2.ts"],
        "src/a1.ts": ["src/a2.ts"],
        "src/a3.ts": ["src/a4.ts", "src/a5.ts"],
        "src/a4.ts": ["src/a5.ts"],
    }
    root, scan = _write_scan(tmp_path, files, import_map)
    out = compute_batches(root, scan)
    assert out["algorithm"] == "louvain"
    assert out["totalFiles"] == 6
    all_paths = {f["path"] for b in out["batches"] for f in b["files"]}
    assert all_paths == {f["path"] for f in files}


def test_size_enforcement_splits_large_community(tmp_path):
    # 40 files all in one fully-connected cluster → must split (>35).
    files = [_code(f"src/m{i:02d}.ts") for i in range(40)]
    import_map = {f["path"]: [g["path"] for g in files if g["path"] != f["path"]] for f in files}
    root, scan = _write_scan(tmp_path, files, import_map)
    out = compute_batches(root, scan)
    for b in out["batches"]:
        assert len(b["files"]) <= 35


def test_small_batch_merging():
    singletons = [{"files": [{"path": f"s{i}.ts"}], "mergeable": True} for i in range(10)]
    merged = merge_small_batches(singletons)
    # 10 singletons → pooled into ceil(10/25)=1 misc batch.
    assert len(merged) == 1
    assert len(merged[0]["files"]) == 10
    assert all("mergeable" not in b for b in merged)


def test_non_mergeable_preserved():
    batches = [
        {"files": [{"path": "Dockerfile"}], "mergeable": False},
        {"files": [{"path": "a.ts"}], "mergeable": True},
        {"files": [{"path": "b.ts"}], "mergeable": True},
    ]
    merged = merge_small_batches(batches)
    # Dockerfile batch kept standalone; the two mergeable singletons pooled.
    sizes = sorted(len(b["files"]) for b in merged)
    assert sizes == [1, 2]


def test_count_based_fallback_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UA_COMPUTE_BATCHES_FORCE_LOUVAIN_THROW", "1")
    files = [_code(f"src/a{i}.ts") for i in range(5)]
    root, scan = _write_scan(tmp_path, files, {})
    out = compute_batches(root, scan)
    assert out["algorithm"] == "count-fallback"


def test_neighbor_map_cross_batch(tmp_path):
    # 40 fully-connected files force a size-enforcement split into 2 batches;
    # the import edges spanning the split become cross-batch neighbors.
    files = [_code(f"src/m{i:02d}.ts") for i in range(40)]
    import_map = {f["path"]: [g["path"] for g in files if g["path"] != f["path"]] for f in files}
    root, scan = _write_scan(tmp_path, files, import_map)
    out = compute_batches(root, scan)
    found = False
    for b in out["batches"]:
        for _path, neighbors in b.get("neighborMap", {}).items():
            for n in neighbors:
                assert n["batchIndex"] != b["batchIndex"]
                assert "symbols" in n
                found = True
    assert found


def test_non_code_grouping_dockerfile_and_workflows():
    files = [
        _noncode("services/api/Dockerfile", "infra", "dockerfile"),
        _noncode("services/api/docker-compose.yml", "infra", "yaml"),
        _noncode(".github/workflows/ci.yml", "infra", "yaml"),
        _noncode(".github/workflows/release.yml", "infra", "yaml"),
    ]
    groups = build_non_code_batches(files)
    # One Dockerfile cluster, one workflows group.
    cluster_paths = [sorted(f["path"] for f in g["files"]) for g in groups]
    assert ["services/api/Dockerfile", "services/api/docker-compose.yml"] in cluster_paths
    assert [".github/workflows/ci.yml", ".github/workflows/release.yml"] in cluster_paths
    # Dockerfile + workflows groups are non-mergeable (semantic).
    assert all(not g["mergeable"] for g in groups)


def test_changed_files_filter(tmp_path):
    files = [_code(f"src/a{i}.ts") for i in range(6)]
    import_map = {"src/a0.ts": ["src/a1.ts"], "src/a3.ts": ["src/a4.ts"]}
    root, scan = _write_scan(tmp_path, files, import_map)
    out = compute_batches(root, scan, changed_files={"src/a0.ts"})
    # Only batches containing the changed file survive.
    assert all(any(f["path"] == "src/a0.ts" for f in b["files"]) for b in out["batches"])
    # totalFiles still reflects full project.
    assert out["totalFiles"] == 6


def test_determinism(tmp_path):
    files = [_code(f"src/a{i}.ts") for i in range(8)]
    import_map = {f"src/a{i}.ts": [f"src/a{(i + 1) % 8}.ts"] for i in range(8)}
    root, scan = _write_scan(tmp_path, files, import_map)
    out1 = compute_batches(root, scan)
    out2 = compute_batches(root, scan)
    assert json.dumps(out1) == json.dumps(out2)


def test_count_based_assignment_chunks():
    files = [_code(f"f{i}.ts") for i in range(25)]
    assignment = count_based_assignment(files, batch_size=12)
    communities = set(assignment.values())
    assert communities == {"count_0", "count_1", "count_2"}


def test_run_louvain_returns_mapping(tmp_path):
    files = [_code("a.ts"), _code("b.ts")]
    mapping = run_louvain(files, {"a.ts": ["b.ts"]})
    assert set(mapping.keys()) == {"a.ts", "b.ts"}
