# Deterministic Schemas And Validators For Analysis Agents

  ## Summary

  - Make arch_analysis the schema and validation source of
    truth for domain, project scan, and file batch
    outputs.

  - Replace LLM-authored JSON assembly where it is
    deterministic: project scan assembly, file-analyzer
    batch input/context prep, seeded file tags/edges,
    import-edge self-checking, and batch output splitting.

  - Update agent prompts under understand-anything-plugin/
    agents to reference arch_analysis/schemas/
    *.schema.json contracts instead of duplicating
    required-field/schema lists in markdown.

  ## Public APIs And Schemas

  - Extend arch_analysis.models and arch_analysis.schema
    so generated schemas cover:
      - project-scan-output.schema.json: final project-
        scanner output written to intermediate/scan-
        result.json.

      - knowledge-graph.schema.json and domain-
        graph.schema.json: full graph contracts used by
        domain-analyzer, graph-reviewer, and the guide.

      - graph-fragment.schema.json: { "nodes": [...],
        "edges": [...] } batch/part output from file-
        analyzer.

      - file-analysis-context.schema.json: deterministic
        per-batch context consumed by file-analyzer.

  - Add/update CLIs:
      - python -m
        arch_analysis.assemble_project_scan_result
        <project-root> <narrative.json>: merges LLM
        narrative fields with raw scan/import outputs and
        writes validated scan-result.json.

      - python -m
        arch_analysis.prepare_file_analysis_batch
        <project-root> <batchIndex> [<batchIndex>...]:
        reads batches.json, writes ua-file-analyzer-
        input-<batchIndex>.json and ua-file-
        context-<batchIndex>.json.

      - python -m arch_analysis.validate_structure_output
        <input.json> <extract-results.json>: validates
        Phase 1 Step 3 extraction output against schema
        and batch coverage.

      - python -m arch_analysis.seed_file_batch_graph
        <context.json> <extract-results.json> <seed.json>:
        writes deterministic file nodes, deterministic
        tags, and deterministic edges.

      - python -m arch_analysis.finalize_file_batch_output
        <project-root> <context.json> <seed.json>
        <draft.json>: validates no seeded tags/edges/nodes
        were lost, validates schema/reference/import
        counts, then writes batch-<N>.json or
        batch-<N>-part-<K>.json.

      - Update python -m
        arch_analysis.validate_domain_graph to run JSON
        Schema validation plus domain-specific checks and
        write a review JSON.

  ## Implementation Changes

  - domain-analyzer.md:
      - Replace the inline output schema with a reference
        to arch_analysis/schemas/domain-graph.schema.json.

      - Instruct the agent to write domain-analysis.json,
        run validate_domain_graph, read the review output,
        fix reported issues, and rerun until critical
        issues are gone.

      - Domain validator should enforce domain-only node/
        edge types, contains_flow/flow_step coverage,
        valid cross_domain edges, empty layers, no
        duplicates/self-edges, and monotonic flow_step
        ordering per flow.

  - project-scanner.md:
      - Keep raw scan/import-map CLIs as deterministic
        sources, but stop asking the LLM to manually
        assemble the final contract.

      - Have the LLM write only a small narrative JSON:
        name, optional description basis, and confirmed
        frameworks.

      - Run assemble_project_scan_result, which copies
        files, totals, complexity, and importMap verbatim
        from deterministic outputs, validates with
        project-scan-output.schema.json, and writes
        intermediate/scan-result.json.

  - file-analyzer.md:
      - Replace Phase 1 Step 1 manual JSON creation with
        prepare_file_analysis_batch; cross-batch
        neighborMap becomes validated context JSON, not
        prose-maintained structure.

      - After extract_structure, run
        validate_structure_output; retry extraction once
        on malformed/missing output, then fail hard if
        still invalid.

      - Before semantic edits, run seed_file_batch_graph;
        this seed contains deterministic file nodes,
        required deterministic tags, and required
        deterministic edges such as exact imports, direct
        contains, and direct exports where extraction
        proves them.

      - The LLM edits a draft by filling summaries,
        complexity, semantic tags, and judgment-based
        edges, but must preserve every seeded node/tag/
        edge.

      - Replace manual import-edge self-check and manual
        part splitting with finalize_file_batch_output;
        the finalizer enforces exact import edge coverage,
        validates allowed cross-batch refs from context,
        checks no seed information was lost, and writes
        the correct final batch filenames.

  - All agent prompts:
      - Replace inline schema contracts, required-field
        lists, and enum lists with references to the
        matching schema files when one exists.

      - Keep short examples only as illustrative examples,
        explicitly saying the schema file is
        authoritative.

      - Update architecture-analyzer.md to reference
        existing input.schema.json, output.schema.json,
        and layers.schema.json instead of restating layer
        fields.

      - Update knowledge-graph-guide.md to treat
        knowledge-graph.schema.json as the graph contract
        while keeping concise explanatory tables if
        useful.

  ## Test Plan

  - Update schema drift tests so every generated schema
    file must match its Pydantic model.

  - Add CLI tests for project scan assembly: deterministic
    files and importMap are copied exactly, total
    mismatches fail, and final output validates.

  - Add file-analyzer validator/finalizer tests: missing
    import edges fail, deleted seeded tags fail, deleted
    deterministic edges fail, invalid cross-batch refs
    fail, valid multi-part output writes correct
    filenames.

  - Add structure-output validator tests: duplicate paths,
    missing batch files, bad filesAnalyzed, and malformed
    metrics are reported.

  - Add domain validator tests: missing domain node, flow
    without domain, step without flow, invalid edge type,
    non-empty layers, and non-monotonic flow-step weights.

  - Run pdm run python -m arch_analysis.schema, then pdm
    run pytest arch_analysis/tests.

  ## Assumptions

  - “pr-deterministic scripting” means pre-deterministic
    seeding: generate tags/edges before LLM semantic
    edits, then validate preservation afterward.

  - Existing merge-time recovery in merge_batch_graphs
    remains as a safety net, but file-analyzer validation
    should catch missing deterministic data before merge.

  - New schemas live under arch_analysis/schemas/; prompts
    should not point at TypeScript/Zod schemas as the
    primary contract.