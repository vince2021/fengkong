from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import backend.database as database
from backend.db_models import ModelSnapshotRecord, RatingRunRecord
from backend.governance_evidence import PACKAGE_HASH_EXCLUDED_FIELDS, verify_counterparty_governance_evidence_package
from backend.main import app
from backend.repository import AuditRepository, clear_persistent_data, content_hash
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from tests.database_support import IsolatedTestDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIMARY_TENANT = "tenant-demo-hengxin"
ALTERNATE_TENANT = "tenant-demo-alt"
SHARED_COUNTERPARTY_ID = "cp_supplier_low_001"


def _principal(tenant_id: str, subject: str, role: str) -> Principal:
    return Principal(
        subject=subject,
        name=subject,
        roles=(role,),
        permissions=frozenset(ROLE_PERMISSIONS[role]),
        tenant_id=tenant_id,
        client_id=f"{tenant_id}-evidence-tests",
    )


def _contains_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in forbidden or _contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


class CounterpartyGovernanceEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        cls.test_database.stop()

    def setUp(self) -> None:
        app.dependency_overrides.clear()
        with database.SessionLocal() as session:
            clear_persistent_data(session)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, principal: Principal) -> None:
        app.dependency_overrides[get_current_principal] = lambda: principal

    def _create_counterparty(self, counterparty_id: str) -> dict:
        response = self.client.post(
            "/api/v1/counterparties",
            json={
                "counterparty_id": counterparty_id,
                "credit_code": f"91310000{counterparty_id[-8:]}",
                "name": f"证据测试企业 {counterparty_id}",
                "counterparty_type": "customer",
                "industry": "manufacturing",
                "cooperation_status": "pending",
                "is_key_counterparty": False,
                "requested_limit": 100000,
                "current_limit": 0,
                "current_payment_term_days": 30,
                "external": {},
                "internal": {},
                "financial": {},
                "extensions": {},
                "reason": "建立单户治理证据测试主体",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_export_is_strictly_tenant_scoped_and_same_business_id_is_independent(self) -> None:
        primary = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        alternate = _principal(ALTERNATE_TENANT, "alternate-auditor", "auditor")
        self._as(primary)
        unique_id = "CP-EVIDENCE-ONLY-PRIMARY"
        self._create_counterparty(unique_id)

        primary_only = self.client.get(f"/api/v1/governance-evidence/counterparties/{unique_id}")
        self.assertEqual(primary_only.status_code, 200, primary_only.text)
        self.assertEqual(primary_only.json()["tenant_id"], PRIMARY_TENANT)

        primary_shared = self.client.get(f"/api/v1/governance-evidence/counterparties/{SHARED_COUNTERPARTY_ID}").json()
        self._as(alternate)
        hidden = self.client.get(f"/api/v1/governance-evidence/counterparties/{unique_id}")
        alternate_shared_response = self.client.get(f"/api/v1/governance-evidence/counterparties/{SHARED_COUNTERPARTY_ID}")
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(alternate_shared_response.status_code, 200, alternate_shared_response.text)
        alternate_shared = alternate_shared_response.json()
        self.assertEqual(alternate_shared["tenant_id"], ALTERNATE_TENANT)
        self.assertNotEqual(primary_shared["package_hash"], alternate_shared["package_hash"])
        self.assertNotIn(PRIMARY_TENANT, json.dumps(alternate_shared, ensure_ascii=False))

        self._as(_principal(PRIMARY_TENANT, "primary-client", "client"))
        self.assertEqual(
            self.client.get(f"/api/v1/governance-evidence/counterparties/{SHARED_COUNTERPARTY_ID}").status_code,
            403,
        )

    def test_package_replays_record_hashes_audit_chain_and_platform_asset_reference(self) -> None:
        principal = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        self._as(principal)
        counterparty = self._create_counterparty("CP-EVIDENCE-RATING")
        snapshot_id = str(uuid4())
        run_id = str(uuid4())
        model_config = {"name": "企业评级模型", "version": "evidence-v1", "weights": {"financial": 0.5}}
        rating_input = {"id": counterparty["id"], "financial": {"debt_ratio": 0.42}}
        rating_result = {"total_score": 82.5, "rating": "A", "final_admission": "准入"}
        with database.SessionLocal() as session:
            session.add(ModelSnapshotRecord(
                id=snapshot_id,
                template_key="general",
                model_name="企业评级模型",
                model_version="evidence-v1",
                config_json=model_config,
                config_hash=content_hash(model_config),
            ))
            session.add(RatingRunRecord(
                id=run_id,
                tenant_id=PRIMARY_TENANT,
                counterparty_id=counterparty["id"],
                case_id=None,
                template_key="general",
                model_snapshot_id=snapshot_id,
                input_json=rating_input,
                input_hash=content_hash(rating_input),
                result_json=rating_result,
                result_hash=content_hash(rating_result),
            ))
            session.flush()
            AuditRepository(session).append(
                "rating_run",
                run_id,
                "rating_completed",
                principal.subject,
                {
                    "tenant_id": PRIMARY_TENANT,
                    "counterparty_id": counterparty["id"],
                    "model_snapshot_id": snapshot_id,
                    "input_hash": content_hash(rating_input),
                    "result_hash": content_hash(rating_result),
                },
            )
            session.commit()

        response = self.client.get(f"/api/v1/governance-evidence/counterparties/{counterparty['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        package = response.json()
        self.assertTrue(package["integrity"]["passed"])
        self.assertEqual(package["records"]["rating_runs"][0]["id"], run_id)
        self.assertEqual(package["platform_asset_references"][0]["evidence_scope"], "platform_shared")
        self.assertNotIn("config", package["platform_asset_references"][0])
        self.assertTrue(verify_counterparty_governance_evidence_package(package)["verified"])

        tampered_body = deepcopy(package)
        tampered_body["counterparty"]["name"] = "被篡改的企业名称"
        self.assertFalse(verify_counterparty_governance_evidence_package(tampered_body)["verified"])

        tampered_chain = deepcopy(package)
        chain = next(item for item in tampered_chain["audit"]["tenant_business_chains"] if item["aggregate_type"] == "rating_run")
        chain["events"][0]["payload"]["counterparty_id"] = "CP-TAMPERED"
        body = {key: value for key, value in tampered_chain.items() if key not in PACKAGE_HASH_EXCLUDED_FIELDS}
        tampered_chain["package_hash"] = content_hash(body)
        verification = verify_counterparty_governance_evidence_package(tampered_chain)
        self.assertFalse(verification["verified"])
        self.assertFalse(next(item for item in verification["checks"] if item["key"] == "audit_chain_integrity")["passed"])

    def test_limited_package_discloses_missing_domains_downloads_and_verifies_offline(self) -> None:
        self._as(_principal(PRIMARY_TENANT, "primary-auditor", "auditor"))
        response = self.client.get(f"/api/v1/governance-evidence/counterparties/{SHARED_COUNTERPARTY_ID}")
        self.assertEqual(response.status_code, 200, response.text)
        package = response.json()
        self.assertEqual(package["evidence_assessment"]["level"], "limited")
        self.assertIn("rating_runs", package["evidence_assessment"]["missing_domains"])
        self.assertFalse(_contains_key(package, {"object_key", "secret_reference", "source_content", "key_fingerprint"}))

        download = self.client.get(f"/api/v1/governance-evidence/counterparties/{SHARED_COUNTERPARTY_ID}/download")
        self.assertEqual(download.status_code, 200, download.text)
        self.assertIn("attachment", download.headers["content-disposition"])
        downloaded_package = json.loads(download.content)
        self.assertEqual(downloaded_package["package_hash"], package["package_hash"])
        self.assertEqual(
            {key: value for key, value in downloaded_package.items() if key != "generated_at"},
            {key: value for key, value in package.items() if key != "generated_at"},
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "scripts/verify_counterparty_evidence.py", str(path), "--expected-hash", package["package_hash"]],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["verified"])


if __name__ == "__main__":
    unittest.main()
