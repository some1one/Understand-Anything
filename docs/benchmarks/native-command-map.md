# Native stage contracts

The benchmark resolves a source-built binary once, before measuring anything.
Each invocation is a fresh process, using these production dispatcher contracts:

| Stage | Command | Input and output |
| --- | --- | --- |
| Scan | `scan_project ROOT OUTPUT --exclude=PATTERNS` | Writes the scanner's files, classification, line counts, ignores, and failures |
| Imports | `extract_import_map INPUT OUTPUT` | Input has `projectRoot` and scanner `files`; output has `importMap` and `stats` |
| Batching | `compute_batches ROOT --scan-result INPUT --output OUTPUT` | Input combines scan output and import map; output has `batches` and neighbor data |
| Structure | `extract_structure INPUT OUTPUT` | Input has `projectRoot`, `batchFiles`, `batchImportData`; output has per-file structure |

All commands use `--offline-parsers --parser-cache-dir CACHE`. Missing advertised
parsers fail instead of downloading. Paths used above are private artifacts;
only ROOT identifies the subject. Explicit batching paths preserve the existing
default CLI behavior for normal analysis.

Version 2 measures native process wall time, `wait4` CPU time and individual
worker RSS. It does not claim compatibility with upstream JavaScript schema
1.0.0 timings. Structure CPU is summed and RSS is the maximum worker value;
aggregate concurrent memory is unsupported (`null`). All parser instances start
cold in each process and can be reused within a batch. Filesystem cache state
cannot be forced or measured by this harness.
