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
| `models.py` | input/output | Pydantic models for input validation + the output contract |
| `grouping.py` | A, B | Directory grouping (common-prefix aware) + node-type grouping |
| `patterns.py` | G | Directory & file-level architectural pattern matching |
| `graph.py` | C, E, F, K | Import graph: fan-in/out, inter-group, density, direction, metrics |
| `topology.py` | D, H, I, J | Cross-category edges, deployment topology, data pipeline, doc coverage |
| `schema.py` | I/O | JSON Schema generation + `jsonschema`-based validation |
| `analyze.py` | — | CLI orchestrator: read → validate → compute → validate → write |

## JSON Schema

The pydantic models are the source of truth; `schema.py` renders them to
standalone Draft 2020-12 JSON Schema files under `schemas/`:

- `schemas/input.schema.json` — the input payload contract
- `schemas/output.schema.json` — the result contract

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
`filePatternMatches`, `interGroupMatrix`, and `graphMetrics`.

Exit code `0` on success, `1` on fatal error (message to stderr).

## Tests

```bash
pdm run pytest
```
