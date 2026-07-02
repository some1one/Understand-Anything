"""Tests for arch_analysis.fingerprints — extraction, comparison, classification,
and the load-patch-save store writes."""

from __future__ import annotations

import json

import pytest

from arch_analysis.fingerprints import (
    classify_file_change,
    classify_update,
    compare_fingerprints,
    fingerprint_for_content,
    load_fingerprint_store,
    patch_and_save_fingerprints,
    save_fingerprint_store,
)

FOO = "def foo(a, b):\n    return a + b\n"


def fp(content: str, path: str = "m.py") -> dict:
    return fingerprint_for_content(path, content)


# --------------------------------------------------------------------------
# compare_fingerprints
# --------------------------------------------------------------------------


def test_identical_content_is_none():
    level, _ = compare_fingerprints(fp(FOO), fp(FOO))
    assert level == "NONE"


def test_body_only_edit_is_cosmetic():
    edited = "def foo(a, b):\n    # changed comment\n    return b + a\n"
    level, _ = compare_fingerprints(fp(FOO), fp(edited))
    assert level == "COSMETIC"


def test_added_function_is_structural():
    added = FOO + "\ndef bar():\n    return 1\n"
    level, details = compare_fingerprints(fp(FOO), fp(added))
    assert level == "STRUCTURAL"
    assert any("new function: bar" in d for d in details)


def test_removed_function_is_structural():
    bigger = FOO + "\ndef bar():\n    return 1\n"
    level, details = compare_fingerprints(fp(bigger), fp(FOO))
    assert level == "STRUCTURAL"
    assert any("removed function: bar" in d for d in details)


def test_changed_params_is_structural():
    changed = "def foo(a, b, c):\n    return a + b + c\n"
    level, _ = compare_fingerprints(fp(FOO), fp(changed))
    assert level == "STRUCTURAL"


def test_added_class_is_structural():
    with_class = FOO + "\nclass Bar:\n    def m(self):\n        pass\n"
    level, details = compare_fingerprints(fp(FOO), fp(with_class))
    assert level == "STRUCTURAL"
    assert any("new class: Bar" in d for d in details)


def test_changed_imports_is_structural():
    base = "import os\n" + FOO
    changed = "import os\nimport sys\n" + FOO
    level, details = compare_fingerprints(fp(base), fp(changed))
    assert level == "STRUCTURAL"
    assert any("imports changed" in d for d in details)


def test_unsupported_file_change_is_structural():
    a = fingerprint_for_content("data.bin", "alpha\n")
    b = fingerprint_for_content("data.bin", "beta\n")
    assert a["hasStructuralAnalysis"] is False
    level, _ = compare_fingerprints(a, b)
    assert level == "STRUCTURAL"


# --------------------------------------------------------------------------
# classify_file_change (new / deleted / modified)
# --------------------------------------------------------------------------


def test_new_file_is_structural_new(tmp_path):
    (tmp_path / "new.py").write_text(FOO)
    res = classify_file_change(tmp_path, "new.py", stored=None)
    assert res["status"] == "new"
    assert res["changeLevel"] == "STRUCTURAL"


def test_deleted_file_is_structural_deleted(tmp_path):
    res = classify_file_change(tmp_path, "gone.py", stored=fp(FOO))
    assert res["status"] == "deleted"
    assert res["changeLevel"] == "STRUCTURAL"


def test_modified_cosmetic(tmp_path):
    (tmp_path / "m.py").write_text("def foo(a, b):\n    return b + a\n")
    res = classify_file_change(tmp_path, "m.py", stored=fp(FOO))
    assert res["status"] == "modified"
    assert res["changeLevel"] == "COSMETIC"


# --------------------------------------------------------------------------
# classify_update — decision thresholds
# --------------------------------------------------------------------------


def _changes(n, status="modified", level="STRUCTURAL", prefix="src/f"):
    return [
        {"filePath": f"{prefix}{i}.py", "changeLevel": level, "status": status, "details": []}
        for i in range(n)
    ]


def test_classify_skip_when_no_structural():
    graph = {f"src/f{i}.py" for i in range(20)}
    decision = classify_update(_changes(2, level="COSMETIC"), graph)
    assert decision["action"] == "SKIP"


def test_classify_partial_small_localized():
    graph = {f"src/f{i}.py" for i in range(40)}
    decision = classify_update(_changes(2), graph)
    assert decision["action"] == "PARTIAL_UPDATE"
    assert decision["rerunArchitecture"] is False


def test_classify_architecture_on_new_directory():
    graph = {f"src/f{i}.py" for i in range(40)}
    changes = [
        {"filePath": "brand/new/feature.py", "changeLevel": "STRUCTURAL", "status": "new", "details": []}
    ]
    decision = classify_update(changes, graph)
    assert decision["action"] == "ARCHITECTURE_UPDATE"
    assert decision["rerunArchitecture"] is True


def test_classify_architecture_over_partial_limit():
    graph = {f"src/f{i}.py" for i in range(80)}
    decision = classify_update(_changes(12), graph)
    assert decision["action"] == "ARCHITECTURE_UPDATE"


def test_classify_full_over_file_limit():
    graph = {f"src/f{i}.py" for i in range(200)}
    decision = classify_update(_changes(31), graph)
    assert decision["action"] == "FULL_UPDATE"


def test_classify_full_over_half_the_graph():
    graph = {f"src/f{i}.py" for i in range(8)}
    decision = classify_update(_changes(5), graph)
    assert decision["action"] == "FULL_UPDATE"


# --------------------------------------------------------------------------
# Load / patch / save regression
# --------------------------------------------------------------------------


def _seed_store(tmp_path):
    (tmp_path / "a.py").write_text(FOO)
    (tmp_path / "b.py").write_text("def bar():\n    return 1\n")
    fp_path = tmp_path / "fingerprints.json"
    store = {
        "version": "1.0.0",
        "files": {
            "a.py": fingerprint_for_content("a.py", FOO),
            "b.py": fingerprint_for_content("b.py", "def bar():\n    return 1\n"),
        },
    }
    fp_path.write_text(json.dumps(store))
    return fp_path


def test_patch_preserves_unrelated_entries(tmp_path):
    fp_path = _seed_store(tmp_path)
    (tmp_path / "a.py").write_text(FOO + "\ndef baz():\n    return 2\n")
    before, after = patch_and_save_fingerprints(fp_path, tmp_path, ["a.py"])
    assert (before, after) == (2, 2)
    store = json.loads(fp_path.read_text())
    # b.py untouched, a.py re-fingerprinted.
    assert "b.py" in store["files"]
    assert any(f["name"] == "baz" for f in store["files"]["a.py"]["functions"])


def test_patch_removes_deleted_file(tmp_path):
    fp_path = _seed_store(tmp_path)
    (tmp_path / "b.py").unlink()
    before, after = patch_and_save_fingerprints(fp_path, tmp_path, ["b.py"])
    assert before == 2 and after == 1
    store = json.loads(fp_path.read_text())
    assert "b.py" not in store["files"]
    assert "a.py" in store["files"]


def test_save_guard_refuses_to_clobber_populated_store(tmp_path):
    fp_path = tmp_path / "fingerprints.json"
    # Simulate a populated store that failed to load (before_count == 0).
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        save_fingerprint_store(fp_path, {"files": {}}, existed_and_non_empty=True, before_count=0)


def test_load_missing_store_is_empty(tmp_path):
    store, existed = load_fingerprint_store(tmp_path / "nope.json")
    assert existed is False
    assert store["files"] == {}
