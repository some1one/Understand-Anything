"""Port of ``configs/graphql.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

graphql_config = LanguageConfig(
    id="graphql",
    displayName="GraphQL",
    extensions=[".graphql", ".gql"],
    concepts=["types", "queries", "mutations", "subscriptions", "resolvers", "directives", "fragments", "schema"],
    filePatterns={
        "entryPoints": ["schema.graphql"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
