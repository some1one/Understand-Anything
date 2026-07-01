"""Config-driven tree-sitter analyzer plugin.

Port of ``plugins/tree-sitter-plugin.ts``. The TS version loaded WASM grammars
via ``web-tree-sitter``; here we delegate parsing to ``arch_analysis.treesitter``
(``get_parser`` / ``parse``), which already wires up the Python tree-sitter
grammars. Language-specific structural extraction is dispatched to the builtin
:mod:`understand_core.plugins.extractors`.
"""

from __future__ import annotations

import os
import posixpath
from typing import TYPE_CHECKING, Sequence

from understand_core.plugins.extractors import builtin_extractors

if TYPE_CHECKING:
    from understand_core.plugins.extractors.types import LanguageExtractor, TreeSitterNode
    from understand_core.types import CallGraphEntry, ImportResolution, StructuralAnalysis

try:  # Parser backend lives in the (relocated) arch_analysis package.
    from arch_analysis import treesitter as _ts
except Exception:  # pragma: no cover - arch_analysis not on path in this repo
    _ts = None  # type: ignore[assignment]


def _empty_analysis() -> "StructuralAnalysis":
    return {"functions": [], "classes": [], "imports": [], "exports": []}  # type: ignore[return-value]


# Default extension → language mapping used when no LanguageConfig list is given
# (mirrors the TS backward-compat fallback).
_DEFAULT_EXT_TO_LANG: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
}


class TreeSitterPlugin:
    """Analyzer plugin providing structural analysis for code languages."""

    name = "tree-sitter"

    def __init__(
        self,
        configs: Sequence[object] | None = None,
        extractors: "Sequence[LanguageExtractor] | None" = None,
    ) -> None:
        self._extension_to_lang: dict[str, str] = {}
        langs: list[str] = []

        active_configs: list[object] = []
        if configs:
            for c in configs:
                tree_sitter = (
                    c.get("treeSitter") if isinstance(c, dict)
                    else getattr(c, "tree_sitter", None) or getattr(c, "treeSitter", None)
                )
                if not tree_sitter:
                    continue
                active_configs.append(c)
                cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                exts = c.get("extensions") if isinstance(c, dict) else getattr(c, "extensions", [])
                if cid:
                    langs.append(cid)
                for ext in exts or []:
                    key = ext if ext.startswith(".") else f".{ext}"
                    self._extension_to_lang[key] = cid

        if not langs:
            # Backward-compat default: TS/JS.
            langs.extend(["typescript", "javascript"])
            self._extension_to_lang.update(_DEFAULT_EXT_TO_LANG)

        self._configs = active_configs
        self.languages = langs

        # Register extractors (default: all builtins).
        self._extractors: dict[str, "LanguageExtractor"] = {}
        chosen = list(extractors) if extractors else list(builtin_extractors)
        for extractor in chosen:
            self.register_extractor(extractor)

    # -- extractor management -------------------------------------------------

    def register_extractor(self, extractor: "LanguageExtractor") -> None:
        for lang_id in extractor.language_ids:
            self._extractors[lang_id] = extractor

    def _get_extractor(self, lang_key: str) -> "LanguageExtractor | None":
        # ``tsx`` shares TypeScript's extraction logic.
        key = "typescript" if lang_key == "tsx" else lang_key
        return self._extractors.get(key)

    def _language_key_from_path(self, file_path: str) -> str | None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".tsx":
            return "tsx"
        return self._extension_to_lang.get(ext)

    # -- lifecycle ------------------------------------------------------------

    def init(self) -> None:
        """No-op: ``arch_analysis.treesitter`` lazily loads grammars on demand."""
        return None

    def _parse(self, file_path: str, content: str) -> "TreeSitterNode | None":
        if _ts is None:
            return None
        lang_key = self._language_key_from_path(file_path)
        if lang_key is None:
            return None
        # arch_analysis.treesitter.parse takes our language id and returns the
        # root node directly (None for unknown/unloadable grammars).
        root = _ts.parse(lang_key, content)
        if root is None:
            return None
        from understand_core.plugins.extractors.base_extractor import wrap_root

        return wrap_root(root, content)

    # -- AnalyzerPlugin surface ----------------------------------------------

    def analyze_file(self, file_path: str, content: str) -> "StructuralAnalysis":
        root = self._parse(file_path, content)
        if root is None:
            return _empty_analysis()
        lang_key = self._language_key_from_path(file_path)
        extractor = self._get_extractor(lang_key) if lang_key else None
        if extractor is None:
            return _empty_analysis()
        return extractor.extract_structure(root)

    def resolve_imports(self, file_path: str, content: str) -> "list[ImportResolution]":
        analysis = self.analyze_file(file_path, content)
        directory = posixpath.dirname(file_path)
        resolved: list[ImportResolution] = []
        for imp in analysis.get("imports", []) if isinstance(analysis, dict) else analysis.imports:
            source = imp["source"] if isinstance(imp, dict) else imp.source
            specifiers = imp["specifiers"] if isinstance(imp, dict) else imp.specifiers
            if source.startswith("./") or source.startswith("../"):
                resolved_path = posixpath.normpath(posixpath.join(directory, source))
            else:
                resolved_path = source
            resolved.append(
                {"source": source, "resolvedPath": resolved_path, "specifiers": specifiers}  # type: ignore[arg-type]
            )
        return resolved

    def extract_call_graph(self, file_path: str, content: str) -> "list[CallGraphEntry]":
        root = self._parse(file_path, content)
        if root is None:
            return []
        lang_key = self._language_key_from_path(file_path)
        extractor = self._get_extractor(lang_key) if lang_key else None
        if extractor is None:
            return []
        return extractor.extract_call_graph(root)
