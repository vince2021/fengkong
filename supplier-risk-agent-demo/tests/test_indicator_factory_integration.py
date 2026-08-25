from __future__ import annotations

import unittest
from uuid import uuid4

from sqlalchemy import select

import backend.database as database
from backend.database import Base
from backend.db_models import (
    AuditEventRecord,
    IndicatorDefinition,
    ModelChangeRecord,
)
from backend.repository import (
    IndicatorDefinitionRepository,
    ModelGovernanceRepository,
    content_hash,
)
from rating.enterprise_indicator_pool import evaluate_indicator_pool
from rating.risk_screening_policy import apply_risk_screening_policy
from rating.indicator_evaluator import evaluate_indicator_pool_v2
from scripts.seed_indicators import (
    dry_run_pool_json,
    seed_from_pool_json,
    seed_tech_health_placeholders,
)
from tests.database_support import IsolatedTestDatabase


class TestIndicatorGovernance(unittest.TestCase):
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
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()
        self.session.close()

    @staticmethod
    def _draft(code: str) -> dict:
        return {
            "code": code,
            "name": code,
            "category": "external_risk",
            "layer": "atomic",
            "data_type": "numeric",
            "field_path": f"enterprise_risk.{code}",
            "scoring_json": {"type": "boolean_hit", "missing_score": 2},
            "max_score": 3.0,
            "default_weight": 1.0,
        }

    def test_publish_activates_first_version(self):
        repository = IndicatorDefinitionRepository(self.session)

        published = repository.publish_indicator(
            self._draft("A"), actor="admin", actor_name="管理员"
        )

        self.assertEqual(published.version, 1)
        self.assertEqual(published.status, "published")
        self.assertTrue(published.is_active)

    def test_publish_increments_version_and_keeps_single_active(self):
        repository = IndicatorDefinitionRepository(self.session)
        repository.publish_indicator(
            self._draft("B"), actor="admin", actor_name="管理员"
        )
        repository.publish_indicator(
            self._draft("B"), actor="admin", actor_name="管理员"
        )

        versions = self.session.scalars(
            select(IndicatorDefinition)
            .where(IndicatorDefinition.code == "B")
            .order_by(IndicatorDefinition.version)
        ).all()

        self.assertEqual([item.version for item in versions], [1, 2])
        self.assertEqual([item.is_active for item in versions], [False, True])

    def test_publish_writes_indicator_change_and_hashed_audit_evidence(self):
        repository = IndicatorDefinitionRepository(self.session)
        draft = self._draft("C")

        published = repository.publish_indicator(
            draft, actor="admin", actor_name="管理员"
        )

        change = self.session.scalars(
            select(ModelChangeRecord).where(
                ModelChangeRecord.entity_type == "indicator"
            )
        ).one()
        event = self.session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.aggregate_type == "indicator_definition",
                AuditEventRecord.aggregate_id == published.id,
            )
        ).one()
        expected_hash = content_hash(draft)

        self.assertEqual(change.template_key, "C")
        self.assertEqual(change.status, "published")
        self.assertEqual(change.validation_json["config_hash"], expected_hash)
        self.assertEqual(event.payload["config_hash"], expected_hash)
        self.assertTrue(event.event_hash)

    def test_model_and_indicator_versions_use_separate_namespaces(self):
        model_change = ModelChangeRecord(
            id=str(uuid4()),
            template_key="SHARED",
            base_version="0",
            candidate_version="1",
            status="draft",
            entity_type="model",
            config_json={},
            validation_json={},
            impact_json={},
            change_reason="model draft",
            created_by="model-admin",
            created_by_name="模型管理员",
        )
        self.session.add(model_change)
        self.session.commit()

        IndicatorDefinitionRepository(self.session).publish_indicator(
            self._draft("SHARED"), actor="indicator-admin", actor_name="指标管理员"
        )

        changes = self.session.scalars(
            select(ModelChangeRecord).where(
                ModelChangeRecord.template_key == "SHARED",
                ModelChangeRecord.candidate_version == "1",
            )
        ).all()
        model_list = ModelGovernanceRepository(self.session).list_changes()

        self.assertEqual({item.entity_type for item in changes}, {"model", "indicator"})
        self.assertEqual([item["id"] for item in model_list], [model_change.id])


class TestDualTrackRiskScreening(unittest.TestCase):
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
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()
        self.session.close()

    @staticmethod
    def _config() -> dict:
        return {
            "scorecard_type": "default",
            "risk_screening_policy": {
                "enabled": False,
                "aggregation": "most_restrictive",
                "rules": [],
            },
        }

    @staticmethod
    def _base_result() -> dict:
        return {
            "ok": True,
            "rating": "BBB",
            "normalized_score": 80,
            "risk_segment": "中风险",
            "access_strategy": "正常准入",
            "suggested_limit": 1_000_000,
            "suggested_payment_term_days": 90,
            "monitoring_frequency": "季度",
            "review_required": False,
        }

    def test_empty_factory_falls_back_to_v1(self):
        result = apply_risk_screening_policy(
            {"id": "x"}, self._config(), self._base_result()
        )

        screening = result["enterprise_risk_screening"]
        self.assertNotEqual(screening["pool_version"], "indicator-factory-v2")
        self.assertGreater(screening["selected_count"], 0)
        self.assertEqual(result["risk_screening_policy"]["hits"], [])

    def test_published_active_indicator_uses_v2_in_policy_path(self):
        draft = TestIndicatorGovernance._draft("DUAL_TEST")
        draft["data_type"] = "boolean"
        draft["scoring_json"] = {
            "type": "boolean_hit",
            "bands": [
                {"operator": "==", "value": False, "score": 3},
                {"operator": "==", "value": True, "score": 2},
            ],
            "missing_score": 2,
        }
        IndicatorDefinitionRepository(self.session).publish_indicator(
            draft, actor="admin", actor_name="管理员"
        )

        result = apply_risk_screening_policy(
            {"id": "x", "enterprise_risk": {"DUAL_TEST": False}},
            self._config(),
            self._base_result(),
        )

        screening = result["enterprise_risk_screening"]
        self.assertEqual(screening["pool_version"], "indicator-factory-v2")
        self.assertEqual(screening["selected_count"], 1)
        self.assertEqual(screening["details"][0]["indicator_id"], "DUAL_TEST")
        self.assertEqual(screening["details"][0]["score"], 3.0)
        self.assertEqual(result["risk_screening_policy"]["metrics"]["normalized_score"], 100.0)


class TestSeedPoolJson(unittest.TestCase):
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
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()
        self.session.close()

    def test_dry_run_maps_all_rows_without_persisting(self):
        report = dry_run_pool_json()

        self.assertEqual(report["count"], 185)
        self.assertTrue(report["pool_version"])
        self.assertEqual(
            self.session.query(IndicatorDefinition)
            .filter_by(seed_source="pool_json")
            .count(),
            0,
        )
        sample = report["samples"][0]
        self.assertEqual(sample["layer"], "atomic")
        self.assertIn(".", sample["field_path"])
        self.assertIsNone(sample["expression"])

    def test_seed_publishes_every_pool_indicator_with_governance_evidence(self):
        count = seed_from_pool_json(
            self.session, actor="seeder", actor_name="灌入脚本"
        )

        active_count = (
            self.session.query(IndicatorDefinition)
            .filter_by(
                seed_source="pool_json",
                is_active=True,
                status="published",
            )
            .count()
        )
        change_count = (
            self.session.query(ModelChangeRecord)
            .filter_by(entity_type="indicator")
            .count()
        )
        audit_count = (
            self.session.query(AuditEventRecord)
            .filter_by(
                aggregate_type="indicator_definition",
                event_type="indicator_published",
            )
            .count()
        )

        self.assertEqual(count, 185)
        self.assertEqual(active_count, count)
        self.assertEqual(change_count, count)
        self.assertEqual(audit_count, count)

    def test_seed_is_idempotent_without_new_versions_or_evidence(self):
        first = seed_from_pool_json(self.session)
        first_changes = self.session.query(ModelChangeRecord).count()
        first_audits = self.session.query(AuditEventRecord).count()

        second = seed_from_pool_json(self.session)

        self.assertEqual(first, 185)
        self.assertEqual(second, first)
        self.assertEqual(
            self.session.query(IndicatorDefinition).count(),
            first,
        )
        self.assertEqual(self.session.query(ModelChangeRecord).count(), first_changes)
        self.assertEqual(self.session.query(AuditEventRecord).count(), first_audits)

    def test_seeded_composite_indicator_matches_v1_score(self):
        seed_from_pool_json(self.session)
        indicator_id = "eri_legal_key_person_joint_change_1y"
        config = {
            "indicator_selection": [
                {"indicator_id": indicator_id, "weight": 1, "enabled": True}
            ]
        }
        counterparty = {
            "external": {
                "legal_representative_change_count_1y": 1,
                "key_person_change_count_1y": 2,
            }
        }

        v1 = evaluate_indicator_pool(counterparty, config)
        v2 = evaluate_indicator_pool_v2(counterparty, config)

        assert v2 is not None
        self.assertEqual(v1["selected_count"], 1)
        self.assertEqual(v2["selected_count"], v1["selected_count"])
        self.assertEqual(v2["details"][0]["score"], v1["details"][0]["score"])
        self.assertEqual(v2["normalized_score"], v1["normalized_score"])


class TestSeedTechAndActivation(unittest.TestCase):
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
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(AuditEventRecord).delete()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).delete()
        self.session.commit()
        self.session.close()

    def test_tech_placeholders_are_inactive_drafts_and_idempotent(self):
        first = seed_tech_health_placeholders(self.session, actor="seeder")
        second = seed_tech_health_placeholders(self.session, actor="seeder")
        placeholders = (
            self.session.query(IndicatorDefinition)
            .filter_by(seed_source="tech_health")
            .all()
        )

        self.assertEqual(first, 32)
        self.assertEqual(second, first)
        self.assertEqual(len(placeholders), first)
        self.assertTrue(
            all(item.status == "draft" and not item.is_active for item in placeholders)
        )
        self.assertEqual(len({item.category for item in placeholders}), 6)
        self.assertEqual(self.session.query(ModelChangeRecord).count(), 0)
        self.assertEqual(self.session.query(AuditEventRecord).count(), 0)

    def test_pool_is_active_while_tech_drafts_stay_out_of_v2(self):
        pool_count = seed_from_pool_json(
            self.session, actor="seeder", actor_name="灌入脚本"
        )
        placeholder_count = seed_tech_health_placeholders(
            self.session, actor="seeder"
        )

        result = evaluate_indicator_pool_v2({"id": "x"}, {})

        self.assertEqual(pool_count, 185)
        self.assertEqual(placeholder_count, 32)
        self.assertEqual(self.session.query(IndicatorDefinition).count(), 217)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["selected_count"], pool_count)
        self.assertFalse(
            any(
                detail["indicator_id"].startswith("TECH_HEALTH_")
                for detail in result["details"]
            )
        )


if __name__ == "__main__":
    unittest.main()
