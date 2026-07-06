# understand-anything-core (Python)

Python port of `@understand-anything/core` (`understand-anything-plugin/packages/core`)
and the skill builders (`understand-anything-plugin/src`).

- `understand_core/` — analysis engine: graph types, schema, fuzzy + embedding
  search, LLM prompt builders, language/framework registries, structural plugins.
- `skill_builders/` — context/prompt builders for `/understand-chat`,
  `/understand-diff`, `/understand-explain`, `/understand-onboard`.

Deterministic structural analysis already in the repo-root `arch_analysis/`
package (tree-sitter, language detection, ignore filtering, structural
extraction, fingerprints, models/schema, graph merging, auto-update) is
**imported** from `arch_analysis.*` rather than re-implemented. See
`CONVERSION_GUIDE.md`.

```bash
pdm install
pdm run pytest
```
