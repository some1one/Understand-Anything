# Benchmark migration plan

Status: deferred. This document plans the migration; it does not enable or run
benchmarks. Figma analysis and the standalone viewer are outside this work.

## Source and scope

Adapt the deterministic large-monorepo harness introduced by upstream
[PR #587](https://github.com/Egonex-AI/Understand-Anything/pull/587), using the
report contract and documentation at upstream commit `f2d0164` as references:

- `docs/benchmarks/large-monorepo.md`
- `docs/benchmarks/large-repo-report-1.0.0.schema.json`
- `scripts/benchmark-large-repo.mjs`
- `scripts/lib/large-repo-benchmark.mjs`
- `scripts/lib/benchmark-stage-worker.mjs`

Measure the actual Rust scanning, import extraction, batch planning, and
structural extraction commands used by this fork's analysis workflow. Do not
restore the removed TypeScript core, root Node workspace, Python pipeline, or
upstream's package-manager commands. Dashboard benchmarks, LLM execution,
tokens, cost estimates, and end-to-end analysis claims are separate work.

## Implementation sequence

Each step should be an independently tested commit.

1. **Define the report contract.** Preserve upstream stage outcomes, coverage,
   bounded warnings, deterministic input/output digests, and partial-failure
   reports. Record tool and subject commits, dirty state, OS, CPU, memory,
   Rust/compiler and parser versions, concurrency, and effective ignore rules.
   Record release versus debug builds and cold versus warm parser caches.
   Version the schema if Rust metrics or semantics differ; do not present
   incomparable values as the original schema's metrics.
2. **Build a native stage runner.** Use the existing Rust package and production
   command contracts through `packages/rust/run.sh` or its resolved binary.
   Map each stage's arguments and JSON files from the current dispatcher before
   implementation. Build once outside the timed section. Run stages in isolated
   processes to measure wall time, CPU time, and peak resident memory. Report
   unsupported metrics explicitly rather than estimating or substituting zero.
3. **Isolate inputs and artifacts.** Keep intermediate outputs in an owned OS
   temporary directory; never write graph files, configuration, or caches into
   the subject repository. Exclude both `.ua/` and legacy
   `.understand-anything/` analysis data. Resolve symlinks before enforcing an
   explicit output path outside the subject. Keep dictionaries/parser assets
   preconfigured and record their identity; never download inside a timed run.
   Make concurrency explicit and bounded. Support retaining private artifacts
   for diagnosis, with a clear distinction from sanitized public reports.
4. **Account for coverage and failures.** Distinguish successful parsing,
   unsupported capabilities, unreadable files, parse failures, and invalid
   outputs. Unsupported work may produce a degraded result; advertised
   capabilities that fail must fail the run. Bound diagnostic samples across
   the entire run. Sum worker CPU time, but label maximum individual-worker RSS
   separately from aggregate process memory. Preserve primary stage errors when
   cleanup also fails.
5. **Publish report pairs safely.** Produce JSON plus Markdown with matching
   pair IDs, serialize writers, and restore prior outputs after caught delivery
   failures. Document that two file replacements are not crash-atomic and have
   readers reject mismatched pairs. Omit absolute paths, remotes, hostnames, and
   raw source/diagnostics from public reports. Validate schema conformance in
   tests for successful, empty, degraded, and partial-failure runs.
6. **Expose an explicit command and document reproduction.** Add an opt-in Make
   target and `make help` entry without changing bare `make`, normal tests, or
   distribution contents. Document the chosen CLI only after it exists. Pin
   sample repository revisions; never clone or benchmark a large repository in
   normal CI. Use small deterministic fixtures for CI contract checks.

## Acceptance checks

- Run against a tiny multilingual fixture, an empty repository, unsupported
  extensions, malformed source, unreadable input, and simulated failed workers.
  Validate status/exit codes and counts independently of timing values.
- Exercise cancellation, cleanup errors, concurrent report writers, path aliases,
  output-write failure, and report-pair mismatch detection.
- Verify subject Git status and file hashes are unchanged. Confirm both analysis
  directory names and generated report artifacts are excluded from scanning.
- Repeat identical fixtures with fixed concurrency and compare semantic digests;
  timing, temporary paths, and report IDs must not affect those digests.
- Keep semantic output comparison separate from performance comparison across
  the old and new engines. Document intentional parsing differences.
- For manual scale evidence, retain at least three runs on the same machine with
  fixed commits, ignore rules, concurrency, and build mode. Label the first run
  as potentially cold; retain it rather than silently discarding it.
- Report observations, not performance thresholds or speedup claims invented
  before measurements. Large repository execution remains a separate explicit
  action after the harness is implemented.
