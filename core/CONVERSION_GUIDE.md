# TS → Python conversion guide (core project)

We are porting `understand-anything-plugin/src` (skill builders) and
`understand-anything-plugin/packages/core` (the `@understand-anything/core`
engine) from TypeScript to Python into this `core/` PDM project.

**Do NOT touch** the dashboard, skills, hooks, or agents — only the two
TS source trees above are in scope.

## Reuse-first principle (IMPORTANT)

A large share of `packages/core` is **already implemented in Python** in the
`arch_analysis/` package at the repo root. Where equivalent functionality
already exists there, **import and re-export it instead of rewriting**.
Import with `from arch_analysis.<module> import <name>` — do **not** worry that
`arch_analysis` is not on this project's path; the user will relocate it and
fix imports later. Just write the import as `arch_analysis.*`.

Known equivalents already in `arch_analysis` (verify the exact names yourself):

| TS source | arch_analysis equivalent |
|---|---|
| `plugins/tree-sitter-plugin.ts` (parser registry) | `arch_analysis.treesitter` (`get_parser`, `parse`, `node_text`) |
| `languages/*` language **detection** | `arch_analysis.languages` (`detect_language`, `detect_category`, `estimate_complexity`) |
| `ignore-filter.ts` | `arch_analysis.languages` (`IgnoreFilter`, `create_ignore_filter`, `enumerate_files`) |
| `ignore-generator.ts` | `arch_analysis.generate_ignore` |
| `plugins/extractors/*` (structural extraction) | `arch_analysis.structure` (`analyze_file`, `extract_call_graph`, `StructuralAnalysis`) + `arch_analysis.structure.code_extractors` |
| `plugins/parsers/*` (non-code parsers) | `arch_analysis.structure.parsers` |
| `plugins/registry.ts` | `arch_analysis.structure.registry` |
| `fingerprint.ts` | `arch_analysis.fingerprints` |
| `change-classifier.ts` | `arch_analysis.fingerprints` (update classification) |
| `staleness.ts` | `arch_analysis.auto_update_*` / `arch_analysis.fingerprints` |
| graph types (GraphNode/Edge/KnowledgeGraph) | `arch_analysis.models` |
| `schema.ts` validation | `arch_analysis.schema` |
| `analyzer/normalize-graph.ts` | `arch_analysis.merge_batch_graphs` (overlap — reuse where possible) |

When you reuse, write a thin wrapper module that imports from `arch_analysis`
and exposes the same public names the TS module exported (snake_cased). If the
arch_analysis function signature differs, adapt with a small shim. If only part
overlaps, reuse the overlapping part and port the rest.

Genuinely **new** ports (no arch_analysis equivalent — port faithfully):
`search.ts`, `embedding-search.ts`, `analyzer/llm-analyzer.ts`,
`analyzer/layer-detector.ts` (prompt builders), `analyzer/language-lesson.ts`,
`analyzer/graph-builder.ts`, the language/framework **config registries** and
config data, `plugins/discovery.ts`, and all of `src/` (skill builders).

## Project layout

```
core/
  pyproject.toml          # PDM project, distribution=false, py>=3.14
  understand_core/        # port of packages/core  (package: understand_core)
    types.py              # <- types.ts
    schema.py             # <- schema.ts
    search.py             # <- search.ts            (use rapidfuzz)
    embedding_search.py   # <- embedding-search.ts  (use numpy)
    persistence.py        # <- persistence/index.ts
    fingerprint.py        # <- fingerprint.ts
    change_classifier.py  # <- change-classifier.ts
    staleness.py          # <- staleness.ts
    ignore_filter.py      # <- ignore-filter.ts
    ignore_generator.py   # <- ignore-generator.ts
    analyzer/
      graph_builder.py language_lesson.py layer_detector.py
      llm_analyzer.py normalize_graph.py
    languages/
      types.py language_registry.py framework_registry.py
      configs/<lang>.py   # one module per language config
      frameworks/<fw>.py  # one module per framework config
    plugins/
      tree_sitter_plugin.py registry.py discovery.py
      extractors/<lang>_extractor.py + base_extractor.py + types.py
      parsers/<kind>_parser.py
  skill_builders/         # port of src/  (package: skill_builders)
    __init__.py           # <- src/index.ts (public re-exports)
    context_builder.py understand_chat.py diff_analyzer.py
    explain_builder.py onboard_builder.py
  tests/                  # pytest ports of the *.test.ts / __tests__ suites
```

File naming: kebab-case `.ts` → snake_case `.py` (`change-classifier.ts` →
`change_classifier.py`, `cpp-extractor.ts` → `cpp_extractor.py`).

## Conventions

- `from __future__ import annotations` at the top of every module.
- Full type hints. Prefer `pydantic` `BaseModel` for the zod schemas /
  TS interfaces that carry data. Match `arch_analysis.models` style.
- **Preserve JSON wire keys**: the knowledge-graph JSON is camelCase
  (`nodeId`, `languageNotes`, `filePatterns`). Mirror exactly how
  `arch_analysis.models` does it (pydantic with `alias` / `populate_by_name`,
  `model_config = ConfigDict(populate_by_name=True)`). Reuse those models
  rather than redefining when they already exist.
- Function/variable names: snake_case. Exported TS `buildChatContext` →
  `build_chat_context`. Class names stay PascalCase (`SearchEngine`).
- zod schemas → pydantic models; zod `.parse()` → `Model.model_validate()`.
- Replace JS libs: `fuse.js` → `rapidfuzz`; `yaml` → `pyyaml`;
  `ignore` → `pathspec` (or reuse arch_analysis's IgnoreFilter).
- Tests: port `*.test.ts` / `__tests__/*` to `tests/test_<name>.py` (pytest).
  Keep the same cases. If a test depends on JS-only behavior, port the intent.
- Each package `__init__.py` should re-export its public API (mirror the
  corresponding `index.ts`).
- Keep docstrings short; explain anything non-obvious in the port.

## Cross-module contract (so parallel work stays consistent)

- Graph data types live in `understand_core.types` and should re-export /
  alias `arch_analysis.models` types (`GraphNode`, `Edge`, `KnowledgeGraph`,
  etc.). Import them from `understand_core.types` elsewhere.
- `search.SearchEngine(nodes)` with `.search(query, types=None, limit=50)`
  returning `list[SearchResult]` (`SearchResult` = `{node_id, score}`).
- Skill builders import core via `from understand_core import ...`.
