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
