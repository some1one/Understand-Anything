"""Plugin configuration discovery / parsing.

Faithful port of ``plugins/discovery.ts``. Parses and serializes the
``plugins`` config block used to decide which analyzer plugins are enabled.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

try:  # The language configs live in a sibling cluster.
    from understand_core.languages.configs import builtin_language_configs
except Exception:  # pragma: no cover - configs cluster may not be present yet
    builtin_language_configs = []  # type: ignore[assignment]


class PluginEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    enabled: bool = True
    languages: list[str] = Field(default_factory=list)
    options: dict[str, Any] | None = None


class PluginConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    plugins: list[PluginEntry] = Field(default_factory=list)


def _default_languages() -> list[str]:
    langs: list[str] = []
    for config in builtin_language_configs:
        tree_sitter = (
            config.get("treeSitter")
            if isinstance(config, dict)
            else getattr(config, "tree_sitter", None) or getattr(config, "treeSitter", None)
        )
        if not tree_sitter:
            continue
        cid = config.get("id") if isinstance(config, dict) else getattr(config, "id", None)
        if cid:
            langs.append(cid)
    return langs


def default_plugin_config() -> PluginConfig:
    """Build a fresh default plugin config (tree-sitter enabled)."""
    return PluginConfig(
        plugins=[
            PluginEntry(
                name="tree-sitter",
                enabled=True,
                languages=_default_languages(),
            )
        ]
    )


# Module-level constant mirroring DEFAULT_PLUGIN_CONFIG. Consumers that mutate
# should copy via ``default_plugin_config()``.
DEFAULT_PLUGIN_CONFIG: PluginConfig = default_plugin_config()


def parse_plugin_config(json_string: str) -> PluginConfig:
    """Parse a plugin config JSON string; return the default on any failure."""
    if not json_string.strip():
        return default_plugin_config()

    try:
        parsed = json.loads(json_string)
    except (ValueError, TypeError):
        return default_plugin_config()

    if not isinstance(parsed, dict) or not isinstance(parsed.get("plugins"), list):
        return default_plugin_config()

    entries: list[PluginEntry] = []
    for entry in parsed["plugins"]:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        languages = entry.get("languages")
        if not (isinstance(name, str) and name):
            continue
        if not (isinstance(languages, list) and len(languages) > 0):
            continue
        enabled = entry["enabled"] if isinstance(entry.get("enabled"), bool) else True
        options = entry.get("options") if isinstance(entry.get("options"), dict) else None
        entries.append(
            PluginEntry(name=name, enabled=enabled, languages=list(languages), options=options)
        )

    return PluginConfig(plugins=entries)


def serialize_plugin_config(config: PluginConfig) -> str:
    """Serialize a plugin config to pretty JSON (2-space indent), omitting nulls."""
    payload = {
        "plugins": [
            {
                "name": e.name,
                "enabled": e.enabled,
                "languages": e.languages,
                **({"options": e.options} if e.options is not None else {}),
            }
            for e in config.plugins
        ]
    }
    return json.dumps(payload, indent=2)
