"""Port of ``__tests__/domain-normalize.test.ts``."""

from __future__ import annotations

from understand_core.analyzer.normalize_graph import normalize_node_id


class TestNormalizeNodeIdDomainTypes:
    def test_domain_node_ids(self):
        result = normalize_node_id(
            "domain:order-management",
            {"type": "domain", "name": "Order Management"},
        )
        assert result == "domain:order-management"

    def test_flow_node_ids(self):
        result = normalize_node_id(
            "flow:create-order", {"type": "flow", "name": "Create Order"}
        )
        assert result == "flow:create-order"

    def test_step_node_ids_with_filepath(self):
        result = normalize_node_id(
            "step:create-order:validate",
            {
                "type": "step",
                "name": "Validate",
                "filePath": "src/validators/order.ts",
            },
        )
        assert result == "step:create-order:src/validators/order.ts:validate"

    def test_step_node_ids_without_filepath(self):
        result = normalize_node_id(
            "step:validate", {"type": "step", "name": "Validate"}
        )
        assert result == "step:validate"

    def test_bare_step_name_with_filepath(self):
        result = normalize_node_id(
            "validate",
            {
                "type": "step",
                "name": "Validate",
                "filePath": "src/validators/order.ts",
            },
        )
        assert result == "step:src/validators/order.ts:validate"
