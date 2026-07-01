"""Port of ``configs/dockerfile.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

dockerfile_config = LanguageConfig(
    id="dockerfile",
    displayName="Dockerfile",
    extensions=[],
    filenames=["Dockerfile", "Dockerfile.dev", "Dockerfile.prod", "Dockerfile.test"],
    concepts=["multi-stage builds", "layers", "base images", "COPY/ADD", "EXPOSE", "ENTRYPOINT", "CMD", "ARG", "ENV"],
    filePatterns={
        "entryPoints": ["Dockerfile"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
