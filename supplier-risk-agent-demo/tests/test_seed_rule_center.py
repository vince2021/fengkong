from __future__ import annotations

import unittest

from sqlalchemy import select

import backend.database as database
from backend.database import Base
from backend.db_models import (
    AuditEventRecord,
    DecisionPipelineDefinition,
    IndicatorDefinition,
    ModelChangeRecord,
    RuleDefinition,
    RuleSetDefinition,
)
from backend.dependencies import demo_repository
from rating.decision_pipeline import run_decision_pipeline
from rating.rule_evaluator import evaluate_rule_conditions
from scripts.seed_indicators import seed_from_pool_json
from scripts.seed_rule_center import build_seed_plan, dry_run, seed_all
from tests.database_support import IsolatedTestDatabase


class TestSeedRuleCenter(unittest.TestCase):
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

    def _clear(self):
        for model in (
            AuditEventRecord,
            ModelChangeRecord,
            DecisionPipelineDefinition,
            RuleSetDefinition,
            RuleDefinition,
            IndicatorDefinition,
        ):
            self.session.query(model).delete()
        self.session.commit()

    def test_dry_run_validates_plan_without_writes(self):
        summary = seed_all(dry_run=True)

        self.assertEqual(summary["rules"], 14)
        self.assertEqual(summary["rule_sets"], 4)
        self.assertEqual(summary["pipelines"], 3)
        self.assertEqual(self.session.query(RuleDefinition).count(), 0)
        self.assertEqual(self.session.query(ModelChangeRecord).count(), 0)
        self.assertEqual(dry_run(), summary)

    def test_seed_publishes_governed_definitions_in_dependency_order(self):
        counts = seed_all(session=self.session)

        self.assertEqual(counts, {"rules": 14, "rule_sets": 4, "pipelines": 3})
        self.assertEqual(self.session.query(RuleDefinition).count(), 14)
        self.assertEqual(self.session.query(RuleSetDefinition).count(), 4)
        self.assertEqual(self.session.query(DecisionPipelineDefinition).count(), 3)
        self.assertEqual(self.session.query(ModelChangeRecord).count(), 21)
        self.assertEqual(self.session.query(AuditEventRecord).count(), 21)
        self.assertEqual(
            set(self.session.scalars(select(ModelChangeRecord.entity_type)).all()),
            {"rule", "rule_set", "pipeline"},
        )

    def test_seed_is_idempotent_without_creating_new_versions(self):
        seed_all(session=self.session)
        second = seed_all(session=self.session)

        self.assertEqual(second, {"rules": 0, "rule_sets": 0, "pipelines": 0})
        self.assertEqual(
            set(self.session.scalars(select(RuleDefinition.version)).all()), {1}
        )
        self.assertEqual(self.session.query(ModelChangeRecord).count(), 21)

    def test_shared_legacy_rules_are_deduplicated_but_sets_remain_isolated(self):
        plan = build_seed_plan()
        rules_by_code = {item["code"]: item for item in plan["rules"]}
        sets_by_code = {item["code"]: item for item in plan["rule_sets"]}

        self.assertEqual(len([code for code in rules_by_code if code.startswith("SR-")]), 4)
        self.assertEqual(
            sets_by_code["STRONG-RULES-GENERAL"]["rule_codes"],
            sets_by_code["STRONG-RULES-TECH"]["rule_codes"],
        )
        self.assertEqual(
            sets_by_code["STRONG-RULES-CORPORATE"]["rule_codes"],
            ["CR-001", "CR-002", "CR-101", "CR-102", "CR-103", "CR-201"],
        )

    def test_converted_membership_and_threshold_conditions_execute(self):
        seed_all(session=self.session)
        status_rule = self.session.scalars(
            select(RuleDefinition).where(RuleDefinition.code == "SR-001")
        ).one()
        threshold_rule = self.session.scalars(
            select(RuleDefinition).where(RuleDefinition.code == "SR-002")
        ).one()

        status_hit, _ = evaluate_rule_conditions(
            status_rule, {"external": {"registration_status": "注销"}}
        )
        threshold_hit, _ = evaluate_rule_conditions(
            threshold_rule, {"external": {"dishonesty_count": 1}}
        )

        self.assertTrue(status_hit)
        self.assertTrue(threshold_hit)
        self.assertIn("not contains", status_rule.conditions_json[0]["expression"])

    def test_seeded_pipeline_executes_after_indicator_dependencies_are_seeded(self):
        seed_all(session=self.session)
        seed_from_pool_json(self.session)
        context = {
            "counterparty": demo_repository.list_counterparties()[0],
            "config": demo_repository.get_template("general"),
        }

        result = run_decision_pipeline("PIPELINE-GENERAL", context)

        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertEqual(context["pipeline_trace"]["pipeline_code"], "PIPELINE-GENERAL")
        self.assertIn(
            "critical_indicator_count", context["indicator_screening"]
        )


if __name__ == "__main__":
    unittest.main()
