<!-- understand-anything:agent-instructions:start -->
## Understand Anything: efficient codebase exploration

Use the installed Understand Anything skills when unfamiliar structure,
cross-file relationships, or change impact would help the task. Follow project
rules and explicit requests to use or skip skills. These are skill names; use
the host's discovered invocation (`$name` in Codex, or its qualified name).

Choose the smallest useful retrieval:

- Known file or exact symbol/path: read it directly or use `rg`. Generic questions
  do not require graph retrieval.
- `understand-chat <question>`: locate unfamiliar components and cross-file flows
  with a matching subgraph and one-hop neighbors. Query output is bounded to
  32 KiB of JSON, not a fixed number of model tokens.
- `understand-explain <path-or-symbol>`: inspect a component's relationships and
  source excerpt. Prefer a precise path or identifier to an ambiguous name.
- `load-graph <part>[,<part>...]`: load only relevant saved partitions when several
  follow-up questions need the same context. Reuse that context. Avoid `--all`
  unless the whole graph is needed; even a selected partition can be large.
- `understand-diff [base-branch]`: retrieve changed and affected components.
  `understand-onboard` provides broader orientation when that is the actual task.

Discover scope before loading data. Resolve `PLUGIN_ROOT` from the installed
skill's real location and `PROJECT_ROOT` from the target repository. Resolve
`UA_DIR` with `python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT"`.
It selects `.ua/`, or an existing legacy `.understand-anything/`; never mix them.
Read `config.json`'s `includedParts` or list `partitions/*.knowledge-graph.json`
to find parts rather than dumping graph JSON. A part `src/api` is stored as
`partitions/src~api.knowledge-graph.json`. Without arguments, `load-graph` loads
all configured parts, which may be more context than needed. External/stub nodes
refer to unloaded parts: expand only the parts needed to follow the relationship.

Parts can be logical groups spanning folders. Read `partition-layout.json` for
their include/exclude rules rather than assuming a name is a directory. Use
`understand-partitions` to discuss and save grouping changes; generated inventories
are disposable. Normal and full analysis preserve saved grouping definitions.

Check the exact snapshot before relying on graph claims:

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" graph_freshness "$PROJECT_ROOT" "$GRAPH_PATH"
```

For chat/explain/diff, `GRAPH_PATH` is the selected `knowledge-graph.json`; for
loaded partitions, check each exact partition file. A merged graph's freshness
does not establish a partition's freshness. Reuse a check only while the snapshot,
HEAD and relevant working files remain unchanged. Briefly disclose dirty, stale,
or unknown results and verify relevant current source, including local edits.

Prefer skill entrypoints, which include this workflow. Their focused helpers
are available when direct tool use is appropriate:

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" query_graph "$PROJECT_ROOT" "specific question"
python3 "$PLUGIN_ROOT/skills/understand-explain/scripts/component_context.py" "$PROJECT_ROOT" "path-or-symbol"
python3 "$PLUGIN_ROOT/skills/load-graph/scripts/load_graph.py" "$PROJECT_ROOT" "src/api,src/web"
```

Use returned paths and relationships to read only the needed source. Reuse
relevant source, search results and graph slices already in context; retrieve
again for missing scope, changed evidence, or lost context. An index on disk is
not loaded context. Empty results, missing partitions and truncation do not prove
code is absent; use a focused source search. Graphs guide navigation, while
current source establishes behavior. If direct inspection suffices, continue
without indexing. Use `understand` or `understand-add-part` only when analysis is
requested or needed within the task; do not automatically rebuild everything,
download dependencies, or launch the dashboard to answer a question.
<!-- understand-anything:agent-instructions:end -->
