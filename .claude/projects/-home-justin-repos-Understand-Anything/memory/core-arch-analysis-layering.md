---
name: core-arch-analysis-layering
description: How the core package relates to arch_analysis and the live pipeline (post-dedup, 2026-07)
metadata:
  type: project
---

`packages/core` is a thin **on-top layer** over `packages/arch_analysis`; the dependency is one-way (core imports arch_analysis, never the reverse). The live deterministic pipeline (skills/agents/hooks via `run.sh`) invokes **only arch_analysis modules** — `core` is not on that path. Within core, the only production consumer of `understand_core` is `skill_builders/`, and it uses just 5 symbols: `GraphNode, GraphEdge, KnowledgeGraph, Layer` (types) and `SearchEngine` (search).

In July 2026 the duplicated reimplementations were deleted from core (they lived in arch_analysis already and were dead outside tests): `understand_core/{plugins,languages,analyzer}/` and `change_classifier.py`. `fingerprint.py` was reduced to the `fingerprints.json` wire-shape TypedDicts + a `content_hash` re-export. The canonical graph enum sets (`VALID_NODE_TYPES/EDGE_TYPES/COMPLEXITY/DIRECTIONS`) now live once in `arch_analysis/constants.py`, imported by both `arch_analysis/validate_graph.py` and `understand_core/schema.py`. What remains in core: graph types (re-exported from `arch_analysis.models`), persistence, the repair validator (`schema.py`), lexical + semantic search, staleness, and the ignore shims. See `packages/core/CONVERSION_GUIDE.md`.
