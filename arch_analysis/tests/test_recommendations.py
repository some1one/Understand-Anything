"""Tests for the automatable Phase 2 recommendation signals."""

from __future__ import annotations

from arch_analysis.analyze import analyze
from arch_analysis.models import AnalysisInput

from .test_analyze import SAMPLE, SAMPLE_SRC_ONLY


def _rec(sample):
    return analyze(AnalysisInput.model_validate(sample))["phase2Recommendations"]


def test_suggested_layer_by_group():
    rec = _rec(SAMPLE_SRC_ONLY)
    sug = rec["suggestedLayerByGroup"]
    assert sug["routes"] == "layer:api"
    assert sug["services"] == "layer:service"
    assert sug["utils"] == "layer:utility"


def test_group_roles_identify_foundational_utils():
    rec = _rec(SAMPLE_SRC_ONLY)
    # utils is imported by others but imports nothing -> foundational
    assert rec["groupRoles"]["utils"]["role"] == "foundational"
    assert rec["groupRoles"]["utils"]["imports"] == 0
    assert rec["groupRoles"]["utils"]["importedBy"] > 0


def test_topological_order_is_foundational_first():
    rec = _rec(SAMPLE_SRC_ONLY)
    order = rec["topologicalOrder"]
    # routes depends on services depends on utils -> utils before services before routes
    assert order.index("utils") < order.index("services") < order.index("routes")


def test_non_code_layer_suggestions():
    rec = _rec(SAMPLE)
    by_id = {s["layerId"]: s for s in rec["nonCodeLayerSuggestions"]}
    assert by_id["layer:infrastructure"]["recommended"] is True
    assert "service:Dockerfile" in by_id["layer:infrastructure"]["nodeIds"]
    assert by_id["layer:ci-cd"]["recommended"] is True
    # only one document node -> below the 3-doc threshold
    assert by_id["layer:documentation"]["recommended"] is False


def test_default_layer_assignment_covers_every_node():
    result = analyze(AnalysisInput.model_validate(SAMPLE))
    rec = result["phase2Recommendations"]
    assignment = rec["defaultLayerAssignment"]
    input_ids = {n for ids in result["directoryGroups"].values() for n in ids}
    assert set(assignment) == input_ids
    # non-code nodes map by type
    assert assignment["service:Dockerfile"] == "layer:infrastructure"
    assert assignment["document:README.md"] == "layer:documentation"
    assert assignment["config:tsconfig.json"] == "layer:config"
    assert assignment["pipeline:.github/workflows/ci.yml"] == "layer:ci-cd"
