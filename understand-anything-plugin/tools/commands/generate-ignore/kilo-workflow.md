---
description: Generate a starter .understandignore from .gitignore plus built-in defaults.
---

# /understand-generate-ignore

Generates a starter `.ua/.understandignore` (reads `.gitignore`,
dedupes against built-in defaults, suggests test-file exclusions for review).

Parse the supplied arguments into a project path; quote each path separately. Do not evaluate the raw argument text as shell code. The installer replaces `__PLUGIN_ROOT__` below.

```bash
"__PLUGIN_ROOT__/tools/commands/generate-ignore/run.sh" "<project-root>"
```

Replace placeholders before execution.

Report where the file was written and remind the user to review it. On non-zero
exit, show the error.
