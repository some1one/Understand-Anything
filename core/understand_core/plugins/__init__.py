"""Analyzer plugins: tree-sitter, registry, discovery, extractors, parsers.

Mirrors the public surface re-exported across the TS ``plugins/`` modules.
"""

from __future__ import annotations

from understand_core.plugins.discovery import (
    DEFAULT_PLUGIN_CONFIG,
    PluginConfig,
    PluginEntry,
    default_plugin_config,
    parse_plugin_config,
    serialize_plugin_config,
)
from understand_core.plugins.parsers import register_all_parsers
from understand_core.plugins.registry import AnalyzerPlugin, PluginRegistry
from understand_core.plugins.tree_sitter_plugin import TreeSitterPlugin

__all__ = [
    "TreeSitterPlugin",
    "PluginRegistry",
    "AnalyzerPlugin",
    "register_all_parsers",
    "parse_plugin_config",
    "serialize_plugin_config",
    "default_plugin_config",
    "PluginConfig",
    "PluginEntry",
    "DEFAULT_PLUGIN_CONFIG",
]
