"""Port of ``configs/protobuf.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

protobuf_config = LanguageConfig(
    id="protobuf",
    displayName="Protocol Buffers",
    extensions=[".proto"],
    concepts=["messages", "services", "enums", "oneof", "repeated fields", "maps", "packages", "imports"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
