# Statistics from an existing analysis

This guide covers `make benchmark-static`. For measured native execution, use
the [native stage benchmark](large-monorepo.md). For setup/build timings,
Valgrind and a new Codex graph analysis, use the
[full-run benchmark](../../scripts/benchmark/README.md).

`benchmark-static` reads an existing artifact directory and prints a report.
It does not run analysis, build the engine, load parsers, inspect source files,
access the network, or write into the artifact directory. Python 3 is sufficient.

From the Understand Anything tool checkout:

```sh
make benchmark-static UA_DIR=/absolute/path/to/repo/.ua
make benchmark-static UA_DIR=/absolute/path/to/repo/.ua TOTAL_SECONDS=600 TIME_SCOPE=full
```

`UA_DIR` defaults to this checkout's `.ua`. Pass the artifact directory itself,
including when using an existing legacy `.understand-anything` directory.
The subject repository can be elsewhere; it does not need its own Makefile.

`TOTAL_SECONDS` is optional. Supply a finite positive number of elapsed wall-clock
seconds from the original analysis, such as `600` or `123.5`. This is recorded as
user-supplied time, not the runtime of the report command. `TIME_SCOPE` defaults
to `unknown`. Set it to `full` only when the duration covers all files in the
saved scan. `TIME_SCOPE=incremental` records the duration while suppressing
full-snapshot throughput. The command cannot reconstruct the files processed
in a historical incremental run from the merged graph alone.

The default output is Markdown. Save a report outside the artifact directory:

```sh
make benchmark-static UA_DIR=/path/to/repo/.ua TOTAL_SECONDS=600 TIME_SCOPE=full > /tmp/saved-analysis.md
make benchmark-static UA_DIR=/path/to/repo/.ua TOTAL_SECONDS=600 TIME_SCOPE=full FORMAT=json > /tmp/saved-analysis.json
```

JSON uses a separate `saved-analysis-statistics` report type and schema version
`1.0.0`; it is not a native benchmark report and does not use that report's
paired-file validation protocol.

## Inputs and interpretation

- Required: `knowledge-graph.json`, containing `nodes` and `edges` arrays.
- Optional: `meta.json`, `config.json`, and `intermediate/scan-result.json`.
  Missing optional files are reported through unavailable values; malformed
  files produce an error instead of being silently ignored.
- Graph statistics include node/relationship type counts, layer count, distinct
  file paths, isolated nodes, and the ten largest incoming/outgoing relationship
  counts. These hubs count all relationship types, including containment and
  documentation; they are not exclusively dependency hubs.
- Consistency checks count duplicate node IDs and relationships referencing
  missing IDs. These are reported as findings without preventing a report.
- Scan statistics count unique file records, sum their saved `sizeLines`, and
  group files by language/category. Missing or invalid line counts make the
  line total unavailable. Missing scans leave all scan metrics unavailable.
  Duplicate scan paths are rejected to prevent inflated throughput.
- File/graph path differences are informational. The saved intermediate scan
  may cover a different partition or revision from the merged graph; the report
  does not treat these differences as proof of missing analysis.
- Full-scan throughput is `files * 60 / seconds` and `lines / seconds`. It is
  available only with a saved scan, supplied duration and `TIME_SCOPE=full`.
  These are overall averages, including any model work, waiting and orchestration
  included in your duration; they are not measurements of native parser speed.

The report describes the saved snapshot. It records graph/metadata identity when
available, but does not verify current source freshness or semantic accuracy.
It cannot recover CPU, peak memory, stage timing, tokens, cost or parser success
rates that were not recorded. Report unavailable measurements as unavailable,
not zero. When comparing reports, keep analysis scope and timing boundaries
consistent and check recorded commits.

Invalid inputs exit with status 2. A completed report exits with status 0 even
when consistency findings are present.
