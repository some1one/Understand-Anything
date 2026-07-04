"""Port of ``configs/makefile.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

makefile_config = LanguageConfig(
    id="makefile",
    displayName="Makefile",
    extensions=[".mk"],
    filenames=["Makefile", "GNUmakefile", "makefile"],
    concepts=["targets", "dependencies", "recipes", "variables", "pattern rules", "phony targets", "includes"],
    filePatterns={
        "entryPoints": ["Makefile"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
