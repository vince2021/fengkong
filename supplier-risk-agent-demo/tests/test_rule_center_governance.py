from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import backend.database as database
from backend.database import Base
from backend.db_models import (
    AuditEventRecord,
    DecisionPipelineDefinition,
    ModelChangeRecord,
    RuleDefinition,
    RuleSetDefinition,
)
from backend.main import app
from tests.database_support import IsolatedTestDatabase


class TestRuleCenterGovernance(unittest.TestCase):
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

    def tearDown(self):
        app.dependency_overrides.clear()
        self._clear()

    def _clear(self):
        with database.SessionLocal() as session:
            for model in (
                AuditEventRecord,
                ModelChangeRecord,
                DecisionPipelineDefinition,
                RuleSetDefinition,
                RuleDefinition,
            ):
                session.query(model).delete()
            session.commit()

    @staticmethod
    def _definition(code="GOV-RULE", name="治理规则"):
        return {
            "code": code,
            "name": name,
            "rule_type": "strong_rule",
            "category": "credit_risk",
            "enabled": True,
            "conditions_json": [
                {
                    "expression": "requested_limit > 1000000",
                    "operator": "bool",
                    "label": "大额申请",
                }
            ],
            "condition_relation": "all",
            "actions_json": [{"type": "review_required", "value": True}],
            "priority": 10,
        }

    def _create_draft(self, definition=None):
        response = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": "rule",
                "definition": definition or self._definition(),
                "change_reason": "新增受控规则配置",
            },
            headers=self.maker,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _submit(self, change):
        response = self.client.post(
            f"/api/v1/rule-center/governance/changes/{change['id']}/submit",
            json={"expected_row_version": change["row_version"]},
            headers=self.maker,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_draft_is_invisible_until_independent_review_publishes(self):
        draft = self._create_draft()
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/rules", headers=self.reviewer
            ).json(),
            [],
        )

        submitted = self._submit(draft)
        forbidden = self.client.post(
            f"/api/v1/rule-center/governance/changes/{submitted['id']}/review",
            json={
                "expected_row_version": submitted["row_version"],
                "decision": "publish",
                "comment": "创建人不能自行完成复核",
            },
            headers=self.admin,
        )
        self.assertEqual(forbidden.status_code, 200, forbidden.text)

        # Admin is a different principal from the model-admin maker.
        published = forbidden.json()
        self.assertEqual(published["status"], "published")
        active = self.client.get(
            "/api/v1/rule-center/rules/GOV-RULE", headers=self.reviewer
        )
        self.assertEqual(active.status_code, 200, active.text)
        self.assertEqual(active.json()["version"], 1)
        self.assertEqual(published["effective_at"], published["published_at"])

    def test_same_principal_cannot_review_and_stale_version_conflicts(self):
        draft = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": "rule",
                "definition": self._definition("ADMIN-RULE"),
                "change_reason": "管理员创建治理草稿",
            },
            headers=self.admin,
        ).json()
        submitted = self.client.post(
            f"/api/v1/rule-center/governance/changes/{draft['id']}/submit",
            json={"expected_row_version": draft["row_version"]},
            headers=self.admin,
        ).json()
        same_actor = self.client.post(
            f"/api/v1/rule-center/governance/changes/{submitted['id']}/review",
            json={
                "expected_row_version": submitted["row_version"],
                "decision": "publish",
                "comment": "尝试自行审批治理变更",
            },
            headers=self.admin,
        )
        self.assertEqual(same_actor.status_code, 403, same_actor.text)

        stale = self.client.post(
            f"/api/v1/rule-center/governance/changes/{submitted['id']}/review",
            json={
                "expected_row_version": draft["row_version"],
                "decision": "reject",
                "comment": "使用过期版本执行复核",
            },
            headers=self.reviewer,
        )
        self.assertEqual(stale.status_code, 409, stale.text)

    def test_rejection_and_scheduled_activation(self):
        rejected_draft = self._submit(self._create_draft(self._definition("REJECT-ME")))
        rejected = self.client.post(
            f"/api/v1/rule-center/governance/changes/{rejected_draft['id']}/review",
            json={
                "expected_row_version": rejected_draft["row_version"],
                "decision": "reject",
                "comment": "业务口径尚未形成一致意见",
            },
            headers=self.reviewer,
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["status"], "rejected")

        scheduled_draft = self._submit(
            self._create_draft(self._definition("SCHEDULED-RULE"))
        )
        effective_at = datetime.now(timezone.utc) + timedelta(hours=1)
        scheduled = self.client.post(
            f"/api/v1/rule-center/governance/changes/{scheduled_draft['id']}/review",
            json={
                "expected_row_version": scheduled_draft["row_version"],
                "decision": "publish",
                "comment": "批准在业务低峰期生效",
                "effective_at": effective_at.isoformat(),
            },
            headers=self.reviewer,
        )
        self.assertEqual(scheduled.status_code, 200, scheduled.text)
        self.assertEqual(scheduled.json()["status"], "scheduled")
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/rules/SCHEDULED-RULE", headers=self.reviewer
            ).status_code,
            404,
        )

        scan = self.client.post(
            "/api/v1/rule-center/governance/activation-scan",
            json={"as_of": (effective_at + timedelta(minutes=1)).isoformat()},
            headers=self.reviewer,
        )
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertEqual(scan.json()["published_count"], 1)
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/rules/SCHEDULED-RULE", headers=self.reviewer
            ).status_code,
            200,
        )

    def test_restore_creates_new_governed_version(self):
        first = self.client.post(
            "/api/v1/rule-center/rules",
            json=self._definition("RESTORE-RULE", "版本一"),
            headers=self.maker,
        )
        second = self.client.post(
            "/api/v1/rule-center/rules",
            json=self._definition("RESTORE-RULE", "版本二"),
            headers=self.maker,
        )
        self.assertEqual((first.status_code, second.status_code), (201, 201))

        restored = self.client.post(
            "/api/v1/rule-center/governance/restore-drafts",
            json={
                "asset_type": "rule",
                "code": "RESTORE-RULE",
                "version": 1,
                "change_reason": "恢复经过验证的历史规则配置",
            },
            headers=self.maker,
        )
        self.assertEqual(restored.status_code, 201, restored.text)
        self.assertEqual(restored.json()["restore_source"]["version"], 1)
        submitted = self._submit(restored.json())
        published = self.client.post(
            f"/api/v1/rule-center/governance/changes/{submitted['id']}/review",
            json={
                "expected_row_version": submitted["row_version"],
                "decision": "publish",
                "comment": "确认历史版本适合恢复使用",
            },
            headers=self.reviewer,
        )
        self.assertEqual(published.status_code, 200, published.text)
        active = self.client.get(
            "/api/v1/rule-center/rules/RESTORE-RULE", headers=self.reviewer
        ).json()
        self.assertEqual(active["version"], 3)
        self.assertEqual(active["name"], "版本一")
        history = self.client.get(
            "/api/v1/rule-center/governance/history",
            params={"asset_type": "rule", "code": "RESTORE-RULE"},
            headers=self.reviewer,
        ).json()
        self.assertEqual([item["version"] for item in history], [3, 2, 1])

    def test_rule_set_and_pipeline_drafts_validate_published_dependencies(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/rule-center/rules",
                json=self._definition("DEP-RULE"),
                headers=self.maker,
            ).status_code,
            201,
        )
        invalid_set = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": "rule_set",
                "definition": {
                    "code": "DEP-SET-BAD",
                    "name": "依赖缺失规则集",
                    "rule_codes": ["NOT-FOUND"],
                    "evaluation_strategy": "most_restrictive",
                },
                "change_reason": "验证规则集依赖约束",
            },
            headers=self.maker,
        )
        self.assertEqual(invalid_set.status_code, 422, invalid_set.text)

        valid_set = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": "rule_set",
                "definition": {
                    "code": "DEP-SET",
                    "name": "有效依赖规则集",
                    "rule_codes": ["DEP-RULE"],
                    "evaluation_strategy": "most_restrictive",
                },
                "change_reason": "验证规则集治理草稿",
            },
            headers=self.maker,
        )
        self.assertEqual(valid_set.status_code, 201, valid_set.text)

        candidate_pipeline = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": "pipeline",
                "definition": {
                    "code": "DEP-PIPE-BAD",
                    "name": "依赖候选规则集的管线",
                    "stages_json": [
                        {"stage_type": "scoring"},
                        {"stage_type": "strong_rules", "rule_set_code": "DEP-SET"},
                    ],
                },
                "change_reason": "验证管线候选依赖约束",
            },
            headers=self.maker,
        )
        self.assertEqual(candidate_pipeline.status_code, 201, candidate_pipeline.text)

        missing_pipeline = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": "pipeline",
                "definition": {
                    "code": "DEP-PIPE-MISSING",
                    "name": "依赖完全缺失规则集的管线",
                    "stages_json": [
                        {"stage_type": "scoring"},
                        {"stage_type": "strong_rules", "rule_set_code": "NOT-FOUND"},
                    ],
                },
                "change_reason": "验证管线缺失依赖约束",
            },
            headers=self.maker,
        )
        self.assertEqual(missing_pipeline.status_code, 422, missing_pipeline.text)

    def test_only_one_scheduled_change_per_asset(self):
        first = self._submit(self._create_draft(self._definition("ONE-SCHEDULE")))
        second = self._submit(self._create_draft(self._definition("ONE-SCHEDULE")))
        effective_at = datetime.now(timezone.utc) + timedelta(hours=2)

        scheduled = self.client.post(
            f"/api/v1/rule-center/governance/changes/{first['id']}/review",
            json={
                "expected_row_version": first["row_version"],
                "decision": "publish",
                "comment": "第一项安排在低峰期生效",
                "effective_at": effective_at.isoformat(),
            },
            headers=self.reviewer,
        )
        duplicate = self.client.post(
            f"/api/v1/rule-center/governance/changes/{second['id']}/review",
            json={
                "expected_row_version": second["row_version"],
                "decision": "publish",
                "comment": "第二项不应允许同时排期",
                "effective_at": (effective_at + timedelta(hours=1)).isoformat(),
            },
            headers=self.reviewer,
        )
        self.assertEqual(scheduled.status_code, 200, scheduled.text)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

    def test_scheduled_activation_fails_when_active_baseline_drifted(self):
        submitted = self._submit(self._create_draft(self._definition("DRIFT-RULE")))
        effective_at = datetime.now(timezone.utc) + timedelta(hours=1)
        scheduled = self.client.post(
            f"/api/v1/rule-center/governance/changes/{submitted['id']}/review",
            json={
                "expected_row_version": submitted["row_version"],
                "decision": "publish",
                "comment": "批准后等待计划时间生效",
                "effective_at": effective_at.isoformat(),
            },
            headers=self.reviewer,
        )
        self.assertEqual(scheduled.status_code, 200, scheduled.text)
        direct = self.client.post(
            "/api/v1/rule-center/rules",
            json=self._definition("DRIFT-RULE", "基线已被其他发布更新"),
            headers=self.maker,
        )
        self.assertEqual(direct.status_code, 201, direct.text)

        scan = self.client.post(
            "/api/v1/rule-center/governance/activation-scan",
            json={"as_of": (effective_at + timedelta(minutes=1)).isoformat()},
            headers=self.reviewer,
        )
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertEqual(scan.json()["failed_count"], 1)
        listed = self.client.get(
            "/api/v1/rule-center/governance/changes",
            params={"asset_type": "rule", "code": "DRIFT-RULE"},
            headers=self.reviewer,
        ).json()
        failed = next(item for item in listed if item["id"] == submitted["id"])
        self.assertEqual(failed["status"], "activation_failed")

    def test_governance_permissions_and_draft_code_are_enforced(self):
        client_headers = {"Authorization": "Bearer dev-client"}
        auditor_headers = {"Authorization": "Bearer dev-auditor"}
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/governance/changes", headers=client_headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/governance/changes", headers=auditor_headers
            ).status_code,
            200,
        )
        draft = self._create_draft(self._definition("IMMUTABLE-CODE"))
        forbidden_review = self.client.post(
            f"/api/v1/rule-center/governance/changes/{draft['id']}/review",
            json={
                "expected_row_version": draft["row_version"],
                "decision": "reject",
                "comment": "模型管理员没有独立复核权限",
            },
            headers=self.maker,
        )
        changed_code = self.client.put(
            f"/api/v1/rule-center/governance/changes/{draft['id']}",
            json={
                "expected_row_version": draft["row_version"],
                "definition": self._definition("CHANGED-CODE"),
                "change_reason": "尝试修改治理资产编码",
            },
            headers=self.maker,
        )
        auditor_create = self.client.post(
            "/api/v1/rule-center/governance/changes",
            json={
                "asset_type": "rule",
                "definition": self._definition("AUDITOR-CREATE"),
                "change_reason": "审计人员不应创建变更",
            },
            headers=auditor_headers,
        )
        self.assertEqual(forbidden_review.status_code, 403)
        self.assertEqual(changed_code.status_code, 422, changed_code.text)
        self.assertEqual(auditor_create.status_code, 403)


if __name__ == "__main__":
    unittest.main()
