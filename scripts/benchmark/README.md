# Full-run benchmark with Valgrind

This folder contains full-run configuration, Cargo configuration and native
profiling tools. Run the benchmark directly on Linux; no virtual machine is used.

## Run

```sh
make benchmark-setup
make benchmark-full BENCHMARK_SUBJECT=/absolute/path/to/repository \
  BENCHMARK_RUN_DIR=/tmp/ua-full-run-1
```

`benchmark-setup` prepares Valgrind under the ignored `.private/benchmark-tools/`
directory on Debian/Ubuntu, using APT package downloads and extraction without
sudo or system package changes. It reuses an installed Valgrind when available
and fetches matching libc debug symbols if missing. The harness discovers the
local tool automatically. GNU time must already be installed. The setup does not
install Rust, Node, pnpm or Codex; use your existing development setup. The full run requires
stable Rust/Cargo, Python 3.11+, Git, Node 22+, Corepack, and an authenticated
Codex CLI supporting the configured model. Run `codex login` if needed. Corepack
selects the exact pnpm version from the dashboard's `package.json`.

The output directory must be new and outside both subject and tool checkout.
Each run builds in a fresh source copy and retains all outputs. Model analysis
uses its own `analysis-subject` copy, preserving the original source and `.ua`.
Normal builds/tests do not start profiling or invoke a model.

To inspect the plan without running tools or creating files:

```sh
python3 scripts/benchmark/full_run.py /path/to/repo \
  --output-dir /tmp/ua-full-plan --plan
```

## Separate timings

| Phase | Work |
| --- | --- |
| `rust_dependencies` | Locked Cargo dependency fetch into a fresh run-local cache |
| `dashboard_dependencies` | Frozen pnpm install with a fresh store |
| `rust_rebuild` | Production release build, offline and locked, with Cargo `--timings` |
| `parser_language_update` | Fetch pinned parser language-pack assets into a fresh cache |
| `dictionary_language_update` | Download a fresh dictionary generation |
| `dictionary_configuration` | Configure that snapshot offline |
| `dashboard_rebuild` | TypeScript checking and Vite production build |
| `plugin_package_rebuild` | Reassemble the native plugin payload and plugin/dashboard archives from those builds |
| `native_analysis` | Ordinary scan/import/batching/structure benchmark with offline parsers |
| `rust_profiling_rebuild` | Separate optimized build with full debug information, DWARF 4 and symbols retained |
| `valgrind_callgrind` | Replay the native pipeline for instruction costs, call graphs and simulated cache/branch events |
| `valgrind_massif` | Replay for heap, allocation overhead and stack snapshots |
| `valgrind_memcheck` | Replay for invalid access, undefined values and definite/indirect leaks |
| `host_model_analysis` | Codex runs the rebuilt plugin's full `understand --all --full --no-auto-update` workflow |

Packaging uses `build_dist.py --prebuilt-rust ... --prebuilt-dashboard` to avoid
counting compilation or dependency installation twice. Ordinary packaging keeps
its existing behavior. Both distribution archives are rebuilt; Debian packaging
is outside this workflow.

Valgrind instruments each Rust worker directly, including every structural
batch. It does not instrument Python, Node, Cargo or Codex. Each worker gets
its own profile and log, using its stage name and PID to avoid overwrites.
Profile passes use the same production pipeline and integrity checks, with
instrumentation added only to worker launches. The normal native benchmark's
report contract and default execution are unchanged.

Production and profiling executables have separate target directories. The
profiling build retains production optimization/LTO, adds full debug information,
uses DWARF 4 for compatibility and disables stripping. Its identity is recorded;
results from different binaries must not be treated as identical measurements.
Parser libraries may lack debug symbols even when the Rust executable has them.

## Configuration

Edit `full-run.json`, or use `BENCHMARK_CONFIG=/path/to/config.json` with Make.
Partial config files inherit the checked-in defaults.

- `buildJobs`, `concurrency`: production compile and native analysis parallelism.
- `parserLanguages`: empty means fetch all advertised parser languages.
- `phaseTimeoutSeconds`, `workerTimeoutSeconds`: ordinary phase/worker timeouts.
- `valgrindTools`: ordered subset of `callgrind`, `massif`, `memcheck`;
  an empty array disables profiling and the extra Rust profiling build.
- `valgrindConcurrency`: defaults to 1 to bound profiler memory use.
- `valgrindWorkerTimeoutSeconds`: defaults to 3600 because instrumentation is slow.
  Increase `phaseTimeoutSeconds` too for repositories with many batches.
- `sampleIntervalSeconds`: process-group RSS sampling interval.
- `analysisCommand`: defaults to the included Codex wrapper. Set to `null` for a
  deterministic-only run. Custom commands are argv arrays, with `{subject}`,
  `{plugin}`, `{workspace}` and `{run_dir}` placeholders; no shell expansion.

The Codex wrapper explicitly selects **gpt-6.1-sol**, **medium** reasoning and
**standard** service (`service_tier="default"`). It ignores host user config,
links the rebuilt plugin skills into the analysis copy, preapproves the initial
ignore review/all-part selection, and uses workspace write permissions without
interactive approvals. Your authenticated Codex account supplies model access.
The default command and prompt are in `codex_analysis.py`.

## Reports

Read `BENCHMARK_RUN_DIR/report.md` or `report.json` for the phase table.

- `logs/`: phase output, GNU time CPU/RSS/I/O/fault/context-switch measurements,
  and sampled process-group RSS/process counts.
- `workspace/understand-anything-plugin/packages/rust/target/cargo-timings/` and
  `target-valgrind/cargo-timings/`: Cargo crate compilation and concurrency reports.
- `workspace/dist/`: freshly rebuilt plugin and dashboard archives.
- `native.benchmark.json` / `.md`: ordinary native timings, parser coverage,
  individual worker RSS, input identity and semantic digests.
- `valgrind/TOOL/summary.json` / `.md`: explicitly instrumented native results
  and aggregate profile summaries. Callgrind sums event counts; Massif reports
  the largest individual process peak; Memcheck reports error kinds, occurrences
  and lost bytes. Invalid/missing profiles fail the profiling phase.
- `valgrind/TOOL/profiles/`: worker profiles and Valgrind diagnostics. Inspect
  a `.callgrind` file with `callgrind_annotate --auto=no FILE` or KCachegrind;
  inspect a `.massif` file with `ms_print FILE`. Memcheck diagnostics are XML.
- `codex-events.jsonl`, `codex-final-message.txt`, `codex-usage.json`: model events,
  final response and token counts actually emitted by Codex. No cost is inferred.
- `analysis-subject/.ua/` and `analysis-statistics.json`: full graph and saved-artifact
  statistics using only the measured Codex analysis duration.

A failed phase stops later work and retains partial reports and logs. Memcheck
uses error exit 97 for memory errors and definite/indirect leaks; failures are
reported rather than suppressed. Profiles, logs and events are private run
artifacts and may contain source paths or content.

Valgrind timings and OS RSS include profiler overhead and are not ordinary runtime
measurements. Memcheck uses silent fork children to keep parent XML valid when
Rust workers launch helper processes; exec children are not profiled. Cache/branch counts are simulations, not hardware counters.
Massif tracks heap/stack allocations, not full RSS; process peaks are not summed
into a claimed concurrent peak. GNU time's maximum RSS is an individual-process
maximum. RSS samples sum shared pages across a process group, can miss brief
peaks and exclude detached sessions. CPU figures describe local execution, not
remote model-server work. The profile passes cover the four native stages;
other graph helpers used by Codex are not instrumented.

Tool and subject revisions/dirty state are recorded when Git is available.
Staged source contents are hashed; snapshots omit generated artifacts, local
agent installs, `.git`, `.env*`, dependencies and build outputs. Snapshot graph
metadata may therefore lack a Git revision. Caches are fresh per run, while
OS filesystem cache and host contention remain uncontrolled. Keep scope,
versions, parallelism and timing boundaries consistent across comparisons.

## References

- [Callgrind](https://valgrind.org/docs/manual/cl-manual.html)
- [Massif](https://valgrind.org/docs/manual/ms-manual.html)
- [Memcheck](https://valgrind.org/docs/manual/mc-manual.html)
- [Cargo build timings](https://doc.rust-lang.org/cargo/reference/timings.html)
- [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
