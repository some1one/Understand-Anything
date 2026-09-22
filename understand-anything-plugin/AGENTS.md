# Understand Anything plugin

Shared skills in `skills/` support Claude Code and Codex.
Read [HOSTS.md](HOSTS.md) when changing host integration or skill instructions.

- `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` declare the same
  plugin identity and release version.
- `hooks/hooks.json` uses the shared command-hook protocol; the handler reads
  event JSON from stdin and returns structured context.
- `agents/*.md` are native Claude definitions and portable instruction bodies
  loaded explicitly by other hosts.
- `packages/core/run.sh <module> …` launches the deterministic Python engine.
  Keep plugin paths separate from the analyzed project paths.
- `packages/dashboard/` is an independent Node project.

Keep user/developer usage in README files and host/agent execution conventions
in this file, HOSTS.md, and skills. Validate manifests, skill frontmatter, referenced
paths, packaging contents, and affected runtime scripts after integration changes.
