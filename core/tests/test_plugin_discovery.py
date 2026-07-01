"""Port of plugin-discovery.test.ts."""

from __future__ import annotations

import json

from understand_core.plugins.discovery import (
    DEFAULT_PLUGIN_CONFIG,
    PluginConfig,
    PluginEntry,
    default_plugin_config,
    parse_plugin_config,
    serialize_plugin_config,
)


class TestParsePluginConfig:
    def test_parses_valid_config_json(self):
        payload = json.dumps(
            {
                "plugins": [
                    {"name": "tree-sitter", "enabled": True, "languages": ["typescript", "javascript"]},
                    {"name": "python-ast", "enabled": False, "languages": ["python"]},
                ]
            }
        )
        config = parse_plugin_config(payload)
        assert len(config.plugins) == 2
        assert config.plugins[0].name == "tree-sitter"
        assert config.plugins[1].enabled is False

    def test_returns_default_for_invalid_json(self):
        assert parse_plugin_config("not json") == DEFAULT_PLUGIN_CONFIG

    def test_returns_default_for_empty_string(self):
        assert parse_plugin_config("") == DEFAULT_PLUGIN_CONFIG

    def test_filters_out_entries_missing_required_fields(self):
        payload = json.dumps(
            {
                "plugins": [
                    {"name": "valid", "enabled": True, "languages": ["typescript"]},
                    {"enabled": True, "languages": ["python"]},  # missing name
                    {"name": "no-langs", "enabled": True},  # missing languages
                ]
            }
        )
        config = parse_plugin_config(payload)
        assert len(config.plugins) == 1
        assert config.plugins[0].name == "valid"

    def test_defaults_enabled_to_true_when_omitted(self):
        payload = json.dumps({"plugins": [{"name": "tree-sitter", "languages": ["typescript"]}]})
        config = parse_plugin_config(payload)
        assert config.plugins[0].enabled is True

    def test_returns_default_when_plugins_not_array(self):
        payload = json.dumps({"plugins": "not an array"})
        assert parse_plugin_config(payload) == DEFAULT_PLUGIN_CONFIG

    def test_returns_default_when_plugins_missing(self):
        payload = json.dumps({"someOtherField": "value"})
        assert parse_plugin_config(payload) == DEFAULT_PLUGIN_CONFIG


class TestDefaultPluginConfig:
    def test_includes_tree_sitter_enabled_by_default(self):
        assert len(DEFAULT_PLUGIN_CONFIG.plugins) == 1
        assert DEFAULT_PLUGIN_CONFIG.plugins[0].name == "tree-sitter"
        assert DEFAULT_PLUGIN_CONFIG.plugins[0].enabled is True


class TestSerializePluginConfig:
    def test_serializes_to_formatted_json(self):
        config = PluginConfig(
            plugins=[PluginEntry(name="tree-sitter", enabled=True, languages=["typescript", "javascript"])]
        )
        out = serialize_plugin_config(config)
        assert '"name": "tree-sitter"' in out
        assert '"enabled": true' in out
        assert '"languages"' in out

    def test_serializes_config_with_options(self):
        config = PluginConfig(
            plugins=[
                PluginEntry(
                    name="custom-plugin",
                    enabled=True,
                    languages=["python"],
                    options={"strict": True, "timeout": 5000},
                )
            ]
        )
        out = serialize_plugin_config(config)
        assert '"options"' in out
        assert '"strict": true' in out
