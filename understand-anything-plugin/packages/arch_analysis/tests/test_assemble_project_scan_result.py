"""Tests for arch_analysis.assemble_project_scan_result."""

from __future__ import annotations

import pytest

from arch_analysis.assemble_project_scan_result import AssemblyError, assemble_scan_result
from arch_analysis.schema import validate_project_scan_output


def _scan(files=None):
    files = files if files is not None else [
        {"path": "src/a.ts", "language": "typescript", "sizeLines": 10, "fileCategory": "code"},
        {"path": "README.md", "language": "markdown", "sizeLines": 5, "fileCategory": "docs"},
    ]
    return {
        "scriptCompleted": True,
        "files": files,
        "totalFiles": len(files),
        "filteredByIgnore": 3,
        "estimatedComplexity": "moderate",
        "stats": {
            "filesScanned": len(files),
            "byCategory": {"code": 1, "docs": 1},
            "byLanguage": {"typescript": 1, "markdown": 1},
        },
    }


def _import_map():
    return {
        "scriptCompleted": True,
        "stats": {"filesScanned": 2, "filesWithImports": 1, "totalEdges": 0},
        "importMap": {"src/a.ts": ["src/b.ts"], "README.md": []},
    }


def _narrative():
    return {"name": "demo", "description": "A demo project.", "frameworks": ["React"]}


def test_files_and_import_map_copied_verbatim():
    scan, imap = _scan(), _import_map()
    result = assemble_scan_result(scan, imap, _narrative(), "/proj")
    # Copied by reference-equality of content — must be exactly the deterministic data.
    assert result["files"] == scan["files"]
    assert result["importMap"] == imap["importMap"]
    assert result["totalFiles"] == 2
    assert result["filteredByIgnore"] == 3
    assert result["estimatedComplexity"] == "moderate"
    assert result["name"] == "demo"
    assert result["frameworks"] == ["React"]
    # No transient fields leak through.
    assert "scriptCompleted" not in result
    assert "stats" not in result
    validate_project_scan_output(result)


def test_languages_fall_back_to_scan_tally():
    narrative = {"name": "demo", "description": "d", "frameworks": []}
    result = assemble_scan_result(_scan(), _import_map(), narrative, "/proj")
    assert result["languages"] == ["markdown", "typescript"]


def test_total_mismatch_fails():
    scan = _scan()
    scan["totalFiles"] = 99  # disagrees with len(files)
    with pytest.raises(AssemblyError):
        assemble_scan_result(scan, _import_map(), _narrative(), "/proj")


def test_missing_import_map_entry_fails():
    imap = _import_map()
    del imap["importMap"]["README.md"]
    with pytest.raises(AssemblyError):
        assemble_scan_result(_scan(), imap, _narrative(), "/proj")


def test_large_project_note_appended():
    files = [
        {"path": f"src/f{i}.ts", "language": "typescript", "sizeLines": 1, "fileCategory": "code"}
        for i in range(101)
    ]
    scan = _scan(files)
    imap = {"scriptCompleted": True, "stats": {}, "importMap": {f["path"]: [] for f in files}}
    result = assemble_scan_result(scan, imap, _narrative(), "/proj")
    assert "over 100 source files" in result["description"]
    validate_project_scan_output(result)


def test_missing_description_defaults():
    narrative = {"name": "demo", "frameworks": []}
    result = assemble_scan_result(_scan(), _import_map(), narrative, "/proj")
    assert result["description"] == "No description available"
