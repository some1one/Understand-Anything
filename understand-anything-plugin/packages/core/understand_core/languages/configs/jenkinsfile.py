"""Port of ``configs/jenkinsfile.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

jenkinsfile_config = LanguageConfig(
    id="jenkinsfile",
    displayName="Jenkinsfile",
    extensions=[],
    filenames=["Jenkinsfile"],
    concepts=["pipeline", "stages", "steps", "agents", "environment", "post actions", "parallel execution", "shared libraries"],
    filePatterns={
        "entryPoints": ["Jenkinsfile"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
