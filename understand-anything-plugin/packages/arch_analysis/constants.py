"""Constants for the architecture structural analysis.

Every lookup table, threshold, and pattern set referenced by the
architecture-analyzer agent (agents/architecture-analyzer.md, Phase 1) lives
here so the analysis logic stays declarative and the heuristics are auditable
in one place.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Node taxonomy
# --------------------------------------------------------------------------- #

# All recognised file-level node types (section B -- Node Type Grouping).
NODE_TYPES: tuple[str, ...] = (
    "file",
    "config",
    "document",
    "service",
    "pipeline",
    "table",
    "schema",
    "resource",
    "endpoint",
)

# --------------------------------------------------------------------------- #
# Canonical graph type sets (single source of truth)
# --------------------------------------------------------------------------- #
# Superset covering structural + domain + knowledge graphs so valid
# knowledge/domain graphs are not rejected. These are the authoritative sets
# imported by both the strict validator (arch_analysis.validate_graph) and the
# repair validator (understand_core.schema) so the taxonomy lives in one place.

VALID_NODE_TYPES: frozenset[str] = frozenset(
    {
        "file", "function", "class", "module", "concept",
        "config", "document", "service", "table", "endpoint",
        "pipeline", "schema", "resource",
        "domain", "flow", "step",
        "article", "entity", "topic", "claim", "source",
    }
)

VALID_EDGE_TYPES: frozenset[str] = frozenset(
    {
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
    }
)

VALID_COMPLEXITY: frozenset[str] = frozenset({"simple", "moderate", "complex"})
VALID_DIRECTIONS: frozenset[str] = frozenset(
    {"forward", "backward", "bidirectional"}
)

# --------------------------------------------------------------------------- #
# Directory pattern matching (section G)
# --------------------------------------------------------------------------- #

# Single-segment directory name -> architectural pattern label.
DIRECTORY_PATTERN_MAP: dict[str, str] = {
    # api
    "routes": "api",
    "api": "api",
    "controllers": "api",
    "endpoints": "api",
    "handlers": "api",
    "serializers": "api",
    "controller": "api",
    "routers": "api",
    "blueprints": "api",
    # service
    "services": "service",
    "core": "service",
    "lib": "service",
    "domain": "service",
    "logic": "service",
    "signals": "service",
    "internal": "service",
    "composables": "service",
    "mailers": "service",
    "jobs": "service",
    "channels": "service",
    # data
    "models": "data",
    "db": "data",
    "data": "data",
    "persistence": "data",
    "repository": "data",
    "entities": "data",
    "migrations": "data",
    "entity": "data",
    "sql": "data",
    "database": "data",
    "schema": "data",
    # ui
    "components": "ui",
    "views": "ui",
    "pages": "ui",
    "ui": "ui",
    "layouts": "ui",
    "screens": "ui",
    # middleware
    "middleware": "middleware",
    "plugins": "middleware",
    "interceptors": "middleware",
    "guards": "middleware",
    # utility
    "utils": "utility",
    "helpers": "utility",
    "common": "utility",
    "shared": "utility",
    "tools": "utility",
    "templatetags": "utility",
    "pkg": "utility",
    # config
    "config": "config",
    "constants": "config",
    "env": "config",
    "settings": "config",
    "management": "config",
    "commands": "config",
    # test
    "__tests__": "test",
    "test": "test",
    "tests": "test",
    "spec": "test",
    "specs": "test",
    # types
    "types": "types",
    "interfaces": "types",
    "schemas": "types",
    "contracts": "types",
    "dtos": "types",
    "dto": "types",
    "request": "types",
    "response": "types",
    # hooks / state
    "hooks": "hooks",
    "store": "state",
    "state": "state",
    "reducers": "state",
    "actions": "state",
    "slices": "state",
    # assets
    "assets": "assets",
    "static": "assets",
    "public": "assets",
    # entry
    "cmd": "entry",
    "bin": "entry",
    # documentation
    "docs": "documentation",
    "documentation": "documentation",
    "wiki": "documentation",
    # infrastructure
    "deploy": "infrastructure",
    "deployment": "infrastructure",
    "infra": "infrastructure",
    "infrastructure": "infrastructure",
    "k8s": "infrastructure",
    "kubernetes": "infrastructure",
    "helm": "infrastructure",
    "charts": "infrastructure",
    "terraform": "infrastructure",
    "tf": "infrastructure",
    "docker": "infrastructure",
    # ci-cd
    ".github": "ci-cd",
    ".gitlab": "ci-cd",
    ".circleci": "ci-cd",
}

# Multi-segment path suffixes -> label (checked against full file paths).
PATH_SUFFIX_PATTERNS: tuple[tuple[str, str], ...] = (
    ("src/main/java", "service"),
    ("src/test/java", "test"),
)

# --------------------------------------------------------------------------- #
# File-level pattern matching (section G, "Also check file-level patterns")
# --------------------------------------------------------------------------- #

# Regexes that mark a *test* file across ecosystems.
TEST_FILE_REGEXES: tuple[str, ...] = (
    r"\.(test|spec)\.",
    r"^test_.*\.py$",
    r"_test\.go$",
    r"Test\.java$",
    r"_spec\.rb$",
    r"Test\.php$",
    r"Tests\.cs$",
)

# Exact filenames that are program/crate entry points.
ENTRY_FILENAMES: frozenset[str] = frozenset(
    {
        "index.ts",
        "index.js",
        "__init__.py",
        "manage.py",
        "main.rs",
        "lib.rs",
        "Application.java",
        "Program.cs",
        "config.ru",
    }
)
# main.go counts as an entry point only under cmd/.
GO_ENTRY_BASENAME = "main.go"

# Exact filenames that are project/server configuration.
CONFIG_FILENAMES: frozenset[str] = frozenset(
    {
        "wsgi.py",
        "asgi.py",
        "Cargo.toml",
        "go.mod",
        "Gemfile",
        "pom.xml",
        "build.gradle",
        "composer.json",
    }
)

# Exact filenames / dir names that are CI-CD.
CI_FILENAMES: frozenset[str] = frozenset({".gitlab-ci.yml", "Jenkinsfile"})
CI_DIR_SEGMENTS: frozenset[str] = frozenset({".github", ".circleci"})

# Infrastructure directory segments (deployment topology, section H).
INFRA_DIR_SEGMENTS: frozenset[str] = frozenset(
    {"k8s", "kubernetes", "helm", "charts"}
)

# Extension groups.
DOC_EXTENSIONS: tuple[str, ...] = (".md", ".rst")
SCHEMA_EXTENSIONS: tuple[str, ...] = (".sql", ".graphql", ".gql", ".proto", ".prisma")
TYPE_DEF_EXTENSIONS: tuple[str, ...] = (".graphql", ".gql", ".proto")
INFRA_EXTENSIONS: tuple[str, ...] = (".tf", ".tfvars")
MAKEFILE_NAME = "Makefile"

# --------------------------------------------------------------------------- #
# Decision thresholds (Phase 2 heuristics, surfaced for transparency)
# --------------------------------------------------------------------------- #

# Intra-group import density above which a group is "cohesive" (Step 1).
COHESIVE_DENSITY_THRESHOLD = 0.3

# Reserved grouping bucket for files that sit at the common-prefix root.
ROOT_GROUP = "root"

# Minimum file count for spearman correlation to be meaningful.
MIN_FILES_FOR_CORRELATION = 3

# Documentation/config file-count thresholds that warrant a dedicated non-code
# layer (Phase 2, Step 3).
MIN_DOCS_FOR_LAYER = 3
MIN_CONFIGS_FOR_LAYER = 3

# --------------------------------------------------------------------------- #
# Node-type inference (used by generate_input to classify files on disk)
# --------------------------------------------------------------------------- #

# Filenames that are project/build configuration.
NODE_TYPE_CONFIG_FILENAMES: frozenset[str] = frozenset(
    {
        "package.json",
        "tsconfig.json",
        "jsconfig.json",
        "cargo.toml",
        "go.mod",
        "go.sum",
        "gemfile",
        "gemfile.lock",
        "pom.xml",
        "build.gradle",
        "composer.json",
        "pyproject.toml",
        "setup.cfg",
        "pipfile",
        "pipfile.lock",
        "requirements.txt",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)
NODE_TYPE_CONFIG_EXTENSIONS: tuple[str, ...] = (
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".yaml",
    ".yml",
)
# Dotfile basenames that are configuration (e.g. .eslintrc, .prettierrc).
CONFIG_DOTFILE_PREFIXES: tuple[str, ...] = (
    ".eslintrc",
    ".prettierrc",
    ".babelrc",
    ".npmrc",
    ".editorconfig",
    ".env",
)

# --------------------------------------------------------------------------- #
# Layer mappings (Phase 2 automation)
# --------------------------------------------------------------------------- #

# Non-code node type -> the layer it defaults into.
NODE_TYPE_LAYER: dict[str, str] = {
    "config": "layer:config",
    "document": "layer:documentation",
    "service": "layer:infrastructure",
    "resource": "layer:infrastructure",
    "pipeline": "layer:ci-cd",
    "table": "layer:data",
    "schema": "layer:data",
    "endpoint": "layer:data",
}

# File-level pattern label -> layer override (takes precedence over a code
# file's directory group when assigning a default layer).
FILE_PATTERN_LAYER_OVERRIDE: dict[str, str] = {
    "test": "layer:test",
    "types": "layer:types",
    "documentation": "layer:documentation",
    "infrastructure": "layer:infrastructure",
    "ci-cd": "layer:ci-cd",
    "data": "layer:data",
}
