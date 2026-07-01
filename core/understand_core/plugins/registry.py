"""Analyzer plugin registry.

Port of ``plugins/registry.ts``. Maps languages to analyzer plugins and routes
files to the right plugin via a :class:`LanguageRegistry`.

Where possible this wraps the Python ``arch_analysis.structure.registry``; the
extension→language mapping is obtained from ``understand_core.languages`` (the
``LanguageRegistry`` cluster) with a graceful fallback so the registry remains
usable for the pure-logic plugin tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from understand_core.types import (
        CallGraphEntry,
        ImportResolution,
        StructuralAnalysis,
    )

try:  # Cross-cluster: provided by the languages registry port.
    from understand_core.languages.language_registry import LanguageRegistry
except Exception:  # pragma: no cover - fallback when that cluster isn't present
    LanguageRegistry = None  # type: ignore[assignment]


@runtime_checkable
class AnalyzerPlugin(Protocol):
    """Structural interface implemented by every analyzer plugin/parser.

    ``resolve_imports``, ``extract_call_graph`` and ``extract_references`` are
    optional (non-code parsers omit them). Mirrors the TS ``AnalyzerPlugin``.
    """

    name: str
    languages: list[str]

    def analyze_file(self, file_path: str, content: str) -> "StructuralAnalysis": ...


class PluginRegistry:
    """Registry mapping languages → analyzer plugins."""

    def __init__(self, language_registry: object | None = None) -> None:
        self._plugins: list[AnalyzerPlugin] = []
        self._language_map: dict[str, AnalyzerPlugin] = {}
        if language_registry is not None:
            self._language_registry = language_registry
        elif LanguageRegistry is not None:
            self._language_registry = LanguageRegistry.create_default()
        else:  # pragma: no cover - only when languages cluster missing
            self._language_registry = None

    def register(self, plugin: AnalyzerPlugin) -> None:
        self._plugins.append(plugin)
        for lang in plugin.languages:
            self._language_map[lang] = plugin

    def unregister(self, name: str) -> None:
        if not any(p.name == name for p in self._plugins):
            return
        self._plugins = [p for p in self._plugins if p.name != name]
        self._language_map.clear()
        for p in self._plugins:
            for lang in p.languages:
                self._language_map[lang] = p

    def get_plugin_for_language(self, language: str) -> AnalyzerPlugin | None:
        return self._language_map.get(language)

    def _language_id_for_file(self, file_path: str) -> str | None:
        if self._language_registry is None:  # pragma: no cover
            return None
        config = self._language_registry.get_for_file(file_path)
        if config is None:
            return None
        return config.get("id") if isinstance(config, dict) else getattr(config, "id", None)

    def get_plugin_for_file(self, file_path: str) -> AnalyzerPlugin | None:
        lang_id = self._language_id_for_file(file_path)
        if lang_id is None:
            return None
        return self.get_plugin_for_language(lang_id)

    def get_language_for_file(self, file_path: str) -> str | None:
        return self._language_id_for_file(file_path)

    def analyze_file(self, file_path: str, content: str) -> "StructuralAnalysis | None":
        plugin = self.get_plugin_for_file(file_path)
        if plugin is None:
            return None
        return plugin.analyze_file(file_path, content)

    def resolve_imports(
        self, file_path: str, content: str
    ) -> "list[ImportResolution] | None":
        plugin = self.get_plugin_for_file(file_path)
        resolve = getattr(plugin, "resolve_imports", None)
        if plugin is None or resolve is None:
            return None
        return resolve(file_path, content)

    def extract_call_graph(
        self, file_path: str, content: str
    ) -> "list[CallGraphEntry] | None":
        plugin = self.get_plugin_for_file(file_path)
        extract = getattr(plugin, "extract_call_graph", None)
        if plugin is None or extract is None:
            return None
        return extract(file_path, content)

    def get_plugins(self) -> list[AnalyzerPlugin]:
        return list(self._plugins)

    def get_supported_languages(self) -> list[str]:
        return list(self._language_map.keys())
