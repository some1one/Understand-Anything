"""Tests for arch_analysis.extract_structure.

Port of understand-anything-plugin/src/__tests__/extract-structure.test.mjs
(``buildResult`` semantics: importCount fallback incl. empty-array regression,
totalLines wc -l semantics, language pass-through) plus end-to-end extraction
tests that run real snippets through the full pipeline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from arch_analysis.extract_structure import build_result, count_lines, run
from arch_analysis.structure import StructuralAnalysis, analyze_file, extract_call_graph


def _file(**overrides) -> dict:
    base = {"path": "src/foo.py", "language": "python", "fileCategory": "code"}
    base.update(overrides)
    return base


def _analysis(**overrides) -> StructuralAnalysis:
    return StructuralAnalysis(
        functions=overrides.get("functions", []),
        classes=overrides.get("classes", []),
        imports=overrides.get("imports", []),
        exports=overrides.get("exports", []),
    )


# ---------------------------------------------------------------------------
# buildResult: language pass-through
# ---------------------------------------------------------------------------


class TestLanguagePassThrough:
    def test_preserves_input_language(self):
        result = build_result(_file(language="python"), 10, 8, _analysis(), None, {})
        assert result["language"] == "python"

    def test_preserves_none_when_no_language(self):
        result = build_result(_file(language=None), 10, 8, _analysis(), None, {})
        assert result["language"] is None


# ---------------------------------------------------------------------------
# buildResult: importCount fallback
# ---------------------------------------------------------------------------


class TestImportCountFallback:
    def _analysis_with_imports(self) -> StructuralAnalysis:
        return _analysis(
            imports=[
                {"source": ".helpers", "specifiers": []},
                {"source": "..util", "specifiers": []},
                {"source": "./local", "specifiers": []},
            ]
        )

    def test_uses_preresolved_when_batch_has_entries(self):
        batch = {"src/foo.py": ["src/bar.py", "src/baz.py"]}
        result = build_result(_file(), 10, 8, self._analysis_with_imports(), None, batch)
        assert result["metrics"]["importCount"] == 2

    def test_falls_back_when_batch_entry_is_empty_array(self):
        # Regression: empty arrays must fall back to the parser's count.
        batch = {"src/foo.py": []}
        result = build_result(_file(), 10, 8, self._analysis_with_imports(), None, batch)
        assert result["metrics"]["importCount"] == 3

    def test_falls_back_when_no_entry_for_file(self):
        result = build_result(_file(), 10, 8, self._analysis_with_imports(), None, {})
        assert result["metrics"]["importCount"] == 3

    def test_falls_back_when_batch_is_none(self):
        result = build_result(_file(), 10, 8, self._analysis_with_imports(), None, None)
        assert result["metrics"]["importCount"] == 3

    def test_reports_zero_when_neither_has_imports(self):
        result = build_result(_file(), 10, 8, _analysis(), None, {"src/foo.py": []})
        assert result["metrics"]["importCount"] == 0

    def test_excludes_external_package_imports(self):
        ext = _analysis(
            imports=[
                {"source": "os", "specifiers": []},
                {"source": "sys", "specifiers": []},
                {"source": "./local", "specifiers": []},
            ]
        )
        result = build_result(_file(), 10, 8, ext, None, {})
        assert result["metrics"]["importCount"] == 1


# ---------------------------------------------------------------------------
# totalLines (wc -l semantics)
# ---------------------------------------------------------------------------


class TestTotalLines:
    def test_trailing_newline_file(self):
        total, _ = count_lines("a\nb\nc\n")
        assert total == 3

    def test_no_trailing_newline(self):
        total, _ = count_lines("a\nb\nc")
        assert total == 3

    def test_non_empty_lines(self):
        total, non_empty = count_lines("a\n\n  \nb\n")
        assert total == 4
        assert non_empty == 2

    def test_empty_content(self):
        total, non_empty = count_lines("")
        assert total == 1  # split("") -> [""], no trailing newline
        assert non_empty == 0


# ---------------------------------------------------------------------------
# buildResult: no analysis -> basic metrics only
# ---------------------------------------------------------------------------


def test_no_analysis_returns_basic_metrics():
    result = build_result(_file(), 5, 4, None, None, {})
    assert result["metrics"] == {}
    assert "functions" not in result
    assert result["totalLines"] == 5


# ---------------------------------------------------------------------------
# End-to-end extraction through the full pipeline
# ---------------------------------------------------------------------------


class TestPythonExtraction:
    SRC = (
        "import os\n"
        "from .helpers import thing\n"
        "from typing import List\n"
        "\n"
        "GLOBAL = 1\n"
        "\n"
        "def top(a, b=2, *args, **kw):\n"
        "    return helper(a)\n"
        "\n"
        "class Widget:\n"
        "    name: str\n"
        "    def method(self, x):\n"
        "        return self.compute(x)\n"
    )

    def test_functions_classes_exports(self):
        a = analyze_file("src/foo.py", self.SRC)
        assert a is not None
        fn_names = {f["name"] for f in a.functions}
        assert "top" in fn_names
        # Python's extractor (like core's) lists class methods only in the
        # class's `methods` array, not the top-level `functions` array.
        assert "method" not in fn_names
        top = next(f for f in a.functions if f["name"] == "top")
        assert top["params"] == ["a", "b", "*args", "**kw"]
        cls = next(c for c in a.classes if c["name"] == "Widget")
        assert "method" in cls["methods"]
        assert "name" in cls["properties"]
        export_names = {e["name"] for e in a.exports}
        assert {"top", "Widget"} <= export_names

    def test_imports_relative_vs_external(self):
        a = analyze_file("src/foo.py", self.SRC)
        sources = [imp["source"] for imp in a.imports]
        assert "os" in sources
        assert ".helpers" in sources
        # build_result fallback counts only relative imports.
        result = build_result(_file(), *count_lines(self.SRC), a, None, {})
        assert result["metrics"]["importCount"] == 1

    def test_call_graph(self):
        cg = extract_call_graph("src/foo.py", self.SRC)
        pairs = {(e["caller"], e["callee"]) for e in cg}
        assert ("top", "helper") in pairs
        assert ("method", "self.compute") in pairs


class TestTypeScriptExtraction:
    SRC = (
        "import { a } from './a';\n"
        "import x from 'pkg';\n"
        "export function greet(name: string): string {\n"
        "  return format(name);\n"
        "}\n"
        "export class Service {\n"
        "  field = 1;\n"
        "  run(): void {}\n"
        "}\n"
        "export const value = 42;\n"
    )

    def test_structure(self):
        a = analyze_file("src/x.ts", self.SRC)
        assert a is not None
        assert any(f["name"] == "greet" for f in a.functions)
        svc = next(c for c in a.classes if c["name"] == "Service")
        assert "run" in svc["methods"]
        assert "field" in svc["properties"]
        export_names = {e["name"] for e in a.exports}
        assert {"greet", "Service", "value"} <= export_names

    def test_imports(self):
        a = analyze_file("src/x.ts", self.SRC)
        sources = [imp["source"] for imp in a.imports]
        assert "./a" in sources
        assert "pkg" in sources


class TestGoExtraction:
    SRC = (
        "package main\n"
        "\n"
        'import "fmt"\n'
        "\n"
        "type Server struct {\n"
        "    Host string\n"
        "}\n"
        "\n"
        "func (s *Server) Start() error {\n"
        "    return run()\n"
        "}\n"
        "\n"
        "func main() {\n"
        "    fmt.Println(\"hi\")\n"
        "}\n"
    )

    def test_structure(self):
        a = analyze_file("main.go", self.SRC)
        assert a is not None
        cls = next(c for c in a.classes if c["name"] == "Server")
        assert "Host" in cls["properties"]
        assert "Start" in cls["methods"]  # method attached via receiver
        export_names = {e["name"] for e in a.exports}
        assert "Server" in export_names
        assert "Start" in export_names
        assert "main" not in export_names  # lowercase = unexported

    def test_call_graph(self):
        cg = extract_call_graph("main.go", self.SRC)
        pairs = {(e["caller"], e["callee"]) for e in cg}
        assert ("Start", "run") in pairs


class TestKotlinExtraction:
    SRC = (
        "package x\n"
        "import a.b.C\n"
        "private fun secret() {}\n"
        "class Widget(val id: Int, name: String) {\n"
        '  val title: String = ""\n'
        "  fun run(): Int { return obj.go() }\n"
        "}\n"
        "fun top(a: Int): Int = a\n"
    )

    def test_structure(self):
        a = analyze_file("a.kt", self.SRC)
        assert a is not None
        fn_names = {f["name"] for f in a.functions}
        assert {"secret", "run", "top"} <= fn_names
        cls = next(c for c in a.classes if c["name"] == "Widget")
        assert "run" in cls["methods"]
        # `val id` (constructor) and `val title` (body) are properties; the
        # plain `name` constructor param is not.
        assert cls["properties"] == ["id", "title"]
        export_names = {e["name"] for e in a.exports}
        assert {"Widget", "run", "top", "title"} <= export_names
        assert "secret" not in export_names  # private is not exported
        assert any(i["source"] == "a.b.C" for i in a.imports)

    def test_call_graph(self):
        cg = extract_call_graph("a.kt", self.SRC)
        assert ("run", "go") in {(e["caller"], e["callee"]) for e in cg}


class TestSQLExtraction:
    SRC = (
        "CREATE TABLE users (\n"
        "  id INTEGER PRIMARY KEY,\n"
        "  email TEXT,\n"
        "  PRIMARY KEY (id)\n"
        ");\n"
        "\n"
        "CREATE VIEW active_users AS SELECT * FROM users;\n"
        "CREATE INDEX idx_email ON users(email);\n"
    )

    def test_definitions(self):
        a = analyze_file("schema.sql", self.SRC)
        assert a is not None
        by_kind = {d["kind"]: d for d in a.definitions}
        assert "table" in by_kind
        assert by_kind["table"]["name"] == "users"
        assert by_kind["table"]["fields"] == ["id", "email"]  # PRIMARY KEY skipped
        assert any(d["kind"] == "view" and d["name"] == "active_users" for d in a.definitions)
        assert any(d["kind"] == "index" and d["name"] == "idx_email" for d in a.definitions)

    def test_metrics(self):
        a = analyze_file("schema.sql", self.SRC)
        result = build_result(
            {"path": "schema.sql", "language": "sql", "fileCategory": "data"},
            *count_lines(self.SRC),
            a,
            None,
            {},
        )
        assert result["metrics"]["definitionCount"] == 3
        assert len(result["definitions"]) == 3


class TestMarkdownExtraction:
    SRC = (
        "# Title\n"
        "\n"
        "Intro text.\n"
        "\n"
        "## Section A\n"
        "\n"
        "```\n"
        "# not a heading (inside fence)\n"
        "```\n"
        "\n"
        "### Sub\n"
    )

    def test_sections(self):
        a = analyze_file("README.md", self.SRC)
        assert a is not None
        headings = [(s["name"], s["level"]) for s in a.sections]
        assert ("Title", 1) in headings
        assert ("Section A", 2) in headings
        assert ("Sub", 3) in headings
        # The fenced "# not a heading" must be ignored.
        assert all("not a heading" not in s["name"] for s in a.sections)

    def test_build_result_sections(self):
        a = analyze_file("README.md", self.SRC)
        result = build_result(
            {"path": "README.md", "language": "markdown", "fileCategory": "docs"},
            *count_lines(self.SRC),
            a,
            None,
            {},
        )
        assert result["metrics"]["sectionCount"] == 3
        assert result["sections"][0] == {"heading": "Title", "level": 1, "line": 1}


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------


def test_cli_end_to_end(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "mod.py").write_text(
        "from .other import x\n\ndef f():\n    return g()\n", encoding="utf-8"
    )
    (project / "missing_ref.py")  # not created -> should be skipped

    input_data = {
        "projectRoot": str(project),
        "batchFiles": [
            {"path": "mod.py", "language": "python", "sizeLines": 4, "fileCategory": "code"},
            {"path": "nope.py", "language": "python", "sizeLines": 0, "fileCategory": "code"},
        ],
        "batchImportData": {},
    }
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.json"
    input_path.write_text(json.dumps(input_data), encoding="utf-8")

    run(str(input_path), str(output_path))
    out = json.loads(output_path.read_text(encoding="utf-8"))

    assert out["scriptCompleted"] is True
    assert out["filesAnalyzed"] == 1
    assert out["filesSkipped"] == ["nope.py"]
    res = out["results"][0]
    assert res["path"] == "mod.py"
    assert res["metrics"]["importCount"] == 1  # ".other" is relative
    assert any(f["name"] == "f" for f in res["functions"])
    assert res["callGraph"][0]["caller"] == "f"
    assert res["callGraph"][0]["callee"] == "g"


def test_cli_module_invocation(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.ts").write_text("export const z = 1;\n", encoding="utf-8")
    input_data = {
        "projectRoot": str(project),
        "batchFiles": [{"path": "a.ts", "language": "typescript", "sizeLines": 1, "fileCategory": "code"}],
        "batchImportData": {},
    }
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.json"
    input_path.write_text(json.dumps(input_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "arch_analysis.extract_structure", str(input_path), str(output_path)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(output_path.read_text(encoding="utf-8"))
    assert out["filesAnalyzed"] == 1
    assert any(e["name"] == "z" for e in out["results"][0]["exports"])
