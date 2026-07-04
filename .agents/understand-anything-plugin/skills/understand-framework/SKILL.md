---
name: understand-framework
description: Load the framework-specific prompt addendum used by Understand-Anything analysis. Use when another Understand-Anything skill needs prompt guidance for one detected framework such as React, Next.js, Express, Django, FastAPI, Flask, Spring Boot, Ruby on Rails, Vue, or Gin.
---

# /understand-framework

Load a single framework prompt addendum by name. This skill takes exactly one argument: the framework name.

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`.
2. Run the bundled loader with exactly one framework argument:
   ```bash
   python "$SKILL_DIR/scripts/load_prompt.py" "$ARGUMENTS"
   ```
3. Use the markdown printed to stdout as the framework-specific prompt context. If the loader exits non-zero, treat the framework as unsupported and continue without an addendum unless the caller explicitly needs that framework.
