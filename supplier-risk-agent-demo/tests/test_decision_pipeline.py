from __future__ import annotations

import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import backend.database as database
from backend.database import Base
from backend.db_models import (
    DecisionPipelineDefinition,
    IndicatorDefinition,
    RuleDefinition,
    RuleSetDefinition,
)
from rating.decision_pipeline import (
    load_active_pipeline,
    load_active_rule_set,
    load_rule_set_rules,
    run_decision_pipeline,
)
from rating.template_resolver import resolve_template
from tests.database_support import IsolatedTestDatabase


BASE_DIR = Path(__file__).resolve().parents[1]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pipeline(
    code: str,
    stages: list[dict],
    *,
    status: str = "published",
    active: bool = True,
) -> DecisionPipelineDefinition:
    return DecisionPipelineDefinition(
        id=f"pipeline-{code}-{status}",
        code=code,
        name=code,
        stages_json=stages,
        version=1,
        status=status,
        is_active=active,
        row_version=1,
        created_at=_now(),
    )


def _rule_set(
    code: str,
    rule_codes: list[str],
    *,
    status: str = "published",
    active: bool = True,
) -> RuleSetDefinition:
    return RuleSetDefinition(
        id=f"rule-set-{code}-{status}",
        code=code,
        name=code,
        rule_codes=rule_codes,
        evaluation_strategy="most_restrictive",
        version=1,
        status=status,
        is_active=active,
        row_version=1,
        created_at=_now(),
    )


def _rule(
    code: str,
    expression: str,
    actions: list[dict],
    *,
    status: str = "published",
    active: bool = True,
) -> RuleDefinition:
    return RuleDefinition(
        id=f"rule-{code}-{status}",
        code=code,
        name=code,
        rule_type="strong_rule",
        enabled=True,
        conditions_json=[{"expression": expression, "label": code}],
        condition_relation="all",
        actions_json=actions,
        priority=10,
        version=1,
        status=status,
        is_active=active,
        row_version=1,
        created_at=_now(),
    )


def _fixtures() -> tuple[dict, dict]:
    templates = json.loads(
        (BASE_DIR / "data" / "model_templates.json").read_text(encoding="utf-8")
    )["templates"]
    counterparties = json.loads(
        (BASE_DIR / "data" / "counterparties.json").read_text(encoding="utf-8")
    )
    return deepcopy(counterparties[0]), resolve_template("general", templates)


class DecisionPipelineDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = database.SessionLocal()
        self._clear()

    def tearDown(self):
        self._clear()
        self.session.close()

    def _clear(self) -> None:
        for model in (
            DecisionPipelineDefinition,
            RuleSetDefinition,
            RuleDefinition,
            IndicatorDefinition,
        ):
            self.session.query(model).delete()
        self.session.commit()

    def test_loaders_only_return_published_active_definitions(self):
        self.session.add_all(
            [
                _pipeline("ACTIVE", [{"stage_type": "scoring"}]),
                _pipeline("DRAFT", [{"stage_type": "scoring"}], status="draft"),
                _rule_set("ACTIVE-RS", ["R1"]),
                _rule_set("DRAFT-RS", ["R2"], status="draft"),
                _rule("R1", "a > 0", []),
                _rule("R2", "a > 0", [], status="draft"),
            ]
        )
        self.session.commit()

        self.assertEqual(load_active_pipeline("ACTIVE").code, "ACTIVE")
        self.assertIsNone(load_active_pipeline("DRAFT"))
        self.assertEqual(load_active_rule_set("ACTIVE-RS").code, "ACTIVE-RS")
        self.assertIsNone(load_active_rule_set("DRAFT-RS"))
        self.assertEqual(
            [rule.code for rule in load_rule_set_rules(["R2", "R1"])],
            ["R1"],
        )

    def test_missing_pipeline_returns_none_without_mutating_context(self):
        context = {"counterparty": {"id": "x"}, "config": {"version": "1"}}
        before = deepcopy(context)

        result = run_decision_pipeline("MISSING", context)

        self.assertIsNone(result)
        self.assertEqual(context, before)

    def test_missing_rule_set_or_rule_definition_falls_back_atomically(self):
        counterparty, config = _fixtures()
        pipeline = _pipeline(
            "INCOMPLETE",
            [
                {"stage_type": "scoring"},
                {"stage_type": "strong_rules", "rule_set_code": "MISSING-RS"},
            ],
        )
        self.session.add(pipeline)
        self.session.commit()
        context = {"counterparty": counterparty, "config": config}
        before = deepcopy(context)

        self.assertIsNone(run_decision_pipeline("INCOMPLETE", context))
        self.assertEqual(context, before)

        self.session.add(_rule_set("MISSING-RS", ["MISSING-RULE"]))
        self.session.commit()
        self.assertIsNone(run_decision_pipeline("INCOMPLETE", context))
        self.assertEqual(context, before)

    def test_unknown_stage_falls_back_without_partial_trace(self):
        counterparty, config = _fixtures()
        self.session.add(
            _pipeline(
                "UNKNOWN-STAGE",
                [
                    {"stage_type": "scoring"},
                    {"stage_type": "external_http_call"},
                ],
            )
        )
        self.session.commit()
        context = {"counterparty": counterparty, "config": config}

        self.assertIsNone(run_decision_pipeline("UNKNOWN-STAGE", context))
        self.assertNotIn("pipeline_trace", context)

    def test_scoring_rule_and_admission_stages_produce_auditable_trace(self):
        counterparty, config = _fixtures()
        counterparty["external"]["dishonesty_count"] = 1
        config["strong_rules"] = [
            {
                "id": "LEGACY-MUST-NOT-RUN",
                "name": "legacy",
                "conditions": [],
                "action": {"rating_override": "D"},
            }
        ]
        self.session.add_all(
            [
                _rule(
                    "DENY-DISHONEST",
                    "external_dishonesty_count > 0",
                    [
                        {"type": "rating_override", "value": "D"},
                        {"type": "access_strategy", "value": "禁入"},
                        {"type": "limit_multiplier_cap", "value": 0},
                        {"type": "review_required", "value": True},
                    ],
                ),
                _rule_set("STRONG-RS", ["DENY-DISHONEST"]),
                _pipeline(
                    "FULL",
                    [
                        {"stage_type": "scoring"},
                        {
                            "stage_type": "strong_rules",
                            "rule_set_code": "STRONG-RS",
                        },
                        {"stage_type": "strategy_mapping"},
                        {"stage_type": "admission"},
                    ],
                ),
            ]
        )
        self.session.commit()
        context = {"counterparty": counterparty, "config": config}

        result = run_decision_pipeline("FULL", context)

        self.assertIsNotNone(result)
        self.assertEqual(result["rating"], "D")
        self.assertEqual(result["access_strategy"], "禁入")
        self.assertEqual(result["suggested_limit"], 0)
        self.assertEqual(result["final_admission"], "reject")
        self.assertEqual(
            [stage["stage_type"] for stage in context["pipeline_trace"]["stages"]],
            ["scoring", "strong_rules", "strategy_mapping", "admission"],
        )
        strong_stage = context["stage_strong_rules"]
        self.assertEqual(strong_stage["triggered_rules"][0]["code"], "DENY-DISHONEST")
        self.assertNotIn("LEGACY-MUST-NOT-RUN", str(context["pipeline_trace"]))

    def test_unmatched_rule_keeps_baseline_and_approves(self):
        counterparty, config = _fixtures()
        counterparty["external"]["dishonesty_count"] = 0
        self.session.add_all(
            [
                _rule(
                    "DENY-DISHONEST",
                    "external_dishonesty_count > 0",
                    [{"type": "access_strategy", "value": "禁入"}],
                ),
                _rule_set("STRONG-RS", ["DENY-DISHONEST"]),
                _pipeline(
                    "APPROVE",
                    [
                        {"stage_type": "scoring"},
                        {
                            "stage_type": "strong_rules",
                            "rule_set_code": "STRONG-RS",
                        },
                        {"stage_type": "admission"},
                    ],
                ),
            ]
        )
        self.session.commit()

        result = run_decision_pipeline(
            "APPROVE", {"counterparty": counterparty, "config": config}
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["final_admission"], "approve")

    def test_risk_screening_without_active_indicator_falls_back(self):
        counterparty, config = _fixtures()
        self.session.add_all(
            [
                _rule(
                    "DATA-GAP",
                    "indicator_screening_completeness < 0.75",
                    [{"type": "review_required", "value": True}],
                ),
                _rule_set("RISK-RS", ["DATA-GAP"]),
                _pipeline(
                    "RISK",
                    [
                        {"stage_type": "scoring"},
                        {
                            "stage_type": "risk_screening",
                            "rule_set_code": "RISK-RS",
                        },
                    ],
                ),
            ]
        )
        self.session.commit()

        result = run_decision_pipeline(
            "RISK", {"counterparty": counterparty, "config": config}
        )

        self.assertIsNone(result)

    def test_risk_screening_metrics_feed_rule_conditions_and_trace(self):
        counterparty, config = _fixtures()
        config["indicator_selection"] = [
            {"indicator_id": "MISSING-SIGNAL", "weight": 1, "enabled": True}
        ]
        self.session.add_all(
            [
                IndicatorDefinition(
                    id="indicator-missing-signal",
                    code="MISSING-SIGNAL",
                    name="Missing signal",
                    category="external_risk",
                    layer="atomic",
                    data_type="numeric",
                    field_path="enterprise_risk.missing_signal",
                    scoring_json={
                        "type": "numeric_bands",
                        "bands": [{"operator": ">=", "value": 0, "score": 3}],
                        "missing_score": 2,
                    },
                    max_score=3,
                    default_weight=1,
                    version=1,
                    status="published",
                    is_active=True,
                    row_version=1,
                    created_at=_now(),
                ),
                _rule(
                    "DATA-GAP",
                    "indicator_screening_completeness < 0.75",
                    [{"type": "review_required", "value": True}],
                ),
                _rule_set("RISK-RS", ["DATA-GAP"]),
                _pipeline(
                    "RISK-ACTIVE",
                    [
                        {"stage_type": "scoring"},
                        {
                            "stage_type": "risk_screening",
                            "rule_set_code": "RISK-RS",
                        },
                    ],
                ),
            ]
        )
        self.session.commit()
        context = {"counterparty": counterparty, "config": config}

        result = run_decision_pipeline("RISK-ACTIVE", context)

        self.assertIsNotNone(result)
        self.assertTrue(result["review_required"])
        risk_stage = context["stage_risk_screening"]
        self.assertEqual(risk_stage["screening"]["pool_version"], "indicator-factory-v2")
        self.assertEqual(risk_stage["screening"]["completeness"], 0.0)
        self.assertEqual(risk_stage["triggered_rules"][0]["code"], "DATA-GAP")


if __name__ == "__main__":
    unittest.main()
