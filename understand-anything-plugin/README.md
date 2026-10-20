# Understand Anything plugin

Build a codebase knowledge graph with Claude Code or Codex, then query, explain,
compare, or visualize it. Both hosts use the same `skills/`, Rust engine,
and graph files.

## Installation

Use `./install.sh claude` or `./install.sh codex` from the repository root.
The installer generates the correct marketplace format for each host. Native
installation loads plugin skills and hooks; standalone skill fallback does not
load hooks. Start a new session after installing or updating.

For Claude development without installing, launch from the codebase you want
to analyze:

```bash
claude --plugin-dir /absolute/path/to/understand-anything-plugin
```

In Claude native installations, skills use `/understand-anything:<skill-name>`.
Standalone Claude skills use `/<skill-name>`. In Codex, choose the skill with
`$<skill-name>` or the skill picker. Use the host's displayed qualified name if
there is a naming collision.

Already installed but unsure what to do next? Invoke `understand-help` for
first-run setup, requirements, commands, and troubleshooting (native Claude:
`/understand-anything:understand-help`; Codex: `$understand-help`).

## Skills

| Skill | Purpose |
|---|---|
| `understand-help` | Explain installation, first-run setup, usage, and troubleshooting |
| `understand-update` | Configure, update, or repair dictionary dependencies |
| `understand` | Analyze the project, selected folder parts, or changed parts |
| `load-graph` | Load selected part graphs or the full merged graph |
| `understand-add-part` | Add an excluded or newly discovered folder part |
| `understand-merge` | Recombine saved partitions without reanalysis |
| `understand-chat` | Answer questions using graph context and current source |
| `understand-explain` | Explain a file, function, or module |
| `understand-diff` | Describe changed and affected components |
| `understand-onboard` | Draft an onboarding guide |
| `understand-dashboard` | Launch the dashboard and report its tokenized URL |
| `understand-language` | Load one language analysis reference |
| `understand-framework` | Load one framework analysis reference |

Analysis supports a target path and `--source=<dir>[,<dir>]`, `--split=<depth>`,
`--all`, `--full`, `--review`, `--no-domain`, and
`--auto-update` / `--no-auto-update`. It saves the partition selection in
`.understand-anything/config.json`. `--all` selects all detected parts; ignore
review still applies when needed.

## Recommended repository instructions

Add the following to the user's repository `AGENTS.md` (plural) or `CLAUDE.md`,
whichever their host reads. Merge it into existing instructions. It is guidance
for using an installed plugin, not a requirement to index every repository.
`understand-help` can adapt this block to the available skills and project scope.

Using a relevant graph slice can help locate unfamiliar components, trace
relationships across files, and avoid repeated broad searches. Reusing context
already loaded avoids paying for the same retrieval again.

```markdown
## Understand Anything

Use the installed Understand Anything skills when repository structure or
relationships across files would materially help the task:

- Use understand-chat to locate unfamiliar components and trace cross-file flows.
- Use understand-diff for change impact across components, and understand-explain
  when explaining a symbol requires its callers, dependencies, or architecture.
- Use load-graph for the smallest relevant parts when several follow-up questions
  need the same context. Reuse that context rather than loading it each turn.
- Use understand-onboard for a codebase orientation and understand-help for plugin
  setup or usage. Use understand to create or refresh an index when the task needs
  it; use understand-dashboard when visualization is requested or useful.

Skip plugin retrieval for general programming questions, writing, or other tasks
that do not need repository evidence. Read a known file directly for a local
question or edit; use a targeted text search for an exact symbol or path. A
single-file question only needs graph context if relationships outside that file
are relevant. Do not invoke a skill merely because the task mentions code.

Before retrieving, reuse relevant source, search results, and graph context
already in this conversation. Retrieve again only for missing scope, changed files
or revisions, stale evidence, or context that is no longer available. Knowing that
an index exists is different from having its relevant contents loaded.

Treat graph results as navigation hints and snapshots. Confirm behavior against
current source, including uncommitted changes, before editing or making claims.
An empty result or an excluded graph partition is not proof that code is absent;
fall back to a focused source search. If the graph is missing or stale and direct
inspection suffices, continue without indexing. Refresh only the scope needed;
do not start a full rebuild, download, or dashboard as a side effect of a question.

Honor explicit requests to use or skip a skill and the host's invocation rules.
Keep the analyzed project separate from the plugin installation. Keep downloaded
dictionaries, machine-specific dictionary configuration, and generated query
caches out of Git; use shared dictionary storage where configured.
```

Use the host's discovered skill names: native Claude uses
`/understand-anything:<skill-name>`, standalone Claude uses `/<skill-name>`, and
Codex uses `$<skill-name>` or its skill picker. Missing plugin capabilities should
not block a task that ordinary source inspection can answer.

## Runtime and artifacts

The deterministic pipeline runs through `packages/rust/run.sh <command> …`,
which preserves the caller's working directory. Packaged installs ship the Rust
executable. Source checkouts build it with stable Rust and Cargo on first use.
Use absolute paths when analyzing another project. Some workflow helper scripts
and installation tooling still require Python 3.

Artifacts belong to the requested project or worktree:

- `knowledge-graph.json`: merged structural graph.
- `partitions/*.knowledge-graph.json`: saved part graphs.
- `domain-graph.json`: optional business-domain view.
- `fingerprints.json` and `meta.json`: incremental-analysis baseline.
- `intermediate/`: scan, validation reports, and working outputs.

A graph is a snapshot. Check source when answering questions about current
behavior. A failed required analysis step keeps intermediate evidence and should
not advance the saved baseline.

The dashboard requires Node.js 22+. Source mode additionally requires pnpm;
prebuilt bundles use `packages/dashboard/serve.mjs`. The launcher reports a
loopback URL with an access token. Open the full URL, including `?token=`.
Analysis does not launch the dashboard automatically.

## Optional auto-update

Enable with the analysis skill's `--auto-update` flag. Native hooks compare the
stored commit with HEAD at session start and after shell tools. The hook reads
local state and supplies a workflow reminder; the host performs the update.
In Codex, review and trust the hook definition before expecting it to run.

Part-based graphs refresh affected partitions and merge them again. Legacy
graphs use the fingerprint workflow in `hooks/auto-update-prompt.md`.
Standalone skill installs require explicit analysis runs because they do not
register hooks.

## Troubleshooting and maintenance

- Missing skill: start a new session and check `claude plugin list` or
  `codex plugin list --json`; confirm you installed for the intended scope.
- Missing auto-update: verify native installation, hook trust, and the boolean
  `autoUpdate` setting.
- Rust startup failure: check that the packaged executable is present, or
  build a source checkout with `cargo +stable build --locked --release` from
  `packages/rust/`.
- Dashboard startup failure: use the printed log path and check Node/pnpm.
- Native installer failure: the installer reports fallback to standalone skills;
  inspect the preceding host CLI error before assuming native hooks are active.

[Engine reference](packages/rust/README.md) documents the Rust package.
[Command reference](tools/README.md) describes deterministic command wrappers.
[Host integration](HOSTS.md) documents invocation and agent dispatch conventions.

The compatibility manifests are `.claude-plugin/plugin.json` and
`.codex-plugin/plugin.json`. Shared hooks live at `hooks/hooks.json`.
Validate changes with `claude plugin validate /path/to/plugin` and the repository's
integration tests. Keep manifest versions aligned when preparing a release.

## Context limits and regression checks

The chat query helper emits at most 32 KiB of serialized UTF-8 JSON, including
indentation, its trailing newline, metadata, and omission counts. Matches take
priority over neighbors. Layers contain only selected member IDs plus their
total membership count, and every returned edge references a returned node.
Oversized text is shortened; oversized identities are omitted rather than changed.
The limit bounds bytes, not model tokens.

Queries normalize Unicode, punctuation, case, and English inflections using
local LemmInflect lemma/POS data in the Rust engine. Function words such as “this” and “is,”
generic filler, and unambiguous adjectives/adverbs are filtered. Technical
modifiers (for example “private” and “asynchronously”), negation, unknown words,
quoted terms, and graph names embedded in questions are preserved before stop-word
filtering. Dictionary POS lists
possible uses; ambiguous noun/verb words are retained conservatively. All-filtered
queries return no matches unless they exactly name a graph symbol or path.
The query engine works offline. Missing or corrupt required dictionary data
reports an error; refresh it through explicit plugin maintenance or reinstall. Matches keep graph order; ranking remains future
work. See the [dictionary provenance and license](scripts/dictionaries.md).

Graph saves also generate `.understand-anything/query-dictionaries/` with one
CSpell vocabulary cache per selected dictionary. Rust uses the project's declared
languages and graph file extensions to select language dictionaries, plus shared
software terms. JavaScript and TypeScript share the TypeScript/Node dictionaries.
If no language is identified, or an identified language has no supported dictionary,
only shared software terms are available alongside graph names. There is no
full-list fallback. This leaves a coverage gap for language-specific technical
words absent from the graph: they have no dictionary-based protection from query
filtering. Identifying a supported language enables its dictionary on the next
index or cache refresh; unsupported languages require an additional dictionary.

The cache contains words absent from graph identity fields (`id`, `name`,
`filePath`, including identifier components) and tags. Summary prose is not used
as a list of identifiers. Each indexing update recalculates that difference:
new graph names leave the cache, deleted names return, and the active dictionary
selection follows language changes. Searches read the graph and the active cache
files only; they never load the complete CSpell source data or download words.
Uppercase cached technical words such as `GET` survive stop-word filtering;
ordinary lowercase conversational “get” remains filtered unless it names a graph
symbol or is quoted.

Cache manifests record the graph fingerprint and dictionary checksums. Missing,
stale, or damaged caches produce a warning and fall back to graph-name protection.
Refresh an existing graph without reanalysis using
`packages/rust/run.sh refresh_query_dictionaries /path/to/project` from the plugin
directory. See [CSpell provenance and licenses](scripts/dictionaries.md).

An explicit dashboard `GRAPH_DIR` owns every artifact and source-file lookup.
Missing artifacts use that endpoint's missing/default response within that
project. Working-directory discovery applies when `GRAPH_DIR` is absent.

Run the helper regressions from the repository root with
`python3 -m pytest understand-anything-plugin/tests -q`, alongside `make test-core`,
`python3 -m pytest scripts/tests -q`, and `make test-dashboard`. Dashboard endpoint
regressions start temporary servers on localhost.

## Dictionary maintenance and native helpers

Query normalization, cache reading, graph matching, context bounds, changed-file
collection, incremental pruning, project-context capture, and save summaries run
in Rust. Existing Python entrypoints are compatibility launchers. Use
`packages/rust/run.sh query_graph /path/to/project "GET requests"` to query
without Python. Both cache generation and search use the same Unicode tokenizer.

Distribution bundles contain no dictionaries and packaging never downloads them.
Installers, `install.sh --update`, and [understand-update](skills/understand-update/SKILL.md)
run `scripts/configure_dictionaries.py --plugin-root "$PLUGIN_ROOT"`. This records
compatible system LemmInflect/CSpell paths and downloads only missing components
into the selected download directory. When components are missing and no location
is saved, setup recommends and prompts for shared OS storage or repo-local storage.
System packages are read directly by Rust and are not modified. The chosen absolute
`snapshot` path is saved in configuration and can be edited manually. Existing
choices are reused; unattended first-time setup requires `--storage shared`,
`--storage repo --project-root /path/to/repo`, or `--local-dir /custom/path`.
Project graphs and filtered query caches stay under the analyzed project.
For multiple projects, configure a [shared download directory](scripts/dictionaries.md#share-downloads-across-projects)
and keep [generated dictionary files out of Git](scripts/dictionaries.md#keep-dictionaries-out-of-git).

`make update-dictionaries` repeats discovery and updates local fallbacks;
`make configure-dictionaries` records paths offline. Graph indexing, graph-update
hooks, and searches remain offline. Project caches omit graph names and words the
lemma filter already preserves. They record the lemma fingerprint and must be
refreshed if the lemma data changes. See [dictionary configuration and discovery](scripts/dictionaries.md).

Installation and plugin updates check the versions of system dictionaries in use
against current PyPI/npm releases. If older, recommend updating them with their
package manager before indexing; never update system packages automatically.
Unavailable version information or failed network checks are reported explicitly.
After updating Understand Anything or dictionary libraries, recommend a fresh
full index using `/understand --full`. This rebuild is a recommendation, not an
automatic analysis run. `--offline` skips registry checks as well as downloads.
