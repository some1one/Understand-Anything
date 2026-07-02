"""Deterministic import resolution for the project-scanner pipeline.

Python port of ``skills/understand/extract-import-map.mjs``. Uses tree-sitter
(via :mod:`arch_analysis.treesitter`) to extract raw import sources, then applies
language-specific resolution rules to map them to project-internal file paths.

Usage:
    python -m arch_analysis.extract_import_map <input.json> <output.json>

Input JSON:
    { "projectRoot": <abs-path>,
      "files": [{ "path", "language", "fileCategory" }, ...] }

Output JSON:
    { "scriptCompleted": true,
      "stats": { "filesScanned", "filesWithImports", "totalEdges" },
      "importMap": { <path>: [<resolvedPath>, ...], ... } }

Logging: stderr only (stdout reserved for piped tools). Per-file resilience —
failures emit ``Warning: extract-import-map: ...`` and set importMap[path] = [],
they do not abort the script.

The JS version used tree-sitter for TS/JS, Python, Go, Java, C#, PHP, Rust and
REGEX for Kotlin and Ruby; this port matches that split.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from .treesitter import get_parser, node_text


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def to_posix(p: str) -> str:
    """Normalize a path to forward slashes, dropping empty segments."""
    return "/".join(seg for seg in re.split(r"[\\/]", p) if seg)


def resolve_relative(dir_: str, rel: str) -> str:
    """Join ``dir_`` with relative ``rel``, normalizing ``.``/``..``.

    Returns '' if the path walks above the project root.
    """
    parts = ([seg for seg in dir_.split("/") if seg] if dir_ else []) + [
        seg for seg in rel.split("/") if seg
    ]
    stack: list[str] = []
    for part in parts:
        if part == "" or part == ".":
            continue
        if part == "..":
            if not stack:
                return ""
            stack.pop()
        else:
            stack.append(part)
    return "/".join(stack)


def dir_of(p: str) -> str:
    """Directory portion of a project-relative path ('' for top-level)."""
    i = p.rfind("/")
    return "" if i == -1 else p[:i]


def posix_normalize(p: str) -> str:
    """Mirror of Node's ``path.posix.normalize`` for our anchored paths.

    Collapses ``.``/``..`` segments and strips a leading ``./``. We only ever
    feed it project-anchored candidates, so the result keeps no leading slash.
    """
    leading_dotdot = p.startswith("..")
    stack: list[str] = []
    for part in p.split("/"):
        if part == "" or part == ".":
            continue
        if part == "..":
            if stack and stack[-1] != "..":
                stack.pop()
            else:
                stack.append("..")
        else:
            stack.append(part)
    out = "/".join(stack)
    # Preserve a leading ".." so the resolver's escape guard still trips.
    if leading_dotdot and not out.startswith(".."):
        out = "../" + out if out else ".."
    return out


def posix_join(*parts: str) -> str:
    """Join with '/' and normalize, like ``path.posix.join``."""
    joined = "/".join(p for p in parts if p != "")
    return posix_normalize(joined)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def parse_tsconfig_text(raw: str) -> dict[str, Any] | None:
    """Parse tsconfig content -> {baseUrl, paths: dict[str, list[str]]} or None.

    Strips JSONC comments first, then falls back to the raw text (which
    recovers the case where the naive stripper damaged a string literal
    containing ``//``).
    """
    stripped = re.sub(r"/\*[\s\S]*?\*/", "", raw)
    stripped = re.sub(r"(^|[^:])//.*$", r"\1", stripped, flags=re.MULTILINE)
    parsed: Any
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    compiler_options = (parsed or {}).get("compilerOptions") or {}
    base_url = compiler_options.get("baseUrl", ".")
    paths: dict[str, list[str]] = {}
    raw_paths = compiler_options.get("paths")
    if isinstance(raw_paths, dict):
        for alias, targets in raw_paths.items():
            if isinstance(targets, list):
                paths[alias] = targets
    return {"baseUrl": base_url, "paths": paths}


def load_tsconfigs(
    project_root: str, files: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load every tsconfig.json in ``files`` -> Map<dir, {baseUrl, paths}>."""
    out: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for f in files:
        p = to_posix(f["path"])
        base = p[p.rfind("/") + 1 :] if "/" in p else p
        if base != "tsconfig.json":
            continue
        abs_path = Path(project_root) / p
        if not abs_path.exists():
            continue
        try:
            raw = abs_path.read_text(encoding="utf-8")
        except OSError as err:
            warnings.append(
                f"Warning: extract-import-map: tsconfig.json at {abs_path} failed "
                f"to read ({err}) — path aliases from this config will "
                f"not be applied — relative imports unaffected\n"
            )
            continue
        parsed = parse_tsconfig_text(raw)
        if parsed is None:
            warnings.append(
                f"Warning: extract-import-map: tsconfig.json at {abs_path} failed "
                f"to parse — path aliases from this config will not be applied "
                f"— relative imports unaffected\n"
            )
            continue
        out[dir_of(p)] = parsed
    return out, warnings


def load_go_modules(
    project_root: str, files: list[dict[str, Any]]
) -> tuple[dict[str, str], list[str]]:
    """Load every go.mod in ``files`` -> Map<dir, moduleName>."""
    out: dict[str, str] = {}
    warnings: list[str] = []
    for f in files:
        p = to_posix(f["path"])
        base = p[p.rfind("/") + 1 :] if "/" in p else p
        if base != "go.mod":
            continue
        abs_path = Path(project_root) / p
        if not abs_path.exists():
            continue
        try:
            raw = abs_path.read_text(encoding="utf-8")
        except OSError:
            continue
        module_name = ""
        for line in re.split(r"\r?\n", raw):
            trimmed = re.sub(r"//.*$", "", line).strip()
            if not trimmed.startswith("module "):
                continue
            module_name = trimmed[len("module ") :].strip()
            break
        if not module_name:
            continue
        out[dir_of(p)] = module_name
    return out, warnings


def parse_composer_autoload_text(raw: str) -> dict[str, list[str]] | None:
    """Parse composer.json -> Map<namespacePrefix, dir[]> or None on failure.

    Returned dirs are relative to the composer.json's own directory.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    out: dict[str, list[str]] = {}
    psr4 = ((parsed or {}).get("autoload") or {}).get("psr-4")
    if not isinstance(psr4, dict):
        return out
    for prefix, target in psr4.items():
        targets = target if isinstance(target, list) else [target]
        normalized = [
            re.sub(r"/$", "", to_posix(t)) for t in targets if isinstance(t, str)
        ]
        # Ensure non-empty prefixes end with a backslash; preserve the empty
        # prefix as-is (Composer's fallback mapping).
        if prefix == "" or prefix.endswith("\\"):
            normalized_prefix = prefix
        else:
            normalized_prefix = prefix + "\\"
        out[normalized_prefix] = normalized
    return out


def load_php_autoloads(
    project_root: str, files: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, list[str]]], list[str]]:
    """Load every composer.json in ``files`` -> Map<dir, autoloadMap>."""
    out: dict[str, dict[str, list[str]]] = {}
    warnings: list[str] = []
    for f in files:
        p = to_posix(f["path"])
        base = p[p.rfind("/") + 1 :] if "/" in p else p
        if base != "composer.json":
            continue
        abs_path = Path(project_root) / p
        if not abs_path.exists():
            continue
        try:
            raw = abs_path.read_text(encoding="utf-8")
        except OSError as err:
            warnings.append(
                f"Warning: extract-import-map: composer.json at {abs_path} failed "
                f"to read ({err}) — PSR-4 namespace mapping from this "
                f"composer.json unavailable — PHP imports under this package "
                f"will not resolve\n"
            )
            continue
        parsed = parse_composer_autoload_text(raw)
        if parsed is None:
            warnings.append(
                f"Warning: extract-import-map: composer.json at {abs_path} failed "
                f"to parse — PSR-4 namespace mapping unavailable — PHP imports "
                f"under this package will not resolve\n"
            )
            continue
        out[dir_of(p)] = parsed
    return out, warnings


def find_nearest_config_dir(
    start_dir: str, config_map: dict[str, Any]
) -> str | None:
    """Deepest ancestor directory of ``start_dir`` present in ``config_map``."""
    if not config_map:
        return None
    parts = [seg for seg in start_dir.split("/") if seg] if start_dir else []
    for i in range(len(parts), -1, -1):
        ancestor = "/".join(parts[:i])
        if ancestor in config_map:
            return ancestor
    return None


def build_suffix_index(
    files: list[dict[str, Any]], ext_predicate: Callable[[str], bool]
) -> dict[str, list[str]]:
    """Index files by every directory-bounded suffix of their path."""
    idx: dict[str, list[str]] = {}
    for f in files:
        p = to_posix(f["path"])
        if not ext_predicate(p):
            continue
        parts = p.split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            idx.setdefault(suffix, []).append(p)
    for arr in idx.values():
        arr.sort()
    return idx


class ResolutionContext:
    """Shared per-run resolution state. Build once; pass everywhere."""

    def __init__(self, project_root: str, files: list[dict[str, Any]]):
        self.project_root = project_root
        self.file_set: set[str] = {to_posix(f["path"]) for f in files}

        ts_configs, ts_warnings = load_tsconfigs(project_root, files)
        go_modules, go_warnings = load_go_modules(project_root, files)
        php_autoloads, php_warnings = load_php_autoloads(project_root, files)
        # Canonical drain order: tsconfig -> go -> php.
        for w in ts_warnings:
            sys.stderr.write(w)
        for w in go_warnings:
            sys.stderr.write(w)
        for w in php_warnings:
            sys.stderr.write(w)

        self.ts_configs = ts_configs
        self.go_modules = go_modules
        self.php_autoloads = php_autoloads

        go_files_by_dir: dict[str, list[str]] = {}
        for f in files:
            if not f["path"].endswith(".go"):
                continue
            p = to_posix(f["path"])
            go_files_by_dir.setdefault(dir_of(p), []).append(p)
        for arr in go_files_by_dir.values():
            arr.sort()
        self.go_files_by_dir = go_files_by_dir

        self.java_index = build_suffix_index(files, lambda p: p.endswith(".java"))
        self.kotlin_index = build_suffix_index(files, lambda p: p.endswith(".kt"))
        self.cs_index = build_suffix_index(files, lambda p: p.endswith(".cs"))

        self._warned_no_rust_crate_root: set[str] = set()
        self._warned_no_go_module: set[str] = set()


# ---------------------------------------------------------------------------
# TypeScript / JavaScript resolver
# ---------------------------------------------------------------------------

TS_EXT_PROBES = [
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    "/index.ts", "/index.tsx", "/index.js", "/index.jsx",
]

NODENEXT_REWRITES = {
    ".js": [".ts", ".tsx", ".js", ".jsx"],
    ".jsx": [".tsx", ".jsx"],
    ".mjs": [".mts", ".mjs", ".ts"],
    ".cjs": [".cts", ".cjs", ".ts"],
}


def probe_with_extensions(base_path: str, file_set: set[str]) -> str | None:
    if not base_path:
        return None
    if base_path in file_set:
        return base_path
    for out_ext, src_exts in NODENEXT_REWRITES.items():
        if not base_path.endswith(out_ext):
            continue
        stem = base_path[: -len(out_ext)]
        for src_ext in src_exts:
            candidate = stem + src_ext
            if candidate in file_set:
                return candidate
        return None
    for ext in TS_EXT_PROBES:
        candidate = base_path + ext
        if candidate in file_set:
            return candidate
    return None


def match_ts_alias(alias: str, src: str) -> str | None:
    star_idx = alias.find("*")
    if star_idx == -1:
        return "" if src == alias else None
    prefix = alias[:star_idx]
    suffix = alias[star_idx + 1 :]
    if not src.startswith(prefix):
        return None
    if not src.endswith(suffix):
        return None
    if len(src) < len(prefix) + len(suffix):
        return None
    return src[len(prefix) : len(src) - len(suffix)]


def apply_ts_alias(target: str, wildcard: str) -> str:
    star_idx = target.find("*")
    if star_idx == -1:
        return target
    return target[:star_idx] + wildcard + target[star_idx + 1 :]


def resolve_ts_js_import(
    raw_import: str | None, file: dict[str, Any], ctx: ResolutionContext
) -> str | None:
    if not isinstance(raw_import, str):
        return None
    src = raw_import.strip()
    if not src:
        return None

    importer_dir = dir_of(to_posix(file["path"]))

    if src.startswith("./") or src.startswith("../"):
        base = resolve_relative(importer_dir, src)
        return probe_with_extensions(base, ctx.file_set)

    ts_config_dir = find_nearest_config_dir(importer_dir, ctx.ts_configs)
    if ts_config_dir is not None:
        ts_config = ctx.ts_configs[ts_config_dir]
        base_url = ts_config["baseUrl"]
        paths = ts_config["paths"]
        if paths:
            for alias, targets in paths.items():
                alias_match = match_ts_alias(alias, src)
                if alias_match is None:
                    continue
                for target in targets:
                    mapped = apply_ts_alias(target, alias_match)
                    normalized_base = (
                        "" if base_url in (".", "") else to_posix(base_url)
                    )
                    relative_to_config = (
                        posix_join(normalized_base, mapped)
                        if normalized_base
                        else mapped
                    )
                    candidate = posix_normalize(
                        posix_join(ts_config_dir, relative_to_config)
                        if ts_config_dir
                        else relative_to_config
                    )
                    if candidate.startswith(".."):
                        continue
                    probed = probe_with_extensions(candidate, ctx.file_set)
                    if probed:
                        return probed
    return None


REQUIRE_LITERAL_RE = re.compile(r"""\brequire\(\s*(['"])([^'"`\n]+?)\1\s*\)""")


def strip_js_like_comments(content: str) -> str:
    content = re.sub(r"/\*[\s\S]*?\*/", "", content)
    content = re.sub(r"//[^\n]*", "", content)
    return content


def extract_require_sources(content: str) -> list[str]:
    stripped = strip_js_like_comments(content)
    return [m.group(2) for m in REQUIRE_LITERAL_RE.finditer(stripped)]


KOTLIN_IMPORT_RE = re.compile(
    r"^\s*import\s+(\w+(?:\.\w+)*(?:\.\*)?)(?:\s+as\s+\w+)?\s*$", re.MULTILINE
)


def extract_kotlin_sources(content: str) -> list[str]:
    return [m.group(1) for m in KOTLIN_IMPORT_RE.finditer(content)]


# ---------------------------------------------------------------------------
# Python resolver
# ---------------------------------------------------------------------------


def resolve_python_import(
    raw_import: str | None,
    specifiers: list[str] | None,
    file: dict[str, Any],
    ctx: ResolutionContext,
) -> list[str]:
    if not isinstance(raw_import, str):
        return []
    src = raw_import
    importer_dir = dir_of(to_posix(file["path"]))

    dots = 0
    while dots < len(src) and src[dots] == ".":
        dots += 1
    tail = src[dots:]
    tail_segments = [s for s in tail.split(".") if s] if tail else []

    if dots > 0:
        importer_parts = (
            [s for s in importer_dir.split("/") if s] if importer_dir else []
        )
        drop_levels = dots - 1
        if drop_levels > len(importer_parts):
            return []
        base_parts = importer_parts[: len(importer_parts) - drop_levels]

        if not tail_segments:
            if not isinstance(specifiers, list) or not specifiers:
                return []
            base = "/".join(base_parts)
            matches: list[str] = []
            for spec in specifiers:
                if not spec or spec == "*" or "." in spec:
                    continue
                sub_file = f"{base}/{spec}.py" if base else f"{spec}.py"
                sub_init = (
                    f"{base}/{spec}/__init__.py" if base else f"{spec}/__init__.py"
                )
                if sub_file in ctx.file_set:
                    matches.append(sub_file)
                elif sub_init in ctx.file_set:
                    matches.append(sub_init)
            return matches

        module_parts = base_parts + tail_segments
        return resolve_python_probe(module_parts, specifiers, ctx)

    if not tail_segments:
        return []

    importer_parts = (
        [s for s in importer_dir.split("/") if s] if importer_dir else []
    )
    for i in range(len(importer_parts), -1, -1):
        root_parts = importer_parts[:i]
        candidate_module = root_parts + tail_segments
        matches = resolve_python_probe(candidate_module, specifiers, ctx)
        if matches:
            return matches
    return []


def resolve_python_probe(
    module_parts: list[str], specifiers: list[str] | None, ctx: ResolutionContext
) -> list[str]:
    if not module_parts:
        return []
    base = "/".join(module_parts)
    matches: list[str] = []

    module_file = f"{base}.py"
    package_init = f"{base}/__init__.py"

    if module_file in ctx.file_set:
        matches.append(module_file)
        return matches
    if package_init in ctx.file_set:
        matches.append(package_init)
        if isinstance(specifiers, list):
            for spec in specifiers:
                if not spec or spec == "*" or "." in spec:
                    continue
                sub_file = f"{base}/{spec}.py"
                sub_init = f"{base}/{spec}/__init__.py"
                if sub_file in ctx.file_set:
                    matches.append(sub_file)
                elif sub_init in ctx.file_set:
                    matches.append(sub_init)
        return matches
    return []


# ---------------------------------------------------------------------------
# Go resolver
# ---------------------------------------------------------------------------


def resolve_go_import(
    raw_import: str | None, file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    if not isinstance(raw_import, str):
        return []
    src = raw_import.strip()
    if not src:
        return []

    importer_path = to_posix(file["path"])
    importer_dir = dir_of(importer_path)

    nearest_module_dir = find_nearest_config_dir(importer_dir, ctx.go_modules)
    if nearest_module_dir is None:
        if importer_path not in ctx._warned_no_go_module:
            ctx._warned_no_go_module.add(importer_path)
            sys.stderr.write(
                f"Warning: extract-import-map: Go file {importer_path} has no "
                f"ancestor go.mod — import {src} unresolvable — module-prefix "
                f"imports skipped\n"
            )
        return []

    module_name = ctx.go_modules[nearest_module_dir]

    if src == module_name:
        remainder = ""
    elif src.startswith(module_name + "/"):
        remainder = src[len(module_name) + 1 :]
    else:
        return []

    sub_dir = to_posix(remainder)
    if nearest_module_dir:
        target_dir = f"{nearest_module_dir}/{sub_dir}" if sub_dir else nearest_module_dir
    else:
        target_dir = sub_dir
    go_files = ctx.go_files_by_dir.get(target_dir)
    return list(go_files) if go_files else []


# ---------------------------------------------------------------------------
# Dotted-package resolver (Java / Kotlin / C#)
# ---------------------------------------------------------------------------


def resolve_dotted_fqn(
    fqn: str | None, ext: str, suffix_index: dict[str, list[str]]
) -> list[str]:
    if not isinstance(fqn, str) or not fqn:
        return []
    trimmed = re.sub(r"\.\*$", "", fqn)
    if not trimmed:
        return []
    file_part = trimmed.replace(".", "/") + ext
    matches = suffix_index.get(file_part)
    return list(matches) if matches else []


def resolve_java_import(
    raw_import: str | None, _file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    return resolve_dotted_fqn(raw_import, ".java", ctx.java_index)


def resolve_kotlin_import(
    raw_import: str | None, _file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    return resolve_dotted_fqn(raw_import, ".kt", ctx.kotlin_index)


def resolve_csharp_import(
    raw_import: str | None, _file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    return resolve_dotted_fqn(raw_import, ".cs", ctx.cs_index)


# ---------------------------------------------------------------------------
# Ruby resolver
# ---------------------------------------------------------------------------

RUBY_REQUIRE_RE = re.compile(
    r"""\b(require_relative|require)\s*\(?\s*(['"])([^'"`\n]+?)\2"""
)


def strip_ruby_comments(content: str) -> str:
    return re.sub(r"#[^\n]*", "", content)


def parse_ruby_imports(content: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    stripped = strip_ruby_comments(content)
    for m in RUBY_REQUIRE_RE.finditer(stripped):
        out.append(
            {
                "kind": "relative" if m.group(1) == "require_relative" else "absolute",
                "source": m.group(3),
            }
        )
    return out


def resolve_ruby_import(
    imp: dict[str, str], file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    source = imp["source"]
    if not source:
        return []
    importer_dir = dir_of(to_posix(file["path"]))
    with_ext = source if source.endswith(".rb") else source + ".rb"

    if imp["kind"] == "relative":
        base = resolve_relative(importer_dir, with_ext)
        return [base] if base in ctx.file_set else []

    probes = [f"lib/{with_ext}", f"app/{with_ext}", with_ext]
    for p in probes:
        if p in ctx.file_set:
            return [p]
    return []


# ---------------------------------------------------------------------------
# PHP resolver
# ---------------------------------------------------------------------------


def resolve_php_import(
    raw_import: str | None, file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    if not isinstance(raw_import, str):
        return []
    fqn = raw_import[1:] if raw_import.startswith("\\") else raw_import
    if not fqn:
        return []

    importer_dir = dir_of(to_posix(file["path"]))
    composer_dir = find_nearest_config_dir(importer_dir, ctx.php_autoloads)
    if composer_dir is None:
        return []
    autoload = ctx.php_autoloads.get(composer_dir)
    if not autoload:
        return []

    best_prefix: str | None = None
    best_dirs: list[str] | None = None
    for prefix, dirs in autoload.items():
        if fqn.startswith(prefix) and (
            best_prefix is None or len(prefix) > len(best_prefix)
        ):
            best_prefix = prefix
            best_dirs = dirs
    if best_dirs is None:
        return []

    assert best_prefix is not None
    relative = fqn[len(best_prefix) :].replace("\\", "/")
    if not relative:
        return []
    for d in best_dirs:
        if d:
            dir_under_composer = f"{composer_dir}/{d}" if composer_dir else d
        else:
            dir_under_composer = composer_dir
        candidate = (
            f"{dir_under_composer}/{relative}.php"
            if dir_under_composer
            else f"{relative}.php"
        )
        if candidate in ctx.file_set:
            return [candidate]
    return []


# ---------------------------------------------------------------------------
# Rust resolver
# ---------------------------------------------------------------------------


def probe_rust_module(base: str, file_set: set[str]) -> str | None:
    if not base:
        return None
    if f"{base}.rs" in file_set:
        return f"{base}.rs"
    if f"{base}/mod.rs" in file_set:
        return f"{base}/mod.rs"
    return None


def find_rust_crate_src(importer_dir: str, file_set: set[str]) -> str | None:
    parts = [s for s in importer_dir.split("/") if s]
    for i in range(len(parts), -1, -1):
        ancestor = "/".join(parts[:i])
        child_src = f"{ancestor}/src" if ancestor else "src"
        if f"{child_src}/lib.rs" in file_set or f"{child_src}/main.rs" in file_set:
            return child_src
    return None


def resolve_rust_import(
    raw_import: str | None, file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    if not isinstance(raw_import, str):
        return []
    src = raw_import.strip()
    if not src:
        return []

    importer_dir = dir_of(to_posix(file["path"]))
    segments = [s for s in src.split("::") if s]
    if not segments:
        return []
    head = segments[0]

    if head not in ("crate", "super", "self"):
        return []

    if head == "crate":
        crate_src = find_rust_crate_src(importer_dir, ctx.file_set)
        if not crate_src:
            importer_path = to_posix(file["path"])
            if importer_path not in ctx._warned_no_rust_crate_root:
                ctx._warned_no_rust_crate_root.add(importer_path)
                sys.stderr.write(
                    f"Warning: extract-import-map: Rust file {importer_path} has "
                    f"'use crate::' but no crate root (src/lib.rs or src/main.rs) "
                    f"found — crate-relative imports unresolved\n"
                )
            return []
        base_dir = crate_src
    elif head == "super":
        parts = [s for s in importer_dir.split("/") if s]
        if not parts:
            return []
        base_dir = "/".join(parts[:-1])
    else:  # self
        base_dir = importer_dir

    rest = segments[1:]
    for i in range(len(rest), 0, -1):
        prefix = rest[:i]
        base = (
            f"{base_dir}/{'/'.join(prefix)}" if base_dir else "/".join(prefix)
        )
        match = probe_rust_module(base, ctx.file_set)
        if match:
            return [match]
    return []


RUST_MOD_RE = re.compile(
    r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+(\w+)\s*;\s*$", re.MULTILINE
)


def extract_rust_mod_sources(content: str) -> list[str]:
    stripped = strip_js_like_comments(content)
    return [f"self::{m.group(1)}" for m in RUST_MOD_RE.finditer(stripped)]


# ---------------------------------------------------------------------------
# C / C++ resolver
# ---------------------------------------------------------------------------


def resolve_cpp_import(
    raw_import: str | None, file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    if not isinstance(raw_import, str):
        return []
    src = to_posix(raw_import.strip())
    if not src:
        return []
    importer_dir = dir_of(to_posix(file["path"]))

    candidates = [
        resolve_relative(importer_dir, src),
        f"include/{src}",
        f"src/{src}",
        src,
    ]
    for c in candidates:
        if c and c in ctx.file_set:
            return [c]
    return []


# ---------------------------------------------------------------------------
# Tree-sitter import-source extraction
#
# Replaces @understand-anything/core's per-language extractors. We only need
# the import `source` (and `specifiers` for Python) — the shapes mirror the
# core extractors exactly so the resolvers behave identically.
# ---------------------------------------------------------------------------


def _find_child(node: Any, type_name: str) -> Any | None:
    for c in node.children:
        if c.type == type_name:
            return c
    return None


def _find_children(node: Any, type_name: str) -> list[Any]:
    """All descendants of ``type_name`` (recursive, pre-order), like core."""
    out: list[Any] = []

    def walk(n: Any) -> None:
        for c in n.children:
            if c.type == type_name:
                out.append(c)
            walk(c)

    walk(node)
    return out


def _ts_string_value(node: Any, sb: bytes) -> str:
    for c in node.children:
        if c.type == "string_fragment":
            return node_text(c, sb)
    text = node_text(node, sb)
    return re.sub(r"""^['"`]|['"`]$""", "", text)


def extract_imports(language_id: str, content: str) -> list[dict[str, Any]]:
    """Extract {source, specifiers} entries via tree-sitter.

    Returns [] for languages without a tree-sitter extractor here (Kotlin,
    Ruby) — those go through their dedicated regex pathways.
    """
    parser = get_parser(language_id)
    if parser is None:
        return []
    sb = content.encode("utf-8")
    tree = parser.parse(sb)
    if tree is None:
        return []
    root = tree.root_node

    if language_id in ("typescript", "javascript"):
        return _extract_ts_js(root, sb)
    if language_id == "python":
        return _extract_python(root, sb)
    if language_id == "go":
        return _extract_go(root, sb)
    if language_id == "java":
        return _extract_java(root, sb)
    if language_id == "csharp":
        return _extract_csharp(root, sb)
    if language_id == "php":
        return _extract_php(root, sb)
    if language_id == "rust":
        return _extract_rust(root, sb)
    if language_id in ("c", "cpp"):
        return _extract_cpp(root, sb)
    return []


def _extract_ts_js(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []

    def handle_import(node: Any) -> None:
        source_node = _find_child(node, "string")
        if source_node is None:
            return
        imports.append(
            {"source": _ts_string_value(source_node, sb), "specifiers": []}
        )

    for node in root.children:
        if node.type == "import_statement":
            handle_import(node)
        elif node.type == "export_statement":
            # `export ... from '...'` re-exports carry a string source too.
            sn = _find_child(node, "string")
            if sn is not None:
                imports.append(
                    {"source": _ts_string_value(sn, sb), "specifiers": []}
                )
    return imports


def _extract_python(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    for node in root.children:
        if node.type == "import_statement":
            for dn in _find_children(node, "dotted_name"):
                # Only top-level dotted_names directly under the statement
                # matter; aliased imports nest dotted_name under aliased_import.
                if dn.parent is node:
                    txt = node_text(dn, sb)
                    imports.append({"source": txt, "specifiers": [txt]})
            for ai in _find_children(node, "aliased_import"):
                dn = _find_child(ai, "dotted_name")
                alias = next(
                    (c for c in ai.children if c.type == "identifier"), None
                )
                if dn is not None:
                    src = node_text(dn, sb)
                    spec = node_text(alias, sb) if alias is not None else src
                    imports.append({"source": src, "specifiers": [spec]})
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            source = node_text(module_node, sb) if module_node is not None else ""
            module_id = module_node.id if module_node is not None else None
            specifiers: list[str] = []
            for dn in _find_children(node, "dotted_name"):
                if dn.id == module_id:
                    continue
                # Skip dotted_names nested inside the module's relative_import.
                if module_node is not None and _is_descendant(dn, module_node):
                    continue
                specifiers.append(node_text(dn, sb))
            for ai in _find_children(node, "aliased_import"):
                alias = next(
                    (c for c in ai.children if c.type == "identifier"), None
                )
                if alias is not None:
                    specifiers.append(node_text(alias, sb))
            if _find_child(node, "wildcard_import") is not None:
                specifiers.append("*")
            imports.append({"source": source, "specifiers": specifiers})
    return imports


def _is_descendant(node: Any, ancestor: Any) -> bool:
    cur = node.parent
    while cur is not None:
        if cur.id == ancestor.id:
            return True
        cur = cur.parent
    return False


def _extract_go(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []

    def handle_spec(spec: Any) -> None:
        path_node = spec.child_by_field_name("path")
        if path_node is None:
            return
        content = _find_child(path_node, "interpreted_string_literal_content")
        if content is not None:
            source = node_text(content, sb)
        else:
            source = re.sub(r'^"|"$', "", node_text(path_node, sb))
        imports.append({"source": source, "specifiers": [source.split("/")[-1]]})

    for node in root.children:
        if node.type != "import_declaration":
            continue
        spec_list = _find_child(node, "import_spec_list")
        if spec_list is not None:
            for spec in _find_children(spec_list, "import_spec"):
                handle_spec(spec)
        else:
            spec = _find_child(node, "import_spec")
            if spec is not None:
                handle_spec(spec)
    return imports


def _extract_java(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    for node in root.children:
        if node.type != "import_declaration":
            continue
        has_asterisk = _find_child(node, "asterisk") is not None
        scoped = _find_child(node, "scoped_identifier")
        if scoped is None:
            continue
        full_path = node_text(scoped, sb)
        if has_asterisk:
            imports.append({"source": full_path, "specifiers": ["*"]})
        else:
            imports.append(
                {"source": full_path, "specifiers": [full_path.split(".")[-1]]}
            )
    return imports


def _extract_csharp(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []

    def using_source(node: Any) -> str | None:
        has_equals = _find_child(node, "=") is not None
        if has_equals:
            qn = _find_child(node, "qualified_name")
            return node_text(qn, sb) if qn is not None else None
        qn = _find_child(node, "qualified_name")
        if qn is not None:
            return node_text(qn, sb)
        ident = _find_child(node, "identifier")
        return node_text(ident, sb) if ident is not None else None

    def walk(node: Any) -> None:
        for child in node.children:
            if child.type == "using_directive":
                source = using_source(child)
                if source:
                    imports.append(
                        {"source": source, "specifiers": [source.split(".")[-1]]}
                    )
            elif child.type in (
                "namespace_declaration",
                "file_scoped_namespace_declaration",
            ):
                walk(child)

    walk(root)
    return imports


def _extract_php(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []

    def last_segment(fqn: str) -> str:
        return fqn.split("\\")[-1]

    def use_name(clause: Any, prefix: str) -> str:
        qn = _find_child(clause, "qualified_name")
        if qn is not None:
            return node_text(qn, sb)
        name_node = _find_child(clause, "name")
        if name_node is not None and prefix:
            return prefix + "\\" + node_text(name_node, sb)
        if name_node is not None:
            return node_text(name_node, sb)
        return node_text(clause, sb)

    def handle_use(node: Any) -> None:
        use_group = _find_child(node, "namespace_use_group")
        if use_group is not None:
            ns_name = _find_child(node, "namespace_name")
            prefix = node_text(ns_name, sb) if ns_name is not None else ""
            specifiers: list[str] = []
            for clause in _find_children(use_group, "namespace_use_clause"):
                specifiers.append(last_segment(use_name(clause, prefix)))
            source = (
                prefix + "\\{" + ", ".join(specifiers) + "}"
                if prefix
                else ", ".join(specifiers)
            )
            imports.append({"source": source, "specifiers": specifiers})
            return
        for clause in _find_children(node, "namespace_use_clause"):
            fqn = use_name(clause, "")
            imports.append({"source": fqn, "specifiers": [last_segment(fqn)]})

    def walk(node: Any) -> None:
        for child in node.children:
            if child.type == "namespace_use_declaration":
                handle_use(child)
            elif child.type == "namespace_definition":
                body = _find_child(child, "declaration_list")
                if body is not None:
                    walk(body)

    walk(root)
    return imports


def _rust_scoped_path(node: Any, sb: bytes) -> tuple[str, str]:
    if node.type == "scoped_identifier":
        path_node = node.child_by_field_name("path")
        name_node = node.child_by_field_name("name")
        path = node_text(path_node, sb) if path_node is not None else ""
        name = node_text(name_node, sb) if name_node is not None else ""
        return path, name
    return "", node_text(node, sb)


def _extract_rust(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    for node in root.children:
        if node.type != "use_declaration":
            continue
        argument = node.child_by_field_name("argument")
        if argument is None:
            continue
        t = argument.type
        if t == "identifier":
            txt = node_text(argument, sb)
            imports.append({"source": txt, "specifiers": [txt]})
        elif t == "scoped_identifier":
            path, name = _rust_scoped_path(argument, sb)
            imports.append({"source": path, "specifiers": [name]})
        elif t == "scoped_use_list":
            path_node = argument.child_by_field_name("path")
            list_node = argument.child_by_field_name("list")
            source = node_text(path_node, sb) if path_node is not None else ""
            specifiers: list[str] = []
            if list_node is not None:
                for ch in list_node.children:
                    if ch.type in ("self", "identifier", "scoped_identifier"):
                        specifiers.append(node_text(ch, sb))
            imports.append({"source": source, "specifiers": specifiers})
        elif t == "use_wildcard":
            scoped_id = _find_child(argument, "scoped_identifier")
            source = node_text(scoped_id, sb) if scoped_id is not None else ""
            imports.append({"source": source, "specifiers": ["*"]})
        else:
            txt = node_text(argument, sb)
            imports.append({"source": txt, "specifiers": [txt]})
    return imports


def _extract_cpp(root: Any, sb: bytes) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        for child in node.children:
            if child.type == "preproc_include":
                path_node = child.child_by_field_name("path")
                if path_node is None:
                    continue
                if path_node.type == "system_lib_string":
                    source = re.sub(r"^<|>$", "", node_text(path_node, sb))
                elif path_node.type == "string_literal":
                    content = _find_child(path_node, "string_content")
                    source = (
                        node_text(content, sb)
                        if content is not None
                        else re.sub(r'^"|"$', "", node_text(path_node, sb))
                    )
                else:
                    source = node_text(path_node, sb)
                imports.append({"source": source, "specifiers": [source]})
            else:
                walk(child)

    walk(root)
    return imports


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TS_JS_LANGS = frozenset({"typescript", "javascript", "tsx", "jsx", "vue"})


def resolve_import(
    imp: dict[str, Any], file: dict[str, Any], ctx: ResolutionContext
) -> list[str]:
    lang = file["language"]
    src = imp.get("source")
    if lang in TS_JS_LANGS:
        out = resolve_ts_js_import(src, file, ctx)
        return [out] if out else []
    if lang == "python":
        return resolve_python_import(src, imp.get("specifiers"), file, ctx)
    if lang == "go":
        return resolve_go_import(src, file, ctx)
    if lang == "java":
        return resolve_java_import(src, file, ctx)
    if lang == "kotlin":
        return resolve_kotlin_import(src, file, ctx)
    if lang == "csharp":
        return resolve_csharp_import(src, file, ctx)
    if lang == "php":
        return resolve_php_import(src, file, ctx)
    if lang == "rust":
        return resolve_rust_import(src, file, ctx)
    if lang in ("c", "cpp"):
        return resolve_cpp_import(src, file, ctx)
    return []


def extract_extra_import_sources(file: dict[str, Any], content: str) -> list[str]:
    lang = file["language"]
    if lang in TS_JS_LANGS:
        return extract_require_sources(content)
    if lang == "kotlin":
        return extract_kotlin_sources(content)
    if lang == "rust":
        return extract_rust_mod_sources(content)
    return []


# ---------------------------------------------------------------------------
# Tree-sitter "languages" used for structural import extraction. Maps the
# input file language to the grammar id passed to get_parser. Mirrors the JS
# `TS_JS_LANGS` handling — tsx/jsx/vue all use the TS/JS extractor.
# ---------------------------------------------------------------------------


def _extraction_language(lang: str) -> str | None:
    if lang in ("typescript", "javascript"):
        return lang
    if lang in ("tsx", "jsx", "vue"):
        return "typescript"
    if lang in (
        "python", "go", "java", "csharp", "php", "rust", "c", "cpp",
    ):
        return lang
    return None


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def extract_import_map(input_dict: dict[str, Any]) -> dict[str, Any]:
    """Build the import map for ``input_dict`` and return the result payload."""
    project_root = input_dict.get("projectRoot")
    files = input_dict.get("files")
    if not project_root or not isinstance(files, list):
        raise ValueError("Invalid input: must contain projectRoot and files array")

    # tree-sitter "init": probe one grammar so a totally-broken environment
    # degrades gracefully (empty importMap for every code file), mirroring the
    # JS graceful-init behavior.
    tree_sitter_ready = True
    try:
        if get_parser("typescript") is None:
            tree_sitter_ready = False
    except Exception as err:  # pragma: no cover - defensive
        tree_sitter_ready = False
        sys.stderr.write(
            f"Warning: extract-import-map: tree-sitter init failed "
            f"({err}) — all importMap entries will be empty — "
            f"structural graph will have no import edges\n"
        )
    if not tree_sitter_ready:
        sys.stderr.write(
            "Warning: extract-import-map: tree-sitter init failed "
            "(no parser available) — all importMap entries will be empty — "
            "structural graph will have no import edges\n"
        )

    ctx = ResolutionContext(project_root, files)

    import_map: dict[str, list[str]] = {}
    files_with_imports = 0
    total_edges = 0

    for file in files:
        path = to_posix(file["path"])

        if file.get("fileCategory") != "code":
            import_map[path] = []
            continue

        if not tree_sitter_ready:
            import_map[path] = []
            continue

        absolute_path = Path(project_root) / file["path"]

        try:
            content = absolute_path.read_text(encoding="utf-8")
        except OSError as err:
            sys.stderr.write(
                f"Warning: extract-import-map: import resolution failed for {path} "
                f"(read error: {err}) — importMap[{path}]=[]\n"
            )
            import_map[path] = []
            continue

        try:
            resolved_set: set[str] = set()

            if file["language"] == "ruby":
                for imp in parse_ruby_imports(content):
                    for out in resolve_ruby_import(imp, file, ctx):
                        if out and out in ctx.file_set:
                            resolved_set.add(out)
            else:
                extraction_lang = _extraction_language(file["language"])
                if extraction_lang is not None:
                    for imp in extract_imports(extraction_lang, content):
                        for out in resolve_import(imp, file, ctx):
                            if out and out in ctx.file_set:
                                resolved_set.add(out)
                for extra in extract_extra_import_sources(file, content):
                    for out in resolve_import(
                        {"source": extra, "specifiers": []}, file, ctx
                    ):
                        if out and out in ctx.file_set:
                            resolved_set.add(out)

            resolved = sorted(resolved_set)
        except Exception as err:
            sys.stderr.write(
                f"Warning: extract-import-map: import resolution failed for {path} "
                f"(analyze error: {err}) — importMap[{path}]=[]\n"
            )
            import_map[path] = []
            continue

        import_map[path] = resolved
        if resolved:
            files_with_imports += 1
            total_edges += len(resolved)

    return {
        "scriptCompleted": True,
        "stats": {
            "filesScanned": len(files),
            "filesWithImports": files_with_imports,
            "totalEdges": total_edges,
        },
        "importMap": import_map,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        sys.stderr.write(
            "Usage: python -m arch_analysis.extract_import_map "
            "<input.json> <output.json>\n"
        )
        return 1

    input_path, output_path = args[0], args[1]
    input_dict = json.loads(Path(input_path).read_text(encoding="utf-8"))

    output = extract_import_map(input_dict)

    Path(output_path).write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if not Path(output_path).exists():
        raise RuntimeError(f"output file missing after write: {output_path}")

    stats = output["stats"]
    sys.stderr.write(
        f"extract-import-map: filesScanned={stats['filesScanned']} "
        f"filesWithImports={stats['filesWithImports']} "
        f"totalEdges={stats['totalEdges']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
