"""Tests for understand_core.types.

There is no standalone ``types.test.ts`` in the TS source (graph types are
exercised via schema/persistence tests), so this verifies the Python contract:
the arch_analysis re-exports are present and the TS-only models round-trip with
their camelCase JSON wire keys.
"""

from __future__ import annotations

from understand_core import types as t


def test_reexports_graph_models_from_arch_analysis():
    # These are aliased from arch_analysis.models per the conversion contract.
    for name in ("GraphNode", "GraphEdge", "KnowledgeGraph", "Layer", "ProjectMeta", "GraphProject"):
        assert hasattr(t, name)
    # ProjectMeta is the TS alias for arch_analysis's GraphProject.
    assert t.ProjectMeta is t.GraphProject


def test_analysis_meta_camelcase_wire_keys():
    meta = t.AnalysisMeta(
        lastAnalyzedAt="2026-03-14T00:00:00.000Z",
        gitCommitHash="abc123",
        version="1.0.0",
        analyzedFiles=42,
    )
    dumped = meta.model_dump(by_alias=True, exclude_none=True)
    assert dumped["lastAnalyzedAt"] == "2026-03-14T00:00:00.000Z"
    assert dumped["analyzedFiles"] == 42
    assert "theme" not in dumped


def test_project_config_default_auto_update_false():
    assert t.ProjectConfig().autoUpdate is False
    assert t.ProjectConfig(autoUpdate=True).autoUpdate is True


def test_domain_meta_entry_type():
    dm = t.DomainMeta(entryPoint="POST /api/orders", entryType="http")
    dumped = dm.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"entryPoint": "POST /api/orders", "entryType": "http"}


def test_theme_config_wire_keys():
    theme = t.ThemeConfig(presetId="dark", accentId="gold")
    assert theme.model_dump() == {"presetId": "dark", "accentId": "gold"}


def test_structural_analysis_accepts_dicts():
    sa = t.StructuralAnalysis(
        functions=[{"name": "main", "lineRange": [1, 10], "params": ["x"]}],
        classes=[],
        imports=[{"source": "./a", "specifiers": ["b"], "lineNumber": 1}],
        exports=[{"name": "main", "lineNumber": 1}],
    )
    assert sa.functions[0].name == "main"
    assert sa.imports[0].source == "./a"


def test_full_node_type_includes_knowledge_variants():
    from typing import get_args

    args = set(get_args(t.FullNodeType))
    assert {"article", "entity", "topic", "claim", "source"}.issubset(args)
    assert {"domain", "flow", "step"}.issubset(args)
