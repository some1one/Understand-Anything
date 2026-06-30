"""Pydantic models for input validation and the output contract.

Using pydantic gives us validated, dataclass-like records for the agent's JSON
payloads: malformed input fails loudly with a clear error instead of producing
a silently-wrong analysis.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class FileNode(BaseModel):
    """A single file-level node from the knowledge graph."""

    model_config = ConfigDict(extra="ignore")

    id: str
    type: str = "file"
    name: str | None = None
    filePath: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)

    @property
    def basename(self) -> str:
        """The filename, falling back to the last path segment."""
        if self.name:
            return self.name
        return self.filePath.replace("\\", "/").rsplit("/", 1)[-1]


class Edge(BaseModel):
    """A directed edge between two file-level nodes."""

    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    type: str = "imports"


class AnalysisInput(BaseModel):
    """The full input payload (``ua-arch-input.json``)."""

    model_config = ConfigDict(extra="ignore")

    fileNodes: list[FileNode]
    importEdges: list[Edge] = Field(default_factory=list)
    allEdges: list[Edge] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """The output contract (``ua-arch-results.json``).

    Required keys are strongly typed; ``extra="allow"`` lets the analyzer attach
    additional deterministic signals (graph metrics, matrices, per-file pattern
    classifications) without breaking the documented schema.
    """

    model_config = ConfigDict(extra="allow")

    scriptCompleted: bool
    directoryGroups: dict[str, list[str]]
    nodeTypeGroups: dict[str, list[str]]
    crossCategoryEdges: list[dict]
    interGroupImports: list[dict]
    intraGroupDensity: dict[str, dict]
    patternMatches: dict[str, str]
    deploymentTopology: dict
    dataPipeline: dict
    docCoverage: dict
    dependencyDirection: list[dict]
    fileStats: dict
    fileFanIn: dict[str, int]
    fileFanOut: dict[str, int]


class ScanFile(BaseModel):
    """A single file entry in the scan result."""

    model_config = ConfigDict(extra="forbid")

    path: str
    language: str
    sizeLines: int
    fileCategory: str


class ScanStats(BaseModel):
    """Aggregate counts for a scan result."""

    model_config = ConfigDict(extra="forbid")

    filesScanned: int
    byCategory: dict[str, int]
    byLanguage: dict[str, int]


class ScanResult(BaseModel):
    """Output contract for :mod:`arch_analysis.scan_project`."""

    model_config = ConfigDict(extra="forbid")

    scriptCompleted: bool
    files: list[ScanFile]
    totalFiles: int
    filteredByIgnore: int
    estimatedComplexity: str
    stats: ScanStats


class ImportMapFile(BaseModel):
    """A single file entry in the import-map input."""

    model_config = ConfigDict(extra="ignore")

    path: str
    language: str
    fileCategory: str


class ImportMapInput(BaseModel):
    """Input contract for :mod:`arch_analysis.extract_import_map`."""

    model_config = ConfigDict(extra="ignore")

    projectRoot: str
    files: list[ImportMapFile] = Field(default_factory=list)


class ImportMapStats(BaseModel):
    """Aggregate counts for an import-map result."""

    model_config = ConfigDict(extra="forbid")

    filesScanned: int
    filesWithImports: int
    totalEdges: int


class ImportMapResult(BaseModel):
    """Output contract for :mod:`arch_analysis.extract_import_map`."""

    model_config = ConfigDict(extra="forbid")

    scriptCompleted: bool
    stats: ImportMapStats
    importMap: dict[str, list[str]]


class StructureBatchFile(BaseModel):
    """One file entry in the extract-structure input batch."""

    model_config = ConfigDict(extra="ignore")

    path: str
    language: str | None = None
    sizeLines: int | None = None
    fileCategory: str | None = None


class StructureInput(BaseModel):
    """Input contract for :mod:`arch_analysis.extract_structure`.

    ``batchImportData`` maps a file path to its pre-resolved relative import
    targets (used for ``metrics.importCount``).
    """

    model_config = ConfigDict(extra="ignore")

    projectRoot: str
    batchFiles: list[StructureBatchFile]
    batchImportData: dict[str, list[str]] = Field(default_factory=dict)


class StructureResult(BaseModel):
    """One per-file result in the extract-structure output.

    ``extra="allow"`` keeps the schema open: fields that do not apply to a file
    are simply omitted (the null-tolerant ``buildResult`` shape).
    """

    model_config = ConfigDict(extra="allow")

    path: str
    language: str | None = None
    fileCategory: str | None = None
    totalLines: int
    nonEmptyLines: int
    metrics: dict = Field(default_factory=dict)


class StructureOutput(BaseModel):
    """Output contract for :mod:`arch_analysis.extract_structure`."""

    model_config = ConfigDict(extra="ignore")

    scriptCompleted: bool
    filesAnalyzed: int
    filesSkipped: list[str] = Field(default_factory=list)
    results: list[StructureResult] = Field(default_factory=list)


class Layer(BaseModel):
    """A single architecture layer in the Phase 2 output."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^layer:[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    nodeIds: list[str] = Field(min_length=1)


class LayersOutput(RootModel[list[Layer]]):
    """The Phase 2 output contract: a JSON array of layers."""


# ---------------------------------------------------------------------------
# Project-scanner final output (intermediate/scan-result.json)
# ---------------------------------------------------------------------------


class ProjectScanOutput(BaseModel):
    """Final project-scanner contract written to ``intermediate/scan-result.json``.

    Merges the LLM narrative fields (``name``/``description``/``languages``/
    ``frameworks``) with the deterministic ``files``/``totalFiles``/
    ``filteredByIgnore``/``estimatedComplexity`` from :mod:`scan_project` and the
    ``importMap`` from :mod:`extract_import_map`. The transient
    ``scriptCompleted``/``stats`` fields from those modules are NOT part of this
    contract — they are stripped during assembly.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    files: list[ScanFile]
    totalFiles: int
    filteredByIgnore: int
    estimatedComplexity: str
    importMap: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Knowledge-graph / domain-graph contracts
# ---------------------------------------------------------------------------

# Canonical enums — kept in sync with arch_analysis.validate_graph and the
# dashboard schema (packages/core/src/schema.ts).
NodeType = Literal[
    "file", "function", "class", "module", "concept",
    "config", "document", "service", "table", "endpoint",
    "pipeline", "schema", "resource",
    "domain", "flow", "step",
]

DomainNodeType = Literal["domain", "flow", "step"]

EdgeType = Literal[
    "imports", "exports", "contains", "inherits", "implements",
    "calls", "subscribes", "publishes", "middleware",
    "reads_from", "writes_to", "transforms", "validates",
    "depends_on", "tested_by", "configures",
    "related", "similar_to",
    "deploys", "serves", "provisions", "triggers",
    "migrates", "documents", "routes", "defines_schema",
    "contains_flow", "flow_step", "cross_domain",
]

Complexity = Literal["simple", "moderate", "complex"]
Direction = Literal["forward", "backward", "bidirectional"]


class GraphNode(BaseModel):
    """A node in an assembled knowledge graph or batch fragment.

    ``extra="allow"`` keeps the contract open for optional fields the LLM and
    extractors attach (``lineRange``, ``languageNotes``, ``domainMeta``, etc.).
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    type: NodeType
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    tags: list[str]
    complexity: Complexity
    filePath: str | None = None
    lineRange: list[int] | None = None


class DomainNode(GraphNode):
    """A domain-graph node — restricted to ``domain``/``flow``/``step``."""

    type: DomainNodeType


class GraphEdge(BaseModel):
    """A directed, typed, weighted edge in an assembled graph or fragment."""

    model_config = ConfigDict(extra="allow")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    type: EdgeType
    direction: Direction = "forward"
    weight: float = Field(ge=0.0, le=1.0)


class GraphProject(BaseModel):
    """Project metadata block shared by knowledge and domain graphs."""

    model_config = ConfigDict(extra="allow")

    name: str
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    description: str
    analyzedAt: str
    gitCommitHash: str


class KnowledgeGraph(BaseModel):
    """The full structural knowledge-graph contract (``knowledge-graph.json``)."""

    model_config = ConfigDict(extra="allow")

    version: str
    project: GraphProject
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    layers: list[Layer] = Field(default_factory=list)


class DomainGraph(BaseModel):
    """The domain-graph contract (``domain-graph.json``).

    Nodes are restricted to domain/flow/step types and ``layers`` is empty by
    convention (the dashboard renders domain graphs with a layer-free view).
    """

    model_config = ConfigDict(extra="allow")

    version: str
    project: GraphProject
    nodes: list[DomainNode]
    edges: list[GraphEdge]
    layers: list[Layer] = Field(default_factory=list)


class GraphFragment(BaseModel):
    """A file-analyzer batch/part output: ``{ "nodes": [...], "edges": [...] }``."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic per-batch context for the file-analyzer
# ---------------------------------------------------------------------------


class NeighborEntry(BaseModel):
    """A cross-batch neighbor of a file, with its batch index + exported symbols."""

    model_config = ConfigDict(extra="ignore")

    path: str
    batchIndex: int
    symbols: list[str] = Field(default_factory=list)


class FileAnalysisContext(BaseModel):
    """Deterministic per-batch context consumed by the file-analyzer.

    Produced by :mod:`arch_analysis.prepare_file_analysis_batch` from a single
    ``batches.json`` entry. Carries everything the seeding and finalization
    steps need: the batch's files, fully-resolved import data, and the
    cross-batch neighbor map (whose target paths bound the set of allowed
    cross-batch edge references).
    """

    model_config = ConfigDict(extra="forbid")

    projectRoot: str
    batchIndex: int
    batchFiles: list[StructureBatchFile] = Field(default_factory=list)
    batchImportData: dict[str, list[str]] = Field(default_factory=dict)
    neighborMap: dict[str, list[NeighborEntry]] = Field(default_factory=dict)
