---
name: understand-update
description: Configure, update, or repair Understand Anything dictionary dependencies during plugin maintenance, without updating project graphs. For general installation and getting-started instructions, use understand-help.
argument-hint: "[--offline]"
---

# Update plugin dictionary dependencies

Use this workflow when the user requests plugin maintenance or dictionary updates.
Read [host integration](../../HOSTS.md) and resolve `PLUGIN_ROOT` from this skill's
actual location. This is plugin maintenance, not the graph auto-update workflow.

If the user is also upgrading plugin code through their host's plugin manager,
complete that upgrade first and resolve the newly installed plugin root. This
skill updates dictionary data; it does not select a plugin code release.

Inspect installed dictionaries and saved configuration before maintenance:

```bash
python3 "$PLUGIN_ROOT/scripts/configure_dictionaries.py" --plugin-root "$PLUGIN_ROOT" --inspect
```

Inspection does not write configuration, check registry versions, or download.
If all required system dictionaries are present, use them without asking about
storage. If components are missing and no `snapshot` path is saved, recommend
shared storage and ask the user to choose:

- **Shared OS directory (recommended):** reuse full downloads across repositories.
- **Local repo:** keep downloads under the selected project's
  `.understand-anything/dictionaries/`, ignored by Git.

Resolve `PROJECT_ROOT` to the user's intended repo, not the plugin installation.
If the user already selected a location, honor it without asking again. Pass that
choice with `--storage shared` or `--storage repo --project-root "$PROJECT_ROOT"`.
Use `--local-dir /absolute/path` for a custom location. Then run:

```bash
python3 "$PLUGIN_ROOT/scripts/configure_dictionaries.py" --plugin-root "$PLUGIN_ROOT" [--offline]
```

Append the explicit storage options for first-time setup; omit them to reuse a
saved path. Terminal setup prompts when needed. Noninteractive execution requires
an explicit option or saved choice and otherwise stops before downloading.
`UA_DICTIONARY_STORAGE=shared` or `repo` supplies a choice for unattended installers.
The absolute `snapshot` path is saved in configuration and may be edited manually;
subsequent runs preserve it. `--storage` explicitly selects a new default path.

Rust reads compatible installed LemmInflect/CSpell files directly; do not upgrade
or modify system packages. Only missing components are downloaded. Configuration
is installation-local when writable, otherwise in the user config directory.
Project graphs and filtered query caches remain under the analyzed project's
`.understand-anything/`, regardless of full dictionary storage.
See [storage locations and shared-cache limitations](../../scripts/dictionaries.md).

Report configured paths and any errors. Failed downloads retain the previous
snapshot and configuration. `--offline` discovers and configures without downloads.

Do not analyze projects or rewrite graphs in this skill. The next graph save or
explicit cache refresh uses current local/system dictionaries. Search and graph
updates remain offline. CSpell general software terms always accompany supported
language dictionaries; unknown languages never trigger an all-language fallback.

Installation and plugin updates check the versions of system dictionaries in use
against current PyPI/npm releases. If older, recommend updating them with their
package manager before indexing; never update system packages automatically.
Unavailable version information or failed network checks are reported explicitly.
After updating Understand Anything or dictionary libraries, recommend a fresh
full index using `/understand --full`. This rebuild is a recommendation, not an
automatic analysis run. `--offline` skips registry checks as well as downloads.

When runtime reports inaccessible system dictionaries, relay the config path and
repair options from its error. The user can edit `lemminflect.lookup`,
`lemminflect.overrides`, and `cspell` paths, or use `--lemma-resources` and
`--cspell-root` with the configurator to record moved installations. Alternatively,
run the configurator with `--prefer-local` and the reported `--config` path,
reusing the saved download location or asking for a location if none is saved. Local-only
mode persists; `--prefer-system` restores discovery. Recommend `/understand --full`
after repair. Do not silently download dictionaries during a graph/query skill.
