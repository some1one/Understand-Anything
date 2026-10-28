---
name: understand-setup
description: Prepare Understand Anything after marketplace installation by building its native engine and installing parser libraries and missing dictionary data. Use for plugin setup or retrying a failed runtime initialization.
---

# Set up Understand Anything

Resolve `PLUGIN_ROOT` from this skill's real location, following symlinks.
Read [host integration](../../HOSTS.md) for invocation and root conventions.

Run the shared setup helper in a managed command session and retain the session
until it finishes:

```bash
python3 "$PLUGIN_ROOT/scripts/setup_runtime.py" --plugin-root "$PLUGIN_ROOT"
```

It uses the packaged binary or compiles the Rust engine and its Cargo dependencies,
fetches all supported parser libraries, and configures missing dictionaries. For
a registered local marketplace, language assets default to its plugin source
directory under `packages/rust/parsers` and `packages/rust/dictionaries`.
Saved dictionary locations and explicit environment overrides remain authoritative.
The analyzed project's cwd is never used as the dependency install location.

Source builds require stable Rust/Cargo and network access for missing crates
and language data. This workflow authorizes that setup; use the host's normal
permissions. Report a missing compiler or failed download with the failing step.
Do not treat a failed setup as ready or initiate analysis to test it.

Successful setup is recorded and reused until inputs or installed assets change.
Use `--force` for an explicit dependency recheck. Setup does not create or refresh
project graphs or launch the dashboard. Report the returned asset/config paths
and completion status.
