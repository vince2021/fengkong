"""Tenant-scoped model-risk policy versions and risk acceptance register."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from math import ceil
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import AuditEventRecord, ModelChangeRecord, ModelMonitoringRunRecord, ModelReleaseRecord, ModelRiskAcceptanceRecord, ModelRiskReacceptanceRecord, ModelRiskReviewAssignmentRecord, ModelRiskReviewDelegationRecord, ModelRiskReviewSavedViewRecord, ModelRiskReviewSlaSnapshotRecord, NotificationRecord, TenantMembershipRecord, TenantModelRiskPolicyRecord, TenantMonitoringDiffCaseRecord, TenantMonitoringRunRecord, TenantOutcomeLabelDefinitionRecord, TenantOutcomeLabelRecord, TenantRolloutPolicyRecord, TenantSupervisedEvaluationRecord
from backend.model_risk_catalog import risk_catalog
from backend.repository import AuditRepository, NotificationRepository, content_hash, monitoring_run_evidence_hash
from backend.model_validation_signing import ModelValidationSigner, build_model_validation_signer, public_key_fingerprint, signing_key_metadata, verify_signature


ROLE_BINDINGS = {
    "model_owner": "model_admin",
    "risk_manager": "risk_manager",
    "model_risk_committee": "approver",
}


class ModelRiskPolicyError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


AUDIT_PACKAGE_DOWNLOAD_EVENT = "model_risk_reacceptance_audit_package_downloaded"
REVIEW_RESPONSIBILITY_ROLES = frozenset({"risk_manager", "model_admin", "approver", "admin"})


class ModelRiskPolicyRepository:
    def __init__(self, session: Session, signer: ModelValidationSigner | None = None) -> None:
        self.session = session
        self.audit = AuditRepository(session)
        self.signer = signer or build_model_validation_signer()

    def current_catalog(self, tenant_id: str) -> dict:
        policy = self._active_policy(tenant_id)
        if policy is None:
            items = risk_catalog()
            return {
                "source": "platform_default", "version": "model-risk-catalog-v1",
                "policy": None, "items": items, "config_hash": content_hash(items),
            }
        return {
            "source": "tenant_policy", "version": f"tenant-v{policy.version}",
            "policy": self._policy_view(policy), "items": deepcopy(policy.levels_json),
            "config_hash": policy.config_hash,
        }

    def list_policies(self, tenant_id: str) -> list[dict]:
        rows = self.session.scalars(select(TenantModelRiskPolicyRecord).where(
            TenantModelRiskPolicyRecord.tenant_id == tenant_id,
        ).order_by(TenantModelRiskPolicyRecord.version.desc())).all()
        return [self._policy_view(row) for row in rows]

    def create_policy(self, tenant_id: str, payload: dict, actor_subject: str, actor_name: str) -> dict:
        levels = self._validate_levels(payload["levels"])
        version = int(self.session.scalar(select(func.max(TenantModelRiskPolicyRecord.version)).where(
            TenantModelRiskPolicyRecord.tenant_id == tenant_id,
        )) or 0) + 1
        config = {"name": payload["name"], "description": payload["description"], "levels": levels}
        record = TenantModelRiskPolicyRecord(
            id=str(uuid4()), tenant_id=tenant_id, version=version, name=payload["name"],
            description=payload["description"], levels_json=levels, config_hash=content_hash(config),
            status="draft", is_active=False, change_reason=payload["reason"],
            created_by=actor_subject, created_by_name=actor_name,
        )
        self.session.add(record)
        return self._commit_policy(record, "tenant_model_risk_policy_created", actor_subject, payload["reason"])

    def submit_policy(self, tenant_id: str, policy_id: str, expected_row_version: int, reason: str, actor_subject: str) -> dict:
        record = self._policy(tenant_id, policy_id)
        self._check_version(record.row_version, expected_row_version)
        if record.status not in {"draft", "rejected"}:
            raise ModelRiskPolicyError("POLICY_STATUS_INVALID", "只有草稿或已驳回政策可以提交复核", 409)
        record.status = "pending_review"
        record.change_reason = reason
        record.submitted_at = self._now()
        record.reviewed_by = record.reviewed_by_name = record.review_comment = None
        record.reviewed_at = None
        return self._commit_policy(record, "tenant_model_risk_policy_submitted", actor_subject, reason)

    def review_policy(self, tenant_id: str, policy_id: str, expected_row_version: int, decision: str, comment: str, actor_subject: str, actor_name: str) -> dict:
        record = self._policy(tenant_id, policy_id)
        self._check_version(record.row_version, expected_row_version)
        if record.status != "pending_review":
            raise ModelRiskPolicyError("POLICY_STATUS_INVALID", "只有待复核政策可以审核", 409)
        if record.created_by == actor_subject:
            raise ModelRiskPolicyError("FOUR_EYES_REQUIRED", "政策创建人与复核人必须为不同人员", 409)
        now = self._now()
        record.reviewed_by, record.reviewed_by_name = actor_subject, actor_name
        record.reviewed_at, record.review_comment = now, comment
        if decision == "reject":
            record.status = "rejected"
            event_type = "tenant_model_risk_policy_rejected"
        else:
            active_rows = self.session.scalars(select(TenantModelRiskPolicyRecord).where(
                TenantModelRiskPolicyRecord.tenant_id == tenant_id,
                TenantModelRiskPolicyRecord.is_active.is_(True),
            )).all()
            for active in active_rows:
                active.status, active.is_active = "retired", False
            self.session.flush()
            acceptances = self.session.scalars(select(ModelRiskAcceptanceRecord).where(
                ModelRiskAcceptanceRecord.tenant_id == tenant_id,
                ModelRiskAcceptanceRecord.status.in_(["pending", "accepted"]),
            )).all()
            for acceptance in acceptances:
                acceptance.status = "revoked"
                acceptance.revoked_by, acceptance.revoked_by_name = actor_subject, actor_name
                acceptance.revoked_at = now
                acceptance.revocation_reason = f"模型风险政策已更新至 tenant-v{record.version}，原接受结论自动失效"
            reacceptances = self.session.scalars(select(ModelRiskReacceptanceRecord).where(
                ModelRiskReacceptanceRecord.tenant_id == tenant_id,
                ModelRiskReacceptanceRecord.status.in_(["pending", "accepted"]),
            )).all()
            for reacceptance in reacceptances:
                reacceptance.status = "revoked"
                reacceptance.revoked_by, reacceptance.revoked_by_name = actor_subject, actor_name
                reacceptance.revoked_at = now
                reacceptance.revocation_reason = f"模型风险政策已更新至 tenant-v{record.version}，在役再接受结论自动失效"
            record.status, record.is_active, record.published_at = "published", True, now
            event_type = "tenant_model_risk_policy_published"
        return self._commit_policy(record, event_type, actor_subject, comment)

    def list_acceptances(self, tenant_id: str, change_id: str | None = None) -> list[dict]:
        statement = select(ModelRiskAcceptanceRecord).where(ModelRiskAcceptanceRecord.tenant_id == tenant_id)
        if change_id:
            statement = statement.where(ModelRiskAcceptanceRecord.model_change_id == change_id)
        rows = self.session.scalars(statement.order_by(ModelRiskAcceptanceRecord.created_at.desc())).all()
        return [self._acceptance_view(row) for row in rows]

    def review_queue(self, tenant_id: str, now: datetime | None = None, horizon_days: int = 30) -> list[dict]:
        if not 1 <= horizon_days <= 90:
            raise ModelRiskPolicyError("REVIEW_HORIZON_INVALID", "复核窗口须为 1 至 90 天")
        scan_at = self._as_utc(now or self._now())
        rows = self.session.scalars(select(ModelRiskAcceptanceRecord).where(
            ModelRiskAcceptanceRecord.tenant_id == tenant_id,
            ModelRiskAcceptanceRecord.status == "accepted",
            ModelRiskAcceptanceRecord.review_due_at <= scan_at + timedelta(days=horizon_days),
        ).order_by(ModelRiskAcceptanceRecord.review_due_at, ModelRiskAcceptanceRecord.id)).all()
        queue = []
        for row in rows:
            view = self._acceptance_view(row, now=scan_at)
            if view["effective_status"] not in {"accepted", "overdue"}:
                continue
            remaining = ceil((self._as_utc(row.review_due_at) - scan_at).total_seconds() / 86400)
            owners = {(item["actor_subject"], item["platform_role"], item["actor_name"])
                      for item in row.approvals_json or []}
            owners.add((row.created_by, "model_admin", row.created_by_name))
            queue.append({
                "acceptance_id": row.id, "model_change_id": row.model_change_id,
                "risk_level": row.risk_level, "policy_version": row.policy_version,
                "review_due_at": view["review_due_at"], "days_remaining": remaining,
                "level": "overdue" if self._as_utc(row.review_due_at) <= scan_at else "due_soon" if remaining <= 7 else "upcoming",
                "responsible": [{"subject": subject, "role": role, "name": name}
                                for subject, role, name in sorted(owners)],
            })
        return queue

    def scan_reviews(self, tenant_id: str, actor_subject: str, now: datetime | None = None) -> dict:
        scan_at = self._as_utc(now or self._now())
        queue = self.review_queue(tenant_id, scan_at)
        notifications = NotificationRepository(self.session)
        created_count = 0
        resolved_count = 0
        prior = self.session.scalars(select(NotificationRecord).where(
            NotificationRecord.tenant_id == tenant_id,
            NotificationRecord.category == "model_risk_review",
            NotificationRecord.status != "resolved",
        )).all()
        active_levels = {item["acceptance_id"]: item["level"] for item in queue}
        for notice in prior:
            acceptance_id = (notice.action_json or {}).get("acceptance_id")
            if acceptance_id in active_levels and notice.level == active_levels[acceptance_id]:
                continue
            acceptance = self.session.get(ModelRiskAcceptanceRecord, acceptance_id) if acceptance_id else None
            if acceptance_id not in active_levels and acceptance and acceptance.tenant_id == tenant_id and acceptance.status == "accepted" and self._acceptance_view(acceptance, scan_at)["effective_status"] in {"accepted", "overdue"}:
                continue
            notice.status, notice.read_at = "resolved", scan_at
            resolved_count += 1
            self.audit.append("notification", notice.id, "model_risk_review_notification_resolved", actor_subject, {
                "tenant_id": tenant_id, "acceptance_id": acceptance_id,
            })
        for item in queue:
            # One notification per stage and person; reruns cannot flood the inbox.
            level = item["level"]
            for person in item["responsible"]:
                payload = {
                    "case_id": None, "counterparty_id": None,
                    "recipient_role": person["role"], "recipient_subject": person["subject"],
                    "category": "model_risk_review", "level": level,
                    "severity": "critical" if level == "overdue" else "warning",
                    "title": "模型风险接受复核已逾期" if level == "overdue" else "模型风险接受即将到期",
                    "message": f"模型变更 {item['model_change_id']} 的风险接受须在 {item['review_due_at']} 复核；到期后原结论不可用于新签发或发布。",
                    "action_json": {"page": "model-governance", "model_change_id": item["model_change_id"],
                                    "acceptance_id": item["acceptance_id"]},
                    "dedup_key": f"model-risk-review:{item['acceptance_id']}:{item['review_due_at']}:{level}:{person['subject']}:{person['role']}",
                    "status": "unread",
                }
                notification, created = notifications.create_if_absent(tenant_id, payload)
                if created:
                    created_count += 1
                    self.audit.append("notification", notification["id"], "model_risk_review_notified", actor_subject, {
                        "tenant_id": tenant_id, "acceptance_id": item["acceptance_id"],
                        "level": level, "recipient_subject": person["subject"],
                    })
        result = {"scanned_at": scan_at.isoformat(), "items_scanned": len(queue),
                  "overdue": sum(item["level"] == "overdue" for item in queue),
                  "notifications_created": created_count, "notifications_resolved": resolved_count}
        self.audit.append("model_risk_review_scan", f"{tenant_id}:{scan_at.date().isoformat()}",
                          "model_risk_review_scanned", actor_subject, {"tenant_id": tenant_id, **result})
        self.session.commit()
        return result

    def create_acceptance(self, tenant_id: str, change_id: str, rationale: str, actor_subject: str, actor_name: str) -> dict:
        policy = self._active_policy(tenant_id)
        if policy is None:
            raise ModelRiskPolicyError("TENANT_POLICY_REQUIRED", "请先发布租户模型风险政策，再创建风险接受台账", 409)
        change, evidence = self._change(tenant_id, change_id)
        if change.status != "draft":
            raise ModelRiskPolicyError("CHANGE_STATUS_INVALID", "仅草稿模型变更可以新建风险接受台账", 409)
        independent = evidence.get("independent_validation") or {}
        if independent.get("status") != "approved":
            raise ModelRiskPolicyError("VALIDATION_REQUIRED", "独立验证尚未批准，不能发起风险接受", 409)
        risk_level = independent.get("risk_level")
        level = self._level(policy.levels_json, risk_level)
        existing = self.session.scalar(select(ModelRiskAcceptanceRecord).where(
            ModelRiskAcceptanceRecord.tenant_id == tenant_id,
            ModelRiskAcceptanceRecord.model_change_id == change.id,
            ModelRiskAcceptanceRecord.status.in_(["pending", "accepted"]),
        ))
        if existing:
            if existing.policy_id == policy.id and existing.evidence_binding_hash == change.supervised_validation_binding_hash:
                return {**self._acceptance_view(existing), "idempotent": True}
            existing.status = "revoked"
            existing.revoked_by, existing.revoked_by_name = actor_subject, actor_name
            existing.revoked_at = self._now()
            existing.revocation_reason = "政策版本或监督验证证据已变化，原接受台账自动失效"
            self.session.flush()
        record = ModelRiskAcceptanceRecord(
            id=str(uuid4()), tenant_id=tenant_id, model_change_id=change.id,
            policy_id=policy.id, policy_version=policy.version, policy_config_hash=policy.config_hash,
            evidence_binding_hash=change.supervised_validation_binding_hash,
            risk_level=risk_level, required_roles_json=list(level["acceptance_roles"]), approvals_json=[],
            status="pending", rationale=rationale, created_by=actor_subject, created_by_name=actor_name,
        )
        self.session.add(record)
        return self._commit_acceptance(record, "model_risk_acceptance_created", actor_subject, rationale)

    def list_reacceptances(self, tenant_id: str, release_id: str | None = None) -> list[dict]:
        statement = select(ModelRiskReacceptanceRecord).where(ModelRiskReacceptanceRecord.tenant_id == tenant_id)
        if release_id:
            statement = statement.where(ModelRiskReacceptanceRecord.model_release_id == release_id)
        rows = self.session.scalars(statement.order_by(ModelRiskReacceptanceRecord.created_at.desc())).all()
        return [self._reacceptance_view(row) for row in rows]

    def reacceptance_review_queue(self, tenant_id: str, now: datetime | None = None, horizon_days: int = 30) -> list[dict]:
        if not 1 <= horizon_days <= 90:
            raise ModelRiskPolicyError("REVIEW_HORIZON_INVALID", "复核窗口须为 1 至 90 天")
        scan_at = self._as_utc(now or self._now())
        rows = self.session.scalars(select(ModelRiskReacceptanceRecord).where(
            ModelRiskReacceptanceRecord.tenant_id == tenant_id,
            ModelRiskReacceptanceRecord.status == "accepted",
            ModelRiskReacceptanceRecord.review_due_at <= scan_at + timedelta(days=horizon_days),
        ).order_by(ModelRiskReacceptanceRecord.review_due_at, ModelRiskReacceptanceRecord.id)).all()
        queue = []
        for row in rows:
            view = self._reacceptance_view(row, now=scan_at)
            if view["effective_status"] not in {"accepted", "overdue"}:
                continue
            remaining = ceil((self._as_utc(row.review_due_at) - scan_at).total_seconds() / 86400)
            owners = {(item["actor_subject"], item["platform_role"], item["actor_name"])
                      for item in row.approvals_json or []}
            owners.add((row.created_by, "model_admin", row.created_by_name))
            release = self.session.get(ModelReleaseRecord, row.model_release_id)
            pending = self.session.scalar(select(ModelRiskReacceptanceRecord).where(
                ModelRiskReacceptanceRecord.tenant_id == tenant_id,
                ModelRiskReacceptanceRecord.model_release_id == row.model_release_id,
                ModelRiskReacceptanceRecord.status == "pending",
            ))
            queue.append({
                "reacceptance_id": row.id, "model_release_id": row.model_release_id,
                "model_change_id": row.model_change_id, "risk_level": row.risk_level,
                "model_version": release.model_version if release else None,
                "review_due_at": view["review_due_at"], "days_remaining": remaining,
                "level": "overdue" if remaining <= 0 else "due_soon" if remaining <= 7 else "upcoming",
                "runtime_impact": "blocked" if remaining <= 0 else "at_risk",
                "pending_renewal_id": pending.id if pending else None,
                "evidence_level": (row.operational_evidence_json or {}).get("monitoring_binding", {}).get("evidence_level", "legacy_manual"),
                "responsible": [{"subject": subject, "role": role, "name": name}
                                for subject, role, name in sorted(owners)],
            })
        return queue

    def unified_review_queue(
        self,
        tenant_id: str,
        template_key: str | None = None,
        now: datetime | None = None,
        horizon_days: int = 30,
    ) -> list[dict]:
        """Project all live model-risk obligations into one deterministic work queue."""
        if not 1 <= horizon_days <= 90:
            raise ModelRiskPolicyError("REVIEW_HORIZON_INVALID", "复核窗口须为 1 至 90 天")
        scan_at = self._as_utc(now or self._now())
        items: list[dict] = []

        changes = {
            row.id: row for row in self.session.scalars(select(ModelChangeRecord)).all()
        }
        releases = {
            row.id: row for row in self.session.scalars(select(ModelReleaseRecord)).all()
        }

        for item in self.review_queue(tenant_id, scan_at, horizon_days):
            change = changes.get(item["model_change_id"])
            if template_key and (change is None or change.template_key != template_key):
                continue
            priority = "P2" if item["level"] == "overdue" else "P3" if item["level"] == "due_soon" else "P4"
            items.append({
                "id": f"risk_acceptance:{item['acceptance_id']}", "source": "risk_acceptance",
                "priority": priority,
                "priority_reason": "风险接受已逾期" if item["level"] == "overdue" else "风险接受即将到期" if item["level"] == "due_soon" else "风险接受进入复核窗口",
                "state": item["level"], "title": "模型风险接受定期复核",
                "summary": f"{item['risk_level']} 风险接受须按政策 tenant-v{item['policy_version']} 完成复核",
                "due_at": item["review_due_at"], "days_remaining": item["days_remaining"],
                "model_key": change.template_key if change else None,
                "model_version": change.candidate_version if change else None,
                "model_change_id": item["model_change_id"], "model_release_id": None,
                "policy_id": None, "monitoring_run_id": None, "diff_case_id": None,
                "evidence_level": "supervised", "responsible": item["responsible"],
                "action": {"target": "model-risk-policy", "label": "查看风险接受"},
            })

        for item in self.reacceptance_review_queue(tenant_id, scan_at, horizon_days):
            release = releases.get(item["model_release_id"])
            model_key = release.template_key if release else None
            if template_key and model_key != template_key:
                continue
            priority = "P2" if item["level"] == "overdue" else "P3" if item["level"] == "due_soon" else "P4"
            items.append({
                "id": f"risk_reacceptance:{item['reacceptance_id']}", "source": "risk_reacceptance",
                "priority": priority,
                "priority_reason": "在役再接受已逾期并阻断运行" if item["level"] == "overdue" else "在役再接受即将到期" if item["level"] == "due_soon" else "在役再接受进入续期窗口",
                "state": item["level"], "title": "在役模型再接受续期",
                "summary": "续期待签" if item["pending_renewal_id"] else "待创建续期并补充当前运行证据",
                "due_at": item["review_due_at"], "days_remaining": item["days_remaining"],
                "model_key": model_key, "model_version": item["model_version"],
                "model_change_id": item["model_change_id"], "model_release_id": item["model_release_id"],
                "policy_id": None, "monitoring_run_id": None, "diff_case_id": None,
                "evidence_level": item["evidence_level"], "responsible": item["responsible"],
                "action": {"target": "release-approval-dashboard", "label": "处理在役续期"},
            })

        rollout_statement = select(TenantRolloutPolicyRecord).where(TenantRolloutPolicyRecord.tenant_id == tenant_id)
        policies = self.session.scalars(rollout_statement).all()
        policy_by_id = {row.id: row for row in policies}
        eligible_policy_ids = {
            row.id for row in policies
            if not template_key or template_key in {row.champion_model_key, row.challenger_model_key}
        }
        from backend.tenant_outcome_repository import TenantOutcomeRepository, TenantRolloutError
        outcome_repository = TenantOutcomeRepository(self.session)

        run_statement = select(TenantMonitoringRunRecord).where(
            TenantMonitoringRunRecord.tenant_id == tenant_id,
            TenantMonitoringRunRecord.governance_status.in_(("published", "retracted")),
        ).order_by(TenantMonitoringRunRecord.observed_to.desc(), TenantMonitoringRunRecord.created_at.desc())
        latest_runs: dict[tuple[str, str, str], TenantMonitoringRunRecord] = {}
        for run in self.session.scalars(run_statement).all():
            if run.policy_id not in eligible_policy_ids or (template_key and run.model_key != template_key):
                continue
            latest_runs.setdefault((run.policy_id, run.model_key, run.model_version), run)
        for run in latest_runs.values():
            gate = outcome_repository.monitoring_gate(tenant_id, run.policy_id, run.id)
            if gate["status"] == "accepted":
                continue
            priority = "P0" if gate["status"] == "evidence_stale" else "P1" if gate["status"] == "blocked" else "P3"
            reasons = gate.get("reasons") or ["需要复核当前监控证据"]
            items.append({
                "id": f"monitoring_gate:{run.id}", "source": "monitoring_gate",
                "priority": priority, "priority_reason": reasons[0], "state": gate["status"],
                "title": "租户监控证据失效" if gate["status"] == "evidence_stale" else "租户监控门禁阻断" if gate["status"] == "blocked" else "租户监控诊断观察",
                "summary": "；".join(reasons), "due_at": None, "days_remaining": None,
                "model_key": run.model_key, "model_version": run.model_version,
                "model_change_id": None, "model_release_id": None,
                "policy_id": run.policy_id, "monitoring_run_id": run.id, "diff_case_id": None,
                "evidence_level": run.evidence_level,
                "responsible": [{"subject": None, "role": role, "name": "模型管理员" if role == "model_admin" else "风控经理"} for role in ("model_admin", "risk_manager")],
                "action": {"target": "tenant-rollout-governance", "label": "复核监控快照"},
            })

        case_statement = select(TenantMonitoringDiffCaseRecord).where(
            TenantMonitoringDiffCaseRecord.tenant_id == tenant_id,
            TenantMonitoringDiffCaseRecord.status.in_(("open", "assigned", "recomputing", "pending_disposition")),
        ).order_by(TenantMonitoringDiffCaseRecord.due_at, TenantMonitoringDiffCaseRecord.id)
        for case in self.session.scalars(case_statement).all():
            if case.policy_id not in eligible_policy_ids:
                continue
            base_run = self.session.get(TenantMonitoringRunRecord, case.base_run_id)
            policy = policy_by_id.get(case.policy_id)
            model_key = base_run.model_key if base_run else (policy.champion_model_key if policy else None)
            if template_key and model_key != template_key:
                continue
            evidence_stale = False
            try:
                outcome_repository._verify_monitoring_diff_case_integrity(case)
            except TenantRolloutError:
                evidence_stale = True
            due_at = self._as_utc(case.due_at)
            remaining = ceil((due_at - scan_at).total_seconds() / 86400)
            overdue = due_at <= scan_at
            if evidence_stale:
                priority, reason = "P0", "差异工单冻结证据已失效"
            elif case.severity == "critical":
                priority, reason = "P1", "重大监控差异尚未关闭"
            elif overdue:
                priority, reason = "P2", "监控差异工单已逾期"
            elif case.status == "pending_disposition":
                priority, reason = "P3", "重算已完成，等待独立处置"
            else:
                priority, reason = "P4", "监控差异等待调查或重算"
            responsible = [{
                "subject": case.assigned_to, "role": case.assigned_role,
                "name": case.assigned_to_name or case.assigned_role,
            }]
            items.append({
                "id": f"monitoring_diff_case:{case.id}", "source": "monitoring_diff_case",
                "priority": priority, "priority_reason": reason, "state": "evidence_stale" if evidence_stale else case.status,
                "title": "监控差异证据复核", "summary": case.reason,
                "due_at": due_at.isoformat(), "days_remaining": remaining,
                "model_key": model_key, "model_version": base_run.model_version if base_run else None,
                "model_change_id": None, "model_release_id": None,
                "policy_id": case.policy_id, "monitoring_run_id": case.base_run_id, "diff_case_id": case.id,
                "evidence_level": base_run.evidence_level if base_run else None,
                "source_row_version": case.row_version,
                "responsible": responsible,
                "action": {"target": "tenant-rollout-governance", "label": "处理差异工单"},
            })

        ranks = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
        return sorted(items, key=lambda item: (
            ranks[item["priority"]], item["due_at"] or "9999-12-31T23:59:59+00:00", item["source"], item["id"],
        ))

    def review_queue_workbench(
        self,
        tenant_id: str,
        *,
        template_key: str | None = None,
        horizon_days: int = 30,
        source: str | None = None,
        priority: str | None = None,
        owner_subject: str | None = None,
        owner_role: str | None = None,
        ownership: str = "all",
        evidence_level: str | None = None,
        query: str | None = None,
        viewer_subject: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Return a filtered operational view while keeping the queue projection live."""
        if ownership not in {"all", "mine", "unassigned"}:
            raise ModelRiskPolicyError("OWNERSHIP_FILTER_INVALID", "责任范围只能是 all、mine 或 unassigned")
        as_of = self._as_utc(now or self._now())
        items = self.unified_review_queue(tenant_id, template_key=template_key, now=as_of, horizon_days=horizon_days)
        assignments = {
            row.item_id: row for row in self.session.scalars(select(ModelRiskReviewAssignmentRecord).where(
                ModelRiskReviewAssignmentRecord.tenant_id == tenant_id,
            )).all()
        }
        current_subject = owner_subject if ownership == "mine" else None
        delegated_responsibilities: dict[tuple[str, str], ModelRiskReviewDelegationRecord] = {}
        if viewer_subject:
            for delegation in self._active_review_delegations(tenant_id, as_of, delegate_subject=viewer_subject):
                delegated_responsibilities[(delegation.principal_subject, delegation.assigned_role)] = delegation
        enriched: list[dict] = []
        member_options = self.list_review_members(tenant_id, now=as_of)
        for item in items:
            assignment = assignments.get(item["id"])
            if assignment:
                responsible = [{"subject": assignment.assigned_to, "role": assignment.assigned_role, "name": assignment.assigned_to_name or assignment.assigned_role}]
                item = {**item, "responsible": responsible, "assignment": self._review_assignment_view(assignment)}
            else:
                item = {**item, "assignment": None}
            responsible = item.get("responsible") or []
            delegated_from = None
            for person in responsible:
                delegation = delegated_responsibilities.get((person.get("subject"), person.get("role")))
                if delegation:
                    delegated_from = {
                        "subject": delegation.principal_subject, "name": delegation.principal_name,
                        "role": delegation.assigned_role,
                    }
                    item = {**item, "delegated": True, "delegated_from": delegated_from, "delegation_id": delegation.id}
                    break
            if delegated_from is None:
                item = {**item, "delegated": False, "delegated_from": None, "delegation_id": None}
            if source and item["source"] != source:
                continue
            if priority and item["priority"] != priority:
                continue
            if evidence_level and item.get("evidence_level") != evidence_level:
                continue
            if owner_role and not any(person.get("role") == owner_role for person in responsible):
                continue
            if ownership == "unassigned" and any(person.get("subject") for person in responsible):
                continue
            if current_subject and not (
                any(person.get("subject") == current_subject for person in responsible)
                or bool(item["delegated"] and viewer_subject == current_subject)
            ):
                continue
            if query:
                haystack = " ".join(str(item.get(key) or "") for key in ("id", "title", "summary", "model_key", "model_version", "priority_reason"))
                if query.casefold() not in haystack.casefold():
                    continue
            enriched.append(item)
        counts = {key: sum(item["priority"] == key for item in enriched) for key in ("P0", "P1", "P2", "P3", "P4")}
        counts.update({
            "total": len(enriched),
            "mine": sum(
                any(person.get("subject") == (viewer_subject or owner_subject) for person in item.get("responsible") or [])
                or bool(item.get("delegated"))
                for item in enriched
            ) if (viewer_subject or owner_subject) else 0,
            "unassigned": sum(not any(person.get("subject") for person in item.get("responsible") or []) for item in enriched),
        })
        return {
            "schema_version": "model-risk-review-queue-v2", "as_of": self._as_utc(now or self._now()).isoformat(),
            "filters": {"template_key": template_key, "horizon_days": horizon_days, "source": source, "priority": priority,
                        "owner_subject": owner_subject, "owner_role": owner_role, "ownership": ownership,
                        "evidence_level": evidence_level, "query": query},
            "counts": counts, "items": enriched,
            "available_owners": [
                {"subject": member["subject"], "role": role, "name": member["name"]}
                for member in member_options for role in member["roles"]
            ],
            "available_roles": sorted({role for member in member_options for role in member["roles"]}),
        }

    def list_review_saved_views(self, tenant_id: str, owner_subject: str) -> list[dict]:
        rows = self.session.scalars(select(ModelRiskReviewSavedViewRecord).where(
            ModelRiskReviewSavedViewRecord.tenant_id == tenant_id,
            ModelRiskReviewSavedViewRecord.owner_subject == owner_subject,
        ).order_by(ModelRiskReviewSavedViewRecord.is_default.desc(), ModelRiskReviewSavedViewRecord.name)).all()
        return [self._review_saved_view_view(row) for row in rows]

    def create_review_saved_view(self, tenant_id: str, owner_subject: str, payload: dict) -> dict:
        count = self.session.scalar(select(func.count(ModelRiskReviewSavedViewRecord.id)).where(
            ModelRiskReviewSavedViewRecord.tenant_id == tenant_id,
            ModelRiskReviewSavedViewRecord.owner_subject == owner_subject,
        )) or 0
        if count >= 20:
            raise ModelRiskPolicyError("SAVED_VIEW_LIMIT", "每位用户最多保存 20 个复核视图")
        if payload.get("is_default"):
            self._clear_review_default_view(tenant_id, owner_subject)
        record = ModelRiskReviewSavedViewRecord(
            id=str(uuid4()), tenant_id=tenant_id, owner_subject=owner_subject,
            name=payload["name"], filters_json=deepcopy(payload.get("filters") or {}), is_default=bool(payload.get("is_default")),
        )
        self.session.add(record)
        return self._commit_review_operation(record, "model_risk_review_saved_view_created", owner_subject, {"tenant_id": tenant_id, "name": record.name})

    def update_review_saved_view(self, tenant_id: str, owner_subject: str, view_id: str, expected_row_version: int, payload: dict) -> dict:
        record = self._owned_review_saved_view(tenant_id, owner_subject, view_id)
        self._check_version(record.row_version, expected_row_version)
        if payload.get("is_default"):
            self._clear_review_default_view(tenant_id, owner_subject, exclude_id=record.id)
        record.name = payload["name"]
        record.filters_json = deepcopy(payload.get("filters") or {})
        record.is_default = bool(payload.get("is_default"))
        return self._commit_review_operation(record, "model_risk_review_saved_view_updated", owner_subject, {"tenant_id": tenant_id, "name": record.name})

    def delete_review_saved_view(self, tenant_id: str, owner_subject: str, view_id: str, expected_row_version: int) -> None:
        record = self._owned_review_saved_view(tenant_id, owner_subject, view_id)
        self._check_version(record.row_version, expected_row_version)
        self.session.delete(record)
        self._commit_review_operation(None, "model_risk_review_saved_view_deleted", owner_subject, {"tenant_id": tenant_id, "view_id": view_id})

    def list_review_members(self, tenant_id: str, now: datetime | None = None) -> list[dict]:
        as_of = self._as_utc(now or self._now())
        rows = self.session.scalars(select(TenantMembershipRecord).where(
            TenantMembershipRecord.tenant_id == tenant_id,
            TenantMembershipRecord.status == "active",
        ).order_by(TenantMembershipRecord.display_name, TenantMembershipRecord.subject)).all()
        return [
            {
                "subject": row.subject, "name": row.display_name,
                "roles": sorted(set(row.roles_json or []).intersection(REVIEW_RESPONSIBILITY_ROLES)),
                "expires_at": self._as_utc(row.expires_at).isoformat() if row.expires_at else None,
            }
            for row in rows
            if (row.expires_at is None or self._as_utc(row.expires_at) > as_of)
            and set(row.roles_json or []).intersection(REVIEW_RESPONSIBILITY_ROLES)
        ]

    def list_review_delegations(self, tenant_id: str, now: datetime | None = None) -> list[dict]:
        as_of = self._as_utc(now or self._now())
        rows = self.session.scalars(select(ModelRiskReviewDelegationRecord).where(
            ModelRiskReviewDelegationRecord.tenant_id == tenant_id,
        ).order_by(ModelRiskReviewDelegationRecord.starts_at.desc(), ModelRiskReviewDelegationRecord.created_at.desc())).all()
        return [self._review_delegation_view(row, as_of) for row in rows]

    def create_review_delegation(self, tenant_id: str, payload: dict, actor_subject: str, actor_name: str) -> dict:
        principal = self._active_review_member(tenant_id, payload["principal_subject"])
        delegate = self._active_review_member(tenant_id, payload["delegate_subject"])
        if principal is None or delegate is None:
            raise ModelRiskPolicyError("DELEGATION_MEMBER_NOT_FOUND", "原责任人和代理人必须是当前租户的有效成员")
        if principal.subject == delegate.subject:
            raise ModelRiskPolicyError("DELEGATION_SELF_NOT_ALLOWED", "原责任人与代理人不能是同一成员")
        role = payload["assigned_role"]
        if role not in REVIEW_RESPONSIBILITY_ROLES:
            raise ModelRiskPolicyError("DELEGATION_ROLE_INVALID", "所选角色不属于模型风险复核责任角色")
        if role not in (principal.roles_json or []) or role not in (delegate.roles_json or []):
            raise ModelRiskPolicyError("DELEGATION_ROLE_MISMATCH", "原责任人和代理人都必须具备所选责任角色")
        starts_at = self._as_utc(payload["starts_at"])
        ends_at = self._as_utc(payload["ends_at"])
        now = self._as_utc(self._now())
        if ends_at <= starts_at:
            raise ModelRiskPolicyError("DELEGATION_WINDOW_INVALID", "代理结束时间必须晚于开始时间")
        if ends_at <= now:
            raise ModelRiskPolicyError("DELEGATION_WINDOW_EXPIRED", "代理结束时间必须晚于当前时间")
        if ends_at - starts_at > timedelta(days=90):
            raise ModelRiskPolicyError("DELEGATION_WINDOW_TOO_LONG", "单次代理期限不能超过 90 天")
        existing = self.session.scalars(select(ModelRiskReviewDelegationRecord).where(
            ModelRiskReviewDelegationRecord.tenant_id == tenant_id,
            ModelRiskReviewDelegationRecord.principal_subject == principal.subject,
            ModelRiskReviewDelegationRecord.assigned_role == role,
            ModelRiskReviewDelegationRecord.status == "active",
        )).all()
        if any(starts_at < self._as_utc(row.ends_at) and ends_at > self._as_utc(row.starts_at) for row in existing):
            raise ModelRiskPolicyError("DELEGATION_WINDOW_OVERLAP", "该责任人与角色已存在重叠的代理时间窗口", 409)
        record = ModelRiskReviewDelegationRecord(
            id=str(uuid4()), tenant_id=tenant_id,
            principal_subject=principal.subject, principal_name=principal.display_name,
            delegate_subject=delegate.subject, delegate_name=delegate.display_name,
            assigned_role=role, starts_at=starts_at, ends_at=ends_at,
            status="active", reason=payload["reason"], created_by=actor_subject, created_by_name=actor_name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append(
                "model_risk_review_delegation", record.id, "model_risk_review_delegation_created", actor_subject,
                {"tenant_id": tenant_id, "principal_subject": principal.subject, "delegate_subject": delegate.subject,
                 "assigned_role": role, "starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat(),
                 "reason": payload["reason"], "actor_name": actor_name},
            )
            notifications = NotificationRepository(self.session)
            for subject, name, notice_role, title in (
                (delegate.subject, delegate.display_name, role, "模型风险复核代理已生效"),
                (principal.subject, principal.display_name, role, "模型风险复核责任已设置代理"),
            ):
                notifications.create_if_absent(tenant_id, {
                    "case_id": None, "counterparty_id": None,
                    "recipient_role": notice_role, "recipient_subject": subject,
                    "category": "model_risk_delegation", "level": "assignment", "severity": "info",
                    "title": title,
                    "message": f"{principal.display_name} 的 {role} 责任由 {delegate.display_name} 在 {starts_at.isoformat()} 至 {ends_at.isoformat()} 期间代理。{payload['reason']}",
                    "action_json": {"page": "model-governance", "target": "model-risk-policy", "delegation_id": record.id},
                    "dedup_key": f"model-risk-delegation:{record.id}:created:{subject}", "status": "unread",
                })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ModelRiskPolicyError("CONCURRENT_UPDATE", "代理设置发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._review_delegation_view(record, now)

    def revoke_review_delegation(self, tenant_id: str, delegation_id: str, expected_row_version: int, reason: str, actor_subject: str, actor_name: str) -> dict:
        record = self.session.scalar(select(ModelRiskReviewDelegationRecord).where(
            ModelRiskReviewDelegationRecord.tenant_id == tenant_id,
            ModelRiskReviewDelegationRecord.id == delegation_id,
        ))
        if record is None:
            raise ModelRiskPolicyError("DELEGATION_NOT_FOUND", "代理设置不存在", 404)
        self._check_version(record.row_version, expected_row_version)
        if record.status != "active":
            raise ModelRiskPolicyError("DELEGATION_ALREADY_REVOKED", "代理设置已撤销", 409)
        revoked_at = self._as_utc(self._now())
        record.status, record.revoked_by, record.revoked_by_name = "revoked", actor_subject, actor_name
        record.revoked_at, record.revocation_reason = revoked_at, reason
        try:
            self.audit.append(
                "model_risk_review_delegation", record.id, "model_risk_review_delegation_revoked", actor_subject,
                {"tenant_id": tenant_id, "reason": reason, "actor_name": actor_name},
            )
            notifications = NotificationRepository(self.session)
            for subject, notice_role in (
                (record.delegate_subject, record.assigned_role),
                (record.principal_subject, record.assigned_role),
            ):
                notifications.create_if_absent(tenant_id, {
                    "case_id": None, "counterparty_id": None,
                    "recipient_role": notice_role, "recipient_subject": subject,
                    "category": "model_risk_delegation", "level": "revocation", "severity": "warning",
                    "title": "模型风险复核代理已撤销",
                    "message": f"{record.principal_name} 至 {record.delegate_name} 的 {record.assigned_role} 代理已撤销。{reason}",
                    "action_json": {"page": "model-governance", "target": "model-risk-policy", "delegation_id": record.id},
                    "dedup_key": f"model-risk-delegation:{record.id}:revoked:{subject}", "status": "unread",
                })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ModelRiskPolicyError("CONCURRENT_UPDATE", "代理撤销发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._review_delegation_view(record, revoked_at)

    def review_assignment_history(self, tenant_id: str, item_id: str) -> dict:
        rows = self.session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.aggregate_type == "model_risk_review_assignment",
            AuditEventRecord.aggregate_id == item_id,
        ).order_by(AuditEventRecord.created_at, AuditEventRecord.id)).all()
        by_previous_hash = {row.previous_hash: row for row in rows}
        ordered_rows: list[AuditEventRecord] = []
        previous_hash = ""
        while previous_hash in by_previous_hash:
            row = by_previous_hash[previous_hash]
            ordered_rows.append(row)
            previous_hash = row.event_hash
        return {
            "item_id": item_id,
            "items": [
                {
                    "id": row.id, "event_type": row.event_type, "actor": row.actor,
                    "actor_name": (row.payload or {}).get("actor_name"),
                    "action": (row.payload or {}).get("action"),
                    "previous": {
                        "subject": (row.payload or {}).get("previous_assigned_to"),
                        "name": (row.payload or {}).get("previous_assigned_to_name"),
                        "role": (row.payload or {}).get("previous_assigned_role"),
                    },
                    "next": {
                        "subject": (row.payload or {}).get("next_assigned_to"),
                        "name": (row.payload or {}).get("next_assigned_to_name"),
                        "role": (row.payload or {}).get("next_assigned_role"),
                    },
                    "reason": (row.payload or {}).get("reason"),
                    "batch_id": (row.payload or {}).get("batch_id"),
                    "event_hash": row.event_hash,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in ordered_rows
            ],
        }

    def bulk_assign_review_items(self, tenant_id: str, items: list[dict], assignee: str | None, assignee_name: str | None, assigned_role: str, reason: str, actor_subject: str, actor_name: str) -> dict:
        if not items or len(items) > 50:
            raise ModelRiskPolicyError("BULK_ASSIGN_LIMIT", "批量分派必须包含 1 至 50 条队列事项")
        member = None
        if assigned_role not in REVIEW_RESPONSIBILITY_ROLES:
            raise ModelRiskPolicyError("ASSIGNEE_ROLE_INVALID", "所选角色不属于模型风险复核责任角色")
        if assignee:
            member = self._active_review_member(tenant_id, assignee)
            if member is None:
                raise ModelRiskPolicyError("ASSIGNEE_NOT_FOUND", "责任人不属于当前租户的有效成员", 422)
            if assigned_role not in (member.roles_json or []):
                raise ModelRiskPolicyError("ASSIGNEE_ROLE_MISMATCH", "责任人不具备所选责任角色", 422)
            assignee_name = member.display_name
        item_ids = [item["item_id"] for item in items]
        if len(item_ids) != len(set(item_ids)):
            raise ModelRiskPolicyError("DUPLICATE_QUEUE_ITEM", "批量分派不能包含重复队列事项")
        live = {item["id"]: item for item in self.unified_review_queue(tenant_id, horizon_days=90)}
        assignments = {row.item_id: row for row in self.session.scalars(select(ModelRiskReviewAssignmentRecord).where(
            ModelRiskReviewAssignmentRecord.tenant_id == tenant_id, ModelRiskReviewAssignmentRecord.item_id.in_(item_ids),
        )).all()}
        cases = {row.id: row for row in self.session.scalars(select(TenantMonitoringDiffCaseRecord).where(
            TenantMonitoringDiffCaseRecord.tenant_id == tenant_id,
            TenantMonitoringDiffCaseRecord.id.in_([item_id.split(":", 1)[1] for item_id in item_ids if item_id.startswith("monitoring_diff_case:")]),
        )).all()}
        for item in items:
            queue_item = live.get(item["item_id"])
            if queue_item is None:
                raise ModelRiskPolicyError("QUEUE_ITEM_NOT_FOUND", f"复核事项不存在或已离队：{item['item_id']}", 404)
            current = assignments.get(item["item_id"])
            expected = int(item.get("expected_assignment_version", 0))
            if (current.row_version if current else 0) != expected:
                raise ModelRiskPolicyError("CONCURRENT_UPDATE", f"复核事项 {item['item_id']} 的责任归属已变化，请刷新后重试", 409)
            if queue_item["source"] == "monitoring_diff_case":
                case = cases.get(item["item_id"].split(":", 1)[1])
                if case is None or case.status in {"resolved", "rejected"}:
                    raise ModelRiskPolicyError("QUEUE_ITEM_CLOSED", "已关闭差异工单不能重新分派", 409)
                if item.get("expected_source_version") is None or case.row_version != int(item["expected_source_version"]):
                    raise ModelRiskPolicyError("CONCURRENT_UPDATE", "差异工单已被更新，请刷新后重试", 409)
                if assignee is None and case.assigned_to is None:
                    raise ModelRiskPolicyError("ASSIGNMENT_NOT_FOUND", "所选差异工单当前没有可撤回的责任人", 409)
            elif assignee is None and current is None:
                raise ModelRiskPolicyError("ASSIGNMENT_NOT_FOUND", f"复核事项 {item['item_id']} 当前没有可撤回的运营分派", 409)
        batch_id = str(uuid4())
        notification_targets: dict[tuple[str, str, str], dict] = {}
        for item in items:
            item_id = item["item_id"]
            current = assignments.get(item_id)
            queue_item = live[item_id]
            previous_person = (
                {"subject": current.assigned_to, "name": current.assigned_to_name, "role": current.assigned_role}
                if current is not None else
                next((person for person in queue_item.get("responsible") or [] if person.get("subject")), None)
            )
            previous_owner = {
                "subject": previous_person.get("subject") if previous_person else None,
                "name": previous_person.get("name") if previous_person else None,
                "role": previous_person.get("role") if previous_person else None,
            }
            action = "unassign" if assignee is None else "handoff" if previous_owner["subject"] else "assign"
            if assignee:
                notification_targets[(assignee, assigned_role, action)] = {
                    "subject": assignee, "name": assignee_name or assigned_role, "role": assigned_role,
                    "action": action, "count": notification_targets.get((assignee, assigned_role, action), {}).get("count", 0) + 1,
                }
            if previous_owner["subject"] and previous_owner["subject"] != assignee:
                previous_key = (previous_owner["subject"], previous_owner["role"] or assigned_role, "released")
                notification_targets[previous_key] = {
                    "subject": previous_owner["subject"], "name": previous_owner["name"] or previous_owner["role"] or "原责任人",
                    "role": previous_owner["role"] or assigned_role, "action": "released",
                    "count": notification_targets.get(previous_key, {}).get("count", 0) + 1,
                }
            if live[item_id]["source"] == "monitoring_diff_case":
                case = cases[item_id.split(":", 1)[1]]
                next_role = assigned_role if assignee else case.assigned_role
                case.assigned_role, case.assigned_to, case.assigned_to_name = next_role, assignee, assignee_name
                if assignee and case.status == "open":
                    case.status = "assigned"
                elif not assignee and case.status == "assigned":
                    case.status = "open"
                if current is not None:
                    self.session.delete(current)
            elif assignee is None:
                next_role = previous_owner["role"] or assigned_role
                self.session.delete(current)
            elif current is None:
                next_role = assigned_role
                current = ModelRiskReviewAssignmentRecord(id=str(uuid4()), tenant_id=tenant_id, item_id=item_id, source=live[item_id]["source"], assigned_role=assigned_role, assigned_to=assignee, assigned_to_name=assignee_name, reason=reason, assigned_by=actor_subject, assigned_by_name=actor_name)
                self.session.add(current)
            else:
                next_role = assigned_role
                current.assigned_role, current.assigned_to, current.assigned_to_name = assigned_role, assignee, assignee_name
                current.reason, current.assigned_by, current.assigned_by_name = reason, actor_subject, actor_name
            self.audit.append(
                "model_risk_review_assignment", item_id, f"model_risk_review_item_{action}ed", actor_subject,
                {
                    "tenant_id": tenant_id, "batch_id": batch_id, "action": action,
                    "actor_name": actor_name, "reason": reason,
                    "previous_assigned_to": previous_owner["subject"],
                    "previous_assigned_to_name": previous_owner["name"],
                    "previous_assigned_role": previous_owner["role"],
                    "next_assigned_to": assignee, "next_assigned_to_name": assignee_name,
                    "next_assigned_role": next_role,
                },
            )
        batch_action = "unassigned" if assignee is None else "assigned"
        self.audit.append(
            "model_risk_review_assignment_batch", batch_id, f"model_risk_review_items_bulk_{batch_action}", actor_subject,
            {"tenant_id": tenant_id, "item_ids": item_ids, "assigned_to": assignee, "assigned_role": assigned_role, "reason": reason},
        )
        notifications = NotificationRepository(self.session)
        for target in notification_targets.values():
            action_label = {"assign": "已分派", "handoff": "已交接", "released": "已解除"}[target["action"]]
            notifications.create_if_absent(tenant_id, {
                "case_id": None, "counterparty_id": None,
                "recipient_role": target["role"], "recipient_subject": target["subject"],
                "category": "model_risk_assignment", "level": target["action"],
                "severity": "warning" if target["action"] == "released" else "info",
                "title": f"模型风险复核责任{action_label}",
                "message": f"{target['count']} 条模型风险复核事项责任{action_label}。操作人：{actor_name}。原因：{reason}",
                "action_json": {"page": "model-governance", "target": "model-risk-policy", "batch_id": batch_id},
                "dedup_key": f"model-risk-assignment:{batch_id}:{target['action']}:{target['subject']}:{target['role']}",
                "status": "unread",
            })
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ModelRiskPolicyError("CONCURRENT_UPDATE", "批量分派发生并发冲突，请刷新后重试", 409) from exc
        return {"batch_id": batch_id, "assigned_count": len(items), "assignee": assignee, "assigned_role": assigned_role, "action": "unassign" if assignee is None else "assign"}

    def create_review_sla_snapshot(self, tenant_id: str, template_key: str | None = None, snapshot_date: date | None = None, now: datetime | None = None) -> dict:
        target_date = snapshot_date or (self._as_utc(now or self._now()).date())
        workbench = self.review_queue_workbench(tenant_id, template_key=template_key, horizon_days=90, now=now)
        owner_counts: dict[str, int] = {}
        for item in workbench["items"]:
            for person in item.get("responsible") or []:
                key = person.get("subject") or f"role:{person.get('role') or 'unassigned'}"
                owner_counts[key] = owner_counts.get(key, 0) + 1
        payload = {"snapshot_date": target_date.isoformat(), "template_key": template_key, "counts": workbench["counts"], "source_counts": {source: sum(item["source"] == source for item in workbench["items"]) for source in sorted({item["source"] for item in workbench["items"]})}, "owner_counts": owner_counts}
        record = self.session.scalar(select(ModelRiskReviewSlaSnapshotRecord).where(
            ModelRiskReviewSlaSnapshotRecord.tenant_id == tenant_id, ModelRiskReviewSlaSnapshotRecord.snapshot_date == target_date,
            ModelRiskReviewSlaSnapshotRecord.template_key == template_key,
        ))
        if record is None:
            record = ModelRiskReviewSlaSnapshotRecord(id=str(uuid4()), tenant_id=tenant_id, snapshot_date=target_date, template_key=template_key, counts_json=payload["counts"], source_counts_json=payload["source_counts"], owner_counts_json=owner_counts, evidence_hash=content_hash(payload))
            self.session.add(record)
        else:
            record.counts_json, record.source_counts_json, record.owner_counts_json, record.evidence_hash = payload["counts"], payload["source_counts"], owner_counts, content_hash(payload)
        self.session.commit()
        self.session.refresh(record)
        return self._review_sla_snapshot_view(record)

    def list_review_sla_trends(self, tenant_id: str, days: int = 30, template_key: str | None = None) -> dict:
        if not 1 <= days <= 90:
            raise ModelRiskPolicyError("TREND_DAYS_INVALID", "趋势窗口须为 1 至 90 天")
        rows = self.session.scalars(select(ModelRiskReviewSlaSnapshotRecord).where(
            ModelRiskReviewSlaSnapshotRecord.tenant_id == tenant_id,
            ModelRiskReviewSlaSnapshotRecord.template_key == template_key,
            ModelRiskReviewSlaSnapshotRecord.snapshot_date >= self._as_utc(self._now()).date() - timedelta(days=days - 1),
        ).order_by(ModelRiskReviewSlaSnapshotRecord.snapshot_date)).all()
        return {"schema_version": "model-risk-review-sla-trend-v1", "days": days, "template_key": template_key, "items": [self._review_sla_snapshot_view(row) for row in rows]}

    def _clear_review_default_view(self, tenant_id: str, owner_subject: str, exclude_id: str | None = None) -> None:
        statement = select(ModelRiskReviewSavedViewRecord).where(ModelRiskReviewSavedViewRecord.tenant_id == tenant_id, ModelRiskReviewSavedViewRecord.owner_subject == owner_subject, ModelRiskReviewSavedViewRecord.is_default.is_(True))
        if exclude_id:
            statement = statement.where(ModelRiskReviewSavedViewRecord.id != exclude_id)
        for row in self.session.scalars(statement).all():
            row.is_default = False

    def _owned_review_saved_view(self, tenant_id: str, owner_subject: str, view_id: str) -> ModelRiskReviewSavedViewRecord:
        record = self.session.scalar(select(ModelRiskReviewSavedViewRecord).where(ModelRiskReviewSavedViewRecord.id == view_id, ModelRiskReviewSavedViewRecord.tenant_id == tenant_id, ModelRiskReviewSavedViewRecord.owner_subject == owner_subject))
        if record is None:
            raise ModelRiskPolicyError("SAVED_VIEW_NOT_FOUND", "复核视图不存在", 404)
        return record

    def _commit_review_operation(self, record: object | None, event_type: str, actor: str, payload: dict) -> dict:
        try:
            if record is not None:
                self.session.flush()
                aggregate_id = record.id
            else:
                aggregate_id = payload.get("view_id", str(uuid4()))
            self.audit.append("model_risk_review_operations", aggregate_id, event_type, actor, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ModelRiskPolicyError("CONCURRENT_UPDATE", "复核运营配置发生并发冲突，请刷新后重试", 409) from exc
        if record is not None:
            self.session.refresh(record)
            return self._review_saved_view_view(record)
        return {}

    def _active_review_member(self, tenant_id: str, subject: str, now: datetime | None = None) -> TenantMembershipRecord | None:
        record = self.session.scalar(select(TenantMembershipRecord).where(
            TenantMembershipRecord.tenant_id == tenant_id,
            TenantMembershipRecord.subject == subject,
            TenantMembershipRecord.status == "active",
        ))
        as_of = self._as_utc(now or self._now())
        if record is not None and record.expires_at is not None and self._as_utc(record.expires_at) <= as_of:
            return None
        return record

    def _active_review_delegations(self, tenant_id: str, now: datetime, delegate_subject: str | None = None) -> list[ModelRiskReviewDelegationRecord]:
        statement = select(ModelRiskReviewDelegationRecord).where(
            ModelRiskReviewDelegationRecord.tenant_id == tenant_id,
            ModelRiskReviewDelegationRecord.status == "active",
        )
        if delegate_subject:
            statement = statement.where(ModelRiskReviewDelegationRecord.delegate_subject == delegate_subject)
        rows = self.session.scalars(statement.order_by(ModelRiskReviewDelegationRecord.created_at.desc())).all()
        as_of = self._as_utc(now)
        return [row for row in rows if self._as_utc(row.starts_at) <= as_of < self._as_utc(row.ends_at)]

    @staticmethod
    def _review_assignment_view(record: ModelRiskReviewAssignmentRecord) -> dict:
        return {"id": record.id, "item_id": record.item_id, "source": record.source, "assigned_role": record.assigned_role, "assigned_to": record.assigned_to, "assigned_to_name": record.assigned_to_name, "reason": record.reason, "assigned_by": record.assigned_by, "assigned_by_name": record.assigned_by_name, "row_version": record.row_version, "created_at": record.created_at.isoformat() if record.created_at else None, "updated_at": record.updated_at.isoformat() if record.updated_at else None}

    def _review_delegation_view(self, record: ModelRiskReviewDelegationRecord, now: datetime | None = None) -> dict:
        as_of = self._as_utc(now or self._now())
        if record.status == "revoked":
            effective_status = "revoked"
        elif as_of < self._as_utc(record.starts_at):
            effective_status = "scheduled"
        elif as_of >= self._as_utc(record.ends_at):
            effective_status = "expired"
        else:
            effective_status = "active"
        return {
            "id": record.id, "principal_subject": record.principal_subject, "principal_name": record.principal_name,
            "delegate_subject": record.delegate_subject, "delegate_name": record.delegate_name,
            "assigned_role": record.assigned_role, "starts_at": self._as_utc(record.starts_at).isoformat(),
            "ends_at": self._as_utc(record.ends_at).isoformat(), "status": record.status,
            "effective_status": effective_status, "reason": record.reason,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "revoked_by": record.revoked_by, "revoked_by_name": record.revoked_by_name,
            "revoked_at": self._as_utc(record.revoked_at).isoformat() if record.revoked_at else None,
            "revocation_reason": record.revocation_reason, "row_version": record.row_version,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    @staticmethod
    def _review_saved_view_view(record: ModelRiskReviewSavedViewRecord) -> dict:
        return {"id": record.id, "tenant_id": record.tenant_id, "owner_subject": record.owner_subject, "name": record.name, "filters": deepcopy(record.filters_json or {}), "is_default": record.is_default, "row_version": record.row_version, "created_at": record.created_at.isoformat() if record.created_at else None, "updated_at": record.updated_at.isoformat() if record.updated_at else None}

    @staticmethod
    def _review_sla_snapshot_view(record: ModelRiskReviewSlaSnapshotRecord) -> dict:
        return {"id": record.id, "snapshot_date": record.snapshot_date.isoformat(), "template_key": record.template_key, "counts": deepcopy(record.counts_json or {}), "source_counts": deepcopy(record.source_counts_json or {}), "owner_counts": deepcopy(record.owner_counts_json or {}), "evidence_hash": record.evidence_hash, "created_at": record.created_at.isoformat() if record.created_at else None}

    def scan_reacceptance_reviews(self, tenant_id: str, actor_subject: str, now: datetime | None = None) -> dict:
        scan_at = self._as_utc(now or self._now())
        queue = self.reacceptance_review_queue(tenant_id, scan_at)
        notifications = NotificationRepository(self.session)
        prior = self.session.scalars(select(NotificationRecord).where(
            NotificationRecord.tenant_id == tenant_id,
            NotificationRecord.category == "model_risk_reacceptance_review",
            NotificationRecord.status != "resolved",
        )).all()
        active = {item["reacceptance_id"]: item["level"] for item in queue}
        resolved_count = 0
        for notice in prior:
            reacceptance_id = (notice.action_json or {}).get("reacceptance_id")
            if active.get(reacceptance_id) == notice.level:
                continue
            notice.status, notice.read_at = "resolved", scan_at
            resolved_count += 1
            self.audit.append("notification", notice.id, "model_risk_reacceptance_review_notification_resolved", actor_subject,
                              {"tenant_id": tenant_id, "reacceptance_id": reacceptance_id})
        created_count = 0
        for item in queue:
            for person in item["responsible"]:
                level = item["level"]
                message = (f"在役模型 {item['model_version']} 的再接受于 {item['review_due_at']} 到期；"
                           f"{'运行已阻断，请完成新证据签署。' if level == 'overdue' else '请提前准备监控证据并完成续期。'}")
                if item["evidence_level"] != "supervised":
                    message += "当前证据为非监督级别，续期应绑定足量真实结果标签。"
                payload = {
                    "case_id": None, "counterparty_id": None,
                    "recipient_role": person["role"], "recipient_subject": person["subject"],
                    "category": "model_risk_reacceptance_review", "level": level,
                    "severity": "critical" if level == "overdue" else "warning",
                    "title": "在役模型再接受已逾期" if level == "overdue" else "在役模型再接受即将到期",
                    "message": message,
                    "action_json": {"page": "model-governance", "model_change_id": item["model_change_id"],
                                    "release_id": item["model_release_id"], "reacceptance_id": item["reacceptance_id"]},
                    "dedup_key": f"model-risk-reacceptance:{item['reacceptance_id']}:{item['review_due_at']}:{level}:{person['subject']}:{person['role']}",
                    "status": "unread",
                }
                notification, created = notifications.create_if_absent(tenant_id, payload)
                if created:
                    created_count += 1
                    self.audit.append("notification", notification["id"], "model_risk_reacceptance_review_notified", actor_subject,
                                      {"tenant_id": tenant_id, "reacceptance_id": item["reacceptance_id"], "level": level})
        result = {"scanned_at": scan_at.isoformat(), "items_scanned": len(queue),
                  "overdue": sum(item["level"] == "overdue" for item in queue),
                  "notifications_created": created_count, "notifications_resolved": resolved_count}
        self.audit.append("tenant_model_risk_reacceptance_review_scan", f"{tenant_id}:{scan_at.date().isoformat()}",
                          "model_risk_reacceptance_review_scanned", actor_subject, {"tenant_id": tenant_id, **result})
        self.session.commit()
        return result

    def create_reacceptance(self, tenant_id: str, release_id: str, payload: dict, actor_subject: str, actor_name: str) -> dict:
        policy = self._active_policy(tenant_id)
        if policy is None:
            raise ModelRiskPolicyError("TENANT_POLICY_REQUIRED", "请先发布租户模型风险政策，再发起在役模型再接受", 409)
        release, change, prior = self._reacceptance_subject(tenant_id, release_id)
        prior_view = self._acceptance_view(prior)
        if prior_view["effective_status"] not in {"accepted", "overdue"}:
            raise ModelRiskPolicyError("PRIOR_ACCEPTANCE_INVALID", "原风险接受已失效，请先按当前政策完成模型变更接受", 409)
        if prior.policy_id != policy.id or prior.evidence_binding_hash != change.supervised_validation_binding_hash:
            raise ModelRiskPolicyError("PRIOR_ACCEPTANCE_STALE", "原风险接受与当前政策或监督证据不一致", 409)
        level = self._level(policy.levels_json, prior.risk_level)
        existing = self.session.scalar(select(ModelRiskReacceptanceRecord).where(
            ModelRiskReacceptanceRecord.tenant_id == tenant_id,
            ModelRiskReacceptanceRecord.model_release_id == release.id,
            ModelRiskReacceptanceRecord.status == "pending",
        ))
        if existing:
            operational = existing.operational_evidence_json or {}
            if (existing.policy_id == policy.id and existing.source_evidence_binding_hash == change.supervised_validation_binding_hash
                and existing.release_config_hash == release.config_hash and operational.get("observed_from") == payload["observed_from"].isoformat()
                and operational.get("observed_to") == payload["observed_to"].isoformat()
                and operational.get("evidence_reference") == payload["evidence_reference"]
                and operational.get("evidence_summary") == payload["evidence_summary"]
                and existing.rationale == payload["rationale"]
                and existing.monitoring_run_id == payload.get("monitoring_run_id")
                and existing.monitoring_evidence_hash == payload.get("monitoring_evidence_hash")
                and existing.label_evidence_id == payload.get("label_evidence_id")
                and (operational.get("supervised_binding") or {}).get("evaluation_id") == payload.get("supervised_evaluation_id")
                and (operational.get("supervised_binding") or {}).get("evidence_hash") == payload.get("supervised_evidence_hash")):
                return {**self._reacceptance_view(existing), "idempotent": True}
            raise ModelRiskPolicyError("REACCEPTANCE_PENDING_EXISTS", "已有待签续期；请先完成签署或明确撤销后重新发起", 409)
        now = self._now()
        monitoring_binding = self._monitoring_binding(release, payload)
        supervised_binding = self._supervised_binding(tenant_id, release, payload)
        operational = {
            "schema_version": "in-service-model-risk-evidence-v1",
            "captured_at": now.isoformat(), "observed_from": payload["observed_from"].isoformat(),
            "observed_to": payload["observed_to"].isoformat(), "evidence_reference": payload["evidence_reference"],
            "evidence_summary": payload["evidence_summary"],
            "monitoring_binding": monitoring_binding,
            "supervised_binding": supervised_binding,
            "label_evidence_id": payload.get("label_evidence_id"),
            "release": {"id": release.id, "template_key": release.template_key, "model_version": release.model_version,
                        "config_hash": release.config_hash, "published_at": release.published_at.isoformat() if release.published_at else None},
            "source_change": {"id": change.id, "supervised_validation_binding_hash": change.supervised_validation_binding_hash},
            "prior_acceptance": {"id": prior.id, "policy_id": prior.policy_id, "policy_config_hash": prior.policy_config_hash,
                                 "evidence_binding_hash": prior.evidence_binding_hash, "accepted_at": prior.accepted_at.isoformat() if prior.accepted_at else None},
        }
        record = ModelRiskReacceptanceRecord(
            id=str(uuid4()), tenant_id=tenant_id, model_release_id=release.id, model_change_id=change.id,
            prior_acceptance_id=prior.id, policy_id=policy.id, policy_version=policy.version,
            policy_config_hash=policy.config_hash, source_evidence_binding_hash=change.supervised_validation_binding_hash,
            release_config_hash=release.config_hash, operational_evidence_json=operational,
            operational_evidence_hash=content_hash(operational), risk_level=prior.risk_level,
            monitoring_run_id=monitoring_binding.get("monitoring_run_id"),
            monitoring_evidence_hash=monitoring_binding.get("evidence_hash"),
            label_evidence_id=payload.get("label_evidence_id"),
            required_roles_json=list(level["acceptance_roles"]), approvals_json=[], status="pending",
            rationale=payload["rationale"], created_by=actor_subject, created_by_name=actor_name,
        )
        self.session.add(record)
        return self._commit_reacceptance(record, "model_risk_reacceptance_created", actor_subject, payload["rationale"])

    def accept_reacceptance(self, tenant_id: str, reacceptance_id: str, expected_row_version: int, acceptance_role: str, note: str, actor_subject: str, actor_name: str, actor_roles: tuple[str, ...]) -> dict:
        record = self._reacceptance(tenant_id, reacceptance_id)
        self._check_version(record.row_version, expected_row_version)
        if record.status != "pending":
            raise ModelRiskPolicyError("REACCEPTANCE_STATUS_INVALID", "只有待签署在役再接受记录可以操作", 409)
        self._assert_reacceptance_current(record)
        binding = (record.operational_evidence_json or {}).get("supervised_binding") or {}
        if binding.get("evidence_level") != "supervised":
            raise ModelRiskPolicyError("REACCEPTANCE_SUPERVISION_REQUIRED", "须绑定同租户已批准的监督评估；共享监控运行仅为非监督诊断，不能正式签署", 409)
        if acceptance_role not in record.required_roles_json:
            raise ModelRiskPolicyError("ACCEPTANCE_ROLE_INVALID", "该风险等级不需要当前接受席位")
        required_platform_role = ROLE_BINDINGS[acceptance_role]
        if required_platform_role not in actor_roles and "admin" not in actor_roles:
            raise ModelRiskPolicyError("ACCEPTANCE_ROLE_FORBIDDEN", f"当前账号不具备 {required_platform_role} 角色", 403)
        approvals = deepcopy(record.approvals_json or [])
        if any(item["acceptance_role"] == acceptance_role for item in approvals):
            raise ModelRiskPolicyError("ACCEPTANCE_ROLE_COMPLETED", "该再接受席位已经签署", 409)
        if any(item["actor_subject"] == actor_subject for item in approvals):
            raise ModelRiskPolicyError("FOUR_EYES_REQUIRED", "同一人员不能签署多个在役再接受席位", 409)
        now = self._now()
        approvals.append({"acceptance_role": acceptance_role, "platform_role": required_platform_role,
                          "actor_subject": actor_subject, "actor_name": actor_name, "note": note,
                          "accepted_at": now.isoformat()})
        record.approvals_json = approvals
        if {item["acceptance_role"] for item in approvals} == set(record.required_roles_json):
            level = self._level(self._policy(tenant_id, record.policy_id).levels_json, record.risk_level)
            previous = self.session.scalar(select(ModelRiskReacceptanceRecord).where(
                ModelRiskReacceptanceRecord.tenant_id == tenant_id,
                ModelRiskReacceptanceRecord.model_release_id == record.model_release_id,
                ModelRiskReacceptanceRecord.status == "accepted",
            ))
            if previous:
                previous.status, previous.revoked_at = "revoked", now
                previous.revoked_by, previous.revoked_by_name = actor_subject, actor_name
                previous.revocation_reason = f"由在役再接受 {record.id} 续期替代"
                self.session.flush()
                self.audit.append("model_risk_reacceptance", previous.id, "model_risk_reacceptance_superseded", actor_subject,
                                  {"tenant_id": tenant_id, "replacement_id": record.id, "reason": previous.revocation_reason})
            record.status, record.accepted_at = "accepted", now
            record.review_due_at = now + timedelta(days=int(level["review_days"]))
        return self._commit_reacceptance(record, "model_risk_reacceptance_signed", actor_subject, note)

    def revoke_reacceptance(self, tenant_id: str, reacceptance_id: str, expected_row_version: int, reason: str, actor_subject: str, actor_name: str) -> dict:
        record = self._reacceptance(tenant_id, reacceptance_id)
        self._check_version(record.row_version, expected_row_version)
        if record.status == "revoked":
            raise ModelRiskPolicyError("REACCEPTANCE_STATUS_INVALID", "在役再接受记录已经撤销", 409)
        record.status, record.revoked_at = "revoked", self._now()
        record.revoked_by, record.revoked_by_name, record.revocation_reason = actor_subject, actor_name, reason
        return self._commit_reacceptance(record, "model_risk_reacceptance_revoked", actor_subject, reason)

    def in_service_release_status(self, tenant_id: str, release_id: str, required: bool = False) -> dict:
        release, change, prior = self._reacceptance_subject(tenant_id, release_id)
        policy = self._active_policy(tenant_id)
        if policy is None:
            return {"required": False, "effective_status": "not_required", "release_id": release.id, "reacceptance": None}
        prior_view = self._acceptance_view(prior)
        accepted = self.session.scalar(select(ModelRiskReacceptanceRecord).where(
            ModelRiskReacceptanceRecord.tenant_id == tenant_id,
            ModelRiskReacceptanceRecord.model_release_id == release.id,
            ModelRiskReacceptanceRecord.status == "accepted",
        ))
        pending = self.session.scalar(select(ModelRiskReacceptanceRecord).where(
            ModelRiskReacceptanceRecord.tenant_id == tenant_id,
            ModelRiskReacceptanceRecord.model_release_id == release.id,
            ModelRiskReacceptanceRecord.status == "pending",
        ))
        active = accepted or pending
        reacceptance = self._reacceptance_view(active) if active else None
        effective = "accepted" if prior_view["effective_status"] == "accepted" else (reacceptance or {}).get("effective_status", "required")
        result = {"required": True, "effective_status": effective, "release_id": release.id,
                  "model_change_id": change.id, "prior_acceptance": prior_view, "reacceptance": reacceptance,
                  "pending_renewal": self._reacceptance_view(pending) if pending else None}
        if required and effective != "accepted":
            messages = {"required": "在役模型风险接受已到期，请创建新的运行证据快照并完成再接受",
                        "pending": "在役模型再接受席位尚未全部签署", "overdue": "在役模型再接受已超过复核期限",
                        "policy_stale": "在役模型再接受绑定的政策版本已失效", "evidence_stale": "在役模型再接受绑定的监督证据已变化",
                        "release_stale": "在役模型再接受绑定的发布配置已变化", "revoked": "在役模型再接受已撤销"}
            raise ModelRiskPolicyError("IN_SERVICE_REACCEPTANCE_REQUIRED", messages.get(effective, "在役模型再接受当前不可用"), 409)
        return result

    def audit_package(self, tenant_id: str, reacceptance_id: str, package_format: str = "full") -> dict:
        """Build a deterministic governance export with optional regulatory projection."""
        if package_format not in {"full", "regulatory"}:
            raise ModelRiskPolicyError("AUDIT_PACKAGE_FORMAT_INVALID", "仅支持 full 或 regulatory 导出格式", 422)
        record = self._reacceptance(tenant_id, reacceptance_id)
        view = self._reacceptance_view(record)
        release = self.session.get(ModelReleaseRecord, record.model_release_id)
        change = self.session.get(ModelChangeRecord, record.model_change_id)
        prior = self.session.get(ModelRiskAcceptanceRecord, record.prior_acceptance_id)
        policy = self.session.get(TenantModelRiskPolicyRecord, record.policy_id)
        monitoring = self.session.get(ModelMonitoringRunRecord, record.monitoring_run_id) if record.monitoring_run_id else None
        supervised_binding = (record.operational_evidence_json or {}).get("supervised_binding") or {}
        evaluation = self.session.get(TenantSupervisedEvaluationRecord, supervised_binding.get("evaluation_id")) if supervised_binding.get("evaluation_id") else None
        audit_rows = self.session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.aggregate_type == "model_risk_reacceptance",
            AuditEventRecord.aggregate_id == record.id,
            AuditEventRecord.event_type != AUDIT_PACKAGE_DOWNLOAD_EVENT,
        ).order_by(AuditEventRecord.created_at, AuditEventRecord.id)).all()
        supervised_snapshot = self._supervised_evaluation_snapshot(evaluation) if evaluation and evaluation.tenant_id == tenant_id else None
        if supervised_snapshot and evaluation.tenant_monitoring_run_id:
            tenant_run = self.session.get(TenantMonitoringRunRecord, evaluation.tenant_monitoring_run_id)
            if tenant_run:
                from backend.tenant_outcome_repository import TenantOutcomeRepository
                monitoring_gate = TenantOutcomeRepository(self.session).monitoring_gate(
                    tenant_id, evaluation.policy_id, tenant_run.id,
                )
                supervised_snapshot["tenant_monitoring_run"] = {
                    "id": tenant_run.id, "run_key": tenant_run.run_key,
                    "model_key": tenant_run.model_key, "model_version": tenant_run.model_version,
                    "observed_from": tenant_run.observed_from.isoformat(),
                    "observed_to": tenant_run.observed_to.isoformat(),
                    "dataset_id": tenant_run.dataset_id, "status": tenant_run.status,
                    "evidence_level": tenant_run.evidence_level,
                    "label_definition_id": tenant_run.label_definition_id,
                    "label_definition_version": tenant_run.label_definition_version,
                    "label_definition_hash": tenant_run.label_definition_hash,
                    "label_watermark": deepcopy(tenant_run.label_watermark_json or {}),
                    "monitoring": deepcopy(tenant_run.monitoring_json or {}),
                    "evidence_hash": tenant_run.evidence_hash,
                    "governance_status": tenant_run.governance_status,
                    "monitoring_gate": monitoring_gate,
                }
        package = {
            "schema_version": "model-risk-reacceptance-audit-package-v1",
            "tenant_id": tenant_id, "generated_at": self._now().isoformat(),
            "reacceptance": view,
            "prior_acceptance": self._acceptance_view(prior) if prior else None,
            "release": {
                "id": release.id, "template_key": release.template_key, "model_version": release.model_version,
                "config_hash": release.config_hash, "published_at": release.published_at.isoformat() if release.published_at else None,
            } if release else None,
            "policy": self._policy_view(policy) if policy else None,
            "model_change": {
                "id": change.id, "candidate_version": change.candidate_version,
                "supervised_validation_binding_hash": change.supervised_validation_binding_hash,
            } if change else None,
            "monitoring_run": self._monitoring_run_snapshot(monitoring) if monitoring else None,
            "supervised_evaluation": supervised_snapshot,
            "audit_events": [self._audit_event_snapshot(row) for row in audit_rows],
        }
        # The generation timestamp is presentation metadata; excluding it keeps the export hash stable.
        hashable_package = {key: value for key, value in package.items() if key != "generated_at"}
        package = {**package, "package_hash": content_hash(hashable_package)}
        if package_format == "regulatory":
            return self._sign_regulatory_report(self._regulatory_report(package))
        return package

    def record_audit_package_download(
        self,
        tenant_id: str,
        reacceptance_id: str,
        package_hash: str,
        package_format: str,
        actor_subject: str,
        actor_name: str,
    ) -> None:
        """Persist a tenant audit event without changing the exported package hash."""
        if package_format not in {"full", "regulatory"}:
            raise ModelRiskPolicyError("AUDIT_PACKAGE_FORMAT_INVALID", "仅支持 full 或 regulatory 导出格式", 422)
        self._reacceptance(tenant_id, reacceptance_id)
        try:
            self.audit.append(
                "model_risk_reacceptance",
                reacceptance_id,
                AUDIT_PACKAGE_DOWNLOAD_EVENT,
                actor_subject,
                {
                    "tenant_id": tenant_id,
                    "reacceptance_id": reacceptance_id,
                    "package_hash": package_hash,
                    "format": package_format,
                    "actor": actor_name,
                },
            )
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            raise ModelRiskPolicyError("AUDIT_PACKAGE_LOG_FAILED", "监管审计包下载留痕失败，请稍后重试", 500) from exc

    @staticmethod
    def _regulatory_report(package: dict) -> dict:
        reacceptance = package["reacceptance"]
        operational = reacceptance.get("operational_evidence") or {}
        supervised = package.get("supervised_evaluation")
        monitoring = package.get("monitoring_run")
        monitoring_binding = operational.get("monitoring_binding") or {}
        supervised_binding = operational.get("supervised_binding") or {}
        if supervised:
            evidence_level = "supervised"
            evidence_source = "tenant_supervised_evaluation"
            coverage = deepcopy(supervised.get("coverage") or {})
            metrics = deepcopy(supervised.get("metrics") or {})
            downgrade = None
        else:
            evidence_level = monitoring_binding.get("evidence_level", "non_supervised")
            evidence_source = "platform_monitoring_run" if monitoring else "manual_or_legacy_evidence"
            coverage = deepcopy(monitoring_binding.get("label_coverage") or {})
            metrics = deepcopy(monitoring_binding.get("metrics") or {})
            if not metrics and monitoring:
                monitoring_json = monitoring.get("monitoring") or {}
                metrics = {item.get("key"): item.get("value") for item in monitoring_json.get("performance_metrics", []) if item.get("key")}
                metrics["psi"] = (monitoring_json.get("population_stability") or {}).get("value")
            downgrade = {
                "status": "non_supervised",
                "reason": "未绑定已批准的租户监督评估，指标仅作为非监督稳定性或运行诊断证据",
            }
        status_map = {
            "accepted": "accepted", "pending": "at_risk", "overdue": "at_risk",
            "evidence_stale": "evidence_stale", "policy_stale": "blocked",
            "release_stale": "blocked", "revoked": "blocked",
        }
        approvals = reacceptance.get("approvals") or []
        signer_subjects = [item.get("actor_subject") for item in approvals if item.get("actor_subject")]
        required_roles = reacceptance.get("required_roles") or []
        signed_roles = [item.get("acceptance_role") for item in approvals if item.get("acceptance_role")]
        four_eyes_required = len(required_roles) > 1
        four_eyes_passed = len(set(signer_subjects)) == len(signer_subjects) and set(signed_roles) == set(required_roles)
        release = package.get("release") or {}
        policy = package.get("policy") or {}
        matching_level = next((item for item in policy.get("levels", []) if item.get("level") == reacceptance.get("risk_level")), {})
        report = {
            "schema_version": "model-risk-reacceptance-regulatory-report-v1",
            "tenant_id": package["tenant_id"],
            "generated_at": package["generated_at"],
            "reacceptance_id": reacceptance["id"],
            "model": {
                "release_id": release.get("id"), "template_key": release.get("template_key"),
                "model_version": release.get("model_version"), "config_hash": release.get("config_hash"),
                "published_at": release.get("published_at"),
            },
            "observation_window": {
                "observed_from": operational.get("observed_from"), "observed_to": operational.get("observed_to"),
                "captured_at": operational.get("captured_at"), "evidence_reference": operational.get("evidence_reference"),
            },
            "governance": {
                "risk_level": reacceptance.get("risk_level"), "policy_id": reacceptance.get("policy_id"),
                "policy_version": reacceptance.get("policy_version"), "policy_config_hash": reacceptance.get("policy_config_hash"),
                "required_evidence": list(matching_level.get("required_evidence") or []),
                "required_roles": required_roles, "signed_roles": signed_roles,
                "four_eyes": {
                    "required": four_eyes_required, "passed": four_eyes_passed if four_eyes_required else True,
                    "distinct_signer_count": len(set(signer_subjects)),
                },
                "approvals": deepcopy(approvals),
            },
            "evidence": {
                "level": evidence_level, "source": evidence_source, "coverage": coverage, "metrics": metrics,
                "tenant_supervised_evaluation_id": supervised.get("id") if supervised else supervised_binding.get("evaluation_id"),
                "supervised_evidence_hash": supervised.get("evidence_hash") if supervised else supervised_binding.get("evidence_hash"),
                "label_definition_id": (supervised or {}).get("label_definition_id") or supervised_binding.get("label_definition_id"),
                "label_definition_version": (supervised or {}).get("label_definition_version") or supervised_binding.get("label_definition_version"),
                "downgrade": downgrade,
            },
            "runtime_impact": {
                "status": status_map.get(reacceptance.get("effective_status"), "blocked"),
                "effective_status": reacceptance.get("effective_status"),
                "review_due_at": reacceptance.get("review_due_at"),
            },
            "integrity": {
                "package_hash": package["package_hash"],
                "operational_evidence_hash": reacceptance.get("operational_evidence_hash"),
                "monitoring_evidence_hash": reacceptance.get("monitoring_evidence_hash"),
                "supervised_evidence_hash": supervised.get("evidence_hash") if supervised else None,
                "audit_event_count": len(package.get("audit_events") or []),
                "audit_chain_scope": "governance_events_excluding_downloads",
            },
        }
        hashable_report = {key: value for key, value in report.items() if key != "generated_at"}
        return {**report, "report_hash": content_hash(hashable_report)}

    def _sign_regulatory_report(self, report: dict) -> dict:
        signature_body = {
            "schema_version": report["schema_version"], "tenant_id": report["tenant_id"],
            "reacceptance_id": report["reacceptance_id"], "package_hash": report["integrity"]["package_hash"],
            "report_hash": report["report_hash"], "signature_algorithm": self.signer.algorithm,
            "signing_key_id": self.signer.key_id,
            "key_metadata": signing_key_metadata(self.signer),
        }
        signature = self.signer.sign(signature_body)
        signing = {
            "signature_algorithm": self.signer.algorithm, "signing_key_id": self.signer.key_id,
            "signing_public_key": self.signer.public_key,
            "public_key_fingerprint": public_key_fingerprint(self.signer.public_key),
            "signature": signature, "signature_body": signature_body,
            "key_metadata": signing_key_metadata(self.signer),
            "signature_valid": verify_signature(self.signer.algorithm, signature_body, signature, self.signer.public_key),
            "timestamp_mode": "content_deterministic",
        }
        return {**report, "signing": signing}

    def accept(self, tenant_id: str, acceptance_id: str, expected_row_version: int, acceptance_role: str, note: str, actor_subject: str, actor_name: str, actor_roles: tuple[str, ...]) -> dict:
        record = self._acceptance(tenant_id, acceptance_id)
        self._check_version(record.row_version, expected_row_version)
        if record.status != "pending":
            raise ModelRiskPolicyError("ACCEPTANCE_STATUS_INVALID", "只有待签署风险接受记录可以操作", 409)
        change, evidence = self._change(tenant_id, record.model_change_id)
        policy = self._active_policy(tenant_id)
        if policy is None or policy.id != record.policy_id or change.supervised_validation_binding_hash != record.evidence_binding_hash:
            raise ModelRiskPolicyError("ACCEPTANCE_STALE", "风险政策或监督验证证据已变化，请重新创建接受台账", 409)
        if change.status != "draft" or (evidence.get("independent_validation") or {}).get("status") != "approved":
            raise ModelRiskPolicyError("CHANGE_STATUS_INVALID", "只有独立验证已批准的草稿可以签署风险接受", 409)
        if acceptance_role not in record.required_roles_json:
            raise ModelRiskPolicyError("ACCEPTANCE_ROLE_INVALID", "该风险等级不需要当前接受席位", 422)
        required_platform_role = ROLE_BINDINGS.get(acceptance_role)
        if required_platform_role not in actor_roles and "admin" not in actor_roles:
            raise ModelRiskPolicyError("ACCEPTANCE_ROLE_FORBIDDEN", f"当前账号不具备 {required_platform_role} 角色", 403)
        approvals = deepcopy(record.approvals_json or [])
        if any(item["acceptance_role"] == acceptance_role for item in approvals):
            raise ModelRiskPolicyError("ACCEPTANCE_ROLE_COMPLETED", "该接受席位已经签署", 409)
        if any(item["actor_subject"] == actor_subject for item in approvals):
            raise ModelRiskPolicyError("FOUR_EYES_REQUIRED", "同一人员不能签署多个风险接受席位", 409)
        now = self._now()
        approvals.append({
            "acceptance_role": acceptance_role, "platform_role": required_platform_role,
            "actor_subject": actor_subject, "actor_name": actor_name, "note": note,
            "accepted_at": now.isoformat(),
        })
        record.approvals_json = approvals
        if {item["acceptance_role"] for item in approvals} == set(record.required_roles_json):
            policy = self._policy(tenant_id, record.policy_id)
            level = self._level(policy.levels_json, record.risk_level)
            record.status, record.accepted_at = "accepted", now
            record.review_due_at = now + timedelta(days=int(level["review_days"]))
        return self._commit_acceptance(record, "model_risk_acceptance_signed", actor_subject, note)

    def revoke_acceptance(self, tenant_id: str, acceptance_id: str, expected_row_version: int, reason: str, actor_subject: str, actor_name: str) -> dict:
        record = self._acceptance(tenant_id, acceptance_id)
        self._check_version(record.row_version, expected_row_version)
        if record.status == "revoked":
            raise ModelRiskPolicyError("ACCEPTANCE_STATUS_INVALID", "风险接受记录已经撤销", 409)
        record.status, record.revoked_at = "revoked", self._now()
        record.revoked_by, record.revoked_by_name = actor_subject, actor_name
        record.revocation_reason = reason
        return self._commit_acceptance(record, "model_risk_acceptance_revoked", actor_subject, reason)

    def current_acceptance_snapshot(self, tenant_id: str, change_id: str, required: bool = True) -> dict | None:
        policy = self._active_policy(tenant_id)
        if policy is None:
            return None
        record = self.session.scalar(select(ModelRiskAcceptanceRecord).where(
            ModelRiskAcceptanceRecord.tenant_id == tenant_id,
            ModelRiskAcceptanceRecord.model_change_id == change_id,
            ModelRiskAcceptanceRecord.status.in_(["pending", "accepted"]),
        ))
        if record is None:
            if required:
                raise ModelRiskPolicyError("RISK_ACCEPTANCE_REQUIRED", "当前租户政策要求完成模型风险接受", 409)
            return None
        view = self._acceptance_view(record)
        if record.policy_id != policy.id or view["effective_status"] != "accepted":
            if required:
                messages = {
                    "pending": "模型风险接受席位尚未全部签署",
                    "overdue": "模型风险接受已超过定期复核期限",
                    "policy_stale": "模型风险接受绑定的政策版本已失效",
                    "evidence_stale": "模型风险接受绑定的监督证据已变化",
                }
                raise ModelRiskPolicyError("RISK_ACCEPTANCE_INVALID", messages.get(view["effective_status"], "模型风险接受当前不可用"), 409)
            return view
        return view

    def policy_snapshot(self, tenant_id: str) -> dict:
        return self.current_catalog(tenant_id)

    def _policy(self, tenant_id: str, policy_id: str) -> TenantModelRiskPolicyRecord:
        record = self.session.scalar(select(TenantModelRiskPolicyRecord).where(
            TenantModelRiskPolicyRecord.tenant_id == tenant_id,
            TenantModelRiskPolicyRecord.id == policy_id,
        ))
        if record is None:
            raise ModelRiskPolicyError("POLICY_NOT_FOUND", "模型风险政策不存在", 404)
        return record

    def _active_policy(self, tenant_id: str) -> TenantModelRiskPolicyRecord | None:
        return self.session.scalar(select(TenantModelRiskPolicyRecord).where(
            TenantModelRiskPolicyRecord.tenant_id == tenant_id,
            TenantModelRiskPolicyRecord.status == "published",
            TenantModelRiskPolicyRecord.is_active.is_(True),
        ))

    def _acceptance(self, tenant_id: str, acceptance_id: str) -> ModelRiskAcceptanceRecord:
        record = self.session.scalar(select(ModelRiskAcceptanceRecord).where(
            ModelRiskAcceptanceRecord.tenant_id == tenant_id,
            ModelRiskAcceptanceRecord.id == acceptance_id,
        ))
        if record is None:
            raise ModelRiskPolicyError("ACCEPTANCE_NOT_FOUND", "模型风险接受记录不存在", 404)
        return record

    def _reacceptance(self, tenant_id: str, reacceptance_id: str) -> ModelRiskReacceptanceRecord:
        record = self.session.scalar(select(ModelRiskReacceptanceRecord).where(
            ModelRiskReacceptanceRecord.tenant_id == tenant_id,
            ModelRiskReacceptanceRecord.id == reacceptance_id,
        ))
        if record is None:
            raise ModelRiskPolicyError("REACCEPTANCE_NOT_FOUND", "在役模型再接受记录不存在", 404)
        return record

    def _reacceptance_subject(self, tenant_id: str, release_id: str) -> tuple[ModelReleaseRecord, ModelChangeRecord, ModelRiskAcceptanceRecord]:
        release = self.session.get(ModelReleaseRecord, release_id)
        if release is None or not release.is_active or not release.source_change_id:
            raise ModelRiskPolicyError("IN_SERVICE_RELEASE_NOT_FOUND", "当前租户下不存在可再接受的在役模型发布版本", 404)
        change, evidence = self._change(tenant_id, release.source_change_id)
        if change.status != "published" or release.config_hash != change.validation_json.get("config_hash"):
            raise ModelRiskPolicyError("IN_SERVICE_RELEASE_STALE", "在役模型发布版本与已批准模型变更不一致", 409)
        prior = self.session.scalar(select(ModelRiskAcceptanceRecord).where(
            ModelRiskAcceptanceRecord.tenant_id == tenant_id,
            ModelRiskAcceptanceRecord.model_change_id == change.id,
            ModelRiskAcceptanceRecord.status == "accepted",
        ).order_by(ModelRiskAcceptanceRecord.accepted_at.desc()))
        if prior is None:
            raise ModelRiskPolicyError("PRIOR_ACCEPTANCE_REQUIRED", "在役模型缺少原始风险接受，不能发起再接受", 409)
        return release, change, prior

    def _assert_reacceptance_current(self, record: ModelRiskReacceptanceRecord, now: datetime | None = None) -> None:
        policy = self._active_policy(record.tenant_id)
        release = self.session.get(ModelReleaseRecord, record.model_release_id)
        change = self.session.get(ModelChangeRecord, record.model_change_id)
        if policy is None or policy.id != record.policy_id:
            raise ModelRiskPolicyError("REACCEPTANCE_STALE", "模型风险政策已变化，请重新发起在役再接受", 409)
        if not release or not release.is_active or release.config_hash != record.release_config_hash:
            raise ModelRiskPolicyError("REACCEPTANCE_STALE", "在役模型发布配置已变化，请重新发起再接受", 409)
        if not change or change.supervised_validation_binding_hash != record.source_evidence_binding_hash:
            raise ModelRiskPolicyError("REACCEPTANCE_STALE", "监督验证证据已变化，请重新发起在役再接受", 409)
        if content_hash(record.operational_evidence_json or {}) != record.operational_evidence_hash:
            raise ModelRiskPolicyError("REACCEPTANCE_EVIDENCE_INVALID", "在役运行证据快照完整性校验失败", 409)
        if record.monitoring_run_id:
            run = self.session.get(ModelMonitoringRunRecord, record.monitoring_run_id)
            if not run or self._monitoring_evidence_hash(run) != record.monitoring_evidence_hash:
                raise ModelRiskPolicyError("REACCEPTANCE_EVIDENCE_INVALID", "绑定的监控运行证据已变化或不存在", 409)
        binding = (record.operational_evidence_json or {}).get("supervised_binding") or {}
        if binding.get("evaluation_id"):
            self._supervised_binding(record.tenant_id, release, {
                "supervised_evaluation_id": binding["evaluation_id"],
                "supervised_evidence_hash": binding["evidence_hash"],
            }, expected=binding)

    def _supervised_binding(self, tenant_id: str, release: ModelReleaseRecord, payload: dict, expected: dict | None = None) -> dict:
        evaluation_id = payload.get("supervised_evaluation_id")
        if not evaluation_id:
            if payload.get("supervised_evidence_hash"):
                raise ModelRiskPolicyError("SUPERVISED_EVALUATION_REQUIRED", "监督证据哈希必须绑定评估编号", 422)
            return {"evidence_level": "non_supervised", "reason": "tenant_evaluation_not_bound"}
        evaluation = self.session.scalar(select(TenantSupervisedEvaluationRecord).where(
            TenantSupervisedEvaluationRecord.id == evaluation_id,
            TenantSupervisedEvaluationRecord.tenant_id == tenant_id,
        ))
        if evaluation is None:
            raise ModelRiskPolicyError("SUPERVISED_EVALUATION_NOT_FOUND", "当前租户下不存在该监督评估", 404)
        from backend.tenant_outcome_repository import TenantOutcomeRepository, TenantRolloutError
        try:
            TenantOutcomeRepository(self.session)._verify_evaluation_integrity(evaluation)
        except TenantRolloutError as exc:
            raise ModelRiskPolicyError("SUPERVISED_EVIDENCE_INVALID", exc.message, 409) from exc
        if evaluation.evidence_hash != payload.get("supervised_evidence_hash"):
            raise ModelRiskPolicyError("SUPERVISED_EVIDENCE_HASH_MISMATCH", "监督评估哈希不匹配，请重新选择证据", 409)
        tenant_monitoring = None
        monitoring_gate = None
        if evaluation.tenant_monitoring_run_id:
            tenant_monitoring = self.session.scalar(select(TenantMonitoringRunRecord).where(
                TenantMonitoringRunRecord.id == evaluation.tenant_monitoring_run_id,
                TenantMonitoringRunRecord.tenant_id == tenant_id,
                TenantMonitoringRunRecord.policy_id == evaluation.policy_id,
            ))
            if tenant_monitoring is None or self._tenant_monitoring_evidence_hash(tenant_monitoring) != evaluation.tenant_monitoring_evidence_hash:
                raise ModelRiskPolicyError("SUPERVISED_MONITORING_INVALID", "监督评估绑定的租户监控运行不存在或证据已变化", 409)
            from backend.tenant_outcome_repository import TenantOutcomeRepository
            monitoring_gate = TenantOutcomeRepository(self.session).monitoring_gate(
                tenant_id, evaluation.policy_id, tenant_monitoring.id,
            )
            if monitoring_gate["status"] in {"blocked", "evidence_stale"}:
                raise ModelRiskPolicyError("SUPERVISED_MONITORING_GATE_BLOCKED", "租户监控门禁未通过，不能作为正式再接受证据", 409)
            if monitoring_gate["status"] == "at_risk":
                raise ModelRiskPolicyError("SUPERVISED_MONITORING_GATE_AT_RISK", "租户监控仍处于风险或非监督诊断状态，不能签署正式再接受", 409)
        if evaluation.status != "approved" or evaluation.evidence_level != "supervised":
            raise ModelRiskPolicyError("SUPERVISED_EVALUATION_NOT_APPROVED", "仅已批准且达到监督门槛的评估可用于正式再接受", 409)
        coverage, config, metrics = evaluation.coverage_json or {}, evaluation.config_json or {}, evaluation.metrics_json or {}
        if (coverage.get("mature_count", 0) < config.get("min_mature_samples", 1)
            or coverage.get("event_count", 0) < config.get("min_events", 1)
            or coverage.get("non_event_count", 0) < config.get("min_non_events", 1)
            or not all((metrics.get(arm) or {}).get("metrics_ready") for arm in ("champion", "challenger"))):
            raise ModelRiskPolicyError("SUPERVISED_COVERAGE_INVALID", "监督评估的成熟样本和双模型区分度未达到冻结门槛", 409)
        policy = self.session.get(TenantRolloutPolicyRecord, evaluation.policy_id)
        if policy is None or policy.tenant_id != tenant_id or content_hash(policy.arm_snapshot_json) != policy.assets_hash:
            raise ModelRiskPolicyError("SUPERVISED_ASSETS_INVALID", "租户灰度资产已缺失或完整性校验失败", 409)
        if (policy.champion_model_key, policy.champion_model_version) != (release.template_key, release.model_version) and (policy.challenger_model_key, policy.challenger_model_version) != (release.template_key, release.model_version):
            raise ModelRiskPolicyError("SUPERVISED_MODEL_MISMATCH", "监督评估的冻结模型与在役版本不一致", 409)
        watermark = evaluation.label_watermark_json or {}
        if watermark.get("policy_config_hash") != policy.config_hash or watermark.get("policy_assets_hash") != policy.assets_hash:
            raise ModelRiskPolicyError("SUPERVISED_ASSETS_DRIFTED", "评估所绑定的灰度配置或资产已变化", 409)
        definition = self.session.get(TenantOutcomeLabelDefinitionRecord, evaluation.label_definition_id) if evaluation.label_definition_id else None
        if not definition or definition.tenant_id != tenant_id or definition.version != evaluation.label_definition_version or definition.config_hash != evaluation.label_definition_hash or watermark.get("label_definition_hash") != definition.config_hash:
            raise ModelRiskPolicyError("SUPERVISED_LABEL_DEFINITION_INVALID", "监督评估缺少有效的租户标签口径版本", 409)
        try:
            TenantOutcomeRepository._verify_definition_integrity(definition)
            labels = list(self.session.scalars(select(TenantOutcomeLabelRecord).where(
                TenantOutcomeLabelRecord.tenant_id == tenant_id,
                TenantOutcomeLabelRecord.policy_id == policy.id,
                TenantOutcomeLabelRecord.id.in_(watermark.get("label_ids") or []),
            )).all())
            for label in labels:
                TenantOutcomeRepository(self.session)._verify_label_integrity(label)
        except TenantRolloutError as exc:
            raise ModelRiskPolicyError("SUPERVISED_LABELS_INVALID", exc.message, 409) from exc
        if (len(labels) != watermark.get("label_count") or len(labels) != len(watermark.get("label_ids") or [])
            or sorted(row.evidence_hash for row in labels) != watermark.get("label_evidence_hashes")
            or sorted(row.routing_evidence_hash for row in labels) != watermark.get("routing_evidence_hashes")
            or any(row.label_definition_id != definition.id for row in labels)):
            raise ModelRiskPolicyError("SUPERVISED_LABELS_DRIFTED", "评估标签血缘或证据哈希已变化", 409)
        if (sum(bool(row.observed_event) for row in labels) != coverage.get("event_count")
            or len(labels) - sum(bool(row.observed_event) for row in labels) != coverage.get("non_event_count")
            or any(len(arm_rows := [row for row in labels if row.selected_arm == arm]) != metrics[arm]["sample_count"]
                   or sum(bool(row.observed_event) for row in arm_rows) != metrics[arm]["event_count"]
                   for arm in ("champion", "challenger"))):
            raise ModelRiskPolicyError("SUPERVISED_LABELS_DRIFTED", "当前标签事件分布与冻结评估不一致", 409)
        binding = {"evidence_level": "supervised", "evaluation_id": evaluation.id,
                   "evidence_hash": evaluation.evidence_hash, "policy_id": policy.id,
                   "policy_config_hash": policy.config_hash, "policy_assets_hash": policy.assets_hash,
                   "label_definition_id": definition.id, "label_definition_version": definition.version,
                   "label_definition_hash": definition.config_hash, "label_count": len(labels),
                   "model_key": release.template_key, "model_version": release.model_version}
        if tenant_monitoring is not None:
            binding.update({
                "tenant_monitoring_run_id": tenant_monitoring.id,
                "tenant_monitoring_evidence_hash": tenant_monitoring.evidence_hash,
                "tenant_monitoring_run_key": tenant_monitoring.run_key,
                "tenant_monitoring_observed_from": tenant_monitoring.observed_from.isoformat(),
                "tenant_monitoring_observed_to": tenant_monitoring.observed_to.isoformat(),
                "tenant_monitoring_gate": monitoring_gate,
            })
        if expected is not None:
            comparable = binding
            # Records signed before tenant-monitoring-gate-v1 did not persist the
            # derived gate. They remain readable, while the current gate is still
            # recalculated and must be accepted above.
            if "tenant_monitoring_gate" not in expected:
                comparable = {key: value for key, value in binding.items() if key != "tenant_monitoring_gate"}
            if comparable != expected:
                raise ModelRiskPolicyError("SUPERVISED_EVIDENCE_DRIFTED", "监督评估绑定快照已变化，请重新发起再接受", 409)
        return binding

    @staticmethod
    def _supervised_evaluation_snapshot(record: TenantSupervisedEvaluationRecord) -> dict:
        return {"id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
                "status": record.status, "evidence_level": record.evidence_level,
                "evidence_hash": record.evidence_hash, "label_definition_id": record.label_definition_id,
                "label_definition_version": record.label_definition_version, "label_definition_hash": record.label_definition_hash,
                "tenant_monitoring_run_id": record.tenant_monitoring_run_id,
                "tenant_monitoring_evidence_hash": record.tenant_monitoring_evidence_hash,
                "label_watermark": deepcopy(record.label_watermark_json), "coverage": deepcopy(record.coverage_json),
                "metrics": deepcopy(record.metrics_json), "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None}

    @staticmethod
    def _tenant_monitoring_evidence_hash(run: TenantMonitoringRunRecord) -> str:
        from backend.tenant_outcome_repository import TenantOutcomeRepository
        return TenantOutcomeRepository.monitoring_run_evidence_hash(run)

    def _monitoring_binding(self, release: ModelReleaseRecord, payload: dict) -> dict:
        run_id = payload.get("monitoring_run_id")
        if not run_id:
            # Keep legacy manually captured evidence readable, but mark it clearly as non-supervised.
            return {"status": "legacy_manual", "evidence_level": "non_supervised", "monitoring_run_id": None, "evidence_hash": None}
        run = self.session.get(ModelMonitoringRunRecord, run_id)
        if not run:
            raise ModelRiskPolicyError("MONITORING_RUN_NOT_FOUND", "绑定的模型监控运行不存在", 404)
        if run.status != "completed":
            raise ModelRiskPolicyError("MONITORING_RUN_NOT_COMPLETED", "只有已完成的模型监控运行可以绑定再接受证据", 409)
        if run.template_key != release.template_key or run.model_version != release.model_version:
            raise ModelRiskPolicyError("MONITORING_RUN_MODEL_MISMATCH", "监控运行的模型模板或版本与在役发布版本不一致", 409)
        evidence_hash = self._monitoring_evidence_hash(run)
        if payload.get("monitoring_evidence_hash") != evidence_hash:
            raise ModelRiskPolicyError("MONITORING_EVIDENCE_HASH_MISMATCH", "监控运行证据哈希不匹配，请重新读取运行结果后提交", 409)
        monitoring = deepcopy(run.monitoring_json or {})
        backtesting = monitoring.get("backtesting") or {}
        event_count = int(backtesting.get("event_count") or 0)
        non_event_count = int(backtesting.get("non_event_count") or 0)
        ready = (
            run.evidence_level == "observed_outcome"
            and backtesting.get("status") == "ready"
            and event_count >= 5
            and non_event_count >= 5
        )
        metrics = {item.get("key"): item.get("value") for item in monitoring.get("performance_metrics", []) if item.get("key")}
        metrics["psi"] = (monitoring.get("population_stability") or {}).get("value")
        return {
            "status": "bound", "evidence_level": "supervised" if ready else "non_supervised",
            "monitoring_run_id": run.id, "run_key": run.run_key, "as_of_period": run.as_of_period,
            "dataset_id": run.dataset_id, "run_status": run.status, "source": run.effective_source,
            "evidence_hash": evidence_hash, "label_evidence_id": payload.get("label_evidence_id"),
            "label_coverage": {"event_count": event_count, "non_event_count": non_event_count,
                                "sample_count": event_count + non_event_count,
                                "status": "ready" if ready else "insufficient_or_unlabeled"},
            "metrics": metrics,
        }

    @staticmethod
    def _monitoring_evidence_hash(run: ModelMonitoringRunRecord) -> str:
        return monitoring_run_evidence_hash(run)

    @staticmethod
    def _monitoring_run_snapshot(run: ModelMonitoringRunRecord) -> dict:
        return {
            "id": run.id, "run_key": run.run_key, "template_key": run.template_key,
            "model_version": run.model_version, "as_of_period": run.as_of_period,
            "status": run.status, "effective_source": run.effective_source,
            "evidence_level": run.evidence_level, "dataset_id": run.dataset_id,
            "readiness": deepcopy(run.readiness_json or {}), "monitoring": deepcopy(run.monitoring_json or {}),
            "issue_ids": deepcopy(run.issue_ids or []), "evidence_hash": ModelRiskPolicyRepository._monitoring_evidence_hash(run),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    @staticmethod
    def _audit_event_snapshot(row: AuditEventRecord) -> dict:
        return {
            "id": row.id, "event_type": row.event_type, "actor": row.actor,
            "payload": deepcopy(row.payload or {}), "previous_hash": row.previous_hash,
            "event_hash": row.event_hash, "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _change(self, tenant_id: str, change_id: str) -> tuple[ModelChangeRecord, dict]:
        record = self.session.get(ModelChangeRecord, change_id)
        evidence = deepcopy(record.supervised_validation_evidence_json or {}) if record else {}
        if not record or record.entity_type != "model" or evidence.get("tenant_id") != tenant_id:
            raise ModelRiskPolicyError("CHANGE_NOT_FOUND", "当前租户下不存在该监督模型变更单", 404)
        return record, evidence

    def _acceptance_view(self, record: ModelRiskAcceptanceRecord, now: datetime | None = None) -> dict:
        effective_status = record.status
        policy = self._active_policy(record.tenant_id)
        change = self.session.get(ModelChangeRecord, record.model_change_id)
        now = self._as_utc(now or self._now())
        if record.status != "revoked":
            if policy is None or policy.id != record.policy_id:
                effective_status = "policy_stale"
            elif not change or change.supervised_validation_binding_hash != record.evidence_binding_hash:
                effective_status = "evidence_stale"
            elif record.status == "accepted" and record.review_due_at and self._as_utc(record.review_due_at) <= now:
                effective_status = "overdue"
        return {
            "id": record.id, "tenant_id": record.tenant_id, "model_change_id": record.model_change_id,
            "policy_id": record.policy_id, "policy_version": record.policy_version,
            "policy_config_hash": record.policy_config_hash, "evidence_binding_hash": record.evidence_binding_hash,
            "risk_level": record.risk_level, "required_roles": deepcopy(record.required_roles_json),
            "approvals": deepcopy(record.approvals_json or []), "status": record.status,
            "effective_status": effective_status, "rationale": record.rationale,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "accepted_at": record.accepted_at.isoformat() if record.accepted_at else None,
            "review_due_at": record.review_due_at.isoformat() if record.review_due_at else None,
            "revoked_by": record.revoked_by, "revoked_by_name": record.revoked_by_name,
            "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
            "revocation_reason": record.revocation_reason, "row_version": record.row_version,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def _reacceptance_view(self, record: ModelRiskReacceptanceRecord, now: datetime | None = None) -> dict:
        effective_status = record.status
        now = self._as_utc(now or self._now())
        policy = self._active_policy(record.tenant_id)
        release = self.session.get(ModelReleaseRecord, record.model_release_id)
        change = self.session.get(ModelChangeRecord, record.model_change_id)
        if record.status != "revoked":
            if policy is None or policy.id != record.policy_id:
                effective_status = "policy_stale"
            elif not release or not release.is_active or release.config_hash != record.release_config_hash:
                effective_status = "release_stale"
            elif not change or change.supervised_validation_binding_hash != record.source_evidence_binding_hash:
                effective_status = "evidence_stale"
            elif content_hash(record.operational_evidence_json or {}) != record.operational_evidence_hash:
                effective_status = "evidence_stale"
            elif record.monitoring_run_id:
                monitoring = self.session.get(ModelMonitoringRunRecord, record.monitoring_run_id)
                if not monitoring or self._monitoring_evidence_hash(monitoring) != record.monitoring_evidence_hash:
                    effective_status = "evidence_stale"
            if effective_status in {"pending", "accepted"} and (record.operational_evidence_json or {}).get("supervised_binding", {}).get("evaluation_id"):
                try:
                    self._supervised_binding(record.tenant_id, release, {
                        "supervised_evaluation_id": record.operational_evidence_json["supervised_binding"]["evaluation_id"],
                        "supervised_evidence_hash": record.operational_evidence_json["supervised_binding"]["evidence_hash"],
                    }, expected=record.operational_evidence_json["supervised_binding"])
                except ModelRiskPolicyError:
                    effective_status = "evidence_stale"
            if effective_status == "accepted" and record.review_due_at and self._as_utc(record.review_due_at) <= now:
                effective_status = "overdue"
        return {
            "id": record.id, "tenant_id": record.tenant_id, "model_release_id": record.model_release_id,
            "model_change_id": record.model_change_id, "prior_acceptance_id": record.prior_acceptance_id,
            "policy_id": record.policy_id, "policy_version": record.policy_version,
            "policy_config_hash": record.policy_config_hash, "source_evidence_binding_hash": record.source_evidence_binding_hash,
            "release_config_hash": record.release_config_hash, "operational_evidence": deepcopy(record.operational_evidence_json or {}),
            "operational_evidence_hash": record.operational_evidence_hash, "risk_level": record.risk_level,
            "monitoring_run_id": record.monitoring_run_id, "monitoring_evidence_hash": record.monitoring_evidence_hash,
            "label_evidence_id": record.label_evidence_id,
            "required_roles": deepcopy(record.required_roles_json), "approvals": deepcopy(record.approvals_json or []),
            "status": record.status, "effective_status": effective_status, "rationale": record.rationale,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "accepted_at": record.accepted_at.isoformat() if record.accepted_at else None,
            "review_due_at": record.review_due_at.isoformat() if record.review_due_at else None,
            "revoked_by": record.revoked_by, "revoked_by_name": record.revoked_by_name,
            "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
            "revocation_reason": record.revocation_reason, "row_version": record.row_version,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    @staticmethod
    def _policy_view(record: TenantModelRiskPolicyRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "version": record.version,
            "name": record.name, "description": record.description, "levels": deepcopy(record.levels_json),
            "config_hash": record.config_hash, "status": record.status, "is_active": record.is_active,
            "change_reason": record.change_reason, "created_by": record.created_by,
            "created_by_name": record.created_by_name, "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
            "reviewed_by": record.reviewed_by, "reviewed_by_name": record.reviewed_by_name,
            "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
            "review_comment": record.review_comment, "published_at": record.published_at.isoformat() if record.published_at else None,
            "row_version": record.row_version, "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    @staticmethod
    def _validate_levels(levels: list[dict]) -> list[dict]:
        if {item.get("level") for item in levels} != {"low", "medium", "high"} or len(levels) != 3:
            raise ModelRiskPolicyError("POLICY_LEVELS_INVALID", "风险政策必须且只能包含低、中、高三个等级")
        normalized = []
        for item in levels:
            roles = list(dict.fromkeys(item["acceptance_roles"]))
            if not roles or any(role not in ROLE_BINDINGS for role in roles):
                raise ModelRiskPolicyError("POLICY_ROLES_INVALID", "风险接受角色必须来自受支持的治理席位")
            normalized.append({
                "code": item["code"], "level": item["level"], "name": item["name"],
                "basis": list(item["basis"]), "acceptance_roles": roles,
                "review_days": int(item["review_days"]),
                "regulatory_mapping": list(item["regulatory_mapping"]),
                "required_evidence": list(item["required_evidence"]),
            })
        return sorted(normalized, key=lambda item: ("low", "medium", "high").index(item["level"]))

    @staticmethod
    def _level(levels: list[dict], risk_level: str | None) -> dict:
        for item in levels:
            if item["level"] == risk_level:
                return item
        raise ModelRiskPolicyError("RISK_LEVEL_INVALID", "独立验证风险等级不在当前租户政策中")

    def _commit_policy(self, record: TenantModelRiskPolicyRecord, event_type: str, actor: str, reason: str) -> dict:
        payload = {"tenant_id": record.tenant_id, "version": record.version, "status": record.status, "config_hash": record.config_hash, "reason": reason}
        self._commit(record, "tenant_model_risk_policy", event_type, actor, payload)
        return self._policy_view(record)

    def _commit_acceptance(self, record: ModelRiskAcceptanceRecord, event_type: str, actor: str, reason: str) -> dict:
        payload = {"tenant_id": record.tenant_id, "model_change_id": record.model_change_id, "policy_id": record.policy_id, "risk_level": record.risk_level, "status": record.status, "reason": reason}
        self._commit(record, "model_risk_acceptance", event_type, actor, payload)
        return self._acceptance_view(record)

    def _commit_reacceptance(self, record: ModelRiskReacceptanceRecord, event_type: str, actor: str, reason: str) -> dict:
        payload = {"tenant_id": record.tenant_id, "model_release_id": record.model_release_id,
                   "model_change_id": record.model_change_id, "policy_id": record.policy_id,
                   "operational_evidence_hash": record.operational_evidence_hash, "status": record.status, "reason": reason}
        self._commit(record, "model_risk_reacceptance", event_type, actor, payload)
        return self._reacceptance_view(record)

    def _commit(self, record: object, aggregate_type: str, event_type: str, actor: str, payload: dict) -> None:
        try:
            self.session.flush()
            self.audit.append(aggregate_type, record.id, event_type, actor, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ModelRiskPolicyError("CONCURRENT_UPDATE", "模型风险治理记录发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)

    @staticmethod
    def _check_version(current: int, expected: int) -> None:
        if current != expected:
            raise ModelRiskPolicyError("CONCURRENT_UPDATE", f"记录版本已变化，当前版本为 {current}", 409)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
