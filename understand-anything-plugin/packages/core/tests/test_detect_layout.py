"""Tests for understand_core.detect_layout."""

from __future__ import annotations

from understand_core.detect_layout import detect_layout


def test_single_src_folder():
    files = ["README.md", "package.json", "src/main.ts", "src/api/h.ts"]
    result = detect_layout(files)
    assert result["recommendation"] == {"sourceFolders": ["src"], "splitDepth": 1}
    assert result["detectedRoots"] == ["src"]


def test_prefers_src_over_other_candidates():
    files = ["src/a.ts", "lib/b.ts", "app/c.ts"]
    assert detect_layout(files)["recommendation"]["sourceFolders"] == ["src"]


def test_lib_when_no_src():
    files = ["lib/b.ts", "docs/readme.md"]
    assert detect_layout(files)["recommendation"]["sourceFolders"] == ["lib"]


def test_monorepo_by_workspace_marker():
    files = ["pnpm-workspace.yaml", "packages/a/index.ts", "src/x.ts"]
    result = detect_layout(files)
    assert result["recommendation"] == {"sourceFolders": None, "splitDepth": 2}


def test_monorepo_by_nested_manifests():
    files = [
        "packages/a/package.json",
        "packages/a/src/x.ts",
        "packages/b/pyproject.toml",
        "packages/b/mod.py",
    ]
    result = detect_layout(files)
    assert result["recommendation"] == {"sourceFolders": None, "splitDepth": 2}
    assert result["detectedRoots"] == ["packages/a", "packages/b"]


def test_single_nested_manifest_is_not_monorepo():
    files = ["packages/a/package.json", "packages/a/x.ts", "src/main.ts"]
    # Only one sub-package → not a monorepo; falls through to single-source.
    result = detect_layout(files)
    assert result["recommendation"] == {"sourceFolders": ["src"], "splitDepth": 1}


def test_flat_repo():
    files = ["main.py", "utils.py", "helpers/io.py"]
    result = detect_layout(files)
    assert result["recommendation"] == {"sourceFolders": None, "splitDepth": 1}
    assert result["detectedRoots"] == []
