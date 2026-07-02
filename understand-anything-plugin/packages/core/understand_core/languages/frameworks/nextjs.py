"""Port of ``frameworks/nextjs.ts``."""

from __future__ import annotations

from ..types import FrameworkConfig

nextjs_config = FrameworkConfig(
    id="nextjs",
    displayName="Next.js",
    languages=["typescript", "javascript"],
    detectionKeywords=["\"next\":", "@next/font", "@next/image"],
    manifestFiles=["package.json"],
    promptSnippetPath="./frameworks/nextjs.md",
    entryPoints=["src/app/layout.tsx", "pages/_app.tsx", "src/pages/_app.tsx"],
    layerHints={
        "app": "ui",
        "pages": "ui",
        "api": "api",
        "components": "ui",
        "lib": "service",
        "middleware": "middleware",
    },
)
