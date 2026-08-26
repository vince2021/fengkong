from __future__ import annotations

import unittest
from uuid import uuid4

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
from backend.repository import (
    ConcurrentUpdateError,
    DecisionPipelineRepository,
    RuleDefinitionRepository,
    RuleSetDefinitionRepository,
    content_hash,
)
from tests.database_support import IsolatedTestDatabase


class TestRuleGovernance(unittest.TestCase):
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

    @staticmethod
    def _rule(code="SR-001"):
        return {
            "code": code,
            "name": "测试规则",
            "rule_type": "strong_rule",
            "category": "credit_risk",
            "enabled": True,
            "conditions_json": [{"expression": "a > 0", "label": "test"}],
            "condition_relation": "all",
            "actions_json": [{"type": "rating_override", "value": "D"}],
            "priority": 1,
        }

    def _publish_rule(self, code="SR-001"):
        return RuleDefinitionRepository(self.session).publish_rule(
            self._rule(code), "system", "系统"
        )

    def _publish_rule_set(self, code="RS-TEST", rule_codes=None):
        return RuleSetDefinitionRepository(self.session).publish_rule_set(
            {
                "code": code,
                "name": "测试规则集",
                "rule_codes": ["SR-001"] if rule_codes is None else rule_codes,
                "evaluation_strategy": "most_restrictive",
            },
            "system",
            "系统",
        )

    def test_first_publication_writes_change_and_hashed_audit(self):
        draft = self._rule()
        published = RuleDefinitionRepository(self.session).publish_rule(
            draft, "system", "系统"
        )
        change = self.session.scalars(
            select(ModelChangeRecord).where(ModelChangeRecord.entity_type == "rule")
        ).one()
        event = self.session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.aggregate_type == "rule_definition"
            )
        ).one()

        self.assertEqual((published.version, published.status), (1, "published"))
        self.assertTrue(published.is_active)
        self.assertEqual(change.validation_json["config_hash"], content_hash(draft))
        self.assertEqual(event.payload["config_hash"], content_hash(draft))
        self.assertTrue(event.event_hash)

    def test_version_increment_keeps_one_active_and_isolates_change_types(self):
        self._publish_rule()
        self._publish_rule()
        active = self.session.scalars(
            select(RuleDefinition).where(
                RuleDefinition.code == "SR-001",
                RuleDefinition.is_active.is_(True),
            )
        ).all()
        changes = self.session.scalars(
            select(ModelChangeRecord)
            .where(
                ModelChangeRecord.entity_type == "rule",
                ModelChangeRecord.template_key == "SR-001",
            )
            .order_by(ModelChangeRecord.candidate_version)
        ).all()

        self.assertEqual([(item.version, item.is_active) for item in active], [(2, True)])
        self.assertEqual([item.candidate_version for item in changes], ["1", "2"])

    def test_rule_set_and_pipeline_publish_with_active_dependencies(self):
        self._publish_rule()
        rule_set = self._publish_rule_set()
        pipeline = DecisionPipelineRepository(self.session).publish_pipeline(
            {
                "code": "PIPE-TEST",
                "name": "测试管线",
                "stages_json": [
                    {"stage_type": "scoring"},
                    {"stage_type": "strong_rules", "rule_set_code": "RS-TEST"},
                    {"stage_type": "admission"},
                ],
            },
            "system",
            "系统",
        )

        self.assertTrue(rule_set.is_active)
        self.assertTrue(pipeline.is_active)
        self.assertEqual(
            set(
                self.session.scalars(select(ModelChangeRecord.entity_type)).all()
            ),
            {"rule", "rule_set", "pipeline"},
        )

    def test_missing_dependencies_rejected_without_partial_writes(self):
        with self.assertRaisesRegex(ValueError, "MISSING-RULE"):
            self._publish_rule_set(rule_codes=["MISSING-RULE"])
        with self.assertRaisesRegex(ValueError, "MISSING-RS"):
            DecisionPipelineRepository(self.session).publish_pipeline(
                {
                    "code": "PIPE-BAD",
                    "name": "坏管线",
                    "stages_json": [
                        {"stage_type": "scoring"},
                        {
                            "stage_type": "strong_rules",
                            "rule_set_code": "MISSING-RS",
                        },
                    ],
                },
                "system",
                "系统",
            )

        self.assertEqual(self.session.query(RuleSetDefinition).count(), 0)
        self.assertEqual(self.session.query(DecisionPipelineDefinition).count(), 0)
        self.assertEqual(self.session.query(ModelChangeRecord).count(), 0)
        self.assertEqual(self.session.query(AuditEventRecord).count(), 0)

    def test_empty_duplicate_and_invalid_pipeline_references_rejected(self):
        self._publish_rule()
        for refs in ([], ["SR-001", "SR-001"], [""]):
            with self.assertRaises(ValueError):
                self._publish_rule_set(rule_codes=refs)

        repository = DecisionPipelineRepository(self.session)
        invalid_stages = (
            [],
            [{"stage_type": "admission"}],
            [{"stage_type": "scoring"}, {"stage_type": "unknown"}],
            [{"stage_type": "scoring", "rule_set_code": ""}],
        )
        for stages in invalid_stages:
            with self.assertRaises(ValueError):
                repository.publish_pipeline(
                    {"code": "PIPE-BAD", "name": "坏管线", "stages_json": stages},
                    "system",
                    "系统",
                )

        self._publish_rule_set()
        with self.assertRaisesRegex(ValueError, "重复引用"):
            repository.publish_pipeline(
                {
                    "code": "PIPE-DUP",
                    "name": "重复引用管线",
                    "stages_json": [
                        {"stage_type": "scoring"},
                        {"stage_type": "strong_rules", "rule_set_code": "RS-TEST"},
                        {"stage_type": "admission", "rule_set_code": "RS-TEST"},
                    ],
                },
                "system",
                "系统",
            )

    def test_direct_publish_skips_versions_reserved_by_governance_candidates(self):
        first = self._publish_rule()
        self.session.add(
            ModelChangeRecord(
                id=str(uuid4()),
                template_key="SR-001",
                base_version="1",
                candidate_version="2",
                status="draft",
                entity_type="rule",
                config_json={},
                validation_json={},
                impact_json={},
                change_reason="reserve version",
                created_by="other",
                created_by_name="其他人",
            )
        )
        self.session.commit()

        published = self._publish_rule()

        self.session.expire_all()
        self.assertFalse(self.session.get(RuleDefinition, first.id).is_active)
        self.assertEqual(published.version, 3)
        self.assertEqual(self.session.query(RuleDefinition).count(), 2)
        self.assertEqual(self.session.query(AuditEventRecord).count(), 2)

    def test_rule_model_indicator_and_pipeline_namespaces_are_independent(self):
        for entity_type in ("model", "indicator"):
            self.session.add(
                ModelChangeRecord(
                    id=str(uuid4()),
                    template_key="SHARED",
                    base_version="0",
                    candidate_version="1",
                    status="draft",
                    entity_type=entity_type,
                    config_json={},
                    validation_json={},
                    impact_json={},
                    change_reason="namespace fixture",
                    created_by="system",
                    created_by_name="系统",
                )
            )
        self.session.commit()
        self._publish_rule("SHARED")

        changes = self.session.scalars(
            select(ModelChangeRecord).where(ModelChangeRecord.template_key == "SHARED")
        ).all()
        self.assertEqual(
            {item.entity_type for item in changes}, {"model", "indicator", "rule"}
        )


if __name__ == "__main__":
    unittest.main()
