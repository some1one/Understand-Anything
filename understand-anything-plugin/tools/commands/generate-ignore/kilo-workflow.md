---
description: Generate a starter .understandignore from .gitignore plus built-in defaults.
---

# /understand-generate-ignore

Generates a starter `.understand-anything/.understandignore` (reads `.gitignore`,
dedupes against built-in defaults, suggests test-file exclusions for review).

Execute with the `bash` tool, forwarding `$ARGUMENTS` (`<project-root>`):

```bash
__PLUGIN_ROOT__/tools/commands/generate-ignore/run.sh $ARGUMENTS
```

Report where the file was written and remind the user to review it. On non-zero
exit, show the error.
