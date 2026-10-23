# Native migration fixture expectations

These fixtures began as captures of the Python implementations. Deliberate
behavior changes must have explicit expected values or expected failures;
comparison code must not discard new fields to make old captures pass.

- `structure.json`: Go, Rust, C, and C++ function records now include `owner` in
  both structural analysis and the flattened result. Empty strings identify free
  functions; named owners distinguish receiver methods. The original source,
  call graphs, and all other expected fields remain unchanged.
- `imports.json`: cases 37, 45, and 46 now require extraction errors for a missing
  source file, truncated Composer JSON, and truncated TypeScript configuration.
  Their old partial-success responses remain under `legacyExpected` for history.
  The test asserts the stable diagnostic prefix, allowing platform-specific OS
  text for the missing file. Other import cases retain full output comparison.

Run parser-dependent cases from the Rust package with a populated pinned cache:

```sh
UA_TEST_PARSER_CACHE=/path/to/cache cargo +stable test --locked --test differential captured_structural_extraction -- --ignored
UA_TEST_PARSER_CACHE=/path/to/cache cargo +stable test --locked --test differential captured_import_resolution -- --ignored
UA_TEST_PARSER_CACHE=/path/to/cache cargo +stable test --locked --test runtime all_supported_parsers -- --ignored
```

The grammar-loading test covers every registered grammar, but is only a loading
smoke test. Language-specific structure and symbol tests provide semantic checks.

`additional_commands.json` retains existing legacy-directory fixtures while new
projects expect `.ua`. The generated ignore template includes the migrated,
commented language suggestions. Structure extraction expects `filesUnreadable`
and its warning for the existing mixed readable/missing input. Batch/subdomain
merge fixtures assert their new reports; update preparation asserts the fresh
scan and symbol baseline, and batch application asserts the edge-candidate
record with its exact graph hash. The two command fixtures with a nonexistent
prepared HEAD now assert failure and byte-preserved input artifacts instead of
allowing fingerprint/finalization writes. Real-repository publication behavior
is covered by the dedicated symbol and dirty-update tests.

`updates.json` now expects README changes to proceed and ignore-rule changes to
reconcile the old graph with the current inventory. Neither path advances the
metadata before analysis. Batch application expects coordination locks and
snapshot-bound edge candidates; its retained fragment no longer contains edges
whose endpoints were removed. Missing-input failures may create only the lock.
Seven fingerprint/finalization fixtures contain prepared revisions absent from
their temporary checkout. They now assert the revision-guard error and unchanged
input files, with historical responses retained as `legacyExpected`. Successful
publication and symbol repair continue to run against real temporary Git commits
in `symbol_publication.rs`; worktree and HEAD drift are tested in
`dirty_updates.rs`, and fingerprint corruption is covered by `runtime.rs`.
