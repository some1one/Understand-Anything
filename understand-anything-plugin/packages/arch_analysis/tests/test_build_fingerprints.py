"""Tests for arch_analysis.build_fingerprints."""

from __future__ import annotations

import json

from arch_analysis.build_fingerprints import (
    build_fingerprint_store,
    content_hash,
    main,
)


def test_content_hash_is_sha256_hex():
    h = content_hash("hello\n")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_build_store_captures_python_signatures(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def foo(a, b):\n    return a + b\n\nclass Bar:\n    def m(self):\n        pass\n"
    )
    store = build_fingerprint_store(tmp_path, ["mod.py"], "abc123")
    assert store["version"] == "1.0.0"
    assert store["gitCommitHash"] == "abc123"
    fp = store["files"]["mod.py"]
    assert fp["hasStructuralAnalysis"] is True
    assert any(f["name"] == "foo" for f in fp["functions"])
    assert any(c["name"] == "Bar" for c in fp["classes"])
    assert fp["contentHash"]


def test_unsupported_file_gets_content_hash_only(tmp_path):
    (tmp_path / "data.bin").write_text("not code at all\n")
    store = build_fingerprint_store(tmp_path, ["data.bin"], "h")
    fp = store["files"]["data.bin"]
    assert fp["hasStructuralAnalysis"] is False
    assert fp["functions"] == []
    assert fp["contentHash"]


def test_missing_file_skipped(tmp_path):
    store = build_fingerprint_store(tmp_path, ["nope.py"], "h")
    assert store["files"] == {}


def test_cli_writes_fingerprints_json(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(
            {"projectRoot": str(tmp_path), "sourceFilePaths": ["a.py"], "gitCommitHash": "deadbeef"}
        )
    )
    rc = main([str(input_path)])
    assert rc == 0
    out = json.loads((tmp_path / ".understand-anything" / "fingerprints.json").read_text())
    assert out["gitCommitHash"] == "deadbeef"
    assert "a.py" in out["files"]


def test_cli_rejects_bad_input(tmp_path):
    input_path = tmp_path / "bad.json"
    input_path.write_text(json.dumps({"projectRoot": str(tmp_path)}))
    assert main([str(input_path)]) == 1
