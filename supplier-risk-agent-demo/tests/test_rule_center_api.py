from __future__ import annotations

import unittest

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
from backend.dependencies import demo_repository, get_rule_definition_repository
from backend.main import app
from backend.repository import ConcurrentUpdateError
from tests.database_support import IsolatedTestDatabase


class TestRuleCenterApi(unittest.TestCase):
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
        self.admin = {"Authorization": "Bearer dev-model-admin"}
        self.viewer = {"Authorization": "Bearer dev-auditor"}
        self.forbidden = {"Authorization": "Bearer dev-client"}

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
    def _rule_payload(code="SR-API"):
        return {
            "code": code,
            "name": "API 测试规则",
            "rule_type": "strong_rule",
            "category": "credit_risk",
            "conditions_json": [
                {
                    "expression": "amount > 100",
                    "operator": "bool",
                    "label": "金额过高",
                }
            ],
            "actions_json": [{"type": "review_required", "value": True}],
            "priority": 10,
        }

    def _publish_rule(self, code="SR-API"):
        response = self.client.post(
            "/api/v1/rule-center/rules",
            json=self._rule_payload(code),
            headers=self.admin,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_rule_publish_list_detail_and_test(self):
        published = self._publish_rule()
        listed = self.client.get(
            "/api/v1/rule-center/rules", headers=self.viewer
        )
        detail = self.client.get(
            "/api/v1/rule-center/rules/SR-API", headers=self.viewer
        )
        tested = self.client.post(
            "/api/v1/rule-center/rules/SR-API/test",
            json={"context": {"amount": 150}},
            headers=self.viewer,
        )

        self.assertEqual(published["created_by"], "model-demo")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["code"] for item in listed.json()], ["SR-API"])
        self.assertEqual(detail.json()["version"], 1)
        self.assertEqual(tested.status_code, 200)
        self.assertTrue(tested.json()["triggered"])

    def test_publish_existing_rule_creates_next_version(self):
        self._publish_rule()
        response = self.client.post(
            "/api/v1/rule-center/rules/SR-API/publish", headers=self.admin
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["version"], 2)
        with database.SessionLocal() as session:
            active = session.query(RuleDefinition).filter_by(
                code="SR-API", is_active=True
            ).all()
        self.assertEqual([item.version for item in active], [2])

    def test_rule_set_and_pipeline_publish_with_dependency_validation(self):
        self._publish_rule()
        missing = self.client.post(
            "/api/v1/rule-center/rule-sets",
            json={
                "code": "RS-MISSING",
                "name": "缺失依赖",
                "rule_codes": ["NOT-FOUND"],
            },
            headers=self.admin,
        )
        rule_set = self.client.post(
            "/api/v1/rule-center/rule-sets",
            json={
                "code": "RS-API",
                "name": "API 规则集",
                "rule_codes": ["SR-API"],
            },
            headers=self.admin,
        )
        pipeline = self.client.post(
            "/api/v1/rule-center/pipelines",
            json={
                "code": "PIPE-API",
                "name": "API 管线",
                "stages_json": [
                    {"stage_type": "scoring"},
                    {
                        "stage_type": "strong_rules",
                        "rule_set_code": "RS-API",
                    },
                    {"stage_type": "admission"},
                ],
            },
            headers=self.admin,
        )

        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(rule_set.status_code, 201, rule_set.text)
        self.assertEqual(pipeline.status_code, 201, pipeline.text)
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/rule-sets/RS-API", headers=self.viewer
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/rule-center/pipelines/PIPE-API", headers=self.viewer
            ).status_code,
            200,
        )

    def test_schema_authentication_and_authorization_fail_closed(self):
        unauthenticated = self.client.get("/api/v1/rule-center/rules")
        forbidden_read = self.client.get(
            "/api/v1/rule-center/rules", headers=self.forbidden
        )
        forbidden_write = self.client.post(
            "/api/v1/rule-center/rules",
            json=self._rule_payload(),
            headers=self.viewer,
        )
        invalid = self.client.post(
            "/api/v1/rule-center/rules",
            json={**self._rule_payload(), "conditions_json": []},
            headers=self.admin,
        )

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(forbidden_read.status_code, 403)
        self.assertEqual(forbidden_write.status_code, 403)
        self.assertEqual(invalid.status_code, 422)

    def test_not_found_and_invalid_pipeline_are_stable_errors(self):
        not_found = self.client.get(
            "/api/v1/rule-center/rules/NOPE", headers=self.viewer
        )
        invalid_pipeline = self.client.post(
            "/api/v1/rule-center/pipelines",
            json={
                "code": "PIPE-BAD",
                "name": "非法管线",
                "stages_json": [{"stage_type": "admission"}],
            },
            headers=self.admin,
        )

        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(invalid_pipeline.status_code, 422)
        self.assertIn("scoring", invalid_pipeline.json()["detail"])

    def test_pipeline_simulation_returns_execution_trace(self):
        created = self.client.post(
            "/api/v1/rule-center/pipelines",
            json={
                "code": "PIPE-SIM",
                "name": "模拟管线",
                "stages_json": [{"stage_type": "scoring"}],
            },
            headers=self.admin,
        )
        self.assertEqual(created.status_code, 201, created.text)

        response = self.client.post(
            "/api/v1/rule-center/pipelines/PIPE-SIM/simulate",
            json={
                "counterparty": demo_repository.list_counterparties()[0],
                "config": demo_repository.get_template("general"),
            },
            headers=self.viewer,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["result"]["ok"])
        self.assertEqual(response.json()["trace"]["pipeline_code"], "PIPE-SIM")

    def test_concurrent_publication_conflict_returns_409(self):
        class ConflictingRepository:
            def publish_rule(self, definition, actor, actor_name):
                raise ConcurrentUpdateError("规则定义发布发生并发冲突，请刷新后重试")

        app.dependency_overrides[get_rule_definition_repository] = (
            lambda: ConflictingRepository()
        )
        response = self.client.post(
            "/api/v1/rule-center/rules",
            json=self._rule_payload(),
            headers=self.admin,
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("并发冲突", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
