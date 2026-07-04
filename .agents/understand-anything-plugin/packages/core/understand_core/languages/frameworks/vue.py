"""Port of ``frameworks/vue.ts``."""

from __future__ import annotations

from ..types import FrameworkConfig

vue_config = FrameworkConfig(
    id="vue",
    displayName="Vue",
    languages=["typescript", "javascript"],
    detectionKeywords=["vue", "@vue/cli-service", "nuxt", "vite-plugin-vue"],
    manifestFiles=["package.json"],
    promptSnippetPath="skills/understand-framework/prompts/vue.md",
    entryPoints=["src/main.ts", "src/App.vue", "src/main.js"],
    layerHints={
        "components": "ui",
        "views": "ui",
        "store": "service",
        "composables": "service",
        "router": "config",
        "plugins": "config",
    },
)
