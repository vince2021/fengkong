from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

import backend.database as database
from backend.database import Base
from backend.db_models import (
    AuditEventRecord,
    DecisionPipelineDefinition,
    ModelChangeRecord,
    RuleDefinition,
    RuleSetDefinition,
)
from backend.dependencies import demo_repository
from backend.repository import (
    DecisionPipelineRepository,
    RuleDefinitionRepository,
    RuleSetDefinitionRepository,
)
from rating.scorecard import rate_counterparty
from tests.database_support import IsolatedTestDatabase


class TestDualTrackPipeline(unittest.TestCase):
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
        self.counterparty = demo_repository.list_counterparties()[0]
        self.config = demo_repository.get_template("general")

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
        ):
            self.session.query(model).delete()
        self.session.commit()

    def _publish_scoring_pipeline(self, code="PIPE-TEST"):
        return DecisionPipelineRepository(self.session).publish_pipeline(
            {
                "code": code,
                "name": "评分管线",
                "stages_json": [{"stage_type": "scoring"}],
            },
            "test",
            "测试",
        )

    def test_unbound_model_keeps_exact_v1_result_and_inputs(self):
        config = deepcopy(self.config)
        config.pop("decision_pipeline_code", None)
        counterparty_before = deepcopy(self.counterparty)
        config_before = deepcopy(config)

        result = rate_counterparty(self.counterparty, config)

        self.assertTrue(result["ok"])
        self.assertNotIn("decision_pipeline_trace", result)
        self.assertEqual(self.counterparty, counterparty_before)
        self.assertEqual(config, config_before)

    def test_missing_pipeline_falls_back_atomically_to_v1(self):
        baseline_config = deepcopy(self.config)
        baseline_config.pop("decision_pipeline_code", None)
        expected = rate_counterparty(self.counterparty, baseline_config)
        bound_config = deepcopy(baseline_config)
        bound_config["decision_pipeline_code"] = "MISSING"
        counterparty_before = deepcopy(self.counterparty)
        config_before = deepcopy(bound_config)

        result = rate_counterparty(self.counterparty, bound_config)

        self.assertEqual(result, expected)
        self.assertEqual(self.counterparty, counterparty_before)
        self.assertEqual(bound_config, config_before)

    def test_database_failure_falls_back_to_v1(self):
        baseline_config = deepcopy(self.config)
        baseline_config.pop("decision_pipeline_code", None)
        expected = rate_counterparty(self.counterparty, baseline_config)
        bound_config = deepcopy(baseline_config)
        bound_config["decision_pipeline_code"] = "PIPE-FAIL"

        with patch(
            "rating.decision_pipeline.run_decision_pipeline",
            side_effect=OperationalError("select", {}, Exception("offline")),
        ):
            result = rate_counterparty(self.counterparty, bound_config)

        self.assertEqual(result, expected)

    def test_active_pipeline_is_preferred_and_exposes_trace(self):
        self._publish_scoring_pipeline()
        config = deepcopy(self.config)
        config["decision_pipeline_code"] = "PIPE-TEST"
        counterparty_before = deepcopy(self.counterparty)
        config_before = deepcopy(config)

        result = rate_counterparty(self.counterparty, config)

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["decision_pipeline_trace"]["pipeline_code"], "PIPE-TEST"
        )
        self.assertEqual(
            [stage["stage_type"] for stage in result["decision_pipeline_trace"]["stages"]],
            ["scoring"],
        )
        self.assertEqual(self.counterparty, counterparty_before)
        self.assertEqual(config, config_before)

    def test_pipeline_rule_runs_once_and_is_adapted_for_legacy_consumers(self):
        rule = {
            "code": "CAP-ONCE",
            "name": "额度收紧一次",
            "rule_type": "strong_rule",
            "enabled": True,
            "conditions_json": [
                {"expression": "requested_limit > 0", "operator": "bool"}
            ],
            "condition_relation": "all",
            "actions_json": [
                {"type": "limit_multiplier_cap", "value": 0.5},
                {"type": "review_required", "value": True},
            ],
            "priority": 1,
        }
        RuleDefinitionRepository(self.session).publish_rule(
            rule, "test", "测试"
        )
        RuleSetDefinitionRepository(self.session).publish_rule_set(
            {
                "code": "RS-ONCE",
                "name": "单次规则集",
                "rule_codes": ["CAP-ONCE"],
                "evaluation_strategy": "most_restrictive",
            },
            "test",
            "测试",
        )
        DecisionPipelineRepository(self.session).publish_pipeline(
            {
                "code": "PIPE-ONCE",
                "name": "单次规则管线",
                "stages_json": [
                    {"stage_type": "scoring"},
                    {"stage_type": "strong_rules", "rule_set_code": "RS-ONCE"},
                    {"stage_type": "admission"},
                ],
            },
            "test",
            "测试",
        )
        base_config = deepcopy(self.config)
        base_config.pop("decision_pipeline_code", None)
        base_config["strong_rules"] = []
        base_config["risk_screening_policy"] = {
            "enabled": False,
            "aggregation": "most_restrictive",
            "rules": [],
        }
        base_result = rate_counterparty(self.counterparty, base_config)
        pipeline_config = deepcopy(base_config)
        pipeline_config["decision_pipeline_code"] = "PIPE-ONCE"
        pipeline_config["strong_rules"] = [
            {
                "id": "LEGACY-MUST-NOT-RUN",
                "name": "旧规则不得重复执行",
                "enabled": True,
                "condition_relation": "all",
                "conditions": [
                    {
                        "field": "requested_limit",
                        "operator": ">",
                        "value": 0,
                        "label": "申请额度大于零",
                    }
                ],
                "action": {"limit_multiplier_cap": 0.5},
            }
        ]

        result = rate_counterparty(self.counterparty, pipeline_config)

        self.assertEqual(
            result["suggested_limit"], int(base_result["suggested_limit"] * 0.5)
        )
        self.assertEqual(
            [hit["rule_id"] for hit in result["strong_rule_hits"]], ["CAP-ONCE"]
        )
        self.assertTrue(result["strong_rule_hits"][0]["action"]["review_required"])
        self.assertNotIn("LEGACY-MUST-NOT-RUN", str(result["decision_pipeline_trace"]))


if __name__ == "__main__":
    unittest.main()
