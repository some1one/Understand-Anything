"""Port of ``frameworks/express.ts``."""

from __future__ import annotations

from ..types import FrameworkConfig

express_config = FrameworkConfig(
    id="express",
    displayName="Express",
    languages=["javascript", "typescript"],
    detectionKeywords=["\"express\":", "express-validator", "express-session"],
    manifestFiles=["package.json"],
    promptSnippetPath="skills/understand-framework/prompts/express.md",
    entryPoints=["src/index.js", "src/app.js", "server.js", "app.js", "src/index.ts", "src/app.ts"],
    layerHints={
        "routes": "api",
        "controllers": "service",
        "models": "data",
        "middleware": "middleware",
        "services": "service",
        "db": "data",
    },
)
