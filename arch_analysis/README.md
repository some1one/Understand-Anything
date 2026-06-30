# arch_analysis

Deterministic structural-analysis scripts for the **architecture-analyzer**
agent (`understand-anything-plugin/agents/architecture-analyzer.md`, Phase 1).

The agent's prompt embeds a large, project-agnostic "write and run a script"
spec: directory grouping, import adjacency, density, pattern matching,
deployment topology, etc. That logic is deterministic and doesn't belong in a
per-run prompt — this package implements it once, in a tested, organized form.

## Layout

| Module | Spec sections | Responsibility |
|---|---|---|
| `constants.py` | G, H, Phase 2 | All pattern tables, filename sets, extensions, thresholds |
| `models.py` | input/output | Pydantic models for input, the output contract, and Phase 2 layers |
| `grouping.py` | A, B | Directory grouping (common-prefix aware) + node-type grouping |
| `patterns.py` | G | Directory & file-level pattern matching + node-type inference |
| `graph.py` | C, E, F, K | Import graph: fan-in/out, inter-group, density, direction, metrics |
| `topology.py` | D, H, I, J | Cross-category edges, deployment topology, data pipeline, doc coverage |
| `recommendations.py` | Phase 2 (1-3, 6) | Automatable Phase 2 signals: group roles, suggested layers, non-code layer suggestions, topo order, default assignment |
| `generate_input.py` | — | Build the input JSON for a whole project, obeying `.gitignore` |
| `validate_layers.py` | Phase 2 cross-check | Validate `layers.json`: every node in exactly one layer, no invented ids |
| `schema.py` | I/O | JSON Schema generation + `jsonschema`-based validation |
| `analyze.py` | — | CLI orchestrator: read → validate → compute → validate → write |
| `assemble_project_scan_result.py` | scan | Merge narrative + deterministic scan/import outputs → validated `scan-result.json` |
| `prepare_file_analysis_batch.py` | analyze | From `batches.json`, emit per-batch `extract_structure` input + validated context |
| `validate_structure_output.py` | analyze | Validate `extract_structure` output: schema + batch coverage |
| `file_graph.py` | analyze | Shared deterministic file-node typing + tag rules (seed ↔ finalize) |
| `seed_file_batch_graph.py` | analyze | Deterministic file/function/class nodes, tags, and `imports`/`contains`/`exports` edges |
| `finalize_file_batch_output.py` | analyze | Validate seed preservation + import coverage + cross-batch refs, split, and write `batch-*.json` |
| `validate_assembled_graph.py` | assemble | Pre-layer graph validation (`require_layers=False`) + optional scan-coverage cross-check |
| `validate_domain_graph.py` | domain | Schema + domain-specific review (hierarchy coverage, monotonic flow weights) |
| `fingerprints.py` | auto-update | Shared content-hash + structural-fingerprint logic, comparison, update classification, and load-patch-save store writes |
| `auto_update_common.py` | auto-update | Shared `.understand-anything` path layout, JSON IO, git plumbing, source filtering, `meta.json` writes |
| `auto_update_preflight.py` | auto-update | Phase 0: validate graph/meta, diff commits, filter source + `.understandignore`, handle metadata-only stops |
| `auto_update_fingerprint_check.py` | auto-update | Phase 1: classify changed files vs. stored fingerprints, derive the SKIP/PARTIAL/ARCHITECTURE/FULL decision |
| `auto_update_prepare_batches.py` | auto-update | Phase 2a: changed-file batching (reuses `compute_batches`) + dispatch summary |
| `auto_update_apply_batches.py` | auto-update | Phase 2b: prune changed/deleted-file nodes, merge fresh batches, emit merged graph / arch-rerun input |
| `auto_update_finalize.py` | auto-update | Phase 3: apply layers, lite validation, save graph, patch fingerprints, bump meta, clean intermediate |

## CLI scripts

```bash
# 1. Generate the input file inventory for a project (obeys .gitignore).
pdm run python -m arch_analysis.generate_input <project_root> input.json \
    [--include 'src/**/*.py' ...] [--exclude '**/tests/**' ...] [--no-gitignore]
#    (import/all edges come from the pipeline and are merged into input.json)

# 2. Run the structural analysis.
pdm run analyze input.json results.json

# 3. After the agent writes layers.json, cross-check it.
pdm run python -m arch_analysis.validate_layers input.json layers.json
```

## Auto-update (incremental) command flow

The post-commit hook (`understand-anything-plugin/hooks/auto-update-prompt.md`)
drives an incremental update by chaining these deterministic commands. Each
writes its output under `.understand-anything/intermediate/` and prints a
machine-readable JSON summary to stdout. LLM work is limited to the file-analyzer
and architecture-analyzer dispatches between phases 2a and 3.

```bash
# Phase 0 — pre-flight. Validates graph/meta, diffs commits, filters source +
# .understandignore. STOPs (and bumps meta.json) on no-op cases.
pdm run auto-update-preflight <project-root> [--force]
#   → intermediate/auto-update-state.json  {status, action, changedSourceFiles, ...}

# Phase 1 — fingerprint check (zero LLM tokens). Classifies each changed file
# NONE/COSMETIC/STRUCTURAL and derives the decision. SKIP bumps meta and stops.
pdm run auto-update-fingerprint-check <project-root>
#   → intermediate/change-analysis.json    {action, filesToReanalyze, newFiles, ...}

# Phase 2a — batch the files to reanalyze (reuses compute_batches).
pdm run auto-update-prepare-batches <project-root>
#   → intermediate/batches.json, intermediate/dispatch-summary.json

#   ⇣ LLM: dispatch file-analyzer once per batch → intermediate/batch-<N>.json

# Phase 2b — prune changed/deleted-file nodes, merge fresh batches.
pdm run auto-update-apply-batches <project-root>
#   → intermediate/merged-graph.json (+ ua-arch-input.json when rerunArchitecture)

#   ⇣ LLM (only when ARCHITECTURE_UPDATE): dispatch architecture-analyzer on
#     ua-arch-input.json → intermediate/layers.json

# Phase 3 — apply layers, validate, save, patch fingerprints, clean up.
pdm run auto-update-finalize <project-root>
#   → knowledge-graph.json, fingerprints.json (patched), meta.json,
#     intermediate/auto-update-summary.json
```

The decision gate in `change-analysis.json`:

| `action` | Trigger | Hook behavior |
|---|---|---|
| `SKIP` | no structural changes | bump meta, stop (zero tokens) |
| `PARTIAL_UPDATE` | ≤10 structural files, known dirs | re-analyze files, lite layer update |
| `ARCHITECTURE_UPDATE` | new/removed dirs or >10 structural files | re-analyze + re-run architecture |
| `FULL_UPDATE` | >30 structural files or >50% of graph | recommend `/understand --full`, stop |

## JSON Schema

The pydantic models are the source of truth; `schema.py` renders them to
standalone Draft 2020-12 JSON Schema files under `schemas/`:

- `schemas/input.schema.json` — the input payload contract
- `schemas/output.schema.json` — the result contract
- `schemas/layers.schema.json` — the Phase 2 layer-assignment contract
- `schemas/scan-result.schema.json` / `schemas/project-scan-output.schema.json` — raw scan result and the final project-scanner contract
- `schemas/structure-input.schema.json` / `schemas/structure-output.schema.json` — `extract_structure` I/O
- `schemas/file-analysis-context.schema.json` — deterministic per-batch context for the file-analyzer
- `schemas/graph-fragment.schema.json` — file-analyzer batch/part output (`{nodes, edges}`)
- `schemas/knowledge-graph.schema.json` / `schemas/domain-graph.schema.json` — full structural and domain graph contracts

`analyze.py` validates the input payload against `input.schema.json` before
parsing and the result against `output.schema.json` before writing, in addition
to pydantic's own validation. Regenerate the files after editing the models:

```bash
pdm run python -m arch_analysis.schema
```

A drift test (`tests/test_schema.py`) fails if the committed schema files no
longer match the models.

## Dependencies (and why)

- **orjson** — fast JSON read/write of the input/result payloads
- **pydantic** — validated, dataclass-like records for input and the output contract
- **networkx** — the import graph itself: fan-in/out, components, DAG checks
- **numpy / scipy** — fan-in/fan-out correlation (`spearmanr`) and array math
- **pandas** — pivots the inter-group import counts into a dense matrix

## Usage

```bash
# via the pdm script (preferred)
pdm run analyze input.json results.json

# or directly
pdm run python -m arch_analysis.analyze input.json results.json
```

Input JSON shape (`fileNodes`, `importEdges`, `allEdges`) and the result schema
are documented in the agent markdown. The result includes every documented key
plus a few extra deterministic signals: `commonPathPrefix`,
`filePatternMatches`, `interGroupMatrix`, `graphMetrics`, and
`phase2Recommendations` (the automatable Phase 2 signals).

Exit code `0` on success, `1` on fatal error (message to stderr).

## Tests

```bash
pdm run pytest
```
