"""Tenant-scoped storage metadata for model validation evidence attachments."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db_models import ModelChangeRecord, SupervisedValidationAttachmentRecord
from backend.repository import AuditRepository
from backend.storage import ObjectStorage


class ValidationAttachmentError(RuntimeError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


class SupervisedValidationAttachmentRepository:
    def __init__(self, session: Session, storage: ObjectStorage) -> None:
        self.session = session
        self.storage = storage
        self.audit = AuditRepository(session)

    def upload(self, tenant_id: str, change_id: str, filename: str, content_type: str, content: bytes, actor: str, actor_name: str) -> dict:
        change = self.session.get(ModelChangeRecord, change_id)
        if not change or change.entity_type != "model":
            raise ValidationAttachmentError("模型变更单不存在", 404)
        if change.status != "draft":
            raise ValidationAttachmentError("只有模型变更草稿可以上传验证附件")
        if not content:
            raise ValidationAttachmentError("附件不能为空")
        if len(content) > 10 * 1024 * 1024:
            raise ValidationAttachmentError("单个验证附件不得超过 10MB")
        safe_name = PurePosixPath(filename.replace("\\", "/")).name[:255]
        if not safe_name or safe_name in {".", ".."}:
            raise ValidationAttachmentError("附件文件名无效")
        digest = sha256(content).hexdigest()
        existing = self.session.scalar(select(SupervisedValidationAttachmentRecord).where(
            SupervisedValidationAttachmentRecord.model_change_id == change_id,
            SupervisedValidationAttachmentRecord.sha256 == digest,
            SupervisedValidationAttachmentRecord.status == "active",
        ))
        if existing:
            return self._view(existing)
        attachment_id = str(uuid4())
        key = f"{tenant_id}/model-validation/{change_id}/{attachment_id}/{safe_name}"
        self.storage.put(key, content, content_type or "application/octet-stream")
        record = SupervisedValidationAttachmentRecord(
            id=attachment_id, tenant_id=tenant_id, model_change_id=change_id,
            original_name=safe_name, content_type=content_type or "application/octet-stream",
            size_bytes=len(content), sha256=digest, storage_key=key,
            status="active", uploaded_by=actor, uploaded_by_name=actor_name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("model_validation_attachment", record.id, "model_validation_attachment_uploaded", actor, {
                "tenant_id": tenant_id, "model_change_id": change_id, "sha256": digest,
                "size_bytes": len(content), "original_name": safe_name,
            })
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            self.storage.delete(key)
            raise ValidationAttachmentError("验证附件已存在或发生并发冲突", 409) from exc
        self.session.refresh(record)
        return self._view(record)

    def list(self, tenant_id: str, change_id: str, include_revoked: bool = False) -> list[dict]:
        statement = select(SupervisedValidationAttachmentRecord).where(
            SupervisedValidationAttachmentRecord.tenant_id == tenant_id,
            SupervisedValidationAttachmentRecord.model_change_id == change_id,
        )
        if not include_revoked:
            statement = statement.where(SupervisedValidationAttachmentRecord.status == "active")
        return [self._view(item) for item in self.session.scalars(statement.order_by(SupervisedValidationAttachmentRecord.uploaded_at)).all()]

    def get(self, tenant_id: str, attachment_id: str) -> SupervisedValidationAttachmentRecord:
        record = self.session.scalar(select(SupervisedValidationAttachmentRecord).where(
            SupervisedValidationAttachmentRecord.tenant_id == tenant_id,
            SupervisedValidationAttachmentRecord.id == attachment_id,
        ))
        if not record:
            raise ValidationAttachmentError("验证附件不存在", 404)
        return record

    def download(self, tenant_id: str, attachment_id: str, actor: str) -> tuple[dict, bytes]:
        record = self.get(tenant_id, attachment_id)
        if record.status != "active":
            raise ValidationAttachmentError("验证附件已撤销，不能下载", 410)
        content = self.storage.get(record.storage_key)
        if sha256(content).hexdigest() != record.sha256:
            raise ValidationAttachmentError("验证附件内容哈希不一致", 409)
        self.audit.append("model_validation_attachment", record.id, "model_validation_attachment_downloaded", actor, {"tenant_id": tenant_id, "sha256": record.sha256})
        self.session.commit()
        return self._view(record), content

    def revoke(self, tenant_id: str, attachment_id: str, reason: str, actor: str) -> dict:
        record = self.get(tenant_id, attachment_id)
        if record.status != "active":
            raise ValidationAttachmentError("验证附件已经撤销")
        record.status = "revoked"
        record.revoked_by = actor
        record.revoked_at = datetime.now(timezone.utc)
        record.revoke_reason = reason
        self.audit.append("model_validation_attachment", record.id, "model_validation_attachment_revoked", actor, {"tenant_id": tenant_id, "reason": reason, "sha256": record.sha256})
        self.session.commit()
        return self._view(record)

    def update_scan(self, tenant_id: str, attachment_id: str, expected_row_version: int, scan_status: str, scan_engine: str, result_reason: str, actor: str, actor_name: str) -> dict:
        if scan_status not in {"pending", "passed", "rejected"}:
            raise ValidationAttachmentError("不支持的附件扫描状态")
        record = self.get(tenant_id, attachment_id)
        if record.row_version != expected_row_version:
            raise ValidationAttachmentError("验证附件扫描状态已变化，请刷新后重试", 409)
        if record.status != "active":
            raise ValidationAttachmentError("已撤销附件不能更新扫描状态", 410)
        try:
            content = self.storage.get(record.storage_key)
        except FileNotFoundError as exc:
            raise ValidationAttachmentError("验证附件对象不存在，不能完成扫描回写", 409) from exc
        if sha256(content).hexdigest() != record.sha256:
            raise ValidationAttachmentError("验证附件内容哈希不一致，不能完成扫描回写", 409)
        record.scan_status = scan_status
        record.scan_engine = scan_engine
        record.scan_result_reason = result_reason
        record.scan_completed_by = actor
        record.scan_completed_by_name = actor_name
        record.scan_completed_at = datetime.now(timezone.utc)
        self.audit.append("model_validation_attachment", record.id, "model_validation_attachment_scanned", actor, {
            "tenant_id": tenant_id, "model_change_id": record.model_change_id, "sha256": record.sha256,
            "scan_status": scan_status, "scan_engine": scan_engine, "result_reason": result_reason,
        })
        try:
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            raise ValidationAttachmentError("验证附件扫描状态保存失败", 409) from exc
        self.session.refresh(record)
        return self._view(record)

    def assert_active_for_change(self, tenant_id: str, change_id: str, attachments: list[dict]) -> None:
        for item in attachments:
            record = self.get(tenant_id, str(item.get("attachment_id", "")))
            if record.model_change_id != change_id or record.status != "active" or record.sha256 != item.get("sha256"):
                raise ValidationAttachmentError("监督验证附件未绑定当前变更单、已撤销或哈希不匹配", 409)

    @staticmethod
    def _view(record: SupervisedValidationAttachmentRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "model_change_id": record.model_change_id,
            "name": record.original_name, "reference": f"attachment:{record.id}",
            "content_type": record.content_type, "size_bytes": record.size_bytes, "sha256": record.sha256,
            "status": record.status, "scan_status": record.scan_status, "uploaded_by_name": record.uploaded_by_name,
            "scan_engine": record.scan_engine, "scan_result_reason": record.scan_result_reason,
            "scan_completed_by": record.scan_completed_by, "scan_completed_by_name": record.scan_completed_by_name,
            "scan_completed_at": record.scan_completed_at.isoformat() if record.scan_completed_at else None,
            "row_version": record.row_version,
            "uploaded_at": record.uploaded_at.isoformat() if record.uploaded_at else None,
            "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
        }
