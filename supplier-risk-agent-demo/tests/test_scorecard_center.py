from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.database import Base
from backend.db_models import AuditEventRecord, DecisionPipelineDefinition, ModelChangeRecord, ModelReleaseRecord, ModelSnapshotRecord, RuleCenterReleasePackage, RuleCenterReleasePackageMember, RuleDefinition, RuleSetDefinition, ScorecardDefinition
from backend.repository import content_hash
from backend.scorecard_repository import ScorecardRepository
from backend.scorecard_validation import validate_scorecard
from backend.main import app
from tests.database_support import IsolatedTestDatabase
import backend.database as database


def scorecard(code: str = "SME_SCORE") -> dict:
    return {
        "code": code,
        "name": "小微企业评分卡",
        "description": "用于验证评分卡配置治理闭环",
        "score_scale": {"min": 300, "max": 900, "higher_is_better": True},
        "indicators": [{
            "indicator_code": "shareholder_change", "indicator_version": "indicator-pool-v1",
            "indicator_name": "股东变更", "field_path": "enterprise_risk.shareholder_change", "data_type": "numeric", "weight": 100,
            "bins": [
                {"kind": "range", "label": "无变更", "lower": None, "upper": 1, "lower_inclusive": True, "upper_inclusive": False, "score": 80, "woe": 0.4},
                {"kind": "range", "label": "有变更", "lower": 1, "upper": None, "lower_inclusive": True, "upper_inclusive": False, "score": 20, "woe": -0.7},
                {"kind": "missing", "label": "缺失", "score": 10, "woe": None},
            ],
        }],
    }


class TestScorecardCenter(unittest.TestCase):
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
        for model in [RuleCenterReleasePackageMember, RuleCenterReleasePackage, AuditEventRecord, ScorecardDefinition, ModelReleaseRecord, ModelSnapshotRecord, DecisionPipelineDefinition, RuleSetDefinition, RuleDefinition, ModelChangeRecord]:
            self.session.query(model).delete()
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def test_rejects_overlapping_numeric_bins(self):
        definition = scorecard()
        definition["indicators"][0]["bins"][1]["lower"] = 0.5
        result = validate_scorecard(definition)
        self.assertFalse(result["valid"])
        self.assertTrue(any("重叠" in error for error in result["errors"]))

    def test_draft_captures_fixed_indicator_versions_and_model_impact(self):
        self.session.add(ModelSnapshotRecord(id="snapshot-1", template_key="general", model_name="通用模型", model_version="v1", config_json={"indicator_selection": [{"indicator_id": "shareholder_change", "weight": 1, "enabled": True}]}, config_hash="hash"))
        self.session.commit()
        draft = ScorecardRepository(self.session).create_draft(scorecard(), "建立首版评分卡", "maker", "模型管理员")
        self.assertEqual(draft["definition"]["indicators"][0]["indicator_version"], "indicator-pool-v1")
        self.assertEqual(draft["impact"]["affected_models"], ["general"])
        self.assertTrue(draft["validation"]["valid"])

    def test_four_eye_publish_and_single_active_version(self):
        repository = ScorecardRepository(self.session)
        draft = repository.create_draft(scorecard(), "建立首版评分卡", "maker", "模型管理员")
        submitted = repository.submit(draft["id"], draft["row_version"], "maker", False)
        with self.assertRaises(PermissionError):
            repository.review(submitted["id"], submitted["row_version"], "publish", "同意发布评分卡", "maker", "模型管理员")
        published = repository.review(submitted["id"], submitted["row_version"], "publish", "独立复核通过", "reviewer", "风控经理")
        self.assertEqual(published["status"], "published")
        assets = repository.list_assets()
        self.assertEqual(len(assets), 1)
        self.assertTrue(assets[0]["is_active"])
        self.assertTrue(assets[0]["config_hash"])

        second = repository.create_draft(scorecard(), "调整评分卡区间分值", "maker", "模型管理员")
        second = repository.submit(second["id"], second["row_version"], "maker", False)
        repository.review(second["id"], second["row_version"], "publish", "复核第二版通过", "reviewer", "风控经理")
        assets = repository.list_assets()
        self.assertEqual(sum(asset["is_active"] for asset in assets), 1)
        self.assertEqual([asset["version"] for asset in assets], [2, 1])

    def test_dependency_graph_traces_models_rules_and_release_packages(self):
        pipeline_change = ModelChangeRecord(
            id="pipeline-change", template_key="PIPE-SME", base_version="1", candidate_version="2",
            status="package_draft", entity_type="pipeline",
            config_json={"code": "PIPE-SME", "name": "小微管线候选", "stages_json": [{"stage_type": "scoring"}, {"stage_type": "strong_rules", "rule_set_code": "SET-SME"}]},
            validation_json={"valid": True}, impact_json={}, comparison_evidence_json={},
            change_reason="更新小微规则链", created_by="maker", created_by_name="模型管理员",
        )
        package = RuleCenterReleasePackage(
            id="package-1", name="小微规则发布包", change_reason="同步更新关联规则链",
            status="draft", config_hash="package-hash", dependency_snapshot_json={}, impact_json={},
            created_by="maker", created_by_name="模型管理员",
        )
        self.session.add_all([
            RuleDefinition(id="rule-1", code="RULE-SME", name="小微准入规则", rule_type="strong_rule", conditions_json=[], actions_json=[], version=1, status="published", is_active=True),
            RuleSetDefinition(id="set-1", code="SET-SME", name="小微规则集", rule_codes=["RULE-SME"], version=1, status="published", is_active=True),
            DecisionPipelineDefinition(id="pipeline-1", code="PIPE-SME", name="小微决策管线", stages_json=[{"stage_type": "scoring"}, {"stage_type": "strong_rules", "rule_set_code": "SET-SME"}], version=1, status="published", is_active=True),
            ModelReleaseRecord(
                id="release-1", template_key="sme_model", model_version="M1",
                config_json={"scorecard_binding": {"code": "SME_SCORE"}, "decision_pipeline_code": "PIPE-SME"},
                config_hash="release-hash", is_active=True, published_by="风控经理",
            ),
            ModelChangeRecord(
                id="model-change", template_key="sme_model", base_version="M1", candidate_version="M2",
                status="draft", entity_type="model",
                config_json={"scorecard_binding": {"code": "SME_SCORE"}, "decision_pipeline_code": "PIPE-SME"},
                validation_json={"valid": True}, impact_json={}, comparison_evidence_json={},
                change_reason="准备切换评分卡", created_by="maker", created_by_name="模型管理员",
            ),
            pipeline_change,
            package,
            RuleCenterReleasePackageMember(
                id="member-1", package_id="package-1", change_id="pipeline-change",
                asset_type="pipeline", code="PIPE-SME", candidate_version="2", sequence=1,
            ),
        ])
        self.session.commit()

        draft = ScorecardRepository(self.session).create_draft(scorecard(), "调整评分卡并评估完整依赖", "maker", "模型管理员")
        graph = draft["impact"]["dependency_graph"]
        self.assertEqual(graph["schema_version"], "scorecard-dependency-graph-v1")
        self.assertEqual(graph["summary"], {"indicator": 1, "model": 2, "pipeline": 2, "rule_set": 1, "rule": 1, "release_package": 1})
        self.assertEqual(len(graph["graph_hash"]), 64)
        self.assertTrue(any(edge["relation"] == "fixed_scorecard_binding" for edge in graph["edges"]))
        self.assertTrue(any(edge["relation"] == "included_in_package" for edge in graph["edges"]))
        self.assertEqual({risk["key"] for risk in graph["risks"]}, {"direct_model_binding", "inflight_model_change", "inflight_rule_asset", "inflight_release_package"})
        self.assertIn("sme_model", draft["impact"]["affected_models"])
        self.assertIn("sme_model", draft["impact"]["inflight_model_drafts"])

    def test_dependency_graph_drift_blocks_final_publish(self):
        repository = ScorecardRepository(self.session)
        draft = repository.create_draft(scorecard(), "建立首版评分卡并冻结依赖", "maker", "模型管理员")
        submitted = repository.submit(draft["id"], draft["row_version"], "maker", False)
        self.session.add(ModelSnapshotRecord(
            id="late-snapshot", template_key="late_model", model_name="后加入模型", model_version="v1",
            config_json={"indicator_selection": [{"indicator_id": "shareholder_change", "weight": 1, "enabled": True}]},
            config_hash=content_hash({"late": True}),
        ))
        self.session.commit()
        listed = repository.list_changes()[0]
        self.assertTrue(listed["impact"]["dependency_graph_drifted"])
        with self.assertRaisesRegex(ValueError, "依赖图已变化"):
            repository.review(submitted["id"], submitted["row_version"], "publish", "依赖图复核后批准", "reviewer", "风控经理")

    def test_scorecard_change_api_returns_frozen_and_current_dependency_hashes(self):
        client = TestClient(app)
        created_response = client.post(
            "/api/v1/indicator-center/scorecard-changes",
            json={"definition": scorecard("API_SCORE"), "change_reason": "验证依赖图 API 契约"},
            headers={"Authorization": "Bearer dev-model-admin"},
        )
        self.assertEqual(created_response.status_code, 201, created_response.text)
        created = created_response.json()
        submitted_response = client.post(
            f"/api/v1/indicator-center/scorecard-changes/{created['id']}/submit",
            json={"expected_row_version": created["row_version"]},
            headers={"Authorization": "Bearer dev-model-admin"},
        )
        self.assertEqual(submitted_response.status_code, 200, submitted_response.text)
        frozen_hash = submitted_response.json()["impact"]["dependency_graph_hash"]

        self.session.add(ModelSnapshotRecord(
            id="api-late-snapshot", template_key="api_late_model", model_name="API 后加入模型", model_version="v1",
            config_json={"indicator_selection": [{"indicator_id": "shareholder_change", "enabled": True}]},
            config_hash=content_hash({"api": "late"}),
        ))
        self.session.commit()

        listed_response = client.get(
            "/api/v1/indicator-center/scorecard-changes",
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(listed_response.status_code, 200, listed_response.text)
        listed = next(item for item in listed_response.json() if item["id"] == created["id"])
        self.assertEqual(listed["impact"]["dependency_graph_hash"], frozen_hash)
        self.assertNotEqual(listed["impact"]["dependency_graph_current_hash"], frozen_hash)
        self.assertTrue(listed["impact"]["dependency_graph_drifted"])
        self.assertEqual(listed["impact"]["dependency_graph"]["schema_version"], "scorecard-dependency-graph-v1")


if __name__ == "__main__":
    unittest.main()
