"""Port of ``configs/kubernetes.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

# Note: Kubernetes manifests are YAML with no unique extension or filename. Detection requires content/path heuristics; currently these match yaml_config by extension. A future pass could re-classify them.
kubernetes_config = LanguageConfig(
    id="kubernetes",
    displayName="Kubernetes",
    extensions=[],
    concepts=["deployments", "services", "pods", "configmaps", "secrets", "ingress", "volumes", "namespaces"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": ["k8s/*.yaml", "kubernetes/*.yaml"],
    },
)
