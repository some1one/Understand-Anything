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

## Build and run

Run these commands from this package directory (its `.cargo/config.toml` prevents
build-time grammar-source downloads):

```sh
cargo +stable build --locked --release
./target/release/understand-anything-rs --help
./target/release/understand-anything-rs scan_project /path/to/project /tmp/scan.json
./target/release/understand-anything-rs json_schema --output-dir /tmp/ua-schemas
```

Use stable Rust to build; the dependency floor is Rust 1.90. Local verification
used Rust 1.98.1. Keep `Cargo.lock` with the package. The resulting executable
needs neither Python, PDM, Node nor Cargo. Git remains an optional subprocess for
file enumeration and is required for Git revision/update operations. The Linux
GNU executable uses the operating system's standard dynamic libraries.

The executable preserves the existing underscore command names and legacy aliases.
Relative arguments resolve against the invoking working directory. Commands use
their existing output locations under `.understand-anything` unless an explicit
output argument is supplied. Schema export defaults to `./schemas` and copies
embedded schemas; it does not regenerate the checked-in schema files.

## Parsers

```sh
./target/release/understand-anything-rs parsers list
./target/release/understand-anything-rs --parser-cache-dir /tmp/ua-parsers parsers fetch
./target/release/understand-anything-rs --parser-cache-dir /tmp/ua-parsers parsers fetch rust python tsx
```

The 13 supported grammar IDs are `typescript`, `tsx`, `javascript`, `python`,
`go`, `rust`, `java`, `kotlin`, `csharp`, `php`, `ruby`, `c`, and `cpp`.
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

Ordinary tests require no Python or downloads. Ignored tests are explicit parser
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
| `scan_project` | `scan` |
| `seed_file_batch_graph` | `seed-file-batch` |
| `validate_assembled_graph` | `validate-assembled-graph` |
| `validate_domain_graph` | `validate-domain-graph` |
| `validate_graph` | `validate-graph` |
| `validate_layers` |  |
| `validate_structure_output` | `validate-structure-output` |
| `write_config` |  |

The parser integration uses the language pack’s [low-level Rust API](https://docs.tree-sitter-language-pack.xberg.io/reference/api-rust/); strict validation uses the [Draft 2020-12 validator](https://docs.rs/jsonschema/0.45.1/jsonschema/draft202012/index.html).
