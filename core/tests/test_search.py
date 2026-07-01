"""Port of search.test.ts."""

from __future__ import annotations

from understand_core.search import SearchEngine


def make_node(**overrides) -> dict:
    node = {
        "type": "file",
        "summary": "",
        "tags": [],
        "complexity": "simple",
    }
    node.update(overrides)
    return node


SAMPLE_NODES = [
    make_node(
        id="auth-ctrl",
        name="AuthenticationController",
        type="class",
        summary="Handles user login, logout, and session management",
        tags=["auth", "controller", "security"],
        languageNotes="Uses Express middleware pattern",
    ),
    make_node(
        id="db-pool",
        name="DatabasePool",
        type="class",
        summary="Manages PostgreSQL connection pooling",
        tags=["database", "connection"],
    ),
    make_node(
        id="user-model",
        name="UserModel",
        type="class",
        summary="ORM model for the users table",
        tags=["model", "database", "user"],
    ),
    make_node(
        id="config",
        name="config.ts",
        type="file",
        summary="Application configuration and environment variables",
        tags=["config", "env"],
    ),
    make_node(
        id="helpers",
        name="helpers.ts",
        type="function",
        summary="Utility helper functions for string manipulation",
        tags=["utils", "helpers"],
    ),
    make_node(
        id="auth-middleware",
        name="authMiddleware",
        type="function",
        summary="Express middleware that validates JWT tokens for authentication",
        tags=["auth", "middleware", "security"],
    ),
]


def test_returns_empty_results_for_empty_query():
    engine = SearchEngine(SAMPLE_NODES)
    assert engine.search("") == []
    assert engine.search("  ") == []


def test_finds_exact_name_match():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("AuthenticationController")
    assert len(results) > 0
    assert results[0].node_id == "auth-ctrl"


def test_finds_fuzzy_name_match():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("auth contrl")
    assert len(results) > 0
    assert any(r.node_id == "auth-ctrl" for r in results)


def test_searches_across_summary_field():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("PostgreSQL connection")
    assert len(results) > 0
    assert any(r.node_id == "db-pool" for r in results)


def test_searches_across_tags():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("security")
    assert len(results) > 0
    node_ids = [r.node_id for r in results]
    assert "auth-ctrl" in node_ids
    assert "auth-middleware" in node_ids


def test_ranks_name_matches_higher_than_summary_matches():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("UserModel")
    assert len(results) > 0
    assert results[0].node_id == "user-model"


def test_returns_scored_results_between_0_and_1():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("database")
    assert len(results) > 0
    for result in results:
        assert 0 <= result.score <= 1


def test_can_update_nodes_and_reindex():
    engine = SearchEngine(SAMPLE_NODES)
    before = engine.search("PaymentService")
    had_payment = any(r.node_id == "payment" for r in before)

    engine.update_nodes(
        [
            *SAMPLE_NODES,
            make_node(
                id="payment",
                name="PaymentService",
                type="class",
                summary="Handles payment processing",
                tags=["payment", "billing"],
            ),
        ]
    )

    after = engine.search("PaymentService")
    assert had_payment is False
    assert len(after) > 0
    assert after[0].node_id == "payment"


def test_filters_by_node_type():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("auth", types=["function"])
    assert len(results) > 0
    for result in results:
        node = next(n for n in SAMPLE_NODES if n["id"] == result.node_id)
        assert node["type"] == "function"
    assert any(r.node_id == "auth-middleware" for r in results)
    assert not any(r.node_id == "auth-ctrl" for r in results)


def test_respects_the_limit_option():
    engine = SearchEngine(SAMPLE_NODES)
    results = engine.search("auth", limit=1)
    assert len(results) == 1
