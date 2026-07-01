"""Port of tree-sitter-plugin.test.ts.

The TS plugin loaded WASM grammars; this Python port delegates parsing to
``arch_analysis.treesitter``. When that backend (or its grammars) is not
available, the whole module is skipped — the extractor unit tests cover the
per-language extraction logic directly.
"""

from __future__ import annotations

import pytest

from understand_core.plugins.tree_sitter_plugin import TreeSitterPlugin

# The plugin can only analyze if the arch_analysis tree-sitter backend resolves.
try:
    from arch_analysis import treesitter as _ts  # noqa: F401

    _HAVE_BACKEND = True
except Exception:
    _HAVE_BACKEND = False

pytestmark = pytest.mark.skipif(
    not _HAVE_BACKEND, reason="arch_analysis.treesitter backend not available"
)


@pytest.fixture(scope="module")
def plugin() -> TreeSitterPlugin:
    p = TreeSitterPlugin()
    p.init()
    return p


class TestAnalyzeFile:
    def test_extracts_function_declarations(self, plugin):
        code = (
            "\nfunction greet(name: string): string {\n  return \"Hello \" + name;\n}\n\n"
            "function add(a: number, b: number): number {\n  return a + b;\n}\n"
        )
        result = plugin.analyze_file("test.ts", code)
        assert len(result["functions"]) == 2
        assert result["functions"][0]["name"] == "greet"
        assert result["functions"][0]["params"] == ["name"]
        assert result["functions"][0]["returnType"] == "string"

    def test_extracts_class_with_methods(self, plugin):
        code = (
            "\nclass Calculator {\n  private value: number;\n  public name: string;\n\n"
            "  constructor(initial: number) {\n    this.value = initial;\n  }\n\n"
            "  add(n: number): number {\n    return this.value + n;\n  }\n}\n"
        )
        result = plugin.analyze_file("test.ts", code)
        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "Calculator"
        assert "constructor" in cls["methods"]
        assert "add" in cls["methods"]
        assert "value" in cls["properties"]
        assert "name" in cls["properties"]

    def test_extracts_imports(self, plugin):
        code = (
            "\nimport { foo, bar } from './utils';\nimport * as path from 'path';\n"
            "import type { MyType } from './types';\nimport defaultExport from './module';\n"
        )
        result = plugin.analyze_file("test.ts", code)
        assert len(result["imports"]) == 4
        assert result["imports"][0]["source"] == "./utils"
        assert result["imports"][0]["specifiers"] == ["foo", "bar"]


class TestResolveImports:
    def test_resolves_relative_imports(self, plugin):
        code = (
            "\nimport { foo } from './utils';\nimport { bar } from '../shared/helpers';\n"
            "import * as path from 'path';\n"
        )
        result = plugin.resolve_imports("/project/src/index.ts", code)
        assert len(result) == 3
        assert result[0]["source"] == "./utils"
        assert "utils" in result[0]["resolvedPath"]
        assert result[2]["source"] == "path"
        assert result[2]["resolvedPath"] == "path"


class TestExtractCallGraph:
    def test_extracts_function_calls(self, plugin):
        code = (
            "\nfunction greet(name: string): string {\n  return formatMessage(\"Hello \" + name);\n}\n\n"
            "function formatMessage(msg: string): string {\n  return msg.trim();\n}\n\n"
            "function main() {\n  const result = greet(\"World\");\n  console.log(result);\n}\n"
        )
        result = plugin.extract_call_graph("test.ts", code)
        assert len(result) > 0
        assert any(e["caller"] == "main" and e["callee"] == "greet" for e in result)


class TestMetadata:
    def test_has_correct_name(self, plugin):
        assert plugin.name == "tree-sitter"

    def test_supports_typescript_and_javascript(self, plugin):
        assert "typescript" in plugin.languages
        assert "javascript" in plugin.languages
