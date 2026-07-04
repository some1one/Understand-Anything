---
name: understand-dashboard
description: Launch the interactive web dashboard to visualize a codebase's knowledge graph
argument-hint: [project-path]
---

# /understand-dashboard

Start the Understand Anything dashboard to visualize the knowledge graph for the current project.

## Instructions

1. Determine the project directory:
   - If `$ARGUMENTS` contains a path, use that as the project directory
   - Otherwise, use the current working directory

2. Check that `.understand-anything/knowledge-graph.json` exists in the project directory. If not, tell the user:
   ```
   No knowledge graph found. Run /understand first to analyze this project.
   ```

3. Set `SKILL_DIR` to the directory containing this `SKILL.md`.

4. Launch the dashboard with the bundled Bash script:
   ```bash
   "$SKILL_DIR/scripts/launch_dashboard.sh" "<project-dir>"
   ```

   The script resolves `PLUGIN_ROOT` / `DASHBOARD_DIR`, installs dependencies if needed, builds the core package, starts Vite in the background with `GRAPH_DIR=<project-dir>`, captures the token URL, and prints:
   ```
   Dashboard started at http://127.0.0.1:<PORT>?token=<TOKEN>
   Viewing: <project-dir>/.understand-anything/knowledge-graph.json
   PID: <pid>
   Log: <project-dir>/.understand-anything/tmp/dashboard.log
   ```

5. Report the full tokenized URL to the user.
   **Important:** Always include the `?token=` parameter in the URL you share. If you omit it, the user will be blocked by the token gate and have to manually find the token in the terminal output.

## Notes

- The dashboard auto-opens in the default browser via `--open`
- If port 5173 is already in use, Vite will pick the next available port
- The `GRAPH_DIR` environment variable tells the dashboard where to find the knowledge graph
