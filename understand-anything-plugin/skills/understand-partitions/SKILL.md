---
name: understand-partitions
description: Define or adjust persistent named analysis partitions through discussion, using include/exclude file patterns across folders. Preserve custom grouping during normal and full regeneration.
argument-hint: "[path] [describe the desired groups]"
---

# Manage analysis partitions

Use this skill when a user wants logical groups such as authentication, billing,
or shared infrastructure rather than a uniform directory split. The user can
describe the grouping conversationally; translate that intent into saved rules.
They do not need to author JSON themselves.

Read [host conventions](../../HOSTS.md). Resolve `PLUGIN_ROOT` from this skill's
actual location and `PROJECT_ROOT` from the requested project. Resolve `UA_DIR`:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

1. Read existing `config.json` and `partition-layout.json` when present. Inspect
   existing part names and narrowly relevant paths. Reuse a current scan for
   membership preview; a saved graph proves past membership, not current scope.
   Do not load the entire merged graph just to name groups.
2. Translate the user's requested groups into include/exclude patterns. Clarify
   only material ambiguity: whether unassigned files should remain excluded
   (`custom`) or get folder-based fallback (`hybrid`), and intentional overlap.
   Prefer custom mode when the user asks for a complete named layout. Show a
   concise grouping proposal with representative paths. Proceed when the request
   already defines the scope; do not demand a separate confirmation.
3. Merge the requested edits into the existing definition, preserving unrelated
   groups and legacy overrides. Write the candidate JSON to a temporary file,
   then validate and save through the engine:

   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" write_partition_layout "$PROJECT_ROOT" "/absolute/path/to/candidate-layout.json"
   "$PLUGIN_ROOT/packages/rust/run.sh" partition_layout_status "$PROJECT_ROOT"
   ```

   The first command validates before atomically replacing the saved definition.
   It does not modify graphs, inventories, or `includedParts`.
4. If a current complete scan exists, run `partition_files "$PROJECT_ROOT"`
   through the engine and inspect `intermediate/partitions.json`: show counts,
   overlaps, empty groups, and unmatched files. This updates generated inventories,
   not graphs. If no fresh scan exists, report preview unavailable or run SCAN
   when analysis was requested. Never silently preview against stale data.
5. Select intended part names with `write_config "$PROJECT_ROOT" --parts=...`,
   preserving the existing selection unless the user requested replacement.
   When renaming/removing a group, update `includedParts` too. Retired graph files
   may remain on disk but are excluded from the next selected-part merge.
6. If the user requested regeneration, continue with
   [understand](../understand/SKILL.md). Otherwise report that definitions are
   saved and graphs still need refresh. Configuration alone is not analysis.

## Saved format

`$UA_DIR/partition-layout.json` is user-owned input, retained across cleanup,
normal updates, `--all`, and `--full`. Example:

```json
{
  "version": 1,
  "mode": "custom",
  "partitions": {
    "authentication": {
      "include": ["/src/auth/**", "/api/login.*", "/config/security/**"],
      "exclude": ["**/*.test.*"],
      "description": "Login and access control across packages"
    },
    "operations": {
      "include": ["/deploy/**", "/scripts/**", "/.github/workflows/**"]
    }
  }
}
```

- Patterns use gitignore glob semantics: `/` anchors at project root, `**`
  spans directories, and bare filenames match at any depth. Use `exclude`
  rather than `!` negation. Includes are required and nonempty; excludes default
  to empty. Matching is case sensitive.
- Only files in the filtered scan can be assigned; these rules do not bypass
  `.uaignore`, default binary ignores, or invocation exclusions.
- Overlap between explicit groups is allowed: a shared file belongs to every
  matching group, and changes affect all of them. Excludes apply per group.
- `custom` assigns only matching files. `hybrid` also assigns unmatched files
  using `sourceFolders`/`splitDepth` from the layout or project config. An excluded
  file in hybrid mode may therefore appear in a folder fallback part.
- Groups with no matches remain present with zero files. Warn about unexpected
  empty groups before refreshing their saved graphs.
- Names are logical identifiers, independent of paths. `/` can organize labels;
  it is encoded as `~` in graph filenames. Names cannot contain comma, `~`,
  backslash, control characters, empty components, `.` or `..` components.
- Existing `groupingOverrides` (folder-part name to chosen part name) and
  `pathPrefixParts` (file-path prefix to part name, longest match wins) remain
  supported for legacy layouts. They apply to folder fallback files. Optional
  layout `sourceFolders`/`splitDepth` override command/config folder defaults.

## Regeneration and migration

Generated `intermediate/part-files/` and `partitions.json` are disposable outputs;
editing them alone does not define durable partitions. Migrate hand-authored
inventories into exact file includes or generalized patterns, then validate and
save the layout. Preserve existing graph files while doing so.

The analysis workflow compares saved definitions to the last published
`meta.json.partitionLayout`, so a layout change triggers processing even when
Git HEAD is unchanged. Preparation rejects inventories from a different layout;
publication rejects layout changes made while analysis is running. Repartition
and prepare again after a change. Full regeneration rebuilds the selected groups
using their current rules; it never resets them to folder hierarchy.

Use named parts with [load-graph](../load-graph/SKILL.md) just as with folder parts.
For example, select `authentication,operations` rather than loading every graph.
