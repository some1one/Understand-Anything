"""Build a full chat prompt — port of ``understand-chat.ts``."""

from __future__ import annotations

from understand_core import KnowledgeGraph

from skill_builders.context_builder import (
    build_chat_context,
    format_context_for_prompt,
)


def build_chat_prompt(graph: KnowledgeGraph, query: str) -> str:
    """Combine knowledge-graph context with a system instruction prompt."""
    context = build_chat_context(graph, query)
    formatted_context = format_context_for_prompt(context)

    return "\n".join(
        [
            "You are a knowledgeable assistant that answers questions about a software codebase.",
            "Use the following knowledge graph context to inform your answer.",
            "Reference specific files, functions, classes, and relationships from the graph.",
            "If layers are present, explain which architectural layer(s) are relevant.",
            "Be concise but thorough — link concepts to actual code locations.",
            "",
            "---",
            "",
            formatted_context,
            "---",
            "",
            f"**User question:** {query}",
        ]
    )
