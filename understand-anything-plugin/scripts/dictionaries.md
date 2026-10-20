# Dictionary data and configuration

Distribution archives and Debian payloads contain no dictionary data. Packaging
never downloads dictionaries. Installers and explicit plugin updates run
`scripts/configure_dictionaries.py --plugin-root <plugin-root>` first.

Discovery checks LemmInflect metadata in the installer's Python environment,
global npm/NODE_PATH CSpell packages (including nested CSpell dependencies), and
compatible exported data under standard system/user share directories and
`$CARGO_HOME/share`. Rust crates have no standard installed dictionary-data API;
an arbitrary lemmatizer crate is not interchangeable with LemmInflect POS data.
Only compatible LemmInflect resources and CSpell `.txt`/`.txt.gz` files are used;
trie-only dictionaries require the local fallback. Installed packages are neither
imported nor updated by this tool.

Configuration records absolute system paths plus a local snapshot fallback for
missing components. It is written to `packages/rust/dictionary-config.json` when
the installation is writable; read-only installations use
`$XDG_CONFIG_HOME/understand-anything/dictionaries.json` (default `~/.config`).
When system components are missing and no location has been configured, setup
prompts for shared OS storage (recommended) or local repo storage. The absolute
`snapshot` path and `storage` choice are saved in this configuration. Edit
`snapshot` manually to relocate downloads; later runs preserve the edited path.
Existing installation-local configurations continue using their saved paths.
`UA_DICTIONARY_CONFIG` can select a configuration, and `UA_DICTIONARY_DIR` selects
a snapshot fallback. No files are copied out of system packages.

`make update-dictionaries` rediscovers system packages and refreshes only missing
downloaded components, reusing the saved location. A new location is prompted
for only when required and not already supplied. `make configure-dictionaries` discovers and
records paths offline. The skill [understand-update](../skills/understand-update/SKILL.md)
uses the same discovery-first flow. Missing components are downloaded as data
only: latest CSpell sources pinned to a revision and latest stable LemmInflect
wheel verified against its PyPI SHA-256. No downloaded code is executed.

Rust reads system files directly. Indexing always includes CSpell's general
`software-terms` package, plus only the project's detected development-language
dictionaries. Unknown/unsupported languages get shared terms only, never all
languages. Project caches exclude graph vocabulary and words already preserved
by the normal lemma/query filter (including case variants). The cache records the
lemma fingerprint; changed lemma data invalidates it until the next graph save or
`refresh_query_dictionaries` run. Search reads lemma data and project caches only,
never the full CSpell lists. Graph updates and searches never download.

Local snapshots use `current.json` to select an immutable generation named by its
manifest SHA-256. `cspell.json.gz` contains literal words grouped by dictionary;
`lemmas.json.gz` contains surface forms, POS and lemma mappings. Empty components
are allowed when their system-installed counterpart is configured. Manifests
record upstream versions, source/file checksums and licenses. Generations are
retained for in-flight readers; failed downloads leave the previous pointer intact.

Sources: [CSpell dictionaries](https://github.com/streetsidesoftware/cspell-dicts)
and [LemmInflect](https://github.com/bjascob/LemmInflect). Downloaded components
retain their MIT licenses. Downloaded data under `packages/rust/dictionaries/` is
excluded from distribution bundles and project-local source payload copies and
should be ignored by Git.

Installation and plugin updates check the versions of system dictionaries in use
against current PyPI/npm releases. If older, recommend updating them with their
package manager before indexing; never update system packages automatically.
Unavailable version information or failed network checks are reported explicitly.
After updating Understand Anything or dictionary libraries, recommend a fresh
full index using `/understand --full`. This rebuild is a recommendation, not an
automatic analysis run. `--offline` skips registry checks as well as downloads.

If runtime cannot read configured system files, its error identifies the config
and both repair paths. Edit the JSON paths directly, or rerun configuration with
`--lemma-resources /updated/lemminflect/resources` and/or
`--cspell-root /updated/node_modules` to record moved system packages. Custom
search locations persist across updates. To switch to downloaded data in a shared
user cache:

```bash
python3 "$PLUGIN_ROOT/scripts/configure_dictionaries.py" --plugin-root "$PLUGIN_ROOT" \
  --config /path/to/dictionary-config.json --prefer-local \
  --local-dir "${XDG_CACHE_HOME:-$HOME/.cache}/understand-anything/dictionaries"
```

`--prefer-local` persists until `--prefer-system` is requested. Runtime never
initiates this repair/download itself. After repairing, run `/understand --full`.


## Keep dictionaries out of Git

Full downloaded dictionaries, machine-specific source configuration, and generated
`.understand-anything/query-dictionaries/` caches are reproducible local data.
Do not commit them to the plugin source repository or the analyzed repository.
Keeping a graph under version control does not require committing its dictionary
cache. Preserve the project's separate policy for graph/configuration files.

Recommended repository `.gitignore` entries (adjust for custom installation paths):

```gitignore
# Generated cache tied to this project's graph
/.understand-anything/query-dictionaries/
# Optional full dictionaries downloaded into this repo
/.understand-anything/dictionaries/
# Downloaded data and absolute system paths in source or copied plugin installs
**/understand-anything-plugin/packages/rust/dictionaries/
**/understand-anything-plugin/packages/rust/dictionary-config.json
```

Use `.git/info/exclude` for a personal installation if shared repository ignore
rules are inappropriate. Custom `--local-dir` or `--config` paths inside a repo
need their own ignore entries. Ignore rules do not untrack existing files; review
tracked dictionary artifacts separately before removing them from version control.
Never remove an existing download simply to add an ignore rule.

## Share downloads across projects

Compatible system packages are shared already. When downloaded components are
needed, choose shared storage to reuse them across projects:

```bash
python3 "$PLUGIN_ROOT/scripts/configure_dictionaries.py" --plugin-root "$PLUGIN_ROOT" \
  --storage shared
```

The shared OS defaults are:

| OS | Default user directory |
|---|---|
| Linux | `$XDG_CACHE_HOME/understand-anything/dictionaries`, otherwise `~/.cache/understand-anything/dictionaries` |
| macOS | `~/Library/Caches/understand-anything/dictionaries` (`XDG_CACHE_HOME` overrides it) |
| Windows path selection | `%LOCALAPPDATA%/UnderstandAnything/Cache/dictionaries` |

Use `--storage repo --project-root /absolute/path/to/project` to choose
`<project>/.understand-anything/dictionaries/`, or `--local-dir /custom/path` to
supply another location. Without `--project-root`, repo storage uses the current
working directory; installers pass their explicit project target. New repo download
directories get a `.gitignore` containing `*` before downloads are published.

With missing system data and no saved choice, a terminal prompts for the location;
noninteractive setup stops before downloading. An agent should recommend shared
storage and ask the user which option to use, then pass the answer explicitly.
`UA_DICTIONARY_STORAGE=shared` or `repo` supplies the choice to unattended installers.
Use `--inspect` to report missing data, saved paths, and proposed locations without
writes, registry checks, or downloads. All-system installations need no prompt.

Configuration records an absolute path, for example:

```json
{
  "version": 1,
  "storage": "shared",
  "snapshot": "/home/alex/.cache/understand-anything/dictionaries"
}
```

This is an excerpt: retain the other fields in an existing configuration. Advanced
users can edit `snapshot` directly. Without an explicit storage flag, that path
wins over OS defaults and is preserved even if system dictionaries temporarily
make downloads unnecessary. An explicit `--storage` chooses the corresponding
default again. Changing a path does not move or delete its previous contents.

For a complete shared downloaded snapshot regardless of installed system data,
add `--prefer-local`. This persists a preference for downloaded data, independent
of whether it is shared or repo-local. Use `--prefer-system` to return to discovery.

`--prefer-local` makes the shared snapshot complete even when different installs
can discover different system packages. Avoid sharing a system-first partial
fallback directory between such installs: the current publisher can replace its
pointer with a generation that lacks components another install needs. Configure
shared updates sequentially; cross-process update locking is not implemented.
Current explicit configuration can download again even if the shared data exists;
this setup shares disk storage, not a guarantee of zero repeat network requests.
`--offline` records configuration without downloads and cannot repair missing data.

Keep each project's filtered `query-dictionaries/` cache local to that project's
`.understand-anything/`. Those caches depend on its graph, languages, and lemma
fingerprint; a shared full dictionary is reusable across projects, while these
filtered results are not interchangeable. Sharing does not refresh existing
project graphs automatically.

## Recommended storage improvements

These are proposed changes, not current installer behavior:

1. Keep storage choice explicit and persistent across installer entrypoints; extend
   status output to report duplicate downloads and total shared storage usage.
2. Reuse checksum-validated downloads during ordinary installation. Reserve upstream
   checks and downloads for explicit updates or missing/corrupt components.
3. Store immutable generations per component and version, or publish complete
   snapshots. Prevent a partial refresh from removing components used elsewhere;
   keep provenance, licenses, and checksums with each generation.
4. Serialize shared writers with a cache lock and publish atomically. Let readers
   finish on old generations; make cleanup explicit and retain referenced versions.
5. Keep full downloads outside repos and filtered project caches ignored. Have
   installers offer or maintain narrowly scoped ignore entries for in-repo
   overrides without hiding the user's graph or other project files.
6. Provide a migration/status command that reports current paths and duplicate
   downloads, verifies the shared copy, then repoints configuration. Preserve old
   copies until verification succeeds; offer cleanup separately. Allow version
   pinning where projects need reproducible dictionary behavior.


## Examples: independent components and concurrent updates

**Versioned components:** Repo A has system LemmInflect but needs downloaded CSpell.
Repo B needs both. Today a later partial snapshot for A can omit B's lemma data if
they share one directory. A component-based design would retain separate immutable
`lemminflect/<version-or-hash>/` and `cspell/<version-or-hash>/` directories. Updating
CSpell would change only its reference; B could continue reading its existing
LemmInflect generation. Publishing complete snapshots is another way to prevent
that omission, at the cost of including components A already has installed.

**Concurrent updates:** two installers start updating the same shared cache.
A writer lock would allow installer A to validate and publish first while B waits.
A writes new files into a staging directory, verifies checksums, then atomically
replaces the active manifest pointer. Queries see either the complete old generation
or the complete new one. If A fails before publication, the old pointer remains;
B can then retry or reuse A's validated result. Existing generations remain until
readers no longer need them. The publisher already uses immutable generations and
atomic pointer replacement; writer locking and safe shared cleanup remain proposals.
