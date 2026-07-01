"""Port of ``frameworks/gin.ts``."""

from __future__ import annotations

from ..types import FrameworkConfig

gin_config = FrameworkConfig(
    id="gin",
    displayName="Gin",
    languages=["go"],
    detectionKeywords=["github.com/gin-gonic/gin"],
    manifestFiles=["go.mod"],
    promptSnippetPath="./frameworks/gin.md",
    entryPoints=["main.go", "cmd/server/main.go"],
    layerHints={
        "handlers": "api",
        "routes": "api",
        "models": "data",
        "middleware": "middleware",
        "services": "service",
        "repository": "data",
    },
)
