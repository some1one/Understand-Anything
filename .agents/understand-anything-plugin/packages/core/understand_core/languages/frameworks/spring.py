"""Port of ``frameworks/spring.ts``."""

from __future__ import annotations

from ..types import FrameworkConfig

spring_config = FrameworkConfig(
    id="spring",
    displayName="Spring Boot",
    languages=["java", "kotlin"],
    detectionKeywords=["spring-boot", "spring-boot-starter", "spring-web", "spring-data", "org.springframework"],
    manifestFiles=["pom.xml", "build.gradle", "build.gradle.kts"],
    promptSnippetPath="skills/understand-framework/prompts/spring.md",
    entryPoints=["**/Application.java", "**/App.java"],
    layerHints={
        "controller": "api",
        "service": "service",
        "repository": "data",
        "model": "data",
        "entity": "data",
        "config": "config",
        "dto": "types",
        "security": "middleware",
    },
)
