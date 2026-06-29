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


class Layer(BaseModel):
    """A single architecture layer in the Phase 2 output."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^layer:[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    nodeIds: list[str] = Field(min_length=1)


class LayersOutput(RootModel[list[Layer]]):
    """The Phase 2 output contract: a JSON array of layers."""
