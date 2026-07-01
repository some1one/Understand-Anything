"""Non-code file parsers. Mirrors ``plugins/parsers/index.ts``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from understand_core.plugins.parsers.dockerfile_parser import DockerfileParser
from understand_core.plugins.parsers.env_parser import EnvParser
from understand_core.plugins.parsers.graphql_parser import GraphQLParser
from understand_core.plugins.parsers.json_parser import JSONConfigParser, strip_jsonc_syntax
from understand_core.plugins.parsers.makefile_parser import MakefileParser
from understand_core.plugins.parsers.markdown_parser import MarkdownParser
from understand_core.plugins.parsers.protobuf_parser import ProtobufParser
from understand_core.plugins.parsers.shell_parser import ShellParser
from understand_core.plugins.parsers.sql_parser import SQLParser
from understand_core.plugins.parsers.terraform_parser import TerraformParser
from understand_core.plugins.parsers.toml_parser import TOMLParser
from understand_core.plugins.parsers.yaml_parser import YAMLConfigParser

if TYPE_CHECKING:
    from understand_core.plugins.registry import PluginRegistry

__all__ = [
    "MarkdownParser",
    "YAMLConfigParser",
    "JSONConfigParser",
    "strip_jsonc_syntax",
    "TOMLParser",
    "EnvParser",
    "DockerfileParser",
    "SQLParser",
    "GraphQLParser",
    "ProtobufParser",
    "TerraformParser",
    "MakefileParser",
    "ShellParser",
    "register_all_parsers",
]


def register_all_parsers(registry: "PluginRegistry") -> None:
    """Register all 12 built-in non-code parsers with a ``PluginRegistry``."""
    registry.register(MarkdownParser())
    registry.register(YAMLConfigParser())
    registry.register(JSONConfigParser())
    registry.register(TOMLParser())
    registry.register(EnvParser())
    registry.register(DockerfileParser())
    registry.register(SQLParser())
    registry.register(GraphQLParser())
    registry.register(ProtobufParser())
    registry.register(TerraformParser())
    registry.register(MakefileParser())
    registry.register(ShellParser())
