---
name: skill-path-roots
description: The three path roots skill files must use so agents don't resolve plugin paths against the analyzed project
metadata:
  type: reference
---

Skills are installed apart from the codebase they analyze (often via symlink), so `SKILL.md` files must never use bare relative paths for plugin resources. Three roots:

- `$PROJECT_ROOT` — the analyzed codebase (cwd / `$ARGUMENTS` dir). All `.understand-anything/*` artifacts, source, git state.
- `$SKILL_DIR` — the skill's own dir; its `scripts/`, `prompts/`, `frameworks/`, `languages/` are bundled inside and travel with the skill in every install layout → `$SKILL_DIR/<subdir>/…`.
- `$PLUGIN_ROOT` — full plugin root (resolved by `skills/understand/scripts/ensure_python_env.sh`). The shared `agents/` and `packages/arch_analysis/` (incl. `schemas/`) live here → `$PLUGIN_ROOT/agents/…`, `$PLUGIN_ROOT/packages/arch_analysis/…`.

A bare `agents/foo.md` or `prompts/foo.md` in a SKILL.md is a bug: an agent resolves it against `$PROJECT_ROOT` and fails. See the "Path conventions" note in `skills/understand/SKILL.md` Phase 0. Related: [[core-arch-analysis-layering]].
