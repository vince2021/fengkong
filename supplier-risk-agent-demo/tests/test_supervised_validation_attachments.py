from __future__ import annotations

import unittest
from hashlib import sha256
from tempfile import TemporaryDirectory
from uuid import uuid4

import backend.database as database
from backend.database import Base
from backend.db_models import AuditEventRecord, ModelChangeRecord, SupervisedValidationAttachmentRecord
from backend.storage import LocalObjectStorage
from backend.supervised_validation_attachment_repository import SupervisedValidationAttachmentRepository, ValidationAttachmentError
from tests.database_support import IsolatedTestDatabase


class TestSupervisedValidationAttachments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase(); cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        with database.SessionLocal() as session:
            session.query(SupervisedValidationAttachmentRecord).delete()
            session.query(ModelChangeRecord).delete()
            session.query(AuditEventRecord).delete()
            session.commit()

    def test_hash_bound_download_revoke_and_tenant_isolation(self):
        with database.SessionLocal() as session:
            change = ModelChangeRecord(
                id=str(uuid4()), template_key="general", base_version="v1", candidate_version="v2",
                status="draft", config_json={}, validation_json={"valid": True}, impact_json={},
                comparison_evidence_json={}, supervised_validation_evidence_json={}, change_reason="附件闭环测试",
                created_by="maker", created_by_name="制作者", entity_type="model",
            )
            session.add(change); session.commit(); change_id = change.id
            with TemporaryDirectory() as directory:
                repository = SupervisedValidationAttachmentRepository(session, LocalObjectStorage(directory))
                item = repository.upload("tenant-demo-hengxin", change_id, "验证报告.pdf", "application/pdf", b"evidence", "maker", "制作者")
                self.assertEqual(item["sha256"], sha256(b"evidence").hexdigest())
                metadata, body = repository.download("tenant-demo-hengxin", item["id"], "reviewer")
                self.assertEqual(body, b"evidence")
                self.assertEqual(metadata["status"], "active")
                with self.assertRaisesRegex(ValidationAttachmentError, "不存在"):
                    repository.get("tenant-other", item["id"])
                self.assertEqual(repository.revoke("tenant-demo-hengxin", item["id"], "撤回测试", "maker")["status"], "revoked")
                with self.assertRaisesRegex(ValidationAttachmentError, "已撤销"):
                    repository.download("tenant-demo-hengxin", item["id"], "reviewer")


if __name__ == "__main__":
    unittest.main()
