"""``understand_core`` — graph view-model + skill-builder support layer.

Deterministic structural analysis (tree-sitter parsing, structural extraction,
language detection, ignore filtering, fingerprints, graph assembly/merging, and
the graph models/schema) lives in the sibling ``arch_analysis`` package and is
imported from ``arch_analysis.*`` rather than re-implemented here. This package
carries only what sits *on top* of that engine: the graph types (re-exported
from ``arch_analysis.models``), on-disk persistence, the repair-oriented load
validator, lexical + semantic search, staleness helpers, and the fingerprint
wire shapes.
"""

from __future__ import annotations

# -- graph types ----------------------------------------------------------
from understand_core.types import (
    Complexity,
    Direction,
    Edge,
    EdgeType,
    GraphEdge,
    GraphNode,
    GraphProject,
    KnowledgeGraph,
    Layer,
    NodeType,
    ProjectMeta,
)

# -- persistence ----------------------------------------------------------
from understand_core.persistence import (
    load_config,
    load_domain_graph,
    load_fingerprints,
    load_graph,
    load_meta,
    save_config,
    save_domain_graph,
    save_fingerprints,
    save_graph,
    save_meta,
)

# -- schema / validation --------------------------------------------------
from understand_core.schema import (
    COMPLEXITY_ALIASES,
    DIRECTION_ALIASES,
    EDGE_TYPE_ALIASES,
    NODE_TYPE_ALIASES,
    GraphIssue,
    ValidationResult,
    auto_fix_graph,
    sanitize_graph,
    validate_graph,
)

# -- search ---------------------------------------------------------------
from understand_core.search import SearchEngine, SearchResult
from understand_core.embedding_search import SemanticSearchEngine, cosine_similarity

# -- staleness / fingerprint wire shapes ----------------------------------
from understand_core.staleness import (
    StalenessResult,
    get_changed_files,
    is_stale,
    merge_graph_update,
)
from understand_core.fingerprint import (
    ChangeLevel,
    ClassFingerprint,
    FileFingerprint,
    FingerprintStore,
    FunctionFingerprint,
    ImportFingerprint,
    content_hash,
)

# -- ignore ---------------------------------------------------------------
from understand_core.ignore_filter import (
    DEFAULT_IGNORE_PATTERNS,
    IgnoreFilter,
    create_ignore_filter,
)
from understand_core.ignore_generator import generate_starter_ignore_file

__all__ = [
    # types
    "Complexity", "Direction", "Edge", "EdgeType", "GraphEdge", "GraphNode",
    "GraphProject", "KnowledgeGraph", "Layer", "NodeType", "ProjectMeta",
    # persistence
    "save_graph", "load_graph", "save_meta", "load_meta", "save_fingerprints",
    "load_fingerprints", "save_config", "load_config", "save_domain_graph",
    "load_domain_graph",
    # schema
    "GraphIssue", "ValidationResult", "validate_graph", "sanitize_graph",
    "auto_fix_graph", "NODE_TYPE_ALIASES", "EDGE_TYPE_ALIASES",
    "COMPLEXITY_ALIASES", "DIRECTION_ALIASES",
    # search
    "SearchEngine", "SearchResult", "SemanticSearchEngine", "cosine_similarity",
    # staleness / fingerprint wire shapes
    "StalenessResult", "get_changed_files", "is_stale", "merge_graph_update",
    "ChangeLevel", "ClassFingerprint", "FileFingerprint", "FingerprintStore",
    "FunctionFingerprint", "ImportFingerprint", "content_hash",
    # ignore
    "DEFAULT_IGNORE_PATTERNS", "IgnoreFilter", "create_ignore_filter",
    "generate_starter_ignore_file",
]
