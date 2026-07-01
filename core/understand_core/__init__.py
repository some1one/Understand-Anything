"""``understand_core`` — Python port of ``@understand-anything/core``.

Mirrors the public API of ``packages/core/src/index.ts``. Deterministic
structural analysis that already exists in the repo-root ``arch_analysis``
package (tree-sitter, language detection, ignore filtering, structural
extraction, fingerprints, models/schema, graph merging) is imported from
``arch_analysis.*`` rather than re-implemented.
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

# -- staleness / fingerprints / change classification ---------------------
from understand_core.staleness import (
    StalenessResult,
    get_changed_files,
    is_stale,
    merge_graph_update,
)
from understand_core.fingerprint import (
    ChangeAnalysis,
    ChangeLevel,
    ClassFingerprint,
    FileChangeResult,
    FileFingerprint,
    FingerprintStore,
    FunctionFingerprint,
    ImportFingerprint,
    analyze_changes,
    build_fingerprint_store,
    compare_fingerprints,
    content_hash,
    extract_file_fingerprint,
)
from understand_core.change_classifier import UpdateDecision, classify_update

# -- ignore ---------------------------------------------------------------
from understand_core.ignore_filter import (
    DEFAULT_IGNORE_PATTERNS,
    IgnoreFilter,
    create_ignore_filter,
)
from understand_core.ignore_generator import generate_starter_ignore_file

# -- analyzer -------------------------------------------------------------
from understand_core.analyzer import (
    DroppedEdge,
    GraphBuilder,
    LanguageLessonResult,
    LLMFileAnalysis,
    LLMLayerResponse,
    LLMProjectSummary,
    NormalizationStats,
    NormalizeBatchResult,
    apply_llm_layers,
    build_file_analysis_prompt,
    build_language_lesson_prompt,
    build_layer_detection_prompt,
    build_project_summary_prompt,
    detect_language_concepts,
    detect_layers,
    normalize_batch_output,
    normalize_complexity,
    normalize_node_id,
    parse_file_analysis_response,
    parse_language_lesson_response,
    parse_layer_detection_response,
    parse_project_summary_response,
)

# -- plugins --------------------------------------------------------------
from understand_core.plugins import (
    DEFAULT_PLUGIN_CONFIG,
    AnalyzerPlugin,
    PluginConfig,
    PluginEntry,
    PluginRegistry,
    TreeSitterPlugin,
    parse_plugin_config,
    register_all_parsers,
    serialize_plugin_config,
)
from understand_core.plugins.extractors import LanguageExtractor, builtin_extractors
from understand_core.plugins.parsers import (
    DockerfileParser,
    EnvParser,
    GraphQLParser,
    JSONConfigParser,
    MakefileParser,
    MarkdownParser,
    ProtobufParser,
    ShellParser,
    SQLParser,
    TerraformParser,
    TOMLParser,
    YAMLConfigParser,
)

# -- languages ------------------------------------------------------------
from understand_core.languages import (
    FilePatternConfig,
    FrameworkConfig,
    FrameworkRegistry,
    LanguageConfig,
    LanguageRegistry,
    TreeSitterConfig,
    builtin_framework_configs,
    builtin_language_configs,
)

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
    # staleness / fingerprint / change classifier
    "StalenessResult", "get_changed_files", "is_stale", "merge_graph_update",
    "ChangeAnalysis", "ChangeLevel", "ClassFingerprint", "FileChangeResult",
    "FileFingerprint", "FingerprintStore", "FunctionFingerprint",
    "ImportFingerprint", "analyze_changes", "build_fingerprint_store",
    "compare_fingerprints", "content_hash", "extract_file_fingerprint",
    "UpdateDecision", "classify_update",
    # ignore
    "DEFAULT_IGNORE_PATTERNS", "IgnoreFilter", "create_ignore_filter",
    "generate_starter_ignore_file",
    # analyzer
    "GraphBuilder", "DroppedEdge", "NormalizationStats", "NormalizeBatchResult",
    "LanguageLessonResult", "LLMFileAnalysis", "LLMLayerResponse",
    "LLMProjectSummary", "apply_llm_layers", "build_file_analysis_prompt",
    "build_language_lesson_prompt", "build_layer_detection_prompt",
    "build_project_summary_prompt", "detect_language_concepts", "detect_layers",
    "normalize_batch_output", "normalize_complexity", "normalize_node_id",
    "parse_file_analysis_response", "parse_language_lesson_response",
    "parse_layer_detection_response", "parse_project_summary_response",
    # plugins
    "TreeSitterPlugin", "PluginRegistry", "AnalyzerPlugin", "register_all_parsers",
    "parse_plugin_config", "serialize_plugin_config", "PluginConfig",
    "PluginEntry", "DEFAULT_PLUGIN_CONFIG", "LanguageExtractor",
    "builtin_extractors", "MarkdownParser", "YAMLConfigParser",
    "JSONConfigParser", "TOMLParser", "EnvParser", "DockerfileParser",
    "SQLParser", "GraphQLParser", "ProtobufParser", "TerraformParser",
    "MakefileParser", "ShellParser",
    # languages
    "LanguageConfig", "FrameworkConfig", "TreeSitterConfig", "FilePatternConfig",
    "LanguageRegistry", "FrameworkRegistry", "builtin_language_configs",
    "builtin_framework_configs",
]
