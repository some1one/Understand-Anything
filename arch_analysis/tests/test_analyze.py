"""End-to-end and unit tests for the structural analysis."""

from __future__ import annotations

from arch_analysis.analyze import analyze
from arch_analysis.grouping import common_dir_prefix, group_by_directory
from arch_analysis.models import AnalysisInput, FileNode
from arch_analysis.patterns import classify_file


SAMPLE = {
    "fileNodes": [
        {"id": "file:src/routes/index.ts", "type": "file", "name": "index.ts", "filePath": "src/routes/index.ts", "tags": ["api-handler"]},
        {"id": "file:src/routes/auth.ts", "type": "file", "name": "auth.ts", "filePath": "src/routes/auth.ts", "tags": []},
        {"id": "file:src/services/auth.ts", "type": "file", "name": "auth.ts", "filePath": "src/services/auth.ts", "tags": []},
        {"id": "file:src/services/user.ts", "type": "file", "name": "user.ts", "filePath": "src/services/user.ts", "tags": []},
        {"id": "file:src/utils/format.ts", "type": "file", "name": "format.ts", "filePath": "src/utils/format.ts", "tags": []},
        {"id": "config:tsconfig.json", "type": "config", "name": "tsconfig.json", "filePath": "tsconfig.json", "tags": ["configuration"]},
        {"id": "document:README.md", "type": "document", "name": "README.md", "filePath": "README.md", "tags": ["documentation"]},
        {"id": "service:Dockerfile", "type": "service", "name": "Dockerfile", "filePath": "Dockerfile", "tags": ["infrastructure"]},
        {"id": "pipeline:.github/workflows/ci.yml", "type": "pipeline", "name": "ci.yml", "filePath": ".github/workflows/ci.yml", "tags": []},
    ],
    "importEdges": [
        {"source": "file:src/routes/index.ts", "target": "file:src/services/auth.ts", "type": "imports"},
        {"source": "file:src/routes/auth.ts", "target": "file:src/services/auth.ts", "type": "imports"},
        {"source": "file:src/routes/index.ts", "target": "file:src/utils/format.ts", "type": "imports"},
        {"source": "file:src/services/auth.ts", "target": "file:src/utils/format.ts", "type": "imports"},
        {"source": "file:src/services/user.ts", "target": "file:src/utils/format.ts", "type": "imports"},
    ],
    "allEdges": [
        {"source": "file:src/routes/index.ts", "target": "file:src/services/auth.ts", "type": "imports"},
        {"source": "config:tsconfig.json", "target": "file:src/routes/index.ts", "type": "configures"},
        {"source": "service:Dockerfile", "target": "file:src/routes/index.ts", "type": "deploys"},
        {"source": "document:README.md", "target": "file:src/services/auth.ts", "type": "documents"},
    ],
}


# A project where every file shares the ``src/`` prefix, so directory grouping
# resolves to the fine-grained routes/services/utils buckets (section A example).
SAMPLE_SRC_ONLY = {
    "fileNodes": [n for n in SAMPLE["fileNodes"] if n["filePath"].startswith("src/")],
    "importEdges": SAMPLE["importEdges"],
    "allEdges": [e for e in SAMPLE["allEdges"] if e["type"] == "imports"],
}


def _run():
    return analyze(AnalysisInput.model_validate(SAMPLE))


def _run_src():
    return analyze(AnalysisInput.model_validate(SAMPLE_SRC_ONLY))


def test_completes_and_validates():
    result = _run()
    assert result["scriptCompleted"] is True


def test_every_node_accounted_for_in_directory_groups():
    result = _run()
    grouped = sum(len(ids) for ids in result["directoryGroups"].values())
    assert grouped == result["fileStats"]["totalFileNodes"] == 9


def test_directory_grouping_collapses_when_root_files_present():
    # Root-level files (tsconfig, README, Dockerfile) make the common prefix
    # empty, so everything under src/ groups as a single "src" bucket.
    result = _run()
    groups = result["directoryGroups"]
    assert len(groups["src"]) == 5
    assert "config:tsconfig.json" in groups["root"]
    assert groups[".github"] == ["pipeline:.github/workflows/ci.yml"]


def test_directory_grouping_uses_common_prefix():
    # With a shared src/ prefix the buckets resolve to routes/services/utils.
    result = _run_src()
    groups = result["directoryGroups"]
    assert result["commonPathPrefix"] == "src"
    assert set(groups["routes"]) == {"file:src/routes/index.ts", "file:src/routes/auth.ts"}
    assert set(groups["services"]) == {"file:src/services/auth.ts", "file:src/services/user.ts"}
    assert groups["utils"] == ["file:src/utils/format.ts"]


def test_node_type_groups():
    result = _run()
    counts = result["fileStats"]["nodeTypeCounts"]
    assert counts == {"file": 5, "config": 1, "document": 1, "service": 1, "pipeline": 1}


def test_fan_in_out():
    result = _run()
    # format.ts is imported by three files, imports none
    assert result["fileFanIn"]["file:src/utils/format.ts"] == 3
    assert result["fileFanOut"]["file:src/utils/format.ts"] == 0
    assert result["fileFanOut"]["file:src/routes/index.ts"] == 2


def test_pattern_matches():
    result = _run_src()
    pm = result["patternMatches"]
    assert pm["routes"] == "api"
    assert pm["services"] == "service"
    assert pm["utils"] == "utility"


def test_ci_dir_pattern_matches_in_mixed_project():
    result = _run()
    assert result["patternMatches"][".github"] == "ci-cd"


def test_inter_group_and_direction():
    result = _run_src()
    pairs = {(d["from"], d["to"]): d["count"] for d in result["interGroupImports"]}
    assert pairs[("routes", "services")] == 2
    assert pairs[("routes", "utils")] == 1
    assert pairs[("services", "utils")] == 2
    direction = {(d["dependent"], d["dependsOn"]) for d in result["dependencyDirection"]}
    assert ("routes", "services") in direction
    assert ("services", "utils") in direction


def test_intra_group_density():
    result = _run_src()
    # utils has no internal edges
    assert result["intraGroupDensity"]["utils"]["internalEdges"] == 0
    assert result["intraGroupDensity"]["utils"]["totalEdges"] == 3


def test_cross_category_edges():
    result = _run()
    triples = {
        (d["fromType"], d["toType"], d["edgeType"]): d["count"]
        for d in result["crossCategoryEdges"]
    }
    assert triples[("config", "file", "configures")] == 1
    assert triples[("service", "file", "deploys")] == 1
    assert triples[("document", "file", "documents")] == 1


def test_deployment_topology():
    result = _run()
    topo = result["deploymentTopology"]
    assert topo["hasDockerfile"] is True
    assert topo["hasCI"] is True
    assert topo["hasK8s"] is False
    assert "Dockerfile" in topo["infraFiles"]


def test_doc_coverage():
    result = _run()
    cov = result["docCoverage"]
    assert cov["groupsWithDocs"] >= 1  # the root group has README.md
    assert cov["totalGroups"] == len(result["directoryGroups"])


def test_extra_signals_present():
    result = _run()
    assert result["commonPathPrefix"] == ""  # no single prefix (root files present)
    assert "graphMetrics" in result
    assert result["graphMetrics"]["fileCount"] == 9
    assert "interGroupMatrix" in result


# --- focused unit tests ---------------------------------------------------- #

def test_common_dir_prefix():
    assert common_dir_prefix(["src/a.ts", "src/b.ts", "src/c/d.ts"]) == ["src"]
    assert common_dir_prefix(["src/a.ts", "lib/b.ts"]) == []


def test_flat_project_groups_by_extension():
    nodes = [
        FileNode(id="a", filePath="main.py", name="main.py"),
        FileNode(id="b", filePath="util.py", name="util.py"),
        FileNode(id="c", filePath="test_main.py", name="test_main.py"),
        FileNode(id="d", filePath="README.md", name="README.md"),
    ]
    groups, prefix = group_by_directory(nodes)
    assert prefix == []
    assert "c" in groups["test"]
    assert set(groups["py"]) == {"a", "b"}
    assert groups["md"] == ["d"]


def test_classify_file_rules():
    assert classify_file(FileNode(id="x", filePath="a/b_test.go", name="b_test.go")) == "test"
    assert classify_file(FileNode(id="x", filePath="types/a.d.ts", name="a.d.ts")) == "types"
    assert classify_file(FileNode(id="x", filePath="cmd/app/main.go", name="main.go")) == "entry"
    assert classify_file(FileNode(id="x", filePath="main.go", name="main.go")) is None
    assert classify_file(FileNode(id="x", filePath="infra/main.tf", name="main.tf")) == "infrastructure"
    assert classify_file(FileNode(id="x", filePath="db/schema.sql", name="schema.sql")) == "data"
