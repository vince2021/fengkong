from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import backend.database as database
from backend.database import Base
from backend.db_models import AuditEventRecord, ModelChangeRecord, ModelValidationReportIssuanceRecord, SupervisedValidationAttachmentRecord
from backend.model_validation_issuance_repository import ModelValidationIssuanceRepository
from backend.model_validation_signing import ED25519_SIGNATURE_ALGORITHM, Ed25519Signer
from backend.repository import ModelGovernanceRepository, content_hash
from backend.storage import LocalObjectStorage
from backend.supervised_validation_attachment_repository import SupervisedValidationAttachmentRepository
from tests.database_support import IsolatedTestDatabase


TENANT_ID = "tenant-demo-hengxin"


class TestModelValidationIssuance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase(); cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        with database.SessionLocal() as session:
            session.query(ModelValidationReportIssuanceRecord).delete()
            session.query(SupervisedValidationAttachmentRecord).delete()
            session.query(ModelChangeRecord).delete()
            session.query(AuditEventRecord).delete()
            session.commit()

    def test_issue_revoke_reissue_and_dashboard(self):
        with TemporaryDirectory() as directory, database.SessionLocal() as session:
            storage = LocalObjectStorage(directory)
            change = ModelChangeRecord(
                id=str(uuid4()), template_key="general", base_version="v1", candidate_version="v2",
                status="draft", config_json={"version": "v2"},
                validation_json={"valid": True, "config_hash": "c" * 64, "model_risk": {"release_gate": {"passed": True, "summary": "通过"}}},
                impact_json={}, comparison_evidence_json={}, change_reason="监督报告签发测试",
                created_by="maker", created_by_name="制作者", entity_type="model",
            )
            session.add(change); session.commit()
            attachment = SupervisedValidationAttachmentRepository(session, storage).upload(
                TENANT_ID, change.id, "validation.pdf", "application/pdf", b"signed-report", "maker", "制作者",
            )
            attachment = SupervisedValidationAttachmentRepository(session, storage).update_scan(
                TENANT_ID, attachment["id"], attachment["row_version"], "passed", "demo-av", "未发现恶意内容", "scanner", "安全扫描器",
            )
            evidence = {
                "schema_version": "model-supervised-validation-binding-v1", "tenant_id": TENANT_ID,
                "policy_id": "policy-1", "evaluation_id": "evaluation-1", "report_hash": "r" * 64,
                "report_template_version": "supervised-model-validation-v2", "evidence_level": "supervised",
                "risk_classification": {"proposed_level": "medium"},
                "independent_validation": {"status": "approved", "risk_level": "medium", "opinion": "独立验证已通过", "attachments": [{"attachment_id": attachment["id"], "name": attachment["name"], "reference": attachment["reference"], "sha256": attachment["sha256"]}]},
                "release_approval": {"status": "pending"},
            }
            change.supervised_validation_evidence_json = evidence
            change.supervised_validation_binding_hash = content_hash(evidence)
            session.commit(); session.refresh(change)
            repository = ModelValidationIssuanceRepository(session, storage)
            with self.assertRaisesRegex(ValueError, "尚未完成可信签发"):
                ModelGovernanceRepository(session)._assert_supervised_validation_evidence(change)
            issued = repository.issue(TENANT_ID, change.id, "validator", "独立验证人")
            self.assertTrue(issued["trust_eligible"])
            self.assertTrue(issued["signature_valid"])
            self.assertEqual(ModelGovernanceRepository(session)._assert_supervised_validation_evidence(change)["report_hash"], "r" * 64)
            self.assertTrue(repository.issue(TENANT_ID, change.id, "validator", "独立验证人")["idempotent"])
            dashboard = repository.approval_dashboard(TENANT_ID, "general")
            self.assertEqual(dashboard["rows"][0]["issuance"]["id"], issued["id"])
            self.assertNotIn("验证报告尚未可信签发", dashboard["rows"][0]["blockers"])
            offline = repository.offline_package(TENANT_ID, issued["id"])
            self.assertEqual(offline["schema_version"], "model-validation-offline-verification-v1")
            self.assertTrue(offline["verification"]["signature_valid"])
            revoked = repository.revoke(TENANT_ID, issued["id"], issued["row_version"], "发现签发主体信息需要修正", "revoker", "撤销复核人")
            self.assertEqual(revoked["status"], "revoked")
            replacement = repository.reissue(TENANT_ID, issued["id"], revoked["row_version"], "保持冻结报告内容并修正签发登记", "third", "换发人")
            self.assertEqual(replacement["supersedes_issuance_id"], issued["id"])
            self.assertTrue(replacement["trust_eligible"])

    def test_unscanned_attachment_blocks_issuance(self):
        with TemporaryDirectory() as directory, database.SessionLocal() as session:
            storage = LocalObjectStorage(directory)
            change = ModelChangeRecord(
                id=str(uuid4()), template_key="general", base_version="v1", candidate_version="v2",
                status="draft", config_json={"version": "v2"}, validation_json={"config_hash": "c" * 64},
                impact_json={}, comparison_evidence_json={}, change_reason="扫描门禁测试", created_by="maker",
                created_by_name="制作者", entity_type="model",
            )
            session.add(change); session.commit()
            attachment = SupervisedValidationAttachmentRepository(session, storage).upload(
                TENANT_ID, change.id, "validation.pdf", "application/pdf", b"pending-scan", "maker", "制作者",
            )
            evidence = {
                "tenant_id": TENANT_ID, "evaluation_id": "evaluation-2", "report_hash": "s" * 64,
                "report_template_version": "supervised-model-validation-v2", "evidence_level": "supervised",
                "independent_validation": {"status": "approved", "risk_level": "medium", "attachments": [{"attachment_id": attachment["id"], "sha256": attachment["sha256"]}]},
            }
            change.supervised_validation_evidence_json = evidence
            change.supervised_validation_binding_hash = content_hash(evidence)
            session.commit()
            with self.assertRaisesRegex(ValueError, "尚未完成安全扫描"):
                ModelValidationIssuanceRepository(session, storage).issue(TENANT_ID, change.id, "validator", "独立验证人")

    def test_ed25519_repository_issuance_and_offline_tamper_detection(self):
        with TemporaryDirectory() as directory, database.SessionLocal() as session:
            storage = LocalObjectStorage(directory)
            change = ModelChangeRecord(
                id=str(uuid4()), template_key="general", base_version="v1", candidate_version="v2",
                status="draft", config_json={"version": "v2"},
                validation_json={"config_hash": "e" * 64}, impact_json={}, comparison_evidence_json={},
                change_reason="Ed25519 仓储签发测试", created_by="maker", created_by_name="制作者", entity_type="model",
            )
            evidence = {
                "tenant_id": TENANT_ID, "evaluation_id": "evaluation-ed25519", "report_hash": "e" * 64,
                "report_template_version": "supervised-model-validation-v2", "evidence_level": "supervised",
                "independent_validation": {"status": "approved", "risk_level": "medium", "attachments": []},
            }
            change.supervised_validation_evidence_json = evidence
            change.supervised_validation_binding_hash = content_hash(evidence)
            session.add(change)
            session.commit()

            signer = Ed25519Signer(Ed25519PrivateKey.generate().private_bytes_raw(), "kms-dev-v2")
            repository = ModelValidationIssuanceRepository(session, storage, signer=signer)
            issued = repository.issue(TENANT_ID, change.id, "validator", "独立验证人")
            self.assertEqual(issued["signature_algorithm"], ED25519_SIGNATURE_ALGORITHM)
            self.assertEqual(issued["signing_key_id"], "kms-dev-v2")
            self.assertTrue(issued["signature_valid"])

            offline = repository.offline_package(TENANT_ID, issued["id"])
            self.assertTrue(offline["verification"]["signature_valid"])
            record = session.get(ModelValidationReportIssuanceRecord, issued["id"])
            record.package_json = {**record.package_json, "tampered": True}
            session.commit()
            tampered = repository.offline_package(TENANT_ID, issued["id"])
            self.assertFalse(tampered["verification"]["package_hash_valid"])
            self.assertTrue(tampered["verification"]["signature_valid"])
            self.assertFalse(tampered["verification"]["registry_valid"])


if __name__ == "__main__":
    unittest.main()
