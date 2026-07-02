"""``skill_builders`` — Python port of ``understand-anything-plugin/src``.

Prompt/context builders that consume the knowledge graph and produce
prompt/context strings for the ``/understand-*`` skills. Mirrors ``src/index.ts``.
"""

from __future__ import annotations

from skill_builders.context_builder import (
    ChatContext,
    build_chat_context,
    format_context_for_prompt,
)
from skill_builders.diff_analyzer import (
    DiffContext,
    build_diff_context,
    format_diff_analysis,
)
from skill_builders.explain_builder import (
    ExplainContext,
    build_explain_context,
    format_explain_prompt,
)
from skill_builders.onboard_builder import build_onboarding_guide
from skill_builders.understand_chat import build_chat_prompt

__all__ = [
    "ChatContext",
    "build_chat_context",
    "format_context_for_prompt",
    "build_chat_prompt",
    "DiffContext",
    "build_diff_context",
    "format_diff_analysis",
    "ExplainContext",
    "build_explain_context",
    "format_explain_prompt",
    "build_onboarding_guide",
]
