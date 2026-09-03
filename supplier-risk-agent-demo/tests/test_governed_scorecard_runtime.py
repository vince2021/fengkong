from __future__ import annotations

import unittest

import backend.database as database
from backend.database import Base
from backend.db_models import AuditEventRecord, ModelChangeRecord, ModelSnapshotRecord, ScorecardDefinition
from backend.repository import RatingRunRepository, content_hash
from backend.scorecard_repository import ScorecardRepository
from rating.governed_scorecard import rate_governed_scorecard
from tests.database_support import IsolatedTestDatabase
from tests.test_scorecard_center import scorecard


def model_config(binding: dict | None = None) -> dict:
    config = {
        "name": "绑定评分卡模型", "version": "v2", "scorecard_type": "default",
        "weights": {"external_risk": .25, "internal_performance": .25, "financial_credit": .25, "relationship_stability": .25},
        "thresholds": {}, "strong_rules": [],
        "strategy_mapping": [
            {"score_min": 0, "score_max": 49.99, "rating": "B", "risk_segment": "高风险", "access_strategy": "人工复核", "limit_multiplier": .3, "payment_term_days": 30, "monitoring_frequency": "月度"},
            {"score_min": 50, "score_max": 100, "rating": "A", "risk_segment": "低风险", "access_strategy": "正常准入", "limit_multiplier": 1, "payment_term_days": 90, "monitoring_frequency": "季度"},
        ],
    }
    if binding:
        config["scorecard_binding"] = binding
    return config


class TestGovernedScorecardRuntime(unittest.TestCase):
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
        for model in [AuditEventRecord, ScorecardDefinition, ModelSnapshotRecord, ModelChangeRecord]:
            self.session.query(model).delete()
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def _binding(self) -> dict:
        repository = ScorecardRepository(self.session)
        draft = repository.create_draft(scorecard(), "建立运行评分卡", "maker", "模型管理员")
        submitted = repository.submit(draft["id"], draft["row_version"], "maker", False)
        repository.review(submitted["id"], submitted["row_version"], "publish", "运行配置复核通过", "reviewer", "风控经理")
        return repository.binding_for_asset(repository.list_assets()[0]["id"])

    def test_numeric_bin_and_business_scale_are_traceable(self):
        binding = self._binding()
        counterparty = {"id": "cp-1", "name": "甲企业", "counterparty_type": "supplier", "requested_limit": 1_000_000, "enterprise_risk": {"shareholder_change": 0}}
        result = rate_governed_scorecard(counterparty, model_config(binding))
        self.assertTrue(result["ok"])
        self.assertEqual(result["total_score"], 100.0)
        self.assertEqual(result["scorecard_score"], 900.0)
        self.assertEqual(result["rating"], "A")
        self.assertEqual(result["scorecard_execution"]["details"][0]["bin_label"], "无变更")
        self.assertEqual(result["scorecard_execution"]["config_hash"], binding["config_hash"])

    def test_missing_value_uses_explicit_missing_bin(self):
        result = rate_governed_scorecard({"id": "cp-2", "name": "乙企业", "counterparty_type": "customer", "requested_limit": 500_000}, model_config(self._binding()))
        self.assertTrue(result["ok"])
        self.assertEqual(result["scorecard_execution"]["missing_count"], 1)
        self.assertEqual(result["scorecard_execution"]["details"][0]["bin_kind"], "missing")

    def test_tampered_embedded_config_is_rejected(self):
        binding = self._binding()
        binding["config"]["indicators"][0]["bins"][0]["score"] = 999
        result = rate_governed_scorecard({"id": "cp-3"}, model_config(binding))
        self.assertFalse(result["ok"])
        self.assertIn("哈希不一致", result["error"])

    def test_rating_snapshot_freezes_scorecard_binding(self):
        binding = self._binding()
        config = model_config(binding)
        counterparty = {"id": "cp-4", "name": "丙企业", "counterparty_type": "supplier", "requested_limit": 800_000, "enterprise_risk": {"shareholder_change": 2}}
        result = rate_governed_scorecard(counterparty, config)
        saved = RatingRunRepository(self.session).save_run(counterparty, "general", config, result, "测试员")
        snapshot = self.session.get(ModelSnapshotRecord, saved["model_snapshot_id"])
        self.assertEqual(snapshot.config_json["scorecard_binding"]["config_hash"], binding["config_hash"])
        self.assertEqual(snapshot.config_hash, content_hash(snapshot.config_json))


if __name__ == "__main__":
    unittest.main()
