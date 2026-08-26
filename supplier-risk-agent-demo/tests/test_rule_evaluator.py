from __future__ import annotations

import unittest
from types import SimpleNamespace

from rating.rule_evaluator import (
    apply_rule_actions,
    evaluate_rule_conditions,
    evaluate_rule_set,
    flatten_context,
)


def _make_rule(
    code: str,
    conditions: list[dict],
    *,
    relation: str = "all",
    actions: list[dict] | None = None,
    enabled: bool = True,
    priority: int = 999,
) -> SimpleNamespace:
    return SimpleNamespace(
        code=code,
        name=code,
        enabled=enabled,
        conditions_json=conditions,
        condition_relation=relation,
        actions_json=actions or [{"type": "review_required", "value": True}],
        priority=priority,
    )


def _hit(rule: SimpleNamespace) -> dict:
    return {"rule": rule, "details": []}


class TestFlattenContext(unittest.TestCase):
    def test_flattens_nested_dict_and_preserves_primitives(self):
        flat = flatten_context(
            {
                "external": {"dishonesty_count": 5, "risk": {"score": 80}},
                "requested_limit": 1_000_000,
            }
        )

        self.assertEqual(flat["external_dishonesty_count"], 5)
        self.assertEqual(flat["external_risk_score"], 80)
        self.assertEqual(flat["requested_limit"], 1_000_000)

    def test_empty_dict(self):
        self.assertEqual(flatten_context({}), {})


class TestEvaluateRuleConditions(unittest.TestCase):
    def test_boolean_expression_matches(self):
        rule = _make_rule(
            "R1",
            [{"expression": "external_dishonesty_count > 0", "label": "hit"}],
        )

        triggered, details = evaluate_rule_conditions(
            rule, {"external": {"dishonesty_count": 3}}
        )

        self.assertTrue(triggered)
        self.assertTrue(details[0]["matched"])
        self.assertIs(details[0]["actual_value"], True)

    def test_scalar_expression_uses_operator_and_threshold(self):
        rule = _make_rule(
            "R1",
            [{"expression": "requested_limit", "operator": ">", "value": 500_000}],
        )

        triggered, details = evaluate_rule_conditions(
            rule, {"requested_limit": 1_000_000}
        )

        self.assertTrue(triggered)
        self.assertEqual(details[0]["actual_value"], 1_000_000)

    def test_all_and_any_relations(self):
        conditions = [
            {"expression": "a > 0"},
            {"expression": "b > 0"},
        ]

        all_hit, _ = evaluate_rule_conditions(
            _make_rule("ALL", conditions, relation="all"), {"a": 1, "b": 0}
        )
        any_hit, _ = evaluate_rule_conditions(
            _make_rule("ANY", conditions, relation="any"), {"a": 1, "b": 0}
        )

        self.assertFalse(all_hit)
        self.assertTrue(any_hit)

    def test_contains_supports_safe_container_literals(self):
        rule = _make_rule(
            "R1",
            [
                {
                    "expression": 'contains(["存续", "在业"], registration_status)',
                    "label": "normal status",
                }
            ],
        )

        triggered, _ = evaluate_rule_conditions(rule, {"registration_status": "存续"})

        self.assertTrue(triggered)

    def test_missing_or_unsafe_expression_degrades_to_no_match(self):
        rules = [
            _make_rule("MISSING", [{"expression": "missing_field > 0"}]),
            _make_rule("UNSAFE", [{"expression": '__import__("os")'}]),
        ]

        for rule in rules:
            with self.subTest(rule=rule.code):
                triggered, details = evaluate_rule_conditions(rule, {})
                self.assertFalse(triggered)
                self.assertFalse(details[0]["matched"])
                self.assertIsNone(details[0]["actual_value"])

    def test_empty_conditions_and_unknown_relation_do_not_trigger(self):
        empty_hit, empty_details = evaluate_rule_conditions(_make_rule("EMPTY", []), {})
        invalid_hit, _ = evaluate_rule_conditions(
            _make_rule("INVALID", [{"expression": "a > 0"}], relation="xor"),
            {"a": 1},
        )

        self.assertFalse(empty_hit)
        self.assertEqual(empty_details, [])
        self.assertFalse(invalid_hit)


class TestEvaluateRuleSet(unittest.TestCase):
    def test_only_referenced_rules_are_evaluated(self):
        included = _make_rule("INCLUDED", [{"expression": "a > 0"}])
        excluded = _make_rule("EXCLUDED", [{"expression": "a > 0"}])
        rule_set = SimpleNamespace(
            rule_codes=["INCLUDED"], evaluation_strategy="all_hits"
        )

        triggered = evaluate_rule_set(rule_set, [excluded, included], {"a": 1})

        self.assertEqual([item["rule"].code for item in triggered], ["INCLUDED"])

    def test_disabled_rules_are_skipped_and_priority_is_deterministic(self):
        rules = [
            _make_rule("LOW", [{"expression": "a > 0"}], priority=100),
            _make_rule("DISABLED", [{"expression": "a > 0"}], enabled=False),
            _make_rule("HIGH", [{"expression": "a > 0"}], priority=1),
        ]
        rule_set = SimpleNamespace(
            rule_codes=["LOW", "DISABLED", "HIGH"],
            evaluation_strategy="all_hits",
        )

        triggered = evaluate_rule_set(rule_set, rules, {"a": 1})

        self.assertEqual(
            [item["rule"].code for item in triggered], ["HIGH", "LOW"]
        )

    def test_first_hit_returns_highest_priority_match(self):
        rules = [
            _make_rule("LOW", [{"expression": "a > 0"}], priority=100),
            _make_rule("HIGH", [{"expression": "a > 0"}], priority=1),
        ]
        rule_set = SimpleNamespace(
            rule_codes=["LOW", "HIGH"], evaluation_strategy="first_hit"
        )

        triggered = evaluate_rule_set(rule_set, rules, {"a": 1})

        self.assertEqual([item["rule"].code for item in triggered], ["HIGH"])

    def test_unknown_strategy_fails_closed(self):
        rule_set = SimpleNamespace(
            rule_codes=["R1"], evaluation_strategy="unsupported"
        )

        self.assertEqual(
            evaluate_rule_set(
                rule_set, [_make_rule("R1", [{"expression": "a > 0"}])], {"a": 1}
            ),
            [],
        )


class TestApplyRuleActions(unittest.TestCase):
    def test_rating_override_uses_full_platform_rating_order(self):
        triggered = [
            _hit(
                _make_rule(
                    "R1",
                    [],
                    actions=[{"type": "rating_override", "value": "BBB"}],
                )
            ),
            _hit(
                _make_rule(
                    "R2",
                    [],
                    actions=[{"type": "rating_override", "value": "AA"}],
                )
            ),
        ]

        result = apply_rule_actions(triggered, {"current_result": {"rating": "AAA"}})

        self.assertEqual(result["rating"], "BBB")

    def test_access_and_risk_segment_cannot_be_relaxed(self):
        triggered = [
            _hit(
                _make_rule(
                    "R1",
                    [],
                    actions=[
                        {"type": "access_strategy", "value": "禁入"},
                        {"type": "risk_segment_override", "value": "禁入客商"},
                    ],
                )
            ),
            _hit(
                _make_rule(
                    "R2",
                    [],
                    actions=[
                        {"type": "access_strategy", "value": "自动准入"},
                        {"type": "risk_segment_override", "value": "核心客商"},
                    ],
                )
            ),
        ]
        base = {"access_strategy": "准入", "risk_segment": "普通客商"}

        result = apply_rule_actions(triggered, {"current_result": base})

        self.assertEqual(result["access_strategy"], "禁入")
        self.assertEqual(result["risk_segment"], "禁入客商")

    def test_multiple_limit_caps_use_tightest_cap_without_compounding(self):
        triggered = [
            _hit(
                _make_rule(
                    "R1",
                    [],
                    actions=[{"type": "limit_multiplier_cap", "value": 0.3}],
                )
            ),
            _hit(
                _make_rule(
                    "R2",
                    [],
                    actions=[{"type": "limit_multiplier_cap", "value": 0.8}],
                )
            ),
        ]

        result = apply_rule_actions(
            triggered, {"current_result": {"suggested_limit": 1_000_000}}
        )

        self.assertEqual(result["suggested_limit"], 300_000)

    def test_payment_term_cap_uses_platform_result_key(self):
        triggered = [
            _hit(
                _make_rule(
                    "R1",
                    [],
                    actions=[{"type": "payment_term_days_cap", "value": 30}],
                )
            )
        ]

        result = apply_rule_actions(
            triggered,
            {"current_result": {"suggested_payment_term_days": 60}},
        )

        self.assertEqual(result["suggested_payment_term_days"], 30)

    def test_review_required_is_sticky(self):
        triggered = [
            _hit(
                _make_rule(
                    "R1",
                    [],
                    actions=[{"type": "review_required", "value": True}],
                )
            ),
            _hit(
                _make_rule(
                    "R2",
                    [],
                    actions=[{"type": "review_required", "value": False}],
                )
            ),
        ]

        result = apply_rule_actions(
            triggered, {"current_result": {"review_required": False}}
        )

        self.assertTrue(result["review_required"])

    def test_positive_score_adjustment_cannot_relax_result(self):
        triggered = [
            _hit(
                _make_rule(
                    "R1",
                    [],
                    actions=[{"type": "score_adjustment", "value": -10}],
                )
            ),
            _hit(
                _make_rule(
                    "R2",
                    [],
                    actions=[{"type": "score_adjustment", "value": 20}],
                )
            ),
        ]

        result = apply_rule_actions(
            triggered, {"current_result": {"total_score": 80}}
        )

        self.assertEqual(result["total_score"], 70)

    def test_input_result_is_not_mutated(self):
        base = {"review_required": False, "suggested_limit": 1_000_000}
        triggered = [
            _hit(
                _make_rule(
                    "R1",
                    [],
                    actions=[{"type": "review_required", "value": True}],
                )
            )
        ]

        apply_rule_actions(triggered, {"current_result": base})

        self.assertEqual(
            base, {"review_required": False, "suggested_limit": 1_000_000}
        )


if __name__ == "__main__":
    unittest.main()
