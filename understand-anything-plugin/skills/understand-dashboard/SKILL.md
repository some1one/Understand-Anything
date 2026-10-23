---
name: understand-dashboard
description: Launch the interactive web dashboard to visualize a codebase's knowledge graph. For plugin setup or instructions before the first analysis, use understand-help.
argument-hint: "[project-path]"
---

# /understand-dashboard

Resolve `UA_DIR` after resolving `PLUGIN_ROOT` and `PROJECT_ROOT`, before reading
or writing project artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use this absolute directory throughout the workflow and pass it to workers.
It selects `.ua` for new projects and retains an existing legacy directory;
see [host integration](../../HOSTS.md) for the selection rules.


Launch the Understand Anything dashboard to visualize the current project's knowledge graph.

Read [host integration](../../HOSTS.md) for invocation, argument handling, and agent dispatch.

## Instructions

1. Project directory: use `$ARGUMENTS` if it contains a path, else the current working directory.

2. If `$UA_DIR/knowledge-graph.json` does not exist in the project directory, tell the user:
   ```
   No knowledge graph found. Run /understand first to analyze this project.
   ```

3. Set `SKILL_DIR` to the directory containing this `SKILL.md`.

4. Launch the dashboard:
   ```bash
   "$SKILL_DIR/scripts/launch_dashboard.sh" "<project-dir>"
   ```

   Prints:
   ```
   Dashboard started at http://127.0.0.1:<PORT>?token=<TOKEN>
   Viewing: <project-dir>/.ua/knowledge-graph.json
   PID: <pid>
   Log: <project-dir>/.ua/tmp/dashboard.log
   ```

5. Report the full tokenized URL to the user. **Always include the `?token=` parameter** — omitting it blocks the user at the token gate.

## Notes

- The launcher prints a URL; open it in your browser.
- The launcher reports the actual selected port; do not assume port 5173 is available.
- `GRAPH_DIR` tells the dashboard where to find the knowledge graph
