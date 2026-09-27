from __future__ import annotations

import unittest
from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

import backend.database as database
from backend.db_models import DecisionExecutionRecord, DecisionJobRecord, DecisionPipelineDefinition, ModelReleaseRecord, RatingRunRecord
from backend.dependencies import demo_repository
from backend.main import app
from backend.repository import clear_persistent_data, content_hash
from scripts.seed_indicators import seed_from_pool_json
from scripts.seed_rule_center import seed_all
from tests.database_support import IsolatedTestDatabase


class TenantRuntimeAssetIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.test_database.stop()

    def setUp(self) -> None:
        with database.SessionLocal() as session:
            clear_persistent_data(session)
            seed_from_pool_json(session)
            seed_all(session=session)
            config = demo_repository.get_template("general")
            session.add(ModelReleaseRecord(
                id=str(uuid4()), template_key="general", model_version=config["version"],
                config_json=deepcopy(config), config_hash=content_hash(config), source_change_id=None,
                is_active=True, published_by="runtime-test",
            ))
            session.commit()
        self.model_admin = {"Authorization": "Bearer dev-model-admin"}
        self.risk = {"Authorization": "Bearer dev-risk"}
        self.manager = {"Authorization": "Bearer dev-manager"}
        self.integration = {"Authorization": "Bearer dev-integration"}

    def _publish_model_override(self) -> dict:
        binding = self.client.post(
            "/api/v1/tenant-assets/bindings",
            headers=self.model_admin,
            json={
                "asset_type": "model", "asset_code": "general", "binding_mode": "inherit_active",
                "pinned_version": None, "allow_tenant_override": True, "status": "active",
                "reason": "租户评级运行时覆盖验证",
            },
        )
        self.assertEqual(binding.status_code, 201, binding.text)
        config = demo_repository.get_template("general")
        config["thresholds"]["overdue_rate"] = 0.07
        created = self.client.post(
            "/api/v1/tenant-assets/overrides",
            headers=self.model_admin,
            json={"asset_type": "model", "asset_code": "general", "config": config, "reason": "租户风险偏好阈值调整"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        submitted = self.client.post(
            f"/api/v1/tenant-assets/overrides/{created.json()['id']}/submit",
            headers=self.model_admin,
            json={"expected_row_version": created.json()["row_version"], "reason": "提交独立复核"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        reviewed = self.client.post(
            f"/api/v1/tenant-assets/overrides/{created.json()['id']}/review",
            headers=self.risk,
            json={"expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "覆盖配置验证通过"},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        return reviewed.json()

    def _publish_pipeline_override(self) -> dict:
        binding = self.client.post(
            "/api/v1/tenant-assets/bindings",
            headers=self.model_admin,
            json={
                "asset_type": "pipeline", "asset_code": "PIPELINE-GENERAL", "binding_mode": "inherit_active",
                "pinned_version": None, "allow_tenant_override": True, "status": "active",
                "reason": "租户决策管线运行时覆盖验证",
            },
        )
        self.assertEqual(binding.status_code, 201, binding.text)
        with database.SessionLocal() as session:
            row = session.scalars(select(DecisionPipelineDefinition).where(
                DecisionPipelineDefinition.code == "PIPELINE-GENERAL",
                DecisionPipelineDefinition.is_active.is_(True),
            )).one()
            config = {
                "code": row.code,
                "name": "租户供应商准入管线",
                "version": row.version,
                "stages_json": deepcopy(row.stages_json),
            }
        created = self.client.post(
            "/api/v1/tenant-assets/overrides",
            headers=self.model_admin,
            json={"asset_type": "pipeline", "asset_code": "PIPELINE-GENERAL", "config": config, "reason": "租户管线展示名称调整"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        submitted = self.client.post(
            f"/api/v1/tenant-assets/overrides/{created.json()['id']}/submit",
            headers=self.model_admin,
            json={"expected_row_version": created.json()["row_version"], "reason": "提交租户管线独立复核"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        reviewed = self.client.post(
            f"/api/v1/tenant-assets/overrides/{created.json()['id']}/review",
            headers=self.risk,
            json={"expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "租户管线覆盖验证通过"},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        return reviewed.json()

    def test_rating_and_sync_decision_use_tenant_override_and_freeze_evidence(self) -> None:
        override = self._publish_model_override()
        contract = self.client.get("/api/v1/decisions/contract", headers=self.integration)
        self.assertEqual(contract.status_code, 200, contract.text)
        contract_model = next(item for item in contract.json()["models"] if item["key"] == "general")
        self.assertEqual(contract_model["active_version"], f"tenant-v{override['version']}")
        self.assertEqual(contract_model["source_scope"], "tenant_override")
        self.assertEqual(contract_model["versions"][0]["override_id"], override["id"])
        self.assertEqual(contract_model["resolution_hash"], contract_model["versions"][0]["resolution_hash"])
        sandbox = self.client.get("/api/v1/decisions/sandbox", headers=self.integration)
        self.assertEqual(sandbox.status_code, 200, sandbox.text)
        self.assertEqual(sandbox.json()["request_example"]["assets"]["model_version"], contract_model["active_version"])
        rated = self.client.post(
            "/api/v1/ratings/run",
            headers=self.manager,
            json={"counterparty_id": "cp_supplier_low_001", "template_key": "general"},
        )
        self.assertEqual(rated.status_code, 200, rated.text)
        body = rated.json()
        self.assertEqual(body["model_version"], f"tenant-v{override['version']}")
        self.assertEqual(body["asset_resolution"]["model"]["source_scope"], "tenant_override")
        self.assertEqual(body["asset_resolution"]["model"]["override_id"], override["id"])
        self.assertEqual(len(body["assets_hash"]), 64)
        with database.SessionLocal() as session:
            run = session.scalars(select(RatingRunRecord)).one()
            self.assertEqual(content_hash(run.asset_snapshot_json), run.assets_hash)
            self.assertEqual(run.asset_snapshot_json["resolution_hash"], body["asset_resolution"]["resolution_hash"])

        request = {
            "request_id": "TENANT-OVERRIDE-SYNC-001", "counterparty_id": "cp_supplier_low_001", "input": None,
            "assets": {"model_key": "general", "pipeline_code": "PIPELINE-GENERAL", "rule_set_versions": {}, "rule_versions": {}},
            "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
        }
        decided = self.client.post("/api/v1/decisions", headers=self.integration, json=request)
        self.assertEqual(decided.status_code, 200, decided.text)
        self.assertEqual(decided.json()["assets"]["model"]["source_scope"], "tenant_override")
        self.assertEqual(decided.json()["assets"]["model"]["version"], f"tenant-v{override['version']}")
        pinned = deepcopy(request)
        pinned["request_id"] = "TENANT-OVERRIDE-SYNC-002"
        pinned["assets"]["model_version"] = demo_repository.get_template("general")["version"]
        denied = self.client.post("/api/v1/decisions", headers=self.integration, json=pinned)
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(denied.json()["error"]["code"], "ASSET_VERSION_NOT_ALLOWED")

    def test_decision_job_executes_the_asset_graph_frozen_when_queued(self) -> None:
        payload = {
            "job_key": "TENANT-FROZEN-JOB-001",
            "requests": [{
                "request_id": "TENANT-FROZEN-ITEM-001", "counterparty_id": "cp_supplier_low_001", "input": None,
                "assets": {"model_key": "general", "pipeline_code": "PIPELINE-GENERAL", "rule_set_versions": {}, "rule_versions": {}},
                "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
            }],
            "callback": {"mode": "none", "endpoint_url": "", "secret_reference": "", "simulate_status_sequence": [200], "max_attempts": 3},
        }
        queued = self.client.post("/api/v1/decision-jobs", headers=self.integration, json=payload)
        self.assertEqual(queued.status_code, 202, queued.text)
        with database.SessionLocal() as session:
            job = session.get(DecisionJobRecord, queued.json()["id"])
            self.assertEqual(content_hash(job.asset_snapshot_json), job.assets_hash)
            original = session.scalars(select(DecisionPipelineDefinition).where(
                DecisionPipelineDefinition.code == "PIPELINE-GENERAL",
                DecisionPipelineDefinition.is_active.is_(True),
            )).one()
            original.is_active = False
            session.flush()
            session.add(DecisionPipelineDefinition(
                id=str(uuid4()), code=original.code, name="切换后的平台管线",
                version=original.version + 1, stages_json=deepcopy(original.stages_json), status="published",
                is_active=True, created_by="runtime-test",
            ))
            session.commit()

        completed = self.client.post(f"/api/v1/decision-jobs/{queued.json()['id']}/run", headers=self.integration)
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "completed")
        with database.SessionLocal() as session:
            execution = session.scalars(select(DecisionExecutionRecord)).one()
            self.assertEqual(execution.asset_snapshot_json["pipeline"]["version"], "1")
            self.assertEqual(content_hash(execution.asset_snapshot_json), execution.assets_hash)
            active_version = session.scalar(select(DecisionPipelineDefinition.version).where(
                DecisionPipelineDefinition.code == "PIPELINE-GENERAL",
                DecisionPipelineDefinition.is_active.is_(True),
            ))
            self.assertEqual(active_version, 2)

    def test_contract_tenant_pipeline_version_can_be_executed_verbatim(self) -> None:
        override = self._publish_pipeline_override()
        contract = self.client.get("/api/v1/decisions/contract", headers=self.integration)
        self.assertEqual(contract.status_code, 200, contract.text)
        pipeline = next(item for item in contract.json()["pipelines"] if item["code"] == "PIPELINE-GENERAL")
        self.assertEqual(pipeline["version"], f"tenant-v{override['version']}")
        self.assertEqual(pipeline["source_scope"], "tenant_override")
        self.assertEqual(pipeline["override_id"], override["id"])

        decided = self.client.post(
            "/api/v1/decisions",
            headers=self.integration,
            json={
                "request_id": "TENANT-PIPELINE-CONTRACT-001",
                "counterparty_id": "cp_supplier_low_001",
                "input": None,
                "assets": {
                    "model_key": "general",
                    "pipeline_code": pipeline["code"],
                    "pipeline_version": pipeline["version"],
                    "rule_set_versions": {},
                    "rule_versions": {},
                },
                "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
            },
        )
        self.assertEqual(decided.status_code, 200, decided.text)
        self.assertEqual(decided.json()["assets"]["pipeline"]["version"], pipeline["version"])
        self.assertEqual(decided.json()["assets"]["pipeline"]["resolution_hash"], pipeline["resolution_hash"])


if __name__ == "__main__":
    unittest.main()
