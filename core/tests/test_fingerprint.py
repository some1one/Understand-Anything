"""Port of packages/core/src/__tests__/fingerprint.test.ts."""

from __future__ import annotations

import re

from understand_core.fingerprint import (
    analyze_changes,
    compare_fingerprints,
    content_hash,
    extract_file_fingerprint,
)


class FakeRegistry:
    """Stand-in for core's PluginRegistry; returns a fixed analysis or None."""

    def __init__(self, analysis=None):
        self.analysis = analysis

    def analyze_file(self, file_path, content):
        return self.analysis


# --- contentHash ---


def test_content_hash_consistent():
    h1 = content_hash("hello world")
    h2 = content_hash("hello world")
    assert h1 == h2
    assert re.fullmatch(r"[a-f0-9]{64}", h1)


def test_content_hash_differs():
    assert content_hash("hello") != content_hash("world")


# --- extractFileFingerprint ---


def test_extracts_function_fingerprints():
    analysis = {
        "functions": [
            {"name": "main", "lineRange": [1, 20], "params": ["config", "options"], "returnType": "void"},
            {"name": "helper", "lineRange": [22, 30], "params": [], "returnType": "string"},
        ],
        "classes": [],
        "imports": [],
        "exports": [{"name": "main", "lineNumber": 1}],
    }
    fp = extract_file_fingerprint("src/index.ts", "const x = 1;\n" * 30, analysis)
    assert fp["filePath"] == "src/index.ts"
    assert len(fp["functions"]) == 2
    assert fp["functions"][0] == {
        "name": "main", "params": ["config", "options"],
        "returnType": "void", "exported": True, "lineCount": 20,
    }
    assert fp["functions"][1] == {
        "name": "helper", "params": [], "returnType": "string",
        "exported": False, "lineCount": 9,
    }


def test_extracts_class_fingerprints():
    analysis = {
        "functions": [],
        "classes": [{"name": "MyClass", "lineRange": [1, 50], "methods": ["doStuff", "init"], "properties": ["name"]}],
        "imports": [],
        "exports": [{"name": "MyClass", "lineNumber": 1}],
    }
    fp = extract_file_fingerprint("src/my-class.ts", "x\n" * 50, analysis)
    assert len(fp["classes"]) == 1
    assert fp["classes"][0] == {
        "name": "MyClass", "methods": ["doStuff", "init"],
        "properties": ["name"], "exported": True, "lineCount": 50,
    }


def test_extracts_import_export_fingerprints():
    analysis = {
        "functions": [],
        "classes": [],
        "imports": [
            {"source": "./utils", "specifiers": ["format", "parse"], "lineNumber": 1},
            {"source": "node:fs", "specifiers": ["readFileSync"], "lineNumber": 2},
        ],
        "exports": [{"name": "main", "lineNumber": 5}, {"name": "default", "lineNumber": 10}],
    }
    fp = extract_file_fingerprint("src/index.ts", "x\n", analysis)
    assert len(fp["imports"]) == 2
    assert fp["imports"][0] == {"source": "./utils", "specifiers": ["format", "parse"]}
    assert fp["exports"] == ["main", "default"]


def test_computes_content_hash_and_total_lines():
    content = "line1\nline2\nline3\n"
    analysis = {"functions": [], "classes": [], "imports": [], "exports": []}
    fp = extract_file_fingerprint("src/empty.ts", content, analysis)
    assert fp["contentHash"] == content_hash(content)
    assert fp["totalLines"] == 4


# --- compareFingerprints ---

BASE_FP = {
    "filePath": "src/index.ts",
    "contentHash": "abc123",
    "functions": [{"name": "main", "params": ["config"], "returnType": "void", "exported": True, "lineCount": 20}],
    "classes": [],
    "imports": [{"source": "./utils", "specifiers": ["format"]}],
    "exports": ["main"],
    "totalLines": 30,
    "hasStructuralAnalysis": True,
}


def _base(**overrides):
    import copy
    fp = copy.deepcopy(BASE_FP)
    fp.update(overrides)
    return fp


def test_compare_none_when_identical_hash():
    result = compare_fingerprints(BASE_FP, _base())
    assert result["changeLevel"] == "NONE"
    assert len(result["details"]) == 0


def test_compare_cosmetic_when_structure_identical():
    result = compare_fingerprints(BASE_FP, _base(contentHash="different_hash"))
    assert result["changeLevel"] == "COSMETIC"
    assert "internal logic changed (no structural impact)" in result["details"]


def test_detects_new_functions():
    new_fp = _base(contentHash="different", functions=[
        *BASE_FP["functions"],
        {"name": "newFunc", "params": [], "exported": False, "lineCount": 10},
    ])
    result = compare_fingerprints(BASE_FP, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "new function: newFunc" in result["details"]


def test_detects_removed_functions():
    result = compare_fingerprints(BASE_FP, _base(contentHash="different", functions=[]))
    assert result["changeLevel"] == "STRUCTURAL"
    assert "removed function: main" in result["details"]


def test_detects_param_changes():
    new_fp = _base(contentHash="different", functions=[
        {"name": "main", "params": ["config", "options"], "returnType": "void", "exported": True, "lineCount": 20},
    ])
    result = compare_fingerprints(BASE_FP, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "params changed: main" in result["details"]


def test_detects_export_status_changes():
    new_fp = _base(contentHash="different", functions=[
        {"name": "main", "params": ["config"], "returnType": "void", "exported": False, "lineCount": 20},
    ])
    result = compare_fingerprints(BASE_FP, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "export status changed: main" in result["details"]


def test_detects_significant_size_changes():
    new_fp = _base(contentHash="different", functions=[
        {"name": "main", "params": ["config"], "returnType": "void", "exported": True, "lineCount": 60},
    ])
    result = compare_fingerprints(BASE_FP, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert any("significant size change" in d for d in result["details"])


def test_detects_import_changes():
    new_fp = _base(contentHash="different", imports=[{"source": "./helpers", "specifiers": ["doStuff"]}])
    result = compare_fingerprints(BASE_FP, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "imports changed" in result["details"]


def test_detects_export_list_changes():
    new_fp = _base(contentHash="different", exports=["main", "helper"])
    result = compare_fingerprints(BASE_FP, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "exports changed" in result["details"]


def test_detects_new_and_removed_classes():
    with_class = _base(
        contentHash="different",
        classes=[{"name": "MyClass", "methods": ["init"], "properties": [], "exported": True, "lineCount": 30}],
        hasStructuralAnalysis=True,
    )
    result = compare_fingerprints(BASE_FP, with_class)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "new class: MyClass" in result["details"]


def test_detects_class_method_changes():
    old_fp = _base(classes=[{"name": "Foo", "methods": ["a", "b"], "properties": [], "exported": True, "lineCount": 30}], hasStructuralAnalysis=True)
    new_fp = _base(contentHash="different", classes=[{"name": "Foo", "methods": ["a", "c"], "properties": [], "exported": True, "lineCount": 30}], hasStructuralAnalysis=True)
    result = compare_fingerprints(old_fp, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "methods changed: Foo" in result["details"]


def test_does_not_mutate_input_arrays():
    old_fp = _base(
        classes=[{"name": "Foo", "methods": ["b", "a"], "properties": ["y", "x"], "exported": True, "lineCount": 30}],
        imports=[{"source": "./utils", "specifiers": ["z", "a"]}],
        hasStructuralAnalysis=True,
    )
    new_fp = _base(
        contentHash="different",
        classes=[{"name": "Foo", "methods": ["b", "a"], "properties": ["y", "x"], "exported": True, "lineCount": 30}],
        imports=[{"source": "./utils", "specifiers": ["z", "a"]}],
        hasStructuralAnalysis=True,
    )
    old_methods = list(old_fp["classes"][0]["methods"])
    old_props = list(old_fp["classes"][0]["properties"])
    old_specs = list(old_fp["imports"][0]["specifiers"])
    new_methods = list(new_fp["classes"][0]["methods"])
    compare_fingerprints(old_fp, new_fp)
    assert old_fp["classes"][0]["methods"] == old_methods
    assert old_fp["classes"][0]["properties"] == old_props
    assert old_fp["imports"][0]["specifiers"] == old_specs
    assert new_fp["classes"][0]["methods"] == new_methods


def test_structural_when_no_tree_sitter():
    old_fp = {"filePath": "config.yaml", "contentHash": "hash_old", "functions": [], "classes": [], "imports": [], "exports": [], "totalLines": 10, "hasStructuralAnalysis": False}
    new_fp = {"filePath": "config.yaml", "contentHash": "hash_new", "functions": [], "classes": [], "imports": [], "exports": [], "totalLines": 12, "hasStructuralAnalysis": False}
    result = compare_fingerprints(old_fp, new_fp)
    assert result["changeLevel"] == "STRUCTURAL"
    assert "no structural analysis available — conservative classification" in result["details"]


# --- analyzeChanges ---

EXISTING_STORE = {
    "version": "1.0.0",
    "gitCommitHash": "abc123",
    "generatedAt": "2026-01-01T00:00:00.000Z",
    "files": {
        "src/index.ts": {
            "filePath": "src/index.ts", "contentHash": "hash_a",
            "functions": [{"name": "main", "params": [], "exported": True, "lineCount": 20}],
            "classes": [], "imports": [], "exports": ["main"], "totalLines": 30,
            "hasStructuralAnalysis": True,
        },
        "src/utils.ts": {
            "filePath": "src/utils.ts", "contentHash": "hash_b",
            "functions": [], "classes": [], "imports": [], "exports": [], "totalLines": 10,
            "hasStructuralAnalysis": True,
        },
    },
}


def _write(tmp_path, rel, content):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_classifies_new_files_structural(tmp_path):
    _write(tmp_path, "src/new-file.ts", "new content")
    registry = FakeRegistry({"functions": [], "classes": [], "imports": [], "exports": []})
    result = analyze_changes(str(tmp_path), ["src/new-file.ts"], EXISTING_STORE, registry)
    assert "src/new-file.ts" in result["newFiles"]
    assert result["fileChanges"][0]["changeLevel"] == "STRUCTURAL"


def test_classifies_deleted_files_structural(tmp_path):
    registry = FakeRegistry()
    result = analyze_changes(str(tmp_path), ["src/utils.ts"], EXISTING_STORE, registry)
    assert "src/utils.ts" in result["deletedFiles"]
    assert result["fileChanges"][0]["changeLevel"] == "STRUCTURAL"


def test_classifies_unchanged_content_none(tmp_path):
    content = "test content"
    _write(tmp_path, "src/index.ts", content)
    store = {
        **EXISTING_STORE,
        "files": {
            "src/index.ts": {**EXISTING_STORE["files"]["src/index.ts"], "contentHash": content_hash(content)},
        },
    }
    registry = FakeRegistry({
        "functions": [{"name": "main", "lineRange": [1, 20], "params": []}],
        "classes": [], "imports": [], "exports": [{"name": "main", "lineNumber": 1}],
    })
    result = analyze_changes(str(tmp_path), ["src/index.ts"], store, registry)
    assert "src/index.ts" in result["unchangedFiles"]


def test_ignores_deleted_files_not_in_store(tmp_path):
    registry = FakeRegistry()
    result = analyze_changes(str(tmp_path), ["src/unknown.ts"], EXISTING_STORE, registry)
    assert len(result["deletedFiles"]) == 0
    assert len(result["fileChanges"]) == 0
