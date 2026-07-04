---
description: Generate a starter .understandignore from .gitignore plus built-in defaults.
---

# /understand-generate-ignore

Run the deterministic **generate-ignore** command from Understand-Anything. It
generates a starter `.understand-anything/.understandignore` (reads
`.gitignore`, dedupes against built-in defaults, and suggests test-file
exclusions for review).

Execute this with the `bash` tool, forwarding `$ARGUMENTS` (`<project-root>`):

```bash
__PLUGIN_ROOT__/tools/commands/generate-ignore/run.sh $ARGUMENTS
```

Report where the file was written and remind the user to review it. If it exits
non-zero, show the error.
