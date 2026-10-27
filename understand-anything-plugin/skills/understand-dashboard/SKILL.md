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

4. In Codex or another host with managed long-running commands, launch in a
   **foreground managed session**:
   ```bash
   "$SKILL_DIR/scripts/launch_dashboard.sh" --foreground "<project-dir>"
   ```
   With Codex `exec_command`, use `tty: true` and `yield_time_ms: 1000`, retain
   the returned session ID, and leave that session running. Request the normal
   sandbox escalation if localhost listening fails with `EPERM`.
   The command prints the full tokenized URL directly. Do not append `&`, close
   the session, or send Ctrl-C after startup. Shell backgrounding alone does not
   establish persistence in a managed command runner; do not assume `nohup` or
   `setsid` bypass host process cleanup.

   For an ordinary terminal whose background jobs survive command completion,
   the existing background mode remains available:
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

5. Verify the tokenized URL responds from a separate command before reporting
   success (for example, `curl --fail --silent --output /dev/null '<full-url>'`).
   Use the same network permissions as the server. Checking `ps` from a sandbox
   may not see a server started outside that sandbox. Report the full tokenized
   URL to the user. **Always include the `?token=` parameter** — omitting it
   blocks the user at the token gate. A managed session keeps the command alive
   while the host retains it; do not promise survival after the host closes.

## Notes

- The launcher prints a URL; open it in your browser.
- The launcher reports the actual selected port; do not assume port 5173 is available.
- `GRAPH_DIR` tells the dashboard where to find the knowledge graph
