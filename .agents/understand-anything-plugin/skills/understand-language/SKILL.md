---
name: understand-language
description: Load the language-specific prompt snippet used by Understand-Anything analysis. Use when another Understand-Anything skill needs prompt guidance for one detected language such as TypeScript, Python, C#, C++, YAML, Dockerfile, GraphQL, Terraform, or SQL.
---

# /understand-language

Load a single language prompt snippet by name. This skill takes exactly one argument: the language name.

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`.
2. Run the bundled loader with exactly one language argument:
   ```bash
   python "$SKILL_DIR/scripts/load_prompt.py" "$ARGUMENTS"
   ```
3. Use the markdown printed to stdout as the language-specific prompt context. If the loader exits non-zero, treat the language as unsupported and continue without a snippet unless the caller explicitly needs that language.
