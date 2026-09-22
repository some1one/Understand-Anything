---
name: understand-language
description: Load the language-specific prompt snippet used by Understand-Anything analysis. Use when another Understand-Anything skill needs prompt guidance for one detected language such as TypeScript, Python, C#, C++, YAML, Dockerfile, GraphQL, Terraform, or SQL.
---

# /understand-language

Load a single language prompt snippet by name. Takes exactly one argument: the language name.

Read [host integration](../../HOSTS.md) for invocation, argument handling, and agent dispatch.

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`.
2. Run the loader with exactly one language argument:
   ```bash
   python3 "$SKILL_DIR/scripts/load_prompt.py" "$ARGUMENTS"
   ```
3. Use the markdown printed to stdout as the language-specific prompt context. On non-zero exit, treat the language as unsupported and continue without a snippet unless the caller explicitly needs it.

Apply only patterns supported by the project's actual language version and source.
Examples illustrate possible relationships; they are not evidence that a project
uses a framework or feature. Respect the caller's analysis scope and seeded graph.
