"""Port of ``configs/shell.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

shell_config = LanguageConfig(
    id="shell",
    displayName="Shell Script",
    extensions=[".sh", ".bash", ".zsh"],
    concepts=["variables", "functions", "conditionals", "loops", "pipes", "redirection", "subshells", "exit codes"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [".bashrc", ".zshrc", ".profile"],
    },
)
