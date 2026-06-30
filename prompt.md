 # Consolidate Scriptable Analysis Into arch_analysis and Remove Tours

  ## Summary

  - Make arch_analysis the canonical Python package for deterministic
    pipeline logic currently spread across project-scanner.md, file-
    analyzer.md, domain-analyzer.md, and helper scripts.

  - Fully replace the JS helper scripts used by the /understand pipeline with
    Python modules and CLIs in arch_analysis.

  - Remove the tour feature: delete agents/tour-builder.md, remove tour
    generation from /understand, remove tour UI/actions/instructions, and
    stop emitting tour data in new graphs.

  ## arch_analysis Implementation

  - Add typed Pydantic models and JSON Schemas for:
      - scan result, import-map input/output, file-structure extraction
        input/output, batch plan, graph fragment, knowledge graph, domain
        context, domain graph, validation report.

      - Keep existing AnalysisInput, architecture result, and layer schemas.
      - Regenerate all schemas via python -m arch_analysis.schema; keep
        schema drift tests.

  - Add Python CLIs and PDM scripts:
      - arch_analysis.scan_project <project_root> <output.json>
      - arch_analysis.extract_import_map <input.json> <output.json>
      - arch_analysis.extract_structure <input.json> <output.json>
      - arch_analysis.compute_batches <project_root> [--changed-files PATH]
      - arch_analysis.merge_batch_graphs <project_root>
      - arch_analysis.extract_domain_context <project_root> [--output PATH]
      - arch_analysis.validate_graph <graph.json> <review.json>
      - arch_analysis.validate_domain_graph <domain-graph.json>
      - arch_analysis.generate_ignore <project_root> and
        arch_analysis.build_fingerprints <input.json> if /understand still
        needs those phases after JS helper removal.

  - Required Python packages:
      - Keep existing: orjson, pydantic, networkx, numpy, pandas, scipy,
        jsonschema, pathspec.

      - Add: tree-sitter, tree-sitter-language-pack, pyyaml.
      - Use stdlib tomllib, json, xml.etree, re, pathlib, and subprocess
        where sufficient.

  - Replace JS helper behavior:
      - scan_project: deterministic file enumeration, .understandignore,
        language/category detection, line counts, manifest/README metadata,
        framework detection, complexity, stats.

      - extract_import_map: resolved internal imports for TS/JS, Python, Go,
        Rust, Java, Kotlin, C#, Ruby, PHP, C/C++; warnings are per-file and
        non-fatal.

      - extract_structure: tree-sitter-backed structural extraction plus non-
        code parsers for Markdown, YAML, JSON, TOML, env, Dockerfile, SQL,
        GraphQL, Protobuf, Terraform, Makefile, shell; output metrics must
        match the current file-analyzer contract.

      - compute_batches: use networkx Louvain communities, preserve existing
        max-size, fallback, non-code grouping, neighborMap, batchImportData,
        and changed-files behavior.

      - merge_batch_graphs: move the existing Python merge logic into
        arch_analysis, preserving multipart batch handling, import recovery,
        tested_by canonicalization, dedupe, normalization, warnings, and
        stats.

      - extract_domain_context: move the current domain context scan into
        arch_analysis and validate its output schema.

  ## Instruction and Pipeline Updates

  - Update project-scanner.md to run python -m arch_analysis.scan_project;
    remove references to scan-project.mjs and extract-import-map.mjs.

  - Update file-analyzer.md to run python -m arch_analysis.extract_structure;
    keep LLM-only work limited to summaries, tags, semantic edges, and
    significance judgement; add a required arch_analysis validation step for
    batch fragments.

  - Update domain-analyzer.md and skills/understand-domain/SKILL.md to use
    python -m arch_analysis.extract_domain_context and validate_domain_graph;
    remove references to tours as graph context.

  - Update skills/understand/SKILL.md:
      - Use arch_analysis CLIs for scan, batching, merge, validation, ignore
        generation, and fingerprints.

      - Remove Phase 5 Tour entirely.
      - Assemble final codebase graphs without tour.
      - Remove final summary line for “Tour steps generated”.

  - Update auto-update instructions/hooks to remove rerunTour, tour-builder
    reruns, and tour-specific phase language.

  - Remove or rewrite docs/instructions that describe tours as part of the
    product:
      - agents/knowledge-graph-guide.md
      - agents/graph-reviewer.md
      - skills/understand-chat, understand-diff, understand-explain,
        understand-onboard

      - CLAUDE.md
      - generated demo/sample graph descriptions where they advertise tour
        functionality.

  ## Tour Feature Removal

  - Delete:
      - understand-anything-plugin/agents/tour-builder.md
      - understand-anything-plugin/packages/core/src/analyzer/tour-
        generator.ts

      - tour-generator tests
      - tour-specific dashboard components/actions such as LearnPanel tour
        state, start/next/previous tour actions, tour highlighted node state,
        tour keyboard shortcuts, and “Start Guided Tour” UI.

  - Stop generating or requiring tour in new graph output.
  - Preserve legacy tolerance: schema validation may accept existing graphs
    containing a tour key, but new graph assembly should omit it and no UI or
    instructions should surface it.

  - Update TypeScript types/schemas so KnowledgeGraph no longer requires
    tour; remove TourStep from public exports unless kept only as deprecated
    legacy input parsing.

  - Update onboarding generation to use project metadata, layers, file
    summaries, and dependency edges instead of guided-tour steps.

  ## Script Removal and Package Cleanup

  - Remove replaced helper scripts after Python parity tests exist:
      - skills/understand/scan-project.mjs
      - skills/understand/extract-import-map.mjs
      - skills/understand/extract-structure.mjs
      - skills/understand/compute-batches.mjs
      - skills/understand/build-fingerprints.mjs and generate-ignore.mjs only
        after Python replacements are wired.

  - Remove JS test files that target deleted helper scripts after porting
    their assertions into Python tests.

  - Remove no-longer-needed npm dependencies from understand-anything-plugin/
    package.json / workspace packages, especially graphology batching deps
    and tour-only exports.

  - Keep TypeScript/dashboard packages where still needed for the dashboard
    and non-tour skills.

  ## Test Plan

  - Port existing helper coverage into arch_analysis/tests:
      - scan language/category/.understandignore/determinism/schema/failure
        tests.

      - import resolution tests across supported languages and config edge
        cases.

      - structure extraction metrics, non-code parser output, call graph,
        fallback behavior.

      - batching Louvain/fallback/non-code grouping/neighborMap/changed-
        files.

      - merge batch graph multipart, import recovery, dedupe, and tested_by
        tests.

      - domain context and domain graph validation tests.

  - Add tour-removal tests:
      - /understand instructions contain no tour phase.
      - graph validation accepts graphs without tour.
      - dashboard has no tour controls, tour keyboard shortcuts, or
        LearnPanel tour flow.

      - onboarding output does not include a guided-tour section.

  - Run:
      - pdm run pytest
      - targeted rg checks proving no live references remain to deleted
        scripts or tour-builder.

      - git diff --check.

  ## Assumptions

  - arch_analysis should fully replace JS helper scripts, not wrap them.
  - LLM agents still handle semantic judgement that cannot be made
    deterministic: file summaries/tags, semantic edges, final architecture
    layer descriptions, and business-domain interpretation.

  - Tour data is deprecated for legacy input tolerance only; new outputs omit
    it and product surfaces do not display it.