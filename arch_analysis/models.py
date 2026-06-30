"""Pydantic models for input validation and the output contract.

Using pydantic gives us validated, dataclass-like records for the agent's JSON
payloads: malformed input fails loudly with a clear error instead of producing
a silently-wrong analysis.
"""

from __future__ import annotations

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
