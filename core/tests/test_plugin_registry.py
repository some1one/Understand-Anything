"""Port of plugin-registry.test.ts.

File-path based lookups depend on the LanguageRegistry cluster
(``understand_core.languages.language_registry``); those cases are skipped when
that cluster is not yet importable so the language-map logic can still be
exercised in isolation.
"""

from __future__ import annotations

import pytest

from understand_core.plugins.parsers import register_all_parsers
from understand_core.plugins.registry import PluginRegistry

try:
    from understand_core.languages.language_registry import LanguageRegistry as _LR

    _HAVE_LANG_REGISTRY = _LR is not None
except Exception:
    _HAVE_LANG_REGISTRY = False

needs_lang_registry = pytest.mark.skipif(
    not _HAVE_LANG_REGISTRY, reason="LanguageRegistry cluster not available"
)

EMPTY_ANALYSIS = {"functions": [], "classes": [], "imports": [], "exports": []}


class MockPlugin:
    def __init__(self, name: str, languages: list[str]):
        self.name = name
        self.languages = languages

    def analyze_file(self, file_path, content):
        return dict(EMPTY_ANALYSIS)

    def resolve_imports(self, file_path, content):
        return []


def test_registers_a_plugin():
    registry = PluginRegistry()
    registry.register(MockPlugin("test", ["typescript"]))
    assert len(registry.get_plugins()) == 1


def test_finds_plugin_by_language():
    registry = PluginRegistry()
    plugin = MockPlugin("ts-plugin", ["typescript", "javascript"])
    registry.register(plugin)
    assert registry.get_plugin_for_language("typescript") is plugin
    assert registry.get_plugin_for_language("javascript") is plugin


def test_returns_none_for_unsupported_language():
    registry = PluginRegistry()
    registry.register(MockPlugin("ts-plugin", ["typescript"]))
    assert registry.get_plugin_for_language("python") is None


@needs_lang_registry
def test_finds_plugin_by_file_extension():
    registry = PluginRegistry()
    plugin = MockPlugin("ts-plugin", ["typescript"])
    registry.register(plugin)
    assert registry.get_plugin_for_file("src/index.ts") is plugin
    assert registry.get_plugin_for_file("src/app.tsx") is plugin


@needs_lang_registry
def test_maps_common_extensions_to_languages():
    registry = PluginRegistry()
    plugin = MockPlugin("multi", ["python", "go", "rust"])
    registry.register(plugin)
    assert registry.get_plugin_for_file("main.py") is plugin
    assert registry.get_plugin_for_file("main.go") is plugin
    assert registry.get_plugin_for_file("main.rs") is plugin


def test_lists_all_registered_plugins():
    registry = PluginRegistry()
    registry.register(MockPlugin("a", ["typescript"]))
    registry.register(MockPlugin("b", ["python"]))
    assert len(registry.get_plugins()) == 2


def test_lists_supported_languages():
    registry = PluginRegistry()
    registry.register(MockPlugin("a", ["typescript", "javascript"]))
    registry.register(MockPlugin("b", ["python"]))
    langs = registry.get_supported_languages()
    assert "typescript" in langs
    assert "python" in langs


def test_unregisters_a_plugin_by_name():
    registry = PluginRegistry()
    registry.register(MockPlugin("removable", ["typescript"]))
    assert len(registry.get_plugins()) == 1
    registry.unregister("removable")
    assert len(registry.get_plugins()) == 0


def test_later_registration_takes_priority():
    registry = PluginRegistry()
    registry.register(MockPlugin("first", ["typescript"]))
    second = MockPlugin("second", ["typescript"])
    registry.register(second)
    assert registry.get_plugin_for_language("typescript").name == "second"


@needs_lang_registry
def test_analyze_file_delegates_to_correct_plugin():
    registry = PluginRegistry()
    plugin = MockPlugin("ts-plugin", ["typescript"])
    plugin.analyze_file = lambda fp, c: {
        **EMPTY_ANALYSIS,
        "functions": [{"name": "hello", "lineRange": [1, 5], "params": []}],
    }
    registry.register(plugin)
    result = registry.analyze_file("src/test.ts", "const x = 1;")
    assert result is not None
    assert len(result["functions"]) == 1


@needs_lang_registry
def test_analyze_file_returns_none_for_unsupported():
    registry = PluginRegistry()
    registry.register(MockPlugin("ts-plugin", ["typescript"]))
    assert registry.analyze_file("main.py", "print('hello')") is None


def test_unregister_rebuilds_language_map():
    registry = PluginRegistry()
    plugin1 = MockPlugin("plugin1", ["typescript", "javascript"])
    plugin2 = MockPlugin("plugin2", ["python"])
    registry.register(plugin1)
    registry.register(plugin2)
    assert registry.get_plugin_for_language("typescript") is plugin1
    assert registry.get_plugin_for_language("python") is plugin2
    registry.unregister("plugin1")
    assert registry.get_plugin_for_language("typescript") is None
    assert registry.get_plugin_for_language("python") is plugin2


def test_unregister_noop_for_nonexistent():
    registry = PluginRegistry()
    plugin = MockPlugin("existing", ["typescript"])
    registry.register(plugin)
    registry.unregister("non-existent")
    assert len(registry.get_plugins()) == 1
    assert registry.get_plugin_for_language("typescript") is plugin


@needs_lang_registry
def test_get_language_for_file_returns_id():
    registry = PluginRegistry()
    registry.register(MockPlugin("ts-plugin", ["typescript"]))
    assert registry.get_language_for_file("src/index.ts") == "typescript"
    assert registry.get_language_for_file("src/component.tsx") == "typescript"


@needs_lang_registry
def test_get_language_for_file_returns_none_for_unsupported():
    registry = PluginRegistry()
    registry.register(MockPlugin("ts-plugin", ["typescript"]))
    assert registry.get_language_for_file("unknown.xyz") is None


@needs_lang_registry
def test_resolve_imports_delegates():
    registry = PluginRegistry()
    plugin = MockPlugin("ts-plugin", ["typescript"])
    mock_imports = [{"source": "./utils", "resolvedPath": "./utils.ts", "specifiers": []}]
    plugin.resolve_imports = lambda fp, c: mock_imports
    registry.register(plugin)
    result = registry.resolve_imports("src/index.ts", "import './utils'")
    assert result == mock_imports


@needs_lang_registry
def test_resolve_imports_returns_none_for_unsupported():
    registry = PluginRegistry()
    registry.register(MockPlugin("ts-plugin", ["typescript"]))
    assert registry.resolve_imports("main.py", "import os") is None


@needs_lang_registry
def test_handles_plugins_without_resolve_imports():
    class MarkdownLike:
        name = "markdown"
        languages = ["markdown"]

        def analyze_file(self, fp, c):
            return dict(EMPTY_ANALYSIS)

    registry = PluginRegistry()
    registry.register(MarkdownLike())
    assert registry.resolve_imports("README.md", "# Hello") is None


def test_register_all_parsers_registers_12():
    registry = PluginRegistry()
    register_all_parsers(registry)
    assert len(registry.get_plugins()) == 12
    langs = registry.get_supported_languages()
    for lang in ["markdown", "yaml", "json", "toml", "env", "dockerfile", "sql", "graphql", "protobuf", "terraform", "makefile", "shell"]:
        assert lang in langs
