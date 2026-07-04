"""Graph data types — port of ``packages/core/src/types.ts``.

Per the conversion contract, graph types are canonical here and *re-exported*
from :mod:`arch_analysis.models` where an equivalent already exists. Only the
TS-only types that arch_analysis does not carry are defined fresh.

JSON wire keys stay camelCase (``filePath``, ``lineRange``, ``languageNotes``),
matching arch_analysis pydantic conventions (``populate_by_name`` + aliases).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Re-export the canonical graph models from arch_analysis.
#
# arch_analysis.models already defines GraphNode / GraphEdge / KnowledgeGraph /
# Layer / GraphProject and the enum literals. We alias them so the rest of the
# Python port imports graph types from ``understand_core.types`` (the contract).
# ---------------------------------------------------------------------------
from arch_analysis.models import (  # noqa: E402
    Complexity,
    Direction,
    DomainGraph,
    DomainNode,
    DomainNodeType,
    Edge,
    EdgeType,
    GraphEdge,
    GraphFragment,
    GraphNode,
    GraphProject,
    KnowledgeGraph,
    Layer,
    NodeType,
)

# arch_analysis names the project-metadata block ``GraphProject``; the TS source
# calls it ``ProjectMeta``. Expose both names.
ProjectMeta = GraphProject

# ---------------------------------------------------------------------------
# Full NodeType / EdgeType unions (TS schema.ts carries the knowledge-graph
# variants — article/entity/topic/claim/source and the knowledge edges — that
# arch_analysis.models omits). These mirror schema.ts exactly.
# ---------------------------------------------------------------------------

FullNodeType = Literal[
    "file", "function", "class", "module", "concept",
    "config", "document", "service", "table", "endpoint",
    "pipeline", "schema", "resource",
    "domain", "flow", "step",
    "article", "entity", "topic", "claim", "source",
]

FullEdgeType = Literal[
    "imports", "exports", "contains", "inherits", "implements",
    "calls", "subscribes", "publishes", "middleware",
    "reads_from", "writes_to", "transforms", "validates",
    "depends_on", "tested_by", "configures",
    "related", "similar_to",
    "deploys", "serves", "provisions", "triggers",
    "migrates", "documents", "routes", "defines_schema",
    "contains_flow", "flow_step", "cross_domain",
    "cites", "contradicts", "builds_on", "exemplifies",
    "categorized_under", "authored_by",
]

EntryType = Literal["http", "cli", "event", "cron", "manual"]
GraphKind = Literal["codebase", "knowledge"]


# ---------------------------------------------------------------------------
# Optional metadata blocks (TS: KnowledgeMeta / DomainMeta)
# ---------------------------------------------------------------------------


class KnowledgeMeta(BaseModel):
    """Optional knowledge metadata for article/entity/topic/claim/source nodes."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    category: str | None = None
    content: str | None = None


class DomainMeta(BaseModel):
    """Optional domain metadata for domain/flow/step nodes."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    entities: list[str] | None = None
    businessRules: list[str] | None = None
    crossDomainInteractions: list[str] | None = None
    entryPoint: str | None = None
    entryType: EntryType | None = None


# ---------------------------------------------------------------------------
# Persistence / config types (TS-only, no arch_analysis equivalent)
# ---------------------------------------------------------------------------


class ThemeConfig(BaseModel):
    """Theme configuration (for dashboard customization)."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    presetId: str
    accentId: str


class AnalysisMeta(BaseModel):
    """``meta.json`` — analysis metadata for persistence."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    lastAnalyzedAt: str
    gitCommitHash: str
    version: str
    analyzedFiles: int
    theme: ThemeConfig | None = None


class ProjectConfig(BaseModel):
    """``config.json`` — project config (auto-update opt-in)."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    autoUpdate: bool = False


# ---------------------------------------------------------------------------
# Non-code structural sub-interfaces (TS types.ts)
# ---------------------------------------------------------------------------


class SectionInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    level: int
    lineRange: tuple[int, int]


class DefinitionInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    kind: str
    lineRange: tuple[int, int]
    fields: list[str] = Field(default_factory=list)


class ServiceInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    image: str | None = None
    ports: list[int] = Field(default_factory=list)
    lineRange: tuple[int, int] | None = None


class EndpointInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    method: str | None = None
    path: str
    lineRange: tuple[int, int]


class StepInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    lineRange: tuple[int, int]


class ResourceInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    kind: str
    lineRange: tuple[int, int]


class ReferenceResolution(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    source: str
    target: str
    referenceType: str
    line: int | None = None


# ---------------------------------------------------------------------------
# Plugin interfaces (TS types.ts) — these carry tuple lineRanges as plain dicts
# in the Python pipeline; modeled here for parity with the TS structural shapes.
# ---------------------------------------------------------------------------


class FunctionInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    lineRange: tuple[int, int]
    params: list[str] = Field(default_factory=list)
    returnType: str | None = None


class ClassInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    lineRange: tuple[int, int]
    methods: list[str] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)


class ImportInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    source: str
    specifiers: list[str] = Field(default_factory=list)
    lineNumber: int


class ExportInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    lineNumber: int
    isDefault: bool | None = None


class StructuralAnalysis(BaseModel):
    """Structural analysis result from a code analyzer (e.g. :class:`~understand_core.plugins.tree_sitter_plugin.TreeSitterPlugin`).

    The auto-update pipeline often passes plain dicts here; the helpers in
    :mod:`understand_core.fingerprint` accept either dicts or these models.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    imports: list[ImportInfo] = Field(default_factory=list)
    exports: list[ExportInfo] = Field(default_factory=list)
    sections: list[SectionInfo] | None = None
    definitions: list[DefinitionInfo] | None = None
    services: list[ServiceInfo] | None = None
    endpoints: list[EndpointInfo] | None = None
    steps: list[StepInfo] | None = None
    resources: list[ResourceInfo] | None = None


class ImportResolution(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    source: str
    resolvedPath: str
    specifiers: list[str] = Field(default_factory=list)


class CallGraphEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    caller: str
    callee: str
    lineNumber: int


__all__ = [
    # re-exported from arch_analysis.models
    "Complexity",
    "Direction",
    "DomainGraph",
    "DomainNode",
    "DomainNodeType",
    "Edge",
    "EdgeType",
    "GraphEdge",
    "GraphFragment",
    "GraphNode",
    "GraphProject",
    "KnowledgeGraph",
    "Layer",
    "NodeType",
    "ProjectMeta",
    # extended unions
    "FullNodeType",
    "FullEdgeType",
    "EntryType",
    "GraphKind",
    # metadata
    "KnowledgeMeta",
    "DomainMeta",
    # persistence / config
    "ThemeConfig",
    "AnalysisMeta",
    "ProjectConfig",
    # non-code structural
    "SectionInfo",
    "DefinitionInfo",
    "ServiceInfo",
    "EndpointInfo",
    "StepInfo",
    "ResourceInfo",
    "ReferenceResolution",
    # plugin interfaces
    "FunctionInfo",
    "ClassInfo",
    "ImportInfo",
    "ExportInfo",
    "StructuralAnalysis",
    "ImportResolution",
    "CallGraphEntry",
]
