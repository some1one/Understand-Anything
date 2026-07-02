"""Built-in framework configs (port of ``frameworks/index.ts``)."""

from __future__ import annotations

from ..types import FrameworkConfig

from .django import django_config
from .fastapi import fastapi_config
from .flask import flask_config
from .react import react_config
from .nextjs import nextjs_config
from .express import express_config
from .vue import vue_config
from .spring import spring_config
from .rails import rails_config
from .gin import gin_config

builtin_framework_configs: list[FrameworkConfig] = [
    django_config,
    fastapi_config,
    flask_config,
    react_config,
    nextjs_config,
    express_config,
    vue_config,
    spring_config,
    rails_config,
    gin_config,
]

__all__ = [
    "django_config",
    "fastapi_config",
    "flask_config",
    "react_config",
    "nextjs_config",
    "express_config",
    "vue_config",
    "spring_config",
    "rails_config",
    "gin_config",
    "builtin_framework_configs",
]
