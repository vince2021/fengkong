from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import backend.database as database
from backend.database import Base
from backend.db_models import (
    AuditEventRecord,
    DecisionPipelineDefinition,
    ModelChangeRecord,
    RuleCenterReleasePackage,
    RuleCenterReleasePackageMember,
    RuleCenterReplayDataset,
    RuleCenterReplayDatasetSnapshot,
    RuleCenterReplayRun,
    RuleDefinition,
    RuleSetDefinition,
)
from backend.dependencies import get_rule_center_release_package_repository
from backend.main import app
from backend.repository import DemoRepository, RuleCenterReleasePackageRepository
from tests.database_support import IsolatedTestDatabase


class TestRuleCenterReleasePackages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self._clear()
        self.maker = {"Authorization": "Bearer dev-model-admin"}
        self.reviewer = {"Authorization": "Bearer dev-risk"}
        self.admin = {"Authorization": "Bearer dev-admin"}
        self.snapshot_id = None

    def tearDown(self):
        app.dependency_overrides.clear()
        self._clear()

    def _clear(self):
        with database.SessionLocal() as session:
            for model in (
                RuleCenterReplayRun,
                RuleCenterReplayDatasetSnapshot,
                RuleCenterReplayDataset,
                RuleCenterReleasePackageMember,
                RuleCenterReleasePackage,
                AuditEventRecord,
                ModelChangeRecord,
                DecisionPipelineDefinition,
                RuleSetDefinition,
                RuleDefinition,
            ):
                session.query(model).delete()
            session.commit()

    @staticmethod
    def _rule(code="PKG-RULE"):
        return {
            "code": code,
            "name": "发布包规则",
            "rule_type": "strong_rule",
            "category": "credit_risk",
            "enabled": True,
            "conditions_json": [
                {
                    "expression": "requested_limit > 1000000",
                    "operator": "bool",
                    "label": "高额申请",
                }
            ],
            "condition_relation": "all",
            "actions_json": [{"type": "review_required", "value": True}],
            "priority": 10,
        }

    @staticmethod
    def _rule_set(code="PKG-SET", rule_code="PKG-RULE"):
        return {
            "code": code,
            "name": "发布包规则集",
            "rule_codes": [rule_code],
            "evaluation_strategy": "most_restrictive",
        }

    @staticmethod
    def _pipeline(code="PKG-PIPE", rule_set_code="PKG-SET"):
        return {
            "code": code,
            "name": "发布包决策管线",
            "stages_json": [
                {"stage_type": "scoring"},
                {"stage_type": "strong_rules", "rule_set_code": rule_set_code},
                {"stage_type": "admission"},
            ],
        }

    def _draft(self, asset_type, definition):
        response = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": asset_type,
                "definition": definition,
                "change_reason": "构建统一原子发布包",
            },
            headers=self.maker,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _candidate_chain(self):
        rule = self._draft("rule", self._rule())
        rule_set = self._draft("rule_set", self._rule_set())
        pipeline = self._draft("pipeline", self._pipeline())
        return rule, rule_set, pipeline

    def _create_package(self, changes):
        response = self.client.post(
            "/api/v1/rule-center/governance/packages",
            json={
                "name": "供应商准入策略统一发布",
                "change_reason": "规则、规则集和管线必须同时切换",
                "change_ids": [item["id"] for item in changes],
            },
            headers=self.maker,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _replay_package(self, package, **overrides):
        payload = {
            "dataset_snapshot_id": self._snapshot(),
            "model_key": "general",
            "pipeline_code": "PKG-PIPE",
            "sample_limit": 14,
            "min_sample_count": 10,
            "max_decision_change_rate": 1,
            "max_execution_failure_rate": 0,
            **overrides,
        }
        response = self.client.post(
            f"/api/v1/rule-center/governance/packages/{package['id']}/replays",
            json=payload,
            headers=self.maker,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _snapshot(self):
        if self.snapshot_id:
            return self.snapshot_id
        dataset = self.client.post(
            "/api/v1/rule-center/governance/replay-datasets",
            json={
                "code": "PKG-HISTORY",
                "name": "发布包历史样本",
                "description": "发布包回放测试使用的合成历史样本",
            },
            headers=self.maker,
        )
        self.assertEqual(dataset.status_code, 201, dataset.text)
        snapshot = self.client.post(
            f"/api/v1/rule-center/governance/replay-datasets/{dataset.json()['id']}/snapshots",
            json={
                "source_name": "demo-counterparties",
                "schema_version": "1.0",
                "as_of_date": "2026-06-30",
                "evidence_reference": "test-fixture://demo-counterparties",
                "data_classification": "synthetic",
                "records": DemoRepository().list_counterparties(),
            },
            headers=self.maker,
        )
        self.assertEqual(snapshot.status_code, 201, snapshot.text)
        self.snapshot_id = snapshot.json()["id"]
        return self.snapshot_id

    def _submit_package(self, package, replay=True):
        if replay:
            self._replay_package(package)
        response = self.client.post(
            f"/api/v1/rule-center/governance/packages/{package['id']}/submit",
            json={"expected_row_version": package["row_version"]},
            headers=self.maker,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_replay_evidence_is_required_before_submission(self):
        package = self._create_package(self._candidate_chain())
        blocked = self.client.post(
            f"/api/v1/rule-center/governance/packages/{package['id']}/submit",
            json={"expected_row_version": package["row_version"]},
            headers=self.maker,
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertIn("历史样本回放", blocked.text)

        replay = self._replay_package(package)
        self.assertTrue(replay["gate"]["passed"])
        self.assertEqual(replay["sample_count"], 14)
        self.assertEqual(replay["dataset_snapshot_id"], self.snapshot_id)
        self.assertEqual(len(replay["dataset_snapshot_hash"]), 64)
        self.assertIn("rating_migration_matrix", replay["metrics"])
        self.assertIn("admission_migration_matrix", replay["metrics"])
        self.assertEqual(len(replay["evidence_hash"]), 64)
        submitted = self._submit_package(package, replay=False)
        self.assertEqual(submitted["status"], "pending_review")

    def test_failed_replay_gate_blocks_submission(self):
        rule = self._rule()
        rule["conditions_json"] = [{"expression": "id != ''", "operator": "bool", "label": "全部样本"}]
        rule["actions_json"] = [{"type": "access_strategy", "value": "禁入"}]
        changes = (
            self._draft("rule", rule),
            self._draft("rule_set", self._rule_set()),
            self._draft("pipeline", self._pipeline()),
        )
        package = self._create_package(changes)
        replay = self._replay_package(package, max_decision_change_rate=0)
        self.assertFalse(replay["gate"]["passed"])
        self.assertGreater(replay["metrics"]["decision_change_count"], 0)
        blocked = self.client.post(
            f"/api/v1/rule-center/governance/packages/{package['id']}/submit",
            json={"expected_row_version": package["row_version"]},
            headers=self.maker,
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertIn("回放门禁未通过", blocked.text)

    def test_snapshot_hash_is_rechecked_before_submission(self):
        package = self._create_package(self._candidate_chain())
        replay = self._replay_package(package)
        with database.SessionLocal() as session:
            snapshot = session.get(RuleCenterReplayDatasetSnapshot, replay["dataset_snapshot_id"])
            rows = list(snapshot.samples_json)
            rows[0] = {**rows[0], "label": "tampered"}
            snapshot.samples_json = rows
            session.commit()
        blocked = self.client.post(
            f"/api/v1/rule-center/governance/packages/{package['id']}/submit",
            json={"expected_row_version": package["row_version"]},
            headers=self.maker,
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertIn("快照内容哈希不一致", blocked.text)

    def test_candidate_dependencies_publish_atomically_in_dependency_order(self):
        changes = self._candidate_chain()
        preview = self.client.post(
            "/api/v1/rule-center/governance/packages/impact",
            json={"change_ids": [item["id"] for item in changes]},
            headers=self.maker,
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["release_gate"]["passed"])
        self.assertEqual(preview.json()["impact"]["package_dependency_count"], 2)

        package = self._create_package(changes)
        self.assertEqual([item["asset_type"] for item in package["members"]], ["rule", "rule_set", "pipeline"])
        self.assertEqual(package["impact"]["member_count"], 3)
        self.assertEqual(
            self.client.get("/api/v1/rule-center/rules", headers=self.reviewer).json(),
            [],
        )
        submitted = self._submit_package(package)
        same_actor = self.client.post(
            f"/api/v1/rule-center/governance/packages/{submitted['id']}/review",
            json={
                "expected_row_version": submitted["row_version"],
                "decision": "publish",
                "comment": "创建人不能复核自己的发布包",
            },
            headers=self.maker,
        )
        self.assertEqual(same_actor.status_code, 403)
        published = self.client.post(
            f"/api/v1/rule-center/governance/packages/{submitted['id']}/review",
            json={
                "expected_row_version": submitted["row_version"],
                "decision": "publish",
                "comment": "依赖闭包与影响摘要均已复核通过",
            },
            headers=self.reviewer,
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["status"], "published")
        with database.SessionLocal() as session:
            self.assertEqual(session.query(RuleDefinition).filter_by(is_active=True).count(), 1)
            self.assertEqual(session.query(RuleSetDefinition).filter_by(is_active=True).count(), 1)
            self.assertEqual(session.query(DecisionPipelineDefinition).filter_by(is_active=True).count(), 1)

    def test_missing_candidate_dependency_blocks_package_gate(self):
        rule, rule_set, _ = self._candidate_chain()
        preview = self.client.post(
            "/api/v1/rule-center/governance/packages/impact",
            json={"change_ids": [rule_set["id"]]},
            headers=self.maker,
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertFalse(preview.json()["release_gate"]["passed"])
        self.assertIn("缺少依赖", preview.json()["release_gate"]["summary"])
        blocked = self.client.post(
            "/api/v1/rule-center/governance/packages",
            json={
                "name": "不完整发布包",
                "change_reason": "遗漏规则候选时必须阻断发布",
                "change_ids": [rule_set["id"]],
            },
            headers=self.maker,
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertEqual(rule["status"], "draft")

    def test_rejection_releases_members_back_to_drafts(self):
        package = self._submit_package(self._create_package(self._candidate_chain()))
        rejected = self.client.post(
            f"/api/v1/rule-center/governance/packages/{package['id']}/review",
            json={
                "expected_row_version": package["row_version"],
                "decision": "reject",
                "comment": "影响范围说明不足，退回重新组合",
            },
            headers=self.reviewer,
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["status"], "rejected")
        changes = self.client.get(
            "/api/v1/rule-center/governance/changes", headers=self.maker
        ).json()
        self.assertEqual({item["status"] for item in changes}, {"draft"})

    def test_mid_package_failure_rolls_back_every_published_member(self):
        package = self._submit_package(self._create_package(self._candidate_chain()))

        class FailingPackageRepository(RuleCenterReleasePackageRepository):
            def _repository(self, asset_type):
                repository = super()._repository(asset_type)
                if asset_type == "rule_set":
                    def fail(*args, **kwargs):
                        raise ValueError("模拟规则集发布失败")
                    repository._publish = fail
                return repository

        def override_repository():
            session = database.SessionLocal()
            try:
                yield FailingPackageRepository(session)
            finally:
                session.close()

        app.dependency_overrides[get_rule_center_release_package_repository] = override_repository
        failed = self.client.post(
            f"/api/v1/rule-center/governance/packages/{package['id']}/review",
            json={
                "expected_row_version": package["row_version"],
                "decision": "publish",
                "comment": "验证任一成员失败时整包回滚",
            },
            headers=self.reviewer,
        )
        self.assertEqual(failed.status_code, 409, failed.text)
        with database.SessionLocal() as session:
            self.assertEqual(session.query(RuleDefinition).count(), 0)
            self.assertEqual(session.query(RuleSetDefinition).count(), 0)
            self.assertEqual(session.query(DecisionPipelineDefinition).count(), 0)
            stored = session.get(RuleCenterReleasePackage, package["id"])
            self.assertEqual(stored.status, "pending_review")

    def test_package_permissions_fail_closed(self):
        changes = self._candidate_chain()
        change_ids = [item["id"] for item in changes]
        auditor = {"Authorization": "Bearer dev-auditor"}
        client = {"Authorization": "Bearer dev-client"}
        self.assertEqual(
            self.client.post(
                "/api/v1/rule-center/governance/packages/impact",
                json={"change_ids": change_ids},
                headers=auditor,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/governance/packages", headers=auditor
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/governance/packages", headers=client
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
