# Native large-repository benchmark

This guide covers `make benchmark-large-repo`: native stage timing without AI.
For an existing graph, use [saved analysis statistics](static-analysis.md).
For separately timed setup/builds, Valgrind profiles and one Codex graph analysis,
use the [full-run benchmark](../../scripts/benchmark/README.md).

The opt-in harness measures the fork's production Rust scanner, import extractor,
batch planner, and structural extractor. Python 3.11+ provides orchestration and
POSIX process accounting; it does not implement analysis. Git and a stable Rust
toolchain with the locked Cargo dependencies already fetched are required. Linux and macOS are
supported. The harness does not run LLMs, produce graphs, count tokens, estimate
cost, or measure end-to-end analysis or dashboard performance.

It adapts upstream PR #587 at commit
`f2d0164f72fe678805c34245a6df36acededfebd`. The Rust report uses schema **2.0.0**,
[defined here](large-repo-report-2.0.0.schema.json), because native process timings,
parser coverage, and output semantics differ from upstream JavaScript schema
1.0.0. See the [command map](native-command-map.md) for exact dispatcher contracts.

## Prepare once, outside measurement

From the tool checkout, build the selected engine and preconfigure parser assets:

```sh
make build-core
understand-anything-plugin/packages/rust/run.sh --parser-cache-dir /tmp/ua-benchmark-parsers parsers fetch
```

Fetching is an explicit preparation action with network access. Benchmark runs
use offline Cargo builds and `--offline-parsers`; they never fetch a grammar.
The parser version is pinned to 1.20.0 and every installed asset is hashed.
Dictionaries are unused by these four stages and reported as such. Keep the
cache fixed between comparisons. The default command builds release once before
timing stages; `--no-build` requires a fresh source binary of the selected mode.
When the tool itself is inside the subject, prebuild and use `--no-build` so the
benchmark does not write build artifacts into the subject.

## Run explicitly

```sh
python3 scripts/benchmark_large_repo.py /absolute/path/to/subject \
  --parser-cache-dir /tmp/ua-benchmark-parsers \
  --output /tmp/benchmark-results/subject-run-1.benchmark.json \
  --concurrency 4 --build-mode release --no-build
```

For the default release build and concurrency of 1, Make provides:

```sh
make benchmark-large-repo \
  BENCHMARK_SUBJECT=/absolute/path/to/subject \
  BENCHMARK_OUTPUT=/tmp/benchmark-results/subject-run-1.benchmark.json \
  BENCHMARK_PARSER_CACHE=/tmp/ua-benchmark-parsers
```

This target is independent of bare `make`, builds, distribution packaging, and
normal tests. Nothing clones or benchmarks a large repository in CI. Small
fixtures validate the contracts through `python3 -m pytest scripts/tests -q`.
Install their development dependencies with
`python3 -m pip install -r scripts/tests/requirements.txt` in your test environment.
The `benchmark-contract` CI job prepares only the three grammars needed by the
tiny fixtures, then runs these checks offline. Multilingual acceptance checks
use preconfigured grammars explicitly:

```sh
UA_TEST_PARSER_CACHE=/tmp/ua-benchmark-parsers python3 -m pytest scripts/tests/test_benchmark*.py -q
```

Concurrency is explicit and bounded from 1 through 32. Structure runs one fresh
process per production batch, with at most that many processes active. Each
process starts with cold in-process parser instances; later files within the
same batch reuse them. This is separate from the operating system's filesystem
cache. The first run is labelled `potentially-cold`; use
`--warm-filesystem-cache` to label subsequent runs `warm-requested`. That flag
neither flushes nor warms the OS cache. Per-worker timeouts default to 300 seconds
and can be set with `--worker-timeout SECONDS`. SIGINT/SIGTERM stop active process
groups, reap workers, and attempt a partial report.

## Reports and failure semantics

The required `--output` is a JSON filename outside the subject. Its sibling
`.md` is the human-readable report, and `.lock` is a persistent writer lock.
Existing symlinks are resolved before enforcing the boundary. Hard-linked output
files and nonregular outputs are rejected. All intermediate data lives in an
owned OS temporary directory, which must also be outside the subject. The
subject is read directly; no configuration, graph, parser cache, or intermediate
artifact is written there.

Both `.ua/` and `.understand-anything/` are excluded, even if user rules try to
reinclude them. Generated `*.benchmark.json`, `*.benchmark.md`, and
`*.benchmark.lock` are excluded too. Output paths are always external regardless
of naming. Production defaults and invocation patterns are recorded literally;
user and Git ignore content is represented by SHA-256 to avoid publishing
identifying paths. Git enumeration also applies its normal nested and global
ignore rules. The scanner, including its current classification and newline
count behavior, is the production implementation.

Reports include tool and subject commit and dirty state, binary identity, OS,
CPU, memory, compiler, parser version/asset identity, build mode, cache labels,
concurrency, scale, coverage, stage outcomes, and semantic input/output digests.
Unsupported metrics are `null`. Stage CPU comes from `wait4` for each worker;
structure CPU sums workers. `maxWorkerPeakRssBytes` is the largest individual
worker's peak, **not aggregate concurrent process memory**. Aggregate peak RSS
is unsupported. A structure stage with no batches has zero CPU, no worker RSS,
and zero workers. Total run duration includes orchestration and preparation;
only stage durations are analysis measurements.

Unsupported structural or optional call-graph capability yields `degraded`.
Unreadable input, malformed supported syntax, missing advertised grammars,
failed workers, invalid outputs, missing/duplicate batch membership, or changed
input hashes fail the run. Recovered syntax trees still produce the production
structural output, but coverage counts them as parse failures. Non-code parsers
use the production regex/line capabilities; these do not advertise strict syntax
validation. Import extraction keeps its own production resolution and recovery
rules. Structure coverage is checked independently of those import rules.

Public diagnostics are fixed codes and aggregate counts, bounded to five summary
entries over the whole run. Raw source, file paths, remotes, hostnames, and raw
worker diagnostics are omitted. `--keep-artifacts` retains private inputs,
outputs, and stdout/stderr and prints their directory to stderr. Do not publish
that directory without sanitizing it. Cleanup errors preserve the primary stage
error and appear in `secondaryErrors`.

| Exit | Meaning |
| ---: | --- |
| 0 | Completed `ok` or `degraded`, with JSON and Markdown |
| 1 | Setup, stage, integrity, or cleanup failed; partial report when deliverable |
| 2 | Invalid arguments or unsafe input/output/cache preconditions; no report |
| 3 | Report delivery failed; previous pair restored after caught replacement failures when possible |
| 130 | Cancelled; partial report attempted |

JSON and Markdown share `pairId`. Writers and cooperating readers lock the pair.
Caught replacement failures restore prior files; a restore failure is reported
as the fixed `rollback-failed` code. Two replacements are **not crash atomic**:
power loss or process termination between replacements can leave a mismatched
pair. Consumers must reject a missing/mismatched pair. To check a pair:

```sh
python3 scripts/benchmark_large_repo.py --check-pair /tmp/benchmark-results/subject-run-1.benchmark.json
```

Public reports still identify commits and machine specifications; inspect both
files before sharing them. The schema is validated in tests for successful,
empty, degraded, and partial-failure reports, rather than adding a runtime Python
schema dependency to the CLI.

## Reproduction and comparison

Pin both tool and subject commits, use clean worktrees, and hold machine, ignore
rules, parser assets, concurrency, and build mode constant. Retain **at least
three** runs on that machine, including the first potentially cold result. Give
each run a different output name. Compare input and semantic output digests
before comparing timing. Digests omit report IDs, temporary paths, timestamps,
and performance metrics. Structural output digests combine canonical per-batch
result and coverage hashes, keeping only a bounded number of batch models in
memory. Private artifacts can support a separate semantic
comparison across engines; native parser error recovery, non-code extraction,
and language-pack versions differ intentionally. An output mismatch across
engines is not by itself a performance regression.

A manually requested scale run can use TensorFlow v2.19.0, pinned to
`e36baa302922ea3c7131b302c2996bd2051ee5c4` (the upstream reproduction subject):

```sh
git clone --depth 1 --branch v2.19.0 https://github.com/tensorflow/tensorflow.git ../tensorflow-v2.19.0
if [ "$(git -C ../tensorflow-v2.19.0 rev-parse HEAD)" != e36baa302922ea3c7131b302c2996bd2051ee5c4 ]; then
  echo "Subject revision does not match the pin" >&2; exit 1
fi
python3 scripts/benchmark_large_repo.py ../tensorflow-v2.19.0 \
  --parser-cache-dir /tmp/ua-benchmark-parsers --no-build --concurrency 4 \
  --output /tmp/benchmark-results/tensorflow-run-1.benchmark.json
```

Repeat with run-2 and run-3, retaining run-1 and labelling subsequent runs as
warm-requested where appropriate. This is a recipe, not measured scale evidence.
No large repository was cloned or benchmarked as part of implementing the
harness. Report observations from actual runs; no performance threshold or
speedup claim is implied by this implementation.
