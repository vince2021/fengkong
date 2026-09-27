"""Governed issuance, revocation, and reissue of model validation reports."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import AuditEventRecord, ModelChangeRecord, ModelReleaseRecord, ModelValidationReportIssuanceRecord, SupervisedValidationAttachmentRecord, TenantRolloutPolicyRecord
from backend.model_risk_catalog import risk_level
from backend.model_risk_policy_repository import ModelRiskPolicyError, ModelRiskPolicyRepository
from backend.repository import AuditRepository, ConcurrentUpdateError, content_hash
from backend.storage import ObjectStorage
from backend.model_validation_signing import LEGACY_SIGNATURE_ALGORITHM, ModelValidationSigner, build_model_validation_signer, public_key_fingerprint, verify_signature


SIGNATURE_ALGORITHM = LEGACY_SIGNATURE_ALGORITHM


class ModelValidationIssuanceRepository:
    def __init__(self, session: Session, storage: ObjectStorage, signer: ModelValidationSigner | None = None) -> None:
        self.session = session
        self.storage = storage
        self.audit = AuditRepository(session)
        self.signer = signer or build_model_validation_signer()

    def list(self, tenant_id: str, change_id: str) -> list[dict]:
        self._change(tenant_id, change_id)
        rows = self.session.scalars(select(ModelValidationReportIssuanceRecord).where(
            ModelValidationReportIssuanceRecord.tenant_id == tenant_id,
            ModelValidationReportIssuanceRecord.model_change_id == change_id,
        ).order_by(ModelValidationReportIssuanceRecord.issued_at.desc())).all()
        return [self._view(row) for row in rows]

    def get(self, tenant_id: str, issuance_id: str) -> dict:
        return self._view(self._record(tenant_id, issuance_id), include_package=True)

    def approval_dashboard(self, tenant_id: str, template_key: str | None = None) -> dict:
        risk_governance = ModelRiskPolicyRepository(self.session)
        current_risk_policy = risk_governance.current_catalog(tenant_id)
        statement = select(ModelChangeRecord).where(ModelChangeRecord.entity_type == "model")
        if template_key:
            statement = statement.where(ModelChangeRecord.template_key == template_key)
        changes = self.session.scalars(statement.order_by(ModelChangeRecord.created_at.desc())).all()
        restart_events = self.session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.event_type == "tenant_rollout_policy_restart_requested",
        )).all()
        restarted_change_ids = {str((event.payload or {}).get("model_change_id")) for event in restart_events}
        rows = []
        for change in changes:
            evidence = deepcopy(change.supervised_validation_evidence_json or {})
            if evidence and evidence.get("tenant_id") != tenant_id:
                continue
            active_issuance = self.session.scalar(select(ModelValidationReportIssuanceRecord).where(
                ModelValidationReportIssuanceRecord.tenant_id == tenant_id,
                ModelValidationReportIssuanceRecord.model_change_id == change.id,
                ModelValidationReportIssuanceRecord.revoked_at.is_(None),
            ).order_by(ModelValidationReportIssuanceRecord.issued_at.desc()))
            latest_issuance = self.session.scalar(select(ModelValidationReportIssuanceRecord).where(
                ModelValidationReportIssuanceRecord.tenant_id == tenant_id,
                ModelValidationReportIssuanceRecord.model_change_id == change.id,
            ).order_by(ModelValidationReportIssuanceRecord.issued_at.desc()))
            active_attachments = self.session.scalars(select(SupervisedValidationAttachmentRecord).where(
                SupervisedValidationAttachmentRecord.tenant_id == tenant_id,
                SupervisedValidationAttachmentRecord.model_change_id == change.id,
                SupervisedValidationAttachmentRecord.status == "active",
            )).all() if evidence else []
            blockers = self._dashboard_blockers(change, evidence, active_issuance)
            risk_acceptance = risk_governance.current_acceptance_snapshot(tenant_id, change.id, required=False) if evidence else None
            if evidence and current_risk_policy["source"] == "tenant_policy":
                if not risk_acceptance:
                    blockers.append("模型风险接受台账尚未创建")
                elif risk_acceptance["effective_status"] != "accepted":
                    blockers.append({
                        "pending": "模型风险接受席位尚未全部签署",
                        "overdue": "模型风险接受已超过复核期限",
                        "policy_stale": "模型风险接受政策版本已失效",
                        "evidence_stale": "模型风险接受监督证据已变化",
                    }.get(risk_acceptance["effective_status"], "模型风险接受当前不可用"))
                if active_issuance and risk_acceptance:
                    frozen_risk = (active_issuance.package_json or {}).get("risk_classification") or {}
                    frozen_acceptance = frozen_risk.get("risk_acceptance") or {}
                    if (
                        frozen_risk.get("policy_id") != (current_risk_policy.get("policy") or {}).get("id")
                        or frozen_risk.get("catalog_hash") != current_risk_policy["config_hash"]
                        or frozen_acceptance.get("id") != risk_acceptance.get("id")
                    ):
                        blockers.append("签发报告未冻结当前风险政策与接受结论")
            attachment_refs = (evidence.get("independent_validation") or {}).get("attachments") if evidence else []
            if attachment_refs:
                attachments_by_id = {item.id: item for item in active_attachments}
                for attachment_ref in attachment_refs:
                    attachment = attachments_by_id.get(attachment_ref.get("attachment_id"))
                    if not attachment or attachment.sha256 != attachment_ref.get("sha256"):
                        blockers.append("验证附件缺失或哈希不匹配")
                    elif attachment.scan_status != "passed":
                        blockers.append("验证附件尚未完成安全扫描")
            release = self.session.scalar(select(ModelReleaseRecord).where(ModelReleaseRecord.source_change_id == change.id))
            in_service_risk = None
            if release and current_risk_policy["source"] == "tenant_policy":
                try:
                    in_service_risk = risk_governance.in_service_release_status(tenant_id, release.id)
                    if change.status == "published" and in_service_risk["effective_status"] != "accepted":
                        blockers.append({
                            "required": "在役模型风险接受已到期，请发起运行证据再接受",
                            "pending": "在役模型再接受席位尚未全部签署",
                            "overdue": "在役模型再接受已超过复核期限",
                            "policy_stale": "在役模型再接受政策版本已失效",
                            "evidence_stale": "在役模型再接受监督证据已变化",
                            "release_stale": "在役模型再接受绑定的发布配置已变化",
                            "revoked": "在役模型再接受已撤销",
                        }.get(in_service_risk["effective_status"], "在役模型风险接受当前不可用"))
                except ModelRiskPolicyError as exc:
                    in_service_risk = {"required": True, "effective_status": "required", "release_id": release.id, "reacceptance": None}
                    if change.status == "published":
                        blockers.append(exc.message)
            original_policy = self.session.get(TenantRolloutPolicyRecord, evidence.get("policy_id")) if evidence.get("policy_id") else None
            if change.id in restarted_change_ids:
                restart_status = "draft_created"
            elif change.status == "published" and original_policy and original_policy.status in {"rolled_back", "completed"}:
                restart_status = "eligible"
            elif evidence.get("policy_id"):
                restart_status = "awaiting_release" if change.status != "published" else "awaiting_terminal_policy"
            else:
                restart_status = "not_applicable"
            rows.append({
                "change_id": change.id, "template_key": change.template_key,
                "base_version": change.base_version, "candidate_version": change.candidate_version,
                "change_status": change.status, "created_by_name": change.created_by_name,
                "created_at": change.created_at.isoformat() if change.created_at else None,
                "supervised": bool(evidence), "report_hash": evidence.get("report_hash"),
                "risk_level": (evidence.get("independent_validation") or {}).get("risk_level") or (evidence.get("risk_classification") or {}).get("proposed_level"),
                "independent_validation_status": (evidence.get("independent_validation") or {}).get("status") if evidence else "not_required",
                "release_approval_status": (evidence.get("release_approval") or {}).get("status") if evidence else ("approved" if change.status == "published" else "pending"),
                "attachment_count": len(active_attachments),
                "attachment_hashes": [item.sha256 for item in active_attachments],
                "risk_policy": {"source": current_risk_policy["source"], "version": current_risk_policy["version"], "config_hash": current_risk_policy["config_hash"]},
                "risk_acceptance": risk_acceptance,
                "issuance": self._view(latest_issuance) if latest_issuance else None,
                "release": {"id": release.id, "model_version": release.model_version, "is_active": release.is_active} if release else None,
                "in_service_risk": in_service_risk,
                "restart_status": restart_status, "source_policy_id": evidence.get("policy_id"),
                "blockers": blockers, "ready_for_submit": change.status == "draft" and not blockers,
                "ready_for_release": change.status == "pending_review" and not blockers,
            })
        counts = {
            "total": len(rows), "blocked": sum(bool(item["blockers"]) for item in rows),
            "pending_validation": sum(item["independent_validation_status"] == "pending" for item in rows),
            "pending_release": sum(item["change_status"] == "pending_review" for item in rows),
            "published": sum(item["change_status"] == "published" for item in rows),
            "restart_eligible": sum(item["restart_status"] == "eligible" for item in rows),
        }
        return {"schema_version": "model-release-approval-dashboard-v1", "tenant_id": tenant_id, "counts": counts, "rows": rows}

    def issue(self, tenant_id: str, change_id: str, actor_subject: str, actor_name: str) -> dict:
        change = self._change(tenant_id, change_id)
        evidence = deepcopy(change.supervised_validation_evidence_json or {})
        self._assert_evidence(change, evidence)
        if change.created_by == actor_subject:
            raise PermissionError("模型变更制作者不能签发本人变更的独立验证报告")
        package = self._package(change, evidence)
        active = self.session.scalar(select(ModelValidationReportIssuanceRecord).where(
            ModelValidationReportIssuanceRecord.model_change_id == change.id,
            ModelValidationReportIssuanceRecord.report_hash == evidence["report_hash"],
            ModelValidationReportIssuanceRecord.revoked_at.is_(None),
        ))
        if active:
            if active.package_hash == content_hash(package):
                return {**self._view(active, include_package=True), "idempotent": True}
            raise ValueError("当前报告已有有效签发记录；政策或证据变化时必须先撤销，再按当前证据重新签发")
        issued_at = datetime.now(timezone.utc)
        issuance_id = str(uuid4())
        package_hash = content_hash(package)
        signature_body = self._signature_body(issuance_id, package_hash, actor_subject, actor_name, issued_at, signature_algorithm=self.signer.algorithm, signing_key_id=self.signer.key_id)
        record = ModelValidationReportIssuanceRecord(
            id=issuance_id, tenant_id=tenant_id, model_change_id=change.id,
            report_template_version=evidence["report_template_version"], report_hash=evidence["report_hash"],
            evidence_binding_hash=change.supervised_validation_binding_hash, package_json=package,
            package_hash=package_hash, signature_algorithm=self.signer.algorithm,
            signing_key_id=self.signer.key_id, signing_public_key=self.signer.public_key,
            signature=self.signer.sign(signature_body),
            issued_by=actor_subject, issued_by_name=actor_name, issued_at=issued_at,
        )
        self.session.add(record)
        return self._commit(record, "model_validation_report_issued", actor_subject, {
            "tenant_id": tenant_id, "model_change_id": change.id, "report_hash": record.report_hash,
            "package_hash": package_hash, "signature": record.signature, "signature_algorithm": record.signature_algorithm,
            "signing_key_id": record.signing_key_id, "public_key_fingerprint": public_key_fingerprint(record.signing_public_key),
        }, idempotent=False)

    def revoke(self, tenant_id: str, issuance_id: str, expected_row_version: int, reason: str, actor_subject: str, actor_name: str) -> dict:
        record = self._record(tenant_id, issuance_id)
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("验证报告签发状态已变化，请刷新后重试")
        if record.revoked_at is not None:
            raise ValueError("验证报告签发记录已经撤销")
        if record.issued_by == actor_subject:
            raise PermissionError("验证报告签发人与撤销人必须分离")
        record.revoked_by, record.revoked_by_name = actor_subject, actor_name
        record.revoked_at, record.revocation_reason = datetime.now(timezone.utc), reason
        return self._commit(record, "model_validation_report_revoked", actor_subject, {
            "tenant_id": tenant_id, "model_change_id": record.model_change_id,
            "report_hash": record.report_hash, "signature": record.signature, "reason": reason,
        })

    def reissue(self, tenant_id: str, issuance_id: str, expected_row_version: int, reason: str, actor_subject: str, actor_name: str) -> dict:
        source = self._record(tenant_id, issuance_id)
        if source.row_version != expected_row_version:
            raise ConcurrentUpdateError("验证报告签发状态已变化，请刷新后重试")
        if source.revoked_at is None:
            raise ValueError("只有已撤销的验证报告可以换发")
        if actor_subject in {source.issued_by, source.revoked_by}:
            raise PermissionError("换发人必须区别于原签发人与撤销人")
        source_view = self._view(source, include_package=True)
        if not source_view["registry_valid"]:
            raise ValueError("原签发登记完整性异常，不能换发")
        change = self._change(tenant_id, source.model_change_id)
        current_package = self._package(change, deepcopy(change.supervised_validation_evidence_json or {}))
        if content_hash(current_package) != source.package_hash:
            raise ValueError("原冻结包与当前风险政策或监督证据不一致，不能原样换发；请重新签发")
        existing = self.session.scalar(select(ModelValidationReportIssuanceRecord).where(
            ModelValidationReportIssuanceRecord.supersedes_issuance_id == source.id
        ))
        if existing:
            raise ValueError("该验证报告已经完成换发")
        issued_at = datetime.now(timezone.utc)
        replacement_id = str(uuid4())
        signature_body = self._signature_body(replacement_id, source.package_hash, actor_subject, actor_name, issued_at, source.id, reason, self.signer.algorithm, self.signer.key_id)
        replacement = ModelValidationReportIssuanceRecord(
            id=replacement_id, tenant_id=tenant_id, model_change_id=source.model_change_id,
            report_template_version=source.report_template_version, report_hash=source.report_hash,
            evidence_binding_hash=source.evidence_binding_hash, package_json=deepcopy(source.package_json),
            package_hash=source.package_hash, signature_algorithm=self.signer.algorithm,
            signing_key_id=self.signer.key_id, signing_public_key=self.signer.public_key,
            signature=self.signer.sign(signature_body),
            issued_by=actor_subject, issued_by_name=actor_name, issued_at=issued_at,
            supersedes_issuance_id=source.id, reissue_reason=reason,
        )
        self.session.add(replacement)
        return self._commit(replacement, "model_validation_report_reissued", actor_subject, {
            "tenant_id": tenant_id, "model_change_id": source.model_change_id,
            "report_hash": source.report_hash, "signature": replacement.signature,
            "supersedes_issuance_id": source.id, "reason": reason,
        })

    def _change(self, tenant_id: str, change_id: str) -> ModelChangeRecord:
        change = self.session.get(ModelChangeRecord, change_id)
        evidence = deepcopy(change.supervised_validation_evidence_json or {}) if change else {}
        if not change or change.entity_type != "model" or evidence.get("tenant_id") != tenant_id:
            raise LookupError("当前租户下不存在该监督模型变更单")
        return change

    def _record(self, tenant_id: str, issuance_id: str) -> ModelValidationReportIssuanceRecord:
        record = self.session.scalar(select(ModelValidationReportIssuanceRecord).where(
            ModelValidationReportIssuanceRecord.tenant_id == tenant_id,
            ModelValidationReportIssuanceRecord.id == issuance_id,
        ))
        if not record:
            raise LookupError("验证报告签发记录不存在")
        return record

    def _assert_evidence(self, change: ModelChangeRecord, evidence: dict) -> None:
        if not evidence or not change.supervised_validation_binding_hash or content_hash(evidence) != change.supervised_validation_binding_hash:
            raise ValueError("监督验证证据完整性校验失败")
        if evidence.get("evidence_level") != "supervised":
            raise ValueError("非监督降级证据不能签发正式验证报告")
        if (evidence.get("independent_validation") or {}).get("status") != "approved":
            raise ValueError("独立验证尚未批准，不能签发报告")
        if not evidence.get("report_hash") or not evidence.get("report_template_version"):
            raise ValueError("监督验证证据缺少报告哈希或模板版本")

    @staticmethod
    def _dashboard_blockers(change: ModelChangeRecord, evidence: dict, issuance: ModelValidationReportIssuanceRecord | None) -> list[str]:
        blockers: list[str] = []
        model_risk = (change.validation_json or {}).get("model_risk") or {}
        if (model_risk.get("release_gate") or {}).get("passed") is False:
            blockers.append((model_risk.get("release_gate") or {}).get("summary") or "模型验证门禁未通过")
        comparison = deepcopy(change.comparison_evidence_json or {})
        if comparison and (comparison.get("current_effective_status") or comparison.get("effective_status")) not in {"passed", "exception_approved"}:
            blockers.append("Champion/Challenger 比较证据未通过")
        if change.scorecard_validation_evidence_json and not change.scorecard_validation_binding_hash:
            blockers.append("评分卡验证证据未完成绑定")
        if change.calibration_evidence_json and not change.calibration_evidence_binding_hash:
            blockers.append("校准证据未完成绑定")
        if evidence:
            independent = evidence.get("independent_validation") or {}
            if independent.get("status") != "approved":
                blockers.append("独立验证尚未批准")
            if not issuance:
                blockers.append("验证报告尚未可信签发")
            elif issuance.evidence_binding_hash != change.supervised_validation_binding_hash:
                blockers.append("签发报告与当前监督证据不一致")
        return blockers

    def _package(self, change: ModelChangeRecord, evidence: dict) -> dict:
        independent = evidence["independent_validation"]
        attachment_refs = independent.get("attachments") or []
        attachments = []
        for item in attachment_refs:
            attachment_id = item.get("attachment_id")
            record = self.session.scalar(select(SupervisedValidationAttachmentRecord).where(
                SupervisedValidationAttachmentRecord.tenant_id == evidence["tenant_id"],
                SupervisedValidationAttachmentRecord.model_change_id == change.id,
                SupervisedValidationAttachmentRecord.id == attachment_id,
            ))
            if not record or record.status != "active" or record.sha256 != item.get("sha256"):
                raise ValueError("验证报告附件已撤销、归属不符或哈希不匹配")
            if record.scan_status != "passed":
                raise ValueError("验证报告附件尚未完成安全扫描，不能进入可信签发包")
            content = self.storage.get(record.storage_key)
            if sha256(content).hexdigest() != record.sha256:
                raise ValueError("验证报告附件对象内容哈希不一致")
            attachments.append({
                "attachment_id": record.id, "name": record.original_name, "content_type": record.content_type,
                "size_bytes": record.size_bytes, "sha256": record.sha256, "scan_status": record.scan_status,
            })
        risk_governance = ModelRiskPolicyRepository(self.session)
        policy_snapshot = risk_governance.policy_snapshot(evidence["tenant_id"])
        if policy_snapshot["source"] == "tenant_policy":
            acceptance_snapshot = risk_governance.current_acceptance_snapshot(evidence["tenant_id"], change.id, required=True)
            level = next((item for item in policy_snapshot["items"] if item["level"] == independent["risk_level"]), None)
            if level is None:
                raise ValueError("独立验证风险等级不在当前租户政策中")
        else:
            acceptance_snapshot = None
            level = risk_level(independent["risk_level"])
        return {
            "schema_version": "model-validation-issued-report-v1",
            "tenant_id": evidence["tenant_id"],
            "model_change": {"id": change.id, "template_key": change.template_key, "base_version": change.base_version, "candidate_version": change.candidate_version, "config_hash": change.validation_json.get("config_hash")},
            "report": {"evaluation_id": evidence.get("evaluation_id"), "report_hash": evidence["report_hash"], "report_template_version": evidence["report_template_version"], "evidence_level": evidence["evidence_level"], "evidence_binding_hash": change.supervised_validation_binding_hash},
            "independent_validation": deepcopy(independent),
            "risk_classification": {
                "catalog_source": policy_snapshot["source"], "catalog_version": policy_snapshot["version"],
                "policy_id": (policy_snapshot.get("policy") or {}).get("id"), "selected": level,
                "catalog_hash": policy_snapshot["config_hash"], "risk_acceptance": acceptance_snapshot,
            },
            "attachments": attachments,
            "governance_boundary": {"issued_report_is_release_approval": False, "auto_published": False, "traffic_changed": False},
        }

    @staticmethod
    def _signature_body(issuance_id: str, package_hash: str, actor_subject: str, actor_name: str, issued_at: datetime, supersedes: str | None = None, reason: str | None = None, signature_algorithm: str = SIGNATURE_ALGORITHM, signing_key_id: str | None = None) -> dict:
        normalized = issued_at.replace(tzinfo=timezone.utc) if issued_at.tzinfo is None else issued_at.astimezone(timezone.utc)
        body = {"id": issuance_id, "package_hash": package_hash, "signature_algorithm": signature_algorithm, "issued_by": actor_subject, "issued_by_name": actor_name, "issued_at": normalized.isoformat(), "supersedes_issuance_id": supersedes, "reissue_reason": reason}
        if signing_key_id:
            body["signing_key_id"] = signing_key_id
        return body

    def _view(self, record: ModelValidationReportIssuanceRecord, include_package: bool = False) -> dict:
        signature_body = self._signature_body(record.id, record.package_hash, record.issued_by, record.issued_by_name, record.issued_at, record.supersedes_issuance_id, record.reissue_reason, record.signature_algorithm, record.signing_key_id)
        package_hash_valid = content_hash(record.package_json) == record.package_hash
        signature_valid = verify_signature(record.signature_algorithm, signature_body, record.signature, record.signing_public_key)
        replacement = self.session.scalar(select(ModelValidationReportIssuanceRecord.id).where(ModelValidationReportIssuanceRecord.supersedes_issuance_id == record.id))
        result = {
            "id": record.id, "tenant_id": record.tenant_id, "model_change_id": record.model_change_id,
            "report_template_version": record.report_template_version, "report_hash": record.report_hash,
            "evidence_binding_hash": record.evidence_binding_hash, "package_hash": record.package_hash,
            "signature_algorithm": record.signature_algorithm, "signature": record.signature,
            "signing_key_id": record.signing_key_id, "public_key_fingerprint": public_key_fingerprint(record.signing_public_key),
            "issued_by": record.issued_by, "issued_by_name": record.issued_by_name, "issued_at": record.issued_at.isoformat(),
            "status": "revoked" if record.revoked_at else "active", "revoked_by": record.revoked_by,
            "revoked_by_name": record.revoked_by_name, "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
            "revocation_reason": record.revocation_reason, "supersedes_issuance_id": record.supersedes_issuance_id,
            "replacement_issuance_id": replacement, "reissue_reason": record.reissue_reason,
            "package_hash_valid": package_hash_valid, "signature_valid": signature_valid,
            "registry_valid": package_hash_valid and signature_valid,
            "trust_eligible": record.revoked_at is None and package_hash_valid and signature_valid,
            "row_version": record.row_version,
        }
        if include_package:
            result["package"] = deepcopy(record.package_json)
        return result

    def offline_package(self, tenant_id: str, issuance_id: str) -> dict:
        record = self._record(tenant_id, issuance_id)
        view = self._view(record)
        return {
            "schema_version": "model-validation-offline-verification-v1",
            "issued_at": view["issued_at"],
            "issuance": view,
            "package": deepcopy(record.package_json),
            "verification": {
                "package_hash": record.package_hash,
                "signature_algorithm": record.signature_algorithm,
                "signing_key_id": record.signing_key_id,
                "signing_public_key": record.signing_public_key,
                "public_key_fingerprint": public_key_fingerprint(record.signing_public_key),
                "package_hash_valid": view["package_hash_valid"],
                "signature_valid": view["signature_valid"],
                "registry_valid": view["registry_valid"],
            },
        }

    def _commit(self, record: ModelValidationReportIssuanceRecord, event_type: str, actor: str, payload: dict, **extra: object) -> dict:
        try:
            self.session.flush()
            self.audit.append("model_validation_report_issuance", record.id, event_type, actor, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("验证报告签发状态发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return {**self._view(record, include_package=True), **extra}
