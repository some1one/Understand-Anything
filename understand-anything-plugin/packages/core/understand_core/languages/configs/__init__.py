"""Built-in language configs (port of ``configs/index.ts``)."""

from __future__ import annotations

from ..types import LanguageConfig

from .typescript import typescript_config
from .javascript import javascript_config
from .python import python_config
from .go import go_config
from .rust import rust_config
from .java import java_config
from .ruby import ruby_config
from .php import php_config
from .swift import swift_config
from .kotlin import kotlin_config
from .lua import lua_config
from .c import c_config
from .cpp import cpp_config
from .dart import dart_config
from .csharp import csharp_config
from .markdown import markdown_config
from .yaml import yaml_config
from .json_config import json_config_config
from .toml import toml_config
from .env import env_config
from .xml import xml_config
from .dockerfile import dockerfile_config
from .sql import sql_config
from .graphql import graphql_config
from .protobuf import protobuf_config
from .terraform import terraform_config
from .github_actions import github_actions_config
from .makefile import makefile_config
from .shell import shell_config
from .html import html_config
from .css import css_config
from .openapi import openapi_config
from .kubernetes import kubernetes_config
from .docker_compose import docker_compose_config
from .json_schema import json_schema_config
from .csv import csv_config
from .restructuredtext import restructuredtext_config
from .jenkinsfile import jenkinsfile_config
from .plaintext import plaintext_config

builtin_language_configs: list[LanguageConfig] = [
    typescript_config,
    javascript_config,
    python_config,
    go_config,
    rust_config,
    java_config,
    ruby_config,
    php_config,
    swift_config,
    kotlin_config,
    lua_config,
    c_config,
    cpp_config,
    dart_config,
    csharp_config,
    markdown_config,
    yaml_config,
    json_config_config,
    toml_config,
    env_config,
    xml_config,
    dockerfile_config,
    sql_config,
    graphql_config,
    protobuf_config,
    terraform_config,
    github_actions_config,
    makefile_config,
    shell_config,
    html_config,
    css_config,
    openapi_config,
    kubernetes_config,
    docker_compose_config,
    json_schema_config,
    csv_config,
    restructuredtext_config,
    jenkinsfile_config,
    plaintext_config,
]

__all__ = [
    "typescript_config",
    "javascript_config",
    "python_config",
    "go_config",
    "rust_config",
    "java_config",
    "ruby_config",
    "php_config",
    "swift_config",
    "kotlin_config",
    "lua_config",
    "c_config",
    "cpp_config",
    "dart_config",
    "csharp_config",
    "markdown_config",
    "yaml_config",
    "json_config_config",
    "toml_config",
    "env_config",
    "xml_config",
    "dockerfile_config",
    "sql_config",
    "graphql_config",
    "protobuf_config",
    "terraform_config",
    "github_actions_config",
    "makefile_config",
    "shell_config",
    "html_config",
    "css_config",
    "openapi_config",
    "kubernetes_config",
    "docker_compose_config",
    "json_schema_config",
    "csv_config",
    "restructuredtext_config",
    "jenkinsfile_config",
    "plaintext_config",
    "builtin_language_configs",
]
