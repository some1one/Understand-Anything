"""Shared deterministic file-graph helpers.

Used by :mod:`arch_analysis.seed_file_batch_graph` (to generate the seed) and
:mod:`arch_analysis.finalize_file_batch_output` (to reason about which file a
node belongs to). Keeping the node-typing and tag rules here means the seed and
the finalizer agree by construction.
"""

from __future__ import annotations


def basename(path: str) -> str:
    return path.rsplit("/", 1)[-1] if "/" in path else path


def _ext(path: str) -> str:
    base = basename(path)
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


# Extensions that define a schema (GraphQL / Protobuf / Prisma) — the only
# ``data`` files whose file-level node id is path-only and unambiguous.
_SCHEMA_EXTS = frozenset({"graphql", "gql", "proto", "prisma"})


def file_level_node(category: str | None, path: str) -> tuple[str, str] | None:
    """Return ``(node_type, node_id)`` for a file, or ``None`` to defer to the LLM.

    Deferred files are ``data`` files whose canonical node type requires a named
    sub-node (``table:<path>:<name>``, ``endpoint:<path>:<name>``) that cannot be
    derived without parsing — the LLM creates those nodes itself.
    """
    if category in ("code", "script", "markup"):
        return "file", f"file:{path}"
    if category == "config":
        return "config", f"config:{path}"
    if category == "docs":
        return "document", f"document:{path}"
    if category == "infra":
        return _infra_node(path), f"{_infra_node(path)}:{path}"
    if category == "data":
        if _ext(path) in _SCHEMA_EXTS:
            return "schema", f"schema:{path}"
        return None
    # Unknown category — treat as a generic file node.
    return "file", f"file:{path}"


def _infra_node(path: str) -> str:
    base = basename(path)
    if (
        path.startswith(".github/workflows/")
        or path == ".gitlab-ci.yml"
        or base == "Jenkinsfile"
        or path.startswith(".circleci/")
    ):
        return "pipeline"
    if _ext(path) in ("tf", "tfvars") or base == "Vagrantfile":
        return "resource"
    return "service"


_JS_TS_TEST_EXTS = frozenset({"ts", "tsx", "js", "jsx", "mjs", "cjs", "vue"})
_TEST_SUFFIX_BY_EXT: dict[str, tuple[str, ...]] = {
    "go": ("_test",),
    "py": ("_test",),
    "java": ("Test", "Tests", "IT"),
    "kt": ("Test", "Tests"),
    "cs": ("Test", "Tests"),
    "c": ("_test",),
    "cpp": ("_test",),
    "cc": ("_test",),
}
_TEST_PREFIX_BY_EXT: dict[str, tuple[str, ...]] = {
    "py": ("test_",),
    "c": ("test_",),
    "cpp": ("test_",),
    "cc": ("test_",),
}


def is_test_file(path: str) -> bool:
    """Deterministic test-file detection (mirrors merge_batch_graphs.is_test_path)."""
    base = basename(path)
    stem, _, ext = base.rpartition(".")
    if not stem:
        stem, ext = base, ""
    ext = ext.lower()
    if ext in _JS_TS_TEST_EXTS:
        return stem.endswith(".test") or stem.endswith(".spec")
    if any(stem.startswith(p) for p in _TEST_PREFIX_BY_EXT.get(ext, ())):
        return True
    return any(stem.endswith(s) for s in _TEST_SUFFIX_BY_EXT.get(ext, ()))


_ENTRY_POINT_BASENAMES = frozenset(
    {
        "index.ts", "index.js", "index.tsx", "index.jsx",
        "__init__.py", "manage.py", "main.py", "__main__.py",
        "main.go", "main.rs", "lib.rs",
        "Application.java", "Main.java", "Program.cs", "config.ru",
    }
)


def deterministic_tags(category: str | None, path: str) -> list[str]:
    """Return reliably-derivable tags for a file (the seed's required tags).

    Conservative on purpose: only tags that follow unambiguously from the path
    and category, so the finalizer can demand the LLM preserve them.
    """
    base = basename(path)
    ext = _ext(path)
    tags: list[str] = []

    if is_test_file(path):
        tags.append("test")

    if base in _ENTRY_POINT_BASENAMES:
        tags.append("entry-point")
    if base == "mod.rs":
        tags.append("barrel")

    if category == "infra":
        if base == "Dockerfile" or base.startswith("Dockerfile."):
            tags += ["containerization", "infrastructure"]
        elif base.startswith("docker-compose.") or base.startswith("compose."):
            tags += ["orchestration", "infrastructure"]
        elif _infra_node(path) == "pipeline":
            tags += ["ci-cd", "deployment"]
        elif _infra_node(path) == "resource":
            tags += ["infrastructure", "deployment"]
        else:
            tags.append("infrastructure")
    elif category == "config":
        tags.append("configuration")
    elif category == "docs":
        tags.append("documentation")
    elif category == "data":
        if ext == "sql":
            tags += ["database", "migration"]
        elif ext in ("graphql", "gql"):
            tags += ["api-schema", "schema-definition"]
        elif ext in ("proto", "prisma"):
            tags += ["schema-definition", "data-pipeline"]

    # De-duplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
