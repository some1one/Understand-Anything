# Native analysis engine

The standalone Rust library (`understand_anything`) and executable
(`understand-anything-rs`) power the deterministic Understand Anything pipeline.
The plugin invokes it through `run.sh`; packaged plugins include a platform
binary, while source checkouts build with stable Rust and Cargo on first use.

All commands have native implementations. The module-to-code/test inventory is
[`reference/coverage.json`](reference/coverage.json); observed results are recorded
in [`reference/verification.json`](reference/verification.json). **Full acceptance remains
pending execution of the four-platform CI matrix.** Captured differential tests
cover substantial behavior, not every possible input or diagnostic.

The native helper commands also cover project context capture, incremental changed
paths and pruning, graph saving, diff context, graph queries, and dictionary cache
refresh. Python helper entrypoints forward to these commands; JSON compatibility
requests use `helper_request`, `query_payload`, and `query_terms`.

## Build and run

Run these commands from this package directory (its `.cargo/config.toml` prevents
build-time grammar-source downloads):

```sh
cargo +stable build --locked --release
./target/release/understand-anything-rs --help
./target/release/understand-anything-rs scan_project /path/to/project /tmp/scan.json --exclude="docs/,e2e/,!e2e/keep.ts"
./target/release/understand-anything-rs json_schema --output-dir /tmp/ua-schemas
```

Use stable Rust to build; the dependency floor is Rust 1.90. Local verification
used Rust 1.98.1. Keep `Cargo.lock` with the package. The resulting executable
needs neither Python, PDM, Node nor Cargo. Git remains an optional subprocess for
file enumeration and is required for Git revision/update operations. The Linux
GNU executable uses the operating system's standard dynamic libraries.

The executable preserves the existing underscore command names and legacy aliases.
Relative arguments resolve against the invoking working directory. Commands use
their existing output locations under `.ua` (or the existing legacy `.understand-anything` directory) unless an explicit
output argument is supplied. Schema export defaults to `./schemas` and copies
embedded schemas; it does not regenerate the checked-in schema files.

## Parsers

```sh
./target/release/understand-anything-rs parsers list
./target/release/understand-anything-rs --parser-cache-dir /tmp/ua-parsers parsers fetch
./target/release/understand-anything-rs --parser-cache-dir /tmp/ua-parsers parsers fetch rust python tsx
```

The 15 supported grammar IDs are `typescript`, `tsx`, `javascript`, `python`,
`go`, `rust`, `java`, `kotlin`, `csharp`, `php`, `ruby`, `c`, `cpp`, `swift`, and `scala`.
`tree-sitter-language-pack` and its release/cache version are pinned to **1.20.0**.
Parsers download on first use into the language pack's versioned platform cache;
`--parser-cache-dir` changes its base directory. Predownload the needed grammars
for offline operation. Fetch diagnostics go to stderr, and explicit fetch
failures return nonzero. Analysis retains the reference's empty/skip behavior
when a parser is unavailable. Non-code parsing needs no downloaded grammar.

The frozen Python environment used parser pack 1.12.1. Structural and import
fixtures check compatibility with that reference; this is not a claim that the
two parser releases contain identical grammars.

## Library

Subsystems are public modules. Most functions accept or return `serde_json::Value`
to retain extension metadata. Validated record newtypes in `models` expose
`from_value`, `as_value`, `into_value`, and `without_nulls`; deserialization applies
record defaults, coercions, and its own allow/ignore/forbid policy. Failures use
`Error` variants, including structured validation paths and messages.

```rust
use serde_json::json;
use understand_anything::{models::ProjectConfig, search::SearchEngine};

let config = ProjectConfig::from_value(json!({"includedParts": ["src"]}))?;
assert_eq!(config["autoUpdate"], false);
let index = SearchEngine::new(vec![json!({
    "id": "file:auth.rs", "type": "file", "name": "Authentication",
    "summary": "Manages login sessions", "tags": ["auth"]
})]);
let hits = index.search("login", &[], 10);
Ok::<(), understand_anything::Error>(())
```

- `scan`, `input`, `imports`, `structure`, `noncode`, and `domain_context` provide
  file discovery, import resolution, structural analysis and domain context.
- `analytics` and `batching` provide graph metrics, recommendations, and seeded
  Louvain grouping. Seed 42 and sorted traversal give repeatable memberships;
  memberships need not match Python's Louvain implementation.
- `assembly`, `seed`, `batch_validation`, `batch_merge`, `partition`, and `merge`
  provide the graph and partition pipeline, boundary stubs, and test/import recovery.
- `validation` repairs graphs; `schemas` strictly validates pipeline contracts.
  Their different unknown-field policies are deliberate.
- `persistence`, `fingerprints`, `staleness`, and `updates` provide artifact IO and
  incremental updates. `updates::GitClient` allows deterministic Git fixtures.
- `search`, `embeddings`, and `skills` provide fuzzy/cosine search, embeddings and
  chat/diff/explain/onboarding prompt builders.

Embeddings remain opt-in through `UNDERSTAND_EMBEDDINGS_API_KEY`. The model and
base URL use `UNDERSTAND_EMBEDDINGS_MODEL` and `UNDERSTAND_EMBEDDINGS_BASE_URL`.
`EmbeddingClient` is injectable; tests use a fake client and a local HTTP server.
No test sends an embedding request to a hosted service.

## Verification

```sh
cargo +stable fmt --check
cargo +stable clippy --locked --all-targets -- -D warnings
cargo +stable test --locked
export UA_TEST_PARSER_CACHE=/tmp/ua-parsers
cargo +stable test --locked --test runtime -- --ignored
cargo +stable test --locked --test differential -- --ignored
```

Ordinary tests use a frozen dictionary subset and require no downloads. The
compatibility-launcher test requires Python 3. Ignored tests are explicit parser
integration tests (first run downloads grammars), command/update fixtures using
those parsers, and a local HTTP test. After warming the cache, parser tests also
run with unreachable proxy settings to check offline loading. Corrupt,
interrupted, and wrong-version cache cases run in isolated subprocesses.

The workflow at `../../../.github/workflows/rust-engine.yml` builds and tests
`x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu`,
`x86_64-apple-darwin`, and `aarch64-apple-darwin`. It runs formatting, Clippy,
ordinary/integration tests, a release build, and executable smoke checks with an
empty `PATH`, including cached structural extraction.

### Repository smoke test

```sh
cargo +stable build --locked --release
./target/release/understand-anything-rs --parser-cache-dir "$PWD/target/smoke-parsers" parsers fetch
python3 scripts/smoke.py
```

This development driver copies the current source into a fresh temporary directory
and exercises all 33 commands, including every scan batch, graph assembly,
validation, fingerprints, and a structural incremental update. Deterministic seed
graphs and synthetic layers stand in for the LLM stages. Native subprocesses use
an empty `PATH`, a warm parser cache, disabled embeddings, and unreachable proxies.
The driver itself needs Python and Git; the Rust runtime does not need Python.

The script prints the artifact directory and keeps command stdout/stderr, statuses,
and `report.json` there for inspection. Original source and analysis artifacts are
never used as output locations. Parser fetching is an explicit setup step: do not
reuse a deleted temporary cache and interpret empty parser output as successful
extraction. The default cache lives in the ignored `target/smoke-parsers` directory.
Use `--binary` or `--parser-cache` to test another executable or cache.
The latest local run is recorded in [`reference/smoke.json`](reference/smoke.json).

Fixtures under `tests/fixtures` record Python results, command streams, statuses,
and filesystem effects. Comparisons exclude temporary-root prefixes and generated
timestamps; numeric tolerance is `1e-9`. Rankings and meaningful array order are
retained. Louvain tests instead check repeatability, coverage, bounds, and neighbors.

The fixtures under `tests/fixtures/` preserve the original Python engine's
observed behavior for differential regression testing. They are historical test
data; normal builds and runtime do not need the old Python package.

## Command inventory

| Command | Legacy alias |
| --- | --- |
| `affected_parts` |  |
| `analyze` |  |
| `assemble_part_graph` |  |
| `assemble_project_scan_result` | `assemble-scan` |
| `auto_update_apply_batches` | `auto-update-apply-batches` |
| `auto_update_finalize` | `auto-update-finalize` |
| `auto_update_fingerprint_check` | `auto-update-fingerprint-check` |
| `auto_update_preflight` | `auto-update-preflight` |
| `auto_update_prepare_batches` | `auto-update-prepare-batches` |
| `build_fingerprints` |  |
| `compute_batches` | `batches` |
| `detect_layout` |  |
| `extract_domain_context` | `domain-context` |
| `extract_import_map` | `import-map` |
| `extract_structure` | `structure` |
| `finalize_file_batch_output` | `finalize-file-batch` |
| `generate_ignore` |  |
| `generate_input` |  |
| `json_schema` |  |
| `merge_batch_graphs` | `merge-batches` |
| `merge_parts` |  |
| `merge_subdomain_graphs` | `merge-subdomains` |
| `partition_files` |  |
| `parts_to_process` |  |
| `prepare_file_analysis_batch` | `prepare-batch` |
| `prepare_part_batches` |  |
| `prepare_architecture_update` |  |
| `prepare_part_symbol_retry` |  |
| `scan_project` | `scan` |
| `seed_file_batch_graph` | `seed-file-batch` |
| `validate_assembled_graph` | `validate-assembled-graph` |
| `validate_domain_graph` | `validate-domain-graph` |
| `validate_graph` | `validate-graph` |
| `validate_layers` |  |
| `validate_structure_output` | `validate-structure-output` |
| `write_config` |  |

The parser integration uses the language pack’s [low-level Rust API](https://docs.tree-sitter-language-pack.xberg.io/reference/api-rust/); strict validation uses the [Draft 2020-12 validator](https://docs.rs/jsonschema/0.45.1/jsonschema/draft202012/index.html).

## Selective import extraction

`extract_import_map` accepts an optional `analysisPaths` array of project-relative
paths in its input JSON. Keep `files` as the complete current inventory: resolution
still needs unchanged files and configuration. Only selected files are read for
imports and emitted in `importMap`; `stats.filesScanned` counts that selection.
Omit `analysisPaths` for a full scan, or use an empty array for no work. Selections
are deduplicated in request order. Unknown, absolute, escaping, or malformed paths
fail instead of silently producing incomplete results. Unix backslashes remain
literal filename characters. Callers must merge the selected results into their
previous map and explicitly remove entries for deleted files; a partial result is
not a replacement for the entire project import map.

Incremental fingerprint comparison reconciles the saved graph inventory with a
fresh scoped scan, adding newly included files and pruning deleted/excluded files
even when Git's changed list does not mention them. The before/after inventories
also drive architecture decisions. Incomplete scans stop classification before
metadata changes. Newly discovered ignore controls trigger scope reconciliation
without becoming semantic targets.

Incremental batch preparation rescans the current inventory and aborts on reported
scan failures or missing analysis targets. It refreshes imports for changed files
when the cached inventory and map are complete. Added/deleted paths, resolver
configuration changes, or an incomplete cache trigger a full import refresh so
unchanged importers can resolve newly available targets. Source-read, parser-load,
and resolver-configuration failures leave previous preparation outputs intact.
This refresh updates batch inputs; graph publication remains a separate phase.

## Graph freshness

`run.sh graph_freshness <project-root> [input.json]` performs a read-only check.
With no input file, it uses the commit and analysis time stored in the selected
project data directory's `knowledge-graph.json`. It does not substitute a newer
metadata watermark or start analysis.

An input object can supply `graphCommitHash` and optional `lastAnalyzedAt`, or
be the saved graph itself (including a selected partition graph).
For multiple snapshots, use `{"graphs":{"name":{"graphCommitHash":"…"}}}`;
all entries share one HEAD/worktree snapshot. Results distinguish `fresh`,
`dirty`, `stale` (with `behind`, `ahead`, or `diverged`), and `unknown`.
Git failures and timeouts produce `unknown`, never a claim that the graph is fresh.
Changed paths are scoped to the requested project and exclude generated files
inside `.ua` and `.understand-anything`. Each Git command has a five-second
limit and a four-MiB output limit.

`scan_project` accepts `--exclude=pattern,...` or `--exclude pattern,...`, including
repeated options. Patterns use gitignore syntax and are applied in argument order
after defaults and both `.understandignore` files; `!` negates an earlier rule.
Quote patterns so the shell does not expand them. This filters the scanner's
existing file inventory; it does not make Git-ignored, untracked files enumerable.
Nonempty patterns are retained as `excludePatterns` in scan and assembled scan
output. They do not modify ignore files.

Changed-file handoffs (`write_changed_files`, `compute_batches --changed-files`,
`affected_parts`, and `parts_to_process --changed`) use JSON arrays of paths.
`partition_files` writes `intermediate/part-files/<encoded-part>.json`; the
analysis workflow passes these lists directly to batching. JSON preserves embedded
newlines and filename whitespace. Readers still accept legacy newline- or
NUL-delimited lists. Invalid JSON fails before batch output is replaced.

With `compute_batches --changed-files`, only listed targets are emitted for
analysis. Unchanged imports and importers remain available in `neighborMap`,
with their full-graph batch identities; they do not become analysis targets.

Incremental preparation preserves the original scan and import map in
`intermediate/incremental-scan-baseline.json`, keyed by the analyzed base commit.
Retries against another HEAD reuse this baseline instead of an abandoned
attempt's `scan-result.json`. Keep the baseline with failed-update artifacts;
successful finalization removes it with the other recovery intermediates.

`merge_batch_graphs` recognizes the reserved `batch-existing.json` incremental
baseline alongside numeric analyzer batches. It loads the baseline first so fresh
nodes override duplicate IDs, and retains it even when no analyzer batches are
planned. An invalid baseline stops merging without replacing the assembled graph.
The caller must prune replaced/deleted files from the baseline before merging.

`prepare_part_batches <project-root> <part> [--full]` prepares a partition update
from that part's saved commit, including local tracked changes and untracked
assigned files. It archives previous batch scratch, writes a pruned baseline and
selected batch plan, and records the graph/scan/source snapshot. Partition
publication rejects changed snapshots and missing assigned-file coverage, then
uses verified symbol replacements to recover incoming and fresh candidate edges.
Keep the preparation and recovery artifacts after a failed analysis.

`prepare_part_symbol_retry <project-root> <part>` permits one targeted repair for
symbol omissions in a prepared partition update. It retains successful outputs
and incoming edge evidence, archives failed batches, and writes batches for only
the reported files. The limit is tied to the saved graph and source snapshot;
repreparing that snapshot does not reset it. Source or identity errors block
repair. If repaired assembly fails, stop and retain the saved graph and recovery
artifacts. Successful publication removes the repair marker.

`prepare_architecture_update <project-root> [--full]` plans architecture work after
partition merging using the selected graph inventory and saved fingerprints.
Localized updates reuse layers with deterministic placement by common parent
directory, distinct graph neighbors, then original layer order. Directory changes,
major restructuring, full runs, and unusable baselines require architecture analysis.
The command writes `architecture-update-plan.json` and, only when reusing layers,
`layers.json`. Incremental assemble-review dispatch can be skipped as directed by
the plan; graph validation and an explicit user review remain required.

With refreshed scan and partition inventories, `parts_to_process` supplements the
merged changed-file list with each saved partition's revision and assigned scope.
A stale, ahead-of-HEAD, newly scoped, or unverifiable part is selected even when
absent from that changed-file list. Calls without scan artifacts retain the
legacy affected-path/missing-part selection behavior.
