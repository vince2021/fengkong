from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import AuditEventRecord, AuthorityPolicyActivationRunRecord, AuthorityPolicyEvidenceAnchorRecord, CreditAuthorityPolicyRecord, NotificationRecord
from backend.repository import AuditRepository, ConcurrentUpdateError, NotificationRepository


BUILTIN_POLICY_VERSION = "BUILTIN-2026.07"
DEFAULT_ACTIVATION_SCAN_INTERVAL_MINUTES = 5
ALLOWED_SIGNOFF_ROLES = {"risk_manager", "approver"}
DEFAULT_AUTHORITY_POLICY_CONFIG = {
    "standard_limit": 5_000_000,
    "enhanced_limit": 20_000_000,
    "low_risk_ratings": ["AAA", "AA", "A"],
    "high_risk_ratings": ["C", "D"],
    "restricted_strategies": ["人工复核", "审慎准入", "限制准入"],
    "prohibited_strategies": ["禁入", "不建议准入"],
    "tiers": {
        "standard": {
            "label": "标准级",
            "reason": "建议额度不超过标准授权上限，且评级与准入策略处于低风险范围",
            "slots": [
                {"key": "approver_final", "role": "approver", "label": "有权审批人终审"},
            ],
        },
        "enhanced": {
            "label": "加强级",
            "reason": "建议额度超过标准授权上限，或评级/准入策略需要加强复核",
            "slots": [
                {"key": "risk_concurrence", "role": "risk_manager", "label": "风控经理风险会签"},
                {"key": "approver_final", "role": "approver", "label": "有权审批人终审"},
            ],
        },
        "committee": {
            "label": "委员会级",
            "reason": "建议额度超过加强授权上限，或评级/准入策略触发高风险门槛",
            "slots": [
                {"key": "risk_concurrence", "role": "risk_manager", "label": "风控经理风险会签"},
                {"key": "approver_primary", "role": "approver", "label": "第一有权审批人"},
                {"key": "approver_secondary", "role": "approver", "label": "第二有权审批人"},
            ],
        },
    },
}


def policy_config_hash(config: dict) -> str:
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_authority_policy_config(config: dict) -> dict:
    normalized = deepcopy(config)
    normalized["standard_limit"] = float(normalized["standard_limit"])
    normalized["enhanced_limit"] = float(normalized["enhanced_limit"])
    for key in ["low_risk_ratings", "high_risk_ratings", "restricted_strategies", "prohibited_strategies"]:
        normalized[key] = list(dict.fromkeys(str(item).strip() for item in normalized.get(key, []) if str(item).strip()))
    for tier_key in ["standard", "enhanced", "committee"]:
        tier = normalized["tiers"][tier_key]
        tier["label"] = str(tier["label"]).strip()
        tier["reason"] = str(tier["reason"]).strip()
        tier["slots"] = [
            {
                "key": str(slot["key"]).strip(),
                "role": str(slot["role"]).strip(),
                "label": str(slot["label"]).strip(),
            }
            for slot in tier["slots"]
        ]
    validate_authority_policy_config(normalized)
    return normalized


def validate_authority_policy_config(config: dict) -> None:
    required = {
        "standard_limit",
        "enhanced_limit",
        "low_risk_ratings",
        "high_risk_ratings",
        "restricted_strategies",
        "prohibited_strategies",
        "tiers",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"授权策略缺少配置项：{', '.join(missing)}")
    if config["standard_limit"] <= 0:
        raise ValueError("标准授权上限必须大于 0")
    if config["enhanced_limit"] <= config["standard_limit"]:
        raise ValueError("加强授权上限必须大于标准授权上限")
    if not config["low_risk_ratings"] or not config["high_risk_ratings"]:
        raise ValueError("低风险和高风险评级集合均不能为空")
    if set(config["low_risk_ratings"]).intersection(config["high_risk_ratings"]):
        raise ValueError("同一评级不能同时属于低风险与高风险集合")
    if set(config["restricted_strategies"]).intersection(config["prohibited_strategies"]):
        raise ValueError("同一准入策略不能同时属于加强复核与禁止准入集合")
    tiers = config.get("tiers")
    if not isinstance(tiers, dict) or set(tiers) != {"standard", "enhanced", "committee"}:
        raise ValueError("授权策略必须完整配置 standard、enhanced、committee 三个层级")
    for tier_key, tier in tiers.items():
        slots = tier.get("slots", [])
        if not tier.get("label") or not tier.get("reason") or not 1 <= len(slots) <= 6:
            raise ValueError(f"{tier_key} 层级必须配置名称、触发说明和 1—6 个会签席位")
        keys = [slot.get("key") for slot in slots]
        if len(keys) != len(set(keys)) or any(not key for key in keys):
            raise ValueError(f"{tier_key} 层级的会签席位键必须非空且唯一")
        if any(slot.get("role") not in ALLOWED_SIGNOFF_ROLES for slot in slots):
            raise ValueError(f"{tier_key} 层级只能使用风控经理或授信审批人席位")
        if not any(slot.get("role") == "approver" for slot in slots):
            raise ValueError(f"{tier_key} 层级至少需要一名授信审批人")
    if not any(slot["role"] == "risk_manager" for slot in tiers["enhanced"]["slots"]):
        raise ValueError("加强级至少需要一个风控经理会签席位")
    if sum(slot["role"] == "approver" for slot in tiers["committee"]["slots"]) < 2:
        raise ValueError("委员会级至少需要两名独立授信审批人")


def builtin_policy_snapshot() -> dict:
    config = deepcopy(DEFAULT_AUTHORITY_POLICY_CONFIG)
    return {
        "id": None,
        "policy_version": BUILTIN_POLICY_VERSION,
        "config_hash": policy_config_hash(config),
        "config": config,
        "source": "builtin",
    }


class AuthorityPolicyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def active_snapshot(self) -> dict:
        record = self.session.scalars(
            select(CreditAuthorityPolicyRecord)
            .where(CreditAuthorityPolicyRecord.is_active.is_(True))
            .order_by(CreditAuthorityPolicyRecord.published_at.desc())
        ).first()
        if not record:
            return builtin_policy_snapshot()
        self._assert_integrity(record)
        return {
            "id": record.id,
            "policy_version": record.policy_version,
            "config_hash": record.config_hash,
            "config": deepcopy(record.config_json),
            "source": "published",
        }

    def list(self) -> list[dict]:
        records = self.session.scalars(
            select(CreditAuthorityPolicyRecord)
            .order_by(CreditAuthorityPolicyRecord.created_at.desc(), CreditAuthorityPolicyRecord.id.desc())
        ).all()
        return [_policy_to_dict(record) for record in records]

    def get(self, policy_id: str) -> dict:
        record = self.session.get(CreditAuthorityPolicyRecord, policy_id)
        if not record:
            raise LookupError("授权策略不存在")
        return _policy_to_dict(record)

    def evidence_package(
        self,
        policy_id: str,
        generated_at: datetime | None = None,
    ) -> dict:
        record = self.session.get(CreditAuthorityPolicyRecord, policy_id)
        if not record:
            raise LookupError("授权策略不存在")
        runs = self.session.scalars(
            select(AuthorityPolicyActivationRunRecord)
            .where(AuthorityPolicyActivationRunRecord.scheduled_policy_id == record.id)
            .order_by(
                AuthorityPolicyActivationRunRecord.started_at,
                AuthorityPolicyActivationRunRecord.id,
            )
        ).all()
        lifecycle_audit = _audit_chain_evidence(self.session, "authority_policy", record.id)
        activation_audits = {
            run.id: _audit_chain_evidence(
                self.session,
                "authority_policy_activation_run",
                run.id,
            )
            for run in runs
        }
        notifications_by_run = {
            run.id: _activation_notification_evidence(self.session, run.id)
            for run in runs
        }
        lifecycle_complete = _policy_lifecycle_complete(record, lifecycle_audit)
        activation_audits_valid = all(
            activation_audits[run.id]["valid"]
            and _activation_audit_complete(run, activation_audits[run.id])
            for run in runs
        )
        policy = _policy_to_dict(record)
        config_valid = policy_config_hash(record.config_json) == record.config_hash
        impact_valid = bool(
            record.impact_json
            and record.impact_hash
            and policy_config_hash(record.impact_json) == record.impact_hash
            and record.impact_json.get("candidate_policy_version") == record.policy_version
            and record.impact_json.get("candidate_config_hash") == record.config_hash
            and record.impact_json.get("base_policy_version") == record.base_policy_version
        )
        review_applicable = record.reviewed_by is not None or record.status in {
            "scheduled",
            "published",
            "rejected",
            "cancelled",
        }
        review_separated = (
            record.reviewed_by is not None
            and record.created_by != record.reviewed_by
            if review_applicable
            else True
        )
        activation_consistent = all(
            run.scheduled_policy_version == record.policy_version
            and run.status in {"blocked", "activated"}
            and (
                (
                    run.active_policy_before == record.base_policy_version
                    and run.active_policy_after == record.policy_version
                )
                if run.status == "activated"
                else (
                    run.active_policy_after == run.active_policy_before
                    and bool(run.error_message)
                )
            )
            for run in runs
        )
        incident_roots = [
            run for run in runs
            if run.status == "blocked" and run.incident_status != "not_applicable"
        ]
        required_alert_roles = {"approver", "model_admin", "risk_manager"}
        alerts_complete = all(
            (
                required_alert_roles.issubset({
                    item["recipient_role"] for item in notifications_by_run[run.id]
                })
                and all(
                    (item["status"] == "resolved") == (run.incident_status == "resolved")
                    for item in notifications_by_run[run.id]
                )
            )
            for run in incident_roots
        )
        unresolved_count = sum(
            run.incident_status in {"open", "acknowledged"} for run in incident_roots
        )
        checks = [
            _evidence_check("config_hash", "策略配置指纹", config_valid, record.config_hash),
            _evidence_check("impact_hash", "组合影响评估指纹", impact_valid, record.impact_hash or "缺失"),
            _evidence_check(
                "four_eye_review",
                "创建与审核身份分离",
                review_separated,
                "流程尚未进入审核环节" if not review_applicable else f"{record.created_by} → {record.reviewed_by or '缺失'}",
                applicable=review_applicable,
            ),
            _evidence_check(
                "lifecycle_audit_chain",
                "策略生命周期审计链",
                lifecycle_audit["valid"] and lifecycle_complete,
                f"{lifecycle_audit['event_count']} 个事件 · 终值 {lifecycle_audit['terminal_hash'][:12] or '空'}",
            ),
            _evidence_check(
                "activation_audit_chains",
                "激活运行审计链",
                activation_audits_valid,
                f"{len(runs)} 次关联运行",
            ),
            _evidence_check(
                "activation_consistency",
                "激活结果与策略版本一致",
                activation_consistent,
                f"{sum(run.status == 'activated' for run in runs)} 次成功激活",
            ),
            _evidence_check(
                "incident_alerts",
                "阻断异常责任角色告警",
                alerts_complete,
                f"{len(incident_roots)} 个主异常 · {unresolved_count} 个未结",
            ),
        ]
        integrity = {
            "passed": all(item["passed"] for item in checks),
            "checks": checks,
            "unresolved_incident_count": unresolved_count,
        }
        body = {
            "schema_version": "authority-policy-evidence-v1",
            "policy": policy,
            "activation_runs": [_activation_run_to_dict(run) for run in runs],
            "notifications_by_run": notifications_by_run,
            "audit": {
                "policy_lifecycle": lifecycle_audit,
                "activation_runs": activation_audits,
            },
            "integrity": integrity,
        }
        return {
            **body,
            "generated_at": _as_utc(generated_at or datetime.now(timezone.utc)).isoformat(),
            "package_hash": policy_config_hash(body),
            "package_hash_algorithm": "SHA-256",
        }

    def compare_evidence_packages(
        self,
        base_policy_id: str,
        candidate_policy_id: str,
        generated_at: datetime | None = None,
    ) -> dict:
        if base_policy_id == candidate_policy_id:
            raise ValueError("请选择两个不同的授权策略版本进行比较")
        from backend.authority_policy_impact import build_authority_policy_config_diff

        comparison_time = _as_utc(generated_at or datetime.now(timezone.utc))
        base = self.evidence_package(base_policy_id, generated_at=comparison_time)
        candidate = self.evidence_package(candidate_policy_id, generated_at=comparison_time)
        base_checks = {item["key"]: item for item in base["integrity"]["checks"]}
        candidate_checks = {item["key"]: item for item in candidate["integrity"]["checks"]}
        body = {
            "schema_version": "authority-policy-evidence-comparison-v1",
            "base": _evidence_comparison_summary(base),
            "candidate": _evidence_comparison_summary(candidate),
            "config_diff": build_authority_policy_config_diff(
                base["policy"]["config"],
                candidate["policy"]["config"],
            ),
            "evidence_delta": {
                "lifecycle_event_count": (
                    candidate["audit"]["policy_lifecycle"]["event_count"]
                    - base["audit"]["policy_lifecycle"]["event_count"]
                ),
                "activation_run_count": (
                    len(candidate["activation_runs"]) - len(base["activation_runs"])
                ),
                "unresolved_incident_count": (
                    candidate["integrity"]["unresolved_incident_count"]
                    - base["integrity"]["unresolved_incident_count"]
                ),
                "newly_failed_checks": [
                    key
                    for key, item in candidate_checks.items()
                    if item["applicable"]
                    and not item["passed"]
                    and (key not in base_checks or base_checks[key]["passed"])
                ],
                "resolved_checks": [
                    key
                    for key, item in candidate_checks.items()
                    if item["applicable"]
                    and item["passed"]
                    and key in base_checks
                    and base_checks[key]["applicable"]
                    and not base_checks[key]["passed"]
                ],
            },
        }
        return {
            **body,
            "generated_at": comparison_time.isoformat(),
            "comparison_hash": policy_config_hash(body),
            "comparison_hash_algorithm": "SHA-256",
        }

    def list_evidence_anchors(self, policy_id: str, limit: int = 100) -> list[dict]:
        if not self.session.get(CreditAuthorityPolicyRecord, policy_id):
            raise LookupError("授权策略不存在")
        records = self.session.scalars(
            select(AuthorityPolicyEvidenceAnchorRecord)
            .where(AuthorityPolicyEvidenceAnchorRecord.policy_id == policy_id)
            .order_by(
                AuthorityPolicyEvidenceAnchorRecord.issued_at.desc(),
                AuthorityPolicyEvidenceAnchorRecord.id.desc(),
            )
            .limit(limit)
        ).all()
        return [_evidence_anchor_to_dict(self.session, record) for record in records]

    def get_evidence_anchor(self, anchor_id: str) -> dict:
        record = self.session.get(AuthorityPolicyEvidenceAnchorRecord, anchor_id)
        if not record:
            raise LookupError("授权策略证据锚点不存在")
        return _evidence_anchor_to_dict(self.session, record, include_package=True)

    def issue_evidence_anchor(
        self,
        policy_id: str,
        actor_subject: str,
        actor_name: str,
        issued_at: datetime | None = None,
    ) -> dict:
        issue_time = _as_utc(issued_at or datetime.now(timezone.utc))
        package = self.evidence_package(policy_id, generated_at=issue_time)
        existing = self.session.scalars(
            select(AuthorityPolicyEvidenceAnchorRecord).where(
                AuthorityPolicyEvidenceAnchorRecord.policy_id == policy_id,
                AuthorityPolicyEvidenceAnchorRecord.package_hash == package["package_hash"],
            )
        ).first()
        if existing:
            return {**_evidence_anchor_to_dict(self.session, existing, include_package=True), "idempotent": True}
        anchor_id = str(uuid4())
        anchor_body = {
            "id": anchor_id,
            "policy_id": policy_id,
            "policy_version": package["policy"]["policy_version"],
            "schema_version": package["schema_version"],
            "package_hash": package["package_hash"],
            "integrity_passed": package["integrity"]["passed"],
            "issued_by": actor_subject,
            "issued_by_name": actor_name,
            "issued_at": issue_time.isoformat(),
        }
        record = AuthorityPolicyEvidenceAnchorRecord(
            id=anchor_id,
            policy_id=policy_id,
            policy_version=package["policy"]["policy_version"],
            schema_version=package["schema_version"],
            package_json=deepcopy(package),
            package_hash=package["package_hash"],
            anchor_hash=policy_config_hash(anchor_body),
            integrity_passed=package["integrity"]["passed"],
            issued_by=actor_subject,
            issued_by_name=actor_name,
            issued_at=issue_time,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append(
                "authority_policy_evidence_anchor",
                record.id,
                "authority_policy_evidence_anchor_issued",
                actor_name,
                {
                    "policy_id": policy_id,
                    "policy_version": record.policy_version,
                    "package_hash": record.package_hash,
                    "anchor_hash": record.anchor_hash,
                    "integrity_passed": record.integrity_passed,
                },
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.session.scalars(
                select(AuthorityPolicyEvidenceAnchorRecord).where(
                    AuthorityPolicyEvidenceAnchorRecord.policy_id == policy_id,
                    AuthorityPolicyEvidenceAnchorRecord.package_hash == package["package_hash"],
                )
            ).first()
            if existing:
                return {**_evidence_anchor_to_dict(self.session, existing, include_package=True), "idempotent": True}
            raise ConcurrentUpdateError("证据锚点签发发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return {**_evidence_anchor_to_dict(self.session, record, include_package=True), "idempotent": False}

    def revoke_evidence_anchor(
        self,
        anchor_id: str,
        expected_row_version: int,
        reason: str,
        actor_subject: str,
        actor_name: str,
    ) -> dict:
        record = self.session.get(AuthorityPolicyEvidenceAnchorRecord, anchor_id)
        if not record:
            raise LookupError("授权策略证据锚点不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("证据锚点状态已被其他人员更新，请刷新后重试")
        if record.revoked_at is not None:
            raise ValueError("证据锚点已经撤销，不能重复撤销")
        if record.issued_by == actor_subject:
            raise PermissionError("证据锚点签发人与撤销人必须分离")
        revoked_at = datetime.now(timezone.utc)
        record.revoked_by = actor_subject
        record.revoked_by_name = actor_name
        record.revoked_at = revoked_at
        record.revocation_reason = reason
        try:
            self.audit.append(
                "authority_policy_evidence_anchor",
                record.id,
                "authority_policy_evidence_anchor_revoked",
                actor_name,
                {
                    "policy_id": record.policy_id,
                    "policy_version": record.policy_version,
                    "package_hash": record.package_hash,
                    "anchor_hash": record.anchor_hash,
                    "issued_by": record.issued_by,
                    "revoked_by": actor_subject,
                    "reason": reason,
                },
            )
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("证据锚点状态已被其他人员更新，请刷新后重试") from exc
        self.session.refresh(record)
        return _evidence_anchor_to_dict(self.session, record, include_package=True)

    def restore_source_snapshot(self, source_policy_ref: str) -> dict:
        if source_policy_ref == "builtin":
            source = builtin_policy_snapshot()
            return {
                **source,
                "restore_source_policy_id": None,
                "restore_source_policy_version": source["policy_version"],
            }
        record = self.session.get(CreditAuthorityPolicyRecord, source_policy_ref)
        if not record:
            raise LookupError("待恢复的授权策略不存在")
        self._assert_integrity(record)
        if record.status != "published":
            raise ValueError("只有已发布的历史授权策略可以作为恢复来源")
        return {
            "id": record.id,
            "policy_version": record.policy_version,
            "config_hash": record.config_hash,
            "config": deepcopy(record.config_json),
            "source": "published",
            "restore_source_policy_id": record.id,
            "restore_source_policy_version": record.policy_version,
        }

    def create(
        self,
        policy_version: str,
        change_reason: str,
        config: dict,
        impact: dict,
        actor_subject: str,
        actor_name: str,
        restore_source: dict | None = None,
    ) -> dict:
        normalized = normalize_authority_policy_config(config)
        base = self.active_snapshot()
        self._validate_impact(impact, normalized, base["policy_version"])
        if restore_source:
            normalized_hash = policy_config_hash(normalized)
            source_hash = policy_config_hash(normalize_authority_policy_config(restore_source["config"]))
            base_hash = policy_config_hash(normalize_authority_policy_config(base["config"]))
            if source_hash != normalized_hash:
                raise ValueError("恢复草稿配置与历史来源不一致")
            if source_hash == base_hash:
                raise ValueError("所选授权策略配置已经生效，无需创建恢复草稿")
        record = CreditAuthorityPolicyRecord(
            id=str(uuid4()),
            policy_version=policy_version,
            base_policy_version=base["policy_version"],
            config_json=normalized,
            config_hash=policy_config_hash(normalized),
            impact_json=deepcopy(impact),
            impact_hash=policy_config_hash(impact),
            impact_evaluated_at=datetime.now(timezone.utc),
            restore_source_policy_id=restore_source["restore_source_policy_id"] if restore_source else None,
            restore_source_policy_version=restore_source["restore_source_policy_version"] if restore_source else None,
            change_reason=change_reason,
            created_by=actor_subject,
            created_by_name=actor_name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("authority_policy", record.id, "authority_policy_restore_draft_created" if restore_source else "authority_policy_draft_created", actor_name, {
                "policy_version": policy_version,
                "base_policy_version": record.base_policy_version,
                "config_hash": record.config_hash,
                "impact_hash": record.impact_hash,
                "impact_input_snapshot_hash": impact["input_snapshot_hash"],
                "change_reason": change_reason,
                **({
                    "restore_source_policy_id": record.restore_source_policy_id,
                    "restore_source_policy_version": record.restore_source_policy_version,
                } if restore_source else {}),
            })
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("授权策略版本号不能重复") from exc
        self.session.refresh(record)
        return _policy_to_dict(record)

    def update(self, policy_id: str, expected_row_version: int, change_reason: str, config: dict, impact: dict, actor_subject: str, actor_name: str, allow_admin: bool = False) -> dict:
        record = self._get(policy_id, expected_row_version)
        if record.status != "draft":
            raise ValueError("只有草稿状态的授权策略可以编辑")
        if record.created_by != actor_subject and not allow_admin:
            raise PermissionError("只能编辑本人创建的授权策略草稿")
        if record.restore_source_policy_version:
            raise ValueError("恢复草稿已封存历史来源配置，不能编辑；如需调整请新建普通策略草稿")
        normalized = normalize_authority_policy_config(config)
        self._validate_impact(impact, normalized, record.base_policy_version)
        record.change_reason = change_reason
        record.config_json = normalized
        record.config_hash = policy_config_hash(normalized)
        record.impact_json = deepcopy(impact)
        record.impact_hash = policy_config_hash(impact)
        record.impact_evaluated_at = datetime.now(timezone.utc)
        return self._commit(record, "authority_policy_draft_updated", actor_name, {
            "config_hash": record.config_hash,
            "impact_hash": record.impact_hash,
            "impact_input_snapshot_hash": impact["input_snapshot_hash"],
            "change_reason": change_reason,
        })

    def assert_impact_current(self, policy_id: str, current_impact: dict) -> None:
        record = self.session.get(CreditAuthorityPolicyRecord, policy_id)
        if not record:
            raise LookupError("授权策略不存在")
        self._assert_integrity(record)
        self._assert_impact_integrity(record)
        self._validate_impact(current_impact, record.config_json, record.base_policy_version)
        if record.impact_json["input_snapshot_hash"] != current_impact["input_snapshot_hash"]:
            raise ValueError("授权策略影响评估使用的样本或模型快照已变化，请更新草稿并重新评估")
        if record.impact_json.get("config_diff") != current_impact.get("config_diff"):
            raise ValueError("授权策略配置差异审阅包已变化，请更新草稿并重新评估")

    def submit(self, policy_id: str, expected_row_version: int, actor_subject: str, actor_name: str, allow_admin: bool = False) -> dict:
        record = self._get(policy_id, expected_row_version)
        if record.status != "draft":
            raise ValueError("只有草稿状态的授权策略可以提交审核")
        if record.created_by != actor_subject and not allow_admin:
            raise PermissionError("只能提交本人创建的授权策略草稿")
        self._assert_integrity(record)
        self._assert_impact_integrity(record)
        record.status = "pending_review"
        record.submitted_at = datetime.now(timezone.utc)
        return self._commit(record, "authority_policy_submitted", actor_name, {
            "policy_version": record.policy_version,
            "config_hash": record.config_hash,
            "impact_hash": record.impact_hash,
            "impact_input_snapshot_hash": record.impact_json["input_snapshot_hash"],
        })

    def review(
        self,
        policy_id: str,
        expected_row_version: int,
        decision: str,
        comment: str,
        reviewer_subject: str,
        reviewer_name: str,
        effective_at: datetime | None = None,
    ) -> dict:
        record = self._get(policy_id, expected_row_version)
        if record.status != "pending_review":
            raise ValueError("授权策略当前不处于待审核状态")
        if record.created_by == reviewer_subject:
            raise PermissionError("授权策略创建人与审核人必须分离")
        now = datetime.now(timezone.utc)
        if decision == "reject":
            record.reviewed_by = reviewer_subject
            record.reviewed_by_name = reviewer_name
            record.reviewed_at = now
            record.review_comment = comment
            record.status = "rejected"
            return self._commit(record, "authority_policy_rejected", reviewer_name, {
                "policy_version": record.policy_version,
                "comment": comment,
            })

        self._assert_integrity(record)
        self._assert_impact_integrity(record)
        active = self.active_snapshot()
        if active["policy_version"] != record.base_policy_version:
            raise ValueError(f"生效授权策略已变更为 {active['policy_version']}，请基于最新版本重新创建草稿")
        activation_time = _normalize_effective_at(effective_at, now)
        self._assert_no_other_schedule(record.id)
        record.reviewed_by = reviewer_subject
        record.reviewed_by_name = reviewer_name
        record.reviewed_at = now
        record.review_comment = comment
        if activation_time:
            record.status = "scheduled"
            record.effective_at = activation_time
            return self._commit(record, "authority_policy_scheduled", reviewer_name, {
                "policy_version": record.policy_version,
                "base_policy_version": active["policy_version"],
                "effective_at": activation_time.isoformat(),
                "config_hash": record.config_hash,
                "impact_hash": record.impact_hash,
                "impact_input_snapshot_hash": record.impact_json["input_snapshot_hash"],
                "comment": comment,
            })
        return self._activate(record, now, reviewer_subject, reviewer_name, "authority_policy_published")

    def activate_due(
        self,
        actor_subject: str,
        actor_name: str,
        now: datetime | None = None,
        run_key: str | None = None,
        trigger_type: str = "manual",
        retry_of_run_id: str | None = None,
        resolution_note: str | None = None,
    ) -> dict:
        scan_time = _as_utc(now or datetime.now(timezone.utc))
        if trigger_type not in {"manual", "scheduler"}:
            raise ValueError("策略激活触发类型必须为 manual 或 scheduler")
        resolved_run_key = run_key or f"manual:{uuid4()}"
        existing = self.session.scalars(
            select(AuthorityPolicyActivationRunRecord).where(
                AuthorityPolicyActivationRunRecord.run_key == resolved_run_key
            )
        ).first()
        if existing:
            if existing.trigger_type != trigger_type:
                raise ValueError(
                    f"激活运行键 {resolved_run_key} 已用于 {existing.trigger_type} 触发，不能改作 {trigger_type}"
                )
            if existing.retry_of_run_id != retry_of_run_id:
                raise ValueError(f"激活运行键 {resolved_run_key} 已绑定其他处置上下文")
            return self._activation_run_response(existing, idempotent=True)
        active_before = self.active_snapshot()
        record = self.session.scalars(
            select(CreditAuthorityPolicyRecord)
            .where(
                CreditAuthorityPolicyRecord.status == "scheduled",
                CreditAuthorityPolicyRecord.effective_at.is_not(None),
                CreditAuthorityPolicyRecord.effective_at <= scan_time,
            )
            .order_by(CreditAuthorityPolicyRecord.effective_at, CreditAuthorityPolicyRecord.id)
        ).first()
        run = AuthorityPolicyActivationRunRecord(
            id=str(uuid4()),
            run_key=resolved_run_key,
            trigger_type=trigger_type,
            status="running",
            scheduled_policy_id=record.id if record else None,
            scheduled_policy_version=record.policy_version if record else None,
            scheduled_effective_at=record.effective_at if record else None,
            active_policy_before=active_before["policy_version"],
            active_policy_after=active_before["policy_version"],
            incident_status="not_applicable",
            retry_of_run_id=retry_of_run_id,
            actor_subject=actor_subject,
            actor_name=actor_name,
            started_at=scan_time,
        )
        self.session.add(run)
        if not record:
            run.status = "no_due"
            run.completed_at = scan_time
            self.audit.append(
                "authority_policy_activation_run",
                run.id,
                "authority_policy_activation_scan_no_due",
                actor_name,
                {"run_key": run.run_key, "trigger_type": trigger_type, "active_policy": active_before["policy_version"]},
            )
            return self._commit_activation_run(run)
        try:
            self._assert_integrity(record)
            self._assert_impact_integrity(record)
            if active_before["policy_version"] != record.base_policy_version:
                raise ValueError(
                    f"待生效策略基线为 {record.base_policy_version}，当前策略已变更为 {active_before['policy_version']}，已阻止自动切换"
                )
            activated = self._activate(
                record,
                scan_time,
                actor_subject,
                actor_name,
                "authority_policy_scheduled_activated",
                commit=False,
            )
            run.status = "activated"
            run.active_policy_after = record.policy_version
            run.completed_at = scan_time
            self._resolve_blocked_runs_for_policy(
                record.id,
                actor_subject,
                actor_name,
                "retry_activated" if retry_of_run_id else "activated",
                resolution_note or "预约策略已成功激活，异常自动关闭",
                run.id,
                scan_time,
            )
            self.audit.append(
                "authority_policy_activation_run",
                run.id,
                "authority_policy_activation_run_completed",
                actor_name,
                {
                    "run_key": run.run_key,
                    "trigger_type": trigger_type,
                    "scheduled_policy_id": record.id,
                    "scheduled_policy_version": record.policy_version,
                    "active_policy_before": run.active_policy_before,
                    "active_policy_after": run.active_policy_after,
                },
            )
            return self._commit_activation_run(run, activated)
        except (ValueError, ConcurrentUpdateError) as exc:
            self.session.rollback()
            incident_root = self.session.scalars(
                select(AuthorityPolicyActivationRunRecord)
                .where(
                    AuthorityPolicyActivationRunRecord.scheduled_policy_id == record.id,
                    AuthorityPolicyActivationRunRecord.incident_status.in_(["open", "acknowledged"]),
                )
                .order_by(
                    AuthorityPolicyActivationRunRecord.started_at,
                    AuthorityPolicyActivationRunRecord.id,
                )
            ).first()
            blocked = AuthorityPolicyActivationRunRecord(
                id=run.id,
                run_key=resolved_run_key,
                trigger_type=trigger_type,
                status="blocked",
                scheduled_policy_id=record.id,
                scheduled_policy_version=record.policy_version,
                scheduled_effective_at=record.effective_at,
                active_policy_before=active_before["policy_version"],
                active_policy_after=active_before["policy_version"],
                error_message=str(exc)[:2000],
                incident_status="not_applicable" if incident_root else "open",
                retry_of_run_id=retry_of_run_id or (incident_root.id if incident_root else None),
                actor_subject=actor_subject,
                actor_name=actor_name,
                started_at=scan_time,
                completed_at=scan_time,
            )
            self.session.add(blocked)
            if not incident_root:
                self._create_activation_blocked_notifications(blocked)
            self.audit.append(
                "authority_policy_activation_run",
                blocked.id,
                "authority_policy_activation_run_blocked",
                actor_name,
                {
                    "run_key": blocked.run_key,
                    "trigger_type": trigger_type,
                    "scheduled_policy_id": blocked.scheduled_policy_id,
                    "scheduled_policy_version": blocked.scheduled_policy_version,
                    "error": blocked.error_message,
                    "incident_root_run_id": incident_root.id if incident_root else blocked.id,
                },
            )
            return self._commit_activation_run(blocked)

    def activation_status(
        self,
        limit: int = 12,
        now: datetime | None = None,
        scan_interval_minutes: int = DEFAULT_ACTIVATION_SCAN_INTERVAL_MINUTES,
    ) -> dict:
        checked_at = _as_utc(now or datetime.now(timezone.utc))
        scheduled = self.session.scalars(
            select(CreditAuthorityPolicyRecord)
            .where(CreditAuthorityPolicyRecord.status == "scheduled")
            .order_by(CreditAuthorityPolicyRecord.effective_at, CreditAuthorityPolicyRecord.id)
        ).first()
        runs = self.session.scalars(
            select(AuthorityPolicyActivationRunRecord)
            .order_by(
                AuthorityPolicyActivationRunRecord.started_at.desc(),
                AuthorityPolicyActivationRunRecord.id.desc(),
            )
            .limit(limit)
        ).all()
        latest_scheduler_run = self.session.scalars(
            select(AuthorityPolicyActivationRunRecord)
            .where(AuthorityPolicyActivationRunRecord.trigger_type == "scheduler")
            .order_by(
                AuthorityPolicyActivationRunRecord.started_at.desc(),
                AuthorityPolicyActivationRunRecord.id.desc(),
            )
        ).first()
        unresolved = self.session.scalars(
            select(AuthorityPolicyActivationRunRecord)
            .where(AuthorityPolicyActivationRunRecord.incident_status.in_(["open", "acknowledged"]))
            .order_by(
                AuthorityPolicyActivationRunRecord.started_at,
                AuthorityPolicyActivationRunRecord.id,
            )
            .limit(50)
        ).all()
        unresolved_count = self.session.scalar(
            select(func.count()).select_from(AuthorityPolicyActivationRunRecord).where(
                AuthorityPolicyActivationRunRecord.incident_status.in_(["open", "acknowledged"])
            )
        ) or 0
        return {
            "scheduled_policy": _policy_to_dict(scheduled) if scheduled else None,
            "scheduler_health": _activation_scheduler_health(
                scheduled,
                latest_scheduler_run,
                unresolved_count,
                checked_at,
                scan_interval_minutes,
            ),
            "unresolved_incident_count": unresolved_count,
            "unresolved_incidents": [_activation_run_to_dict(run) for run in unresolved],
            "recent_runs": [_activation_run_to_dict(run) for run in runs],
        }

    def acknowledge_activation_incident(
        self,
        run_id: str,
        expected_row_version: int,
        note: str,
        actor_subject: str,
        actor_name: str,
    ) -> dict:
        run = self._get_activation_run(run_id, expected_row_version)
        if run.status != "blocked":
            raise ValueError("只有切换阻断运行可以进行异常确认")
        if run.incident_status == "resolved":
            raise ValueError("该策略激活异常已经关闭")
        if run.incident_status != "open":
            raise ValueError("该策略激活异常已经确认，请勿重复提交")
        run.incident_status = "acknowledged"
        run.acknowledged_by = actor_subject
        run.acknowledged_by_name = actor_name
        run.acknowledged_at = datetime.now(timezone.utc)
        run.acknowledgement_note = note
        self.audit.append(
            "authority_policy_activation_run",
            run.id,
            "authority_policy_activation_incident_acknowledged",
            actor_name,
            {
                "run_key": run.run_key,
                "scheduled_policy_id": run.scheduled_policy_id,
                "scheduled_policy_version": run.scheduled_policy_version,
                "note": note,
            },
        )
        return self._commit_activation_incident(run)

    def retry_activation_incident(
        self,
        run_id: str,
        expected_row_version: int,
        note: str,
        actor_subject: str,
        actor_name: str,
        run_key: str | None = None,
    ) -> dict:
        resolved_run_key = run_key or f"manual-retry:{run_id}:{uuid4()}"
        existing = self.session.scalars(
            select(AuthorityPolicyActivationRunRecord).where(
                AuthorityPolicyActivationRunRecord.run_key == resolved_run_key
            )
        ).first()
        if existing:
            if existing.retry_of_run_id != run_id or existing.trigger_type != "manual":
                raise ValueError(f"激活运行键 {resolved_run_key} 已绑定其他处置上下文")
            return self._activation_run_response(existing, idempotent=True)
        source = self._get_activation_run(run_id, expected_row_version)
        if source.status != "blocked":
            raise ValueError("只有切换阻断运行可以重试")
        if source.incident_status == "open":
            raise ValueError("请先确认策略激活异常，再执行重试")
        if source.incident_status == "resolved":
            raise ValueError("该策略激活异常已经关闭")
        if source.incident_status != "acknowledged":
            raise ValueError("策略激活异常状态不允许重试")
        scheduled = self.session.get(CreditAuthorityPolicyRecord, source.scheduled_policy_id)
        if not scheduled or scheduled.status != "scheduled":
            raise ValueError("原待生效策略已不在排期中，不能执行重试")
        return self.activate_due(
            actor_subject,
            actor_name,
            run_key=resolved_run_key,
            trigger_type="manual",
            retry_of_run_id=source.id,
            resolution_note=note,
        )

    def _create_activation_blocked_notifications(self, run: AuthorityPolicyActivationRunRecord) -> None:
        notifications = NotificationRepository(self.session)
        for role in ("approver", "model_admin", "risk_manager"):
            notifications.create_if_absent(
                {
                    "case_id": None,
                    "counterparty_id": None,
                    "recipient_role": role,
                    "recipient_subject": None,
                    "category": "authority_policy",
                    "level": "policy_blocked",
                    "severity": "critical",
                    "title": "授权策略到期切换被阻断",
                    "message": f"{run.scheduled_policy_version} 未能按预约时间生效：{run.error_message}",
                    "action_json": {"page": "approvals"},
                    "dedup_key": f"authority-policy-activation:{run.id}:{role}:blocked",
                }
            )

    def _commit_activation_run(
        self,
        run: AuthorityPolicyActivationRunRecord,
        activated_policy: dict | None = None,
    ) -> dict:
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            existing = self.session.scalars(
                select(AuthorityPolicyActivationRunRecord).where(
                    AuthorityPolicyActivationRunRecord.run_key == run.run_key
                )
            ).first()
            if existing:
                return self._activation_run_response(existing, idempotent=True)
            raise ConcurrentUpdateError("授权策略激活运行发生并发冲突，请刷新后重试") from exc
        self.session.refresh(run)
        return self._activation_run_response(run, activated_policy, idempotent=False)

    def _activation_run_response(
        self,
        run: AuthorityPolicyActivationRunRecord,
        activated_policy: dict | None = None,
        idempotent: bool = False,
    ) -> dict:
        if activated_policy is None and run.status == "activated" and run.scheduled_policy_id:
            activated_record = self.session.get(CreditAuthorityPolicyRecord, run.scheduled_policy_id)
            activated_policy = _policy_to_dict(activated_record) if activated_record else None
        return {
            "run": _activation_run_to_dict(run),
            "run_at": _as_utc(run.started_at).isoformat(),
            "due_count": int(run.scheduled_policy_id is not None),
            "activated_count": int(run.status == "activated"),
            "activated_policy": activated_policy,
            "idempotent": idempotent,
        }

    def cancel_schedule(
        self,
        policy_id: str,
        expected_row_version: int,
        reason: str,
        actor_subject: str,
        actor_name: str,
    ) -> dict:
        record = self._get(policy_id, expected_row_version)
        if record.status != "scheduled":
            raise ValueError("只有待生效的授权策略可以取消排期")
        now = datetime.now(timezone.utc)
        if record.effective_at and _as_utc(record.effective_at) <= now:
            incidents = self.session.scalars(
                select(AuthorityPolicyActivationRunRecord).where(
                    AuthorityPolicyActivationRunRecord.scheduled_policy_id == record.id,
                    AuthorityPolicyActivationRunRecord.incident_status.in_(["open", "acknowledged"]),
                )
            ).all()
            if not incidents:
                raise ValueError("授权策略已到预约生效时间，不能取消排期；请先执行到期切换")
            if any(item.incident_status == "open" for item in incidents):
                raise ValueError("策略切换异常尚未确认，请先完成异常确认再取消排期")
        record.status = "cancelled"
        record.schedule_cancelled_at = now
        record.schedule_cancelled_by = actor_subject
        record.schedule_cancelled_by_name = actor_name
        record.schedule_cancel_reason = reason
        self._resolve_blocked_runs_for_policy(
            record.id,
            actor_subject,
            actor_name,
            "schedule_cancelled",
            reason,
            None,
            now,
        )
        return self._commit(record, "authority_policy_schedule_cancelled", actor_name, {
            "policy_version": record.policy_version,
            "effective_at": _as_utc(record.effective_at).isoformat() if record.effective_at else None,
            "reason": reason,
        })

    def _resolve_blocked_runs_for_policy(
        self,
        policy_id: str,
        actor_subject: str,
        actor_name: str,
        resolution_type: str,
        note: str,
        resolved_by_run_id: str | None,
        resolved_at: datetime,
    ) -> None:
        incidents = self.session.scalars(
            select(AuthorityPolicyActivationRunRecord).where(
                AuthorityPolicyActivationRunRecord.scheduled_policy_id == policy_id,
                AuthorityPolicyActivationRunRecord.incident_status.in_(["open", "acknowledged"]),
            )
        ).all()
        for incident in incidents:
            incident.incident_status = "resolved"
            incident.resolved_by = actor_subject
            incident.resolved_by_name = actor_name
            incident.resolved_at = resolved_at
            incident.resolution_type = resolution_type
            incident.resolution_note = note
            incident.resolved_by_run_id = resolved_by_run_id
            self.audit.append(
                "authority_policy_activation_run",
                incident.id,
                "authority_policy_activation_incident_resolved",
                actor_name,
                {
                    "scheduled_policy_id": policy_id,
                    "scheduled_policy_version": incident.scheduled_policy_version,
                    "resolution_type": resolution_type,
                    "resolution_note": note,
                    "resolved_by_run_id": resolved_by_run_id,
                },
            )
            self._resolve_activation_notifications(incident, actor_name, resolved_at)

    def _resolve_activation_notifications(
        self,
        incident: AuthorityPolicyActivationRunRecord,
        actor_name: str,
        resolved_at: datetime,
    ) -> None:
        notifications = self.session.scalars(
            select(NotificationRecord).where(
                NotificationRecord.dedup_key.like(
                    f"authority-policy-activation:{incident.id}:%:blocked"
                ),
                NotificationRecord.status != "resolved",
            )
        ).all()
        for notification in notifications:
            notification.status = "resolved"
            notification.read_at = notification.read_at or resolved_at
            self.audit.append(
                "notification",
                notification.id,
                "authority_policy_notification_auto_resolved",
                actor_name,
                {
                    "activation_run_id": incident.id,
                    "scheduled_policy_id": incident.scheduled_policy_id,
                    "scheduled_policy_version": incident.scheduled_policy_version,
                },
            )

    def _get_activation_run(
        self,
        run_id: str,
        expected_row_version: int,
    ) -> AuthorityPolicyActivationRunRecord:
        run = self.session.get(AuthorityPolicyActivationRunRecord, run_id)
        if not run:
            raise LookupError("策略激活运行不存在")
        if run.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"策略激活异常已被更新，当前版本为 {run.row_version}")
        return run

    def _commit_activation_incident(self, run: AuthorityPolicyActivationRunRecord) -> dict:
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("策略激活异常已被其他用户更新，请刷新后重试") from exc
        self.session.refresh(run)
        return _activation_run_to_dict(run)

    def _assert_no_other_schedule(self, policy_id: str) -> None:
        scheduled = self.session.scalars(
            select(CreditAuthorityPolicyRecord).where(
                CreditAuthorityPolicyRecord.status == "scheduled",
                CreditAuthorityPolicyRecord.id != policy_id,
            )
        ).first()
        if scheduled:
            raise ValueError(
                f"已有待生效授权策略 {scheduled.policy_version}，请先等待生效或取消原排期"
            )

    def _activate(
        self,
        record: CreditAuthorityPolicyRecord,
        activated_at: datetime,
        actor_subject: str,
        actor_name: str,
        event_type: str,
        commit: bool = True,
    ) -> dict:
        active = self.active_snapshot()
        current = self.session.scalars(
            select(CreditAuthorityPolicyRecord).where(CreditAuthorityPolicyRecord.is_active.is_(True))
        ).first()
        if current:
            current.is_active = False
            current.superseded_at = activated_at
            try:
                self.session.flush()
            except (IntegrityError, StaleDataError) as exc:
                if commit:
                    self.session.rollback()
                raise ConcurrentUpdateError("当前生效授权策略已被其他用户更新，请刷新后重试") from exc
        record.status = "published"
        record.is_active = True
        record.effective_at = record.effective_at or activated_at
        record.activated_at = activated_at
        record.published_at = activated_at
        payload = {
            "policy_version": record.policy_version,
            "previous_policy_version": active["policy_version"],
            "config_hash": record.config_hash,
            "impact_hash": record.impact_hash,
            "impact_input_snapshot_hash": record.impact_json["input_snapshot_hash"],
            "effective_at": _as_utc(record.effective_at).isoformat(),
            "activated_at": activated_at.isoformat(),
            "activation_actor_subject": actor_subject,
            "review_comment": record.review_comment,
        }
        if commit:
            return self._commit(record, event_type, actor_name, payload)
        try:
            self.session.flush()
            self.audit.append("authority_policy", record.id, event_type, actor_name, payload)
        except (IntegrityError, StaleDataError) as exc:
            raise ConcurrentUpdateError("当前生效授权策略已被其他用户更新，请刷新后重试") from exc
        return _policy_to_dict(record)

    def _get(self, policy_id: str, expected_row_version: int) -> CreditAuthorityPolicyRecord:
        record = self.session.get(CreditAuthorityPolicyRecord, policy_id)
        if not record:
            raise LookupError("授权策略不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"授权策略版本已变化，当前版本为 {record.row_version}")
        return record

    @staticmethod
    def _assert_integrity(record: CreditAuthorityPolicyRecord) -> None:
        validate_authority_policy_config(record.config_json)
        if policy_config_hash(record.config_json) != record.config_hash:
            raise ValueError(f"授权策略 {record.policy_version} 完整性校验失败，已停止使用")

    @staticmethod
    def _validate_impact(impact: dict, config: dict, base_policy_version: str) -> None:
        if impact.get("candidate_config_hash") != policy_config_hash(config):
            raise ValueError("影响评估与候选授权策略配置不一致，请重新评估")
        if impact.get("base_policy_version") != base_policy_version:
            raise ValueError("影响评估基线已变化，请基于当前生效策略重新评估")
        config_diff = impact.get("config_diff")
        if not isinstance(config_diff, dict) or config_diff.get("version") != "authority-config-diff-v1":
            raise ValueError("影响评估缺少最新策略配置差异审阅包，请重新评估")
        if not impact.get("release_gate", {}).get("passed"):
            summary = impact.get("release_gate", {}).get("summary") or "组合影响评估未通过"
            raise ValueError(f"授权策略影响评估门禁未通过：{summary}")

    @classmethod
    def _assert_impact_integrity(cls, record: CreditAuthorityPolicyRecord) -> None:
        if not record.impact_json or not record.impact_hash:
            raise ValueError("授权策略缺少组合影响评估，不能提交或发布")
        if policy_config_hash(record.impact_json) != record.impact_hash:
            raise ValueError(f"授权策略 {record.policy_version} 影响评估完整性校验失败")
        cls._validate_impact(record.impact_json, record.config_json, record.base_policy_version)

    def _commit(self, record: CreditAuthorityPolicyRecord, event_type: str, actor: str, payload: dict) -> dict:
        try:
            self.session.flush()
            self.audit.append("authority_policy", record.id, event_type, actor, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("授权策略已被其他用户更新，请刷新后重试") from exc
        self.session.refresh(record)
        return _policy_to_dict(record)


def _policy_to_dict(record: CreditAuthorityPolicyRecord) -> dict:
    return {
        "id": record.id,
        "policy_version": record.policy_version,
        "base_policy_version": record.base_policy_version,
        "status": record.status,
        "config": deepcopy(record.config_json),
        "config_hash": record.config_hash,
        "impact": deepcopy(record.impact_json),
        "impact_hash": record.impact_hash,
        "impact_evaluated_at": _as_utc(record.impact_evaluated_at).isoformat() if record.impact_evaluated_at else None,
        "restore_source_policy_id": record.restore_source_policy_id,
        "restore_source_policy_version": record.restore_source_policy_version,
        "change_reason": record.change_reason,
        "created_by": record.created_by,
        "created_by_name": record.created_by_name,
        "submitted_at": _as_utc(record.submitted_at).isoformat() if record.submitted_at else None,
        "reviewed_by": record.reviewed_by,
        "reviewed_by_name": record.reviewed_by_name,
        "reviewed_at": _as_utc(record.reviewed_at).isoformat() if record.reviewed_at else None,
        "review_comment": record.review_comment,
        "effective_at": _as_utc(record.effective_at).isoformat() if record.effective_at else None,
        "activated_at": _as_utc(record.activated_at).isoformat() if record.activated_at else None,
        "published_at": _as_utc(record.published_at).isoformat() if record.published_at else None,
        "superseded_at": _as_utc(record.superseded_at).isoformat() if record.superseded_at else None,
        "schedule_cancelled_at": _as_utc(record.schedule_cancelled_at).isoformat() if record.schedule_cancelled_at else None,
        "schedule_cancelled_by": record.schedule_cancelled_by,
        "schedule_cancelled_by_name": record.schedule_cancelled_by_name,
        "schedule_cancel_reason": record.schedule_cancel_reason,
        "is_active": record.is_active,
        "row_version": record.row_version,
        "created_at": _as_utc(record.created_at).isoformat() if record.created_at else None,
        "updated_at": _as_utc(record.updated_at).isoformat() if record.updated_at else None,
    }


def _activation_run_to_dict(record: AuthorityPolicyActivationRunRecord) -> dict:
    return {
        "id": record.id,
        "run_key": record.run_key,
        "trigger_type": record.trigger_type,
        "status": record.status,
        "scheduled_policy_id": record.scheduled_policy_id,
        "scheduled_policy_version": record.scheduled_policy_version,
        "scheduled_effective_at": _as_utc(record.scheduled_effective_at).isoformat() if record.scheduled_effective_at else None,
        "active_policy_before": record.active_policy_before,
        "active_policy_after": record.active_policy_after,
        "error_message": record.error_message,
        "incident_status": record.incident_status,
        "acknowledged_by": record.acknowledged_by,
        "acknowledged_by_name": record.acknowledged_by_name,
        "acknowledged_at": _as_utc(record.acknowledged_at).isoformat() if record.acknowledged_at else None,
        "acknowledgement_note": record.acknowledgement_note,
        "resolved_by": record.resolved_by,
        "resolved_by_name": record.resolved_by_name,
        "resolved_at": _as_utc(record.resolved_at).isoformat() if record.resolved_at else None,
        "resolution_type": record.resolution_type,
        "resolution_note": record.resolution_note,
        "retry_of_run_id": record.retry_of_run_id,
        "resolved_by_run_id": record.resolved_by_run_id,
        "actor_subject": record.actor_subject,
        "actor_name": record.actor_name,
        "started_at": _as_utc(record.started_at).isoformat(),
        "completed_at": _as_utc(record.completed_at).isoformat() if record.completed_at else None,
        "row_version": record.row_version,
        "created_at": _as_utc(record.created_at).isoformat() if record.created_at else None,
    }


def _audit_chain_evidence(
    session: Session,
    aggregate_type: str,
    aggregate_id: str,
) -> dict:
    records = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.aggregate_type == aggregate_type,
            AuditEventRecord.aggregate_id == aggregate_id,
        )
    ).all()
    by_previous: dict[str, list[AuditEventRecord]] = {}
    for record in records:
        by_previous.setdefault(record.previous_hash, []).append(record)
    ordered: list[AuditEventRecord] = []
    current_hash = ""
    while len(by_previous.get(current_hash, [])) == 1:
        record = by_previous[current_hash][0]
        ordered.append(record)
        current_hash = record.event_hash
    serialized = [_audit_event_evidence(record) for record in ordered]
    hashes_valid = all(item["hash_valid"] for item in serialized)
    complete = len(ordered) == len(records)
    return {
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "valid": bool(records) and complete and hashes_valid,
        "event_count": len(records),
        "terminal_hash": current_hash if complete else "",
        "events": serialized,
    }


def _policy_lifecycle_complete(
    record: CreditAuthorityPolicyRecord,
    audit: dict,
) -> bool:
    creation_events = {
        "authority_policy_draft_created",
        "authority_policy_restore_draft_created",
    }
    transitions = {
        "authority_policy_draft_updated",
        "authority_policy_submitted",
        "authority_policy_rejected",
        "authority_policy_scheduled",
        "authority_policy_schedule_cancelled",
        "authority_policy_published",
        "authority_policy_scheduled_activated",
    }
    lifecycle_events = [
        event["event_type"]
        for event in audit["events"]
        if event["event_type"] in creation_events | transitions
    ]
    if not lifecycle_events or lifecycle_events[0] not in creation_events:
        return False
    state = "draft"
    for event_type in lifecycle_events[1:]:
        if event_type == "authority_policy_draft_updated" and state == "draft":
            continue
        if event_type == "authority_policy_submitted" and state == "draft":
            state = "pending_review"
        elif event_type == "authority_policy_rejected" and state == "pending_review":
            state = "rejected"
        elif event_type == "authority_policy_scheduled" and state == "pending_review":
            state = "scheduled"
        elif event_type == "authority_policy_schedule_cancelled" and state == "scheduled":
            state = "cancelled"
        elif event_type == "authority_policy_published" and state == "pending_review":
            state = "published"
        elif event_type == "authority_policy_scheduled_activated" and state == "scheduled":
            state = "published"
        else:
            return False
    return state == record.status


def _activation_audit_complete(
    run: AuthorityPolicyActivationRunRecord,
    audit: dict,
) -> bool:
    event_types = [event["event_type"] for event in audit["events"]]
    expected_terminal_event = {
        "activated": "authority_policy_activation_run_completed",
        "blocked": "authority_policy_activation_run_blocked",
        "no_due": "authority_policy_activation_scan_no_due",
    }.get(run.status)
    if not expected_terminal_event or expected_terminal_event not in event_types:
        return False
    if run.status != "blocked":
        return True
    if run.incident_status == "acknowledged":
        return "authority_policy_activation_incident_acknowledged" in event_types
    if run.incident_status == "resolved":
        return "authority_policy_activation_incident_resolved" in event_types
    return run.incident_status in {"open", "not_applicable"}


def _audit_event_evidence(record: AuditEventRecord) -> dict:
    expected_hash = policy_config_hash({
        "id": record.id,
        "aggregate_type": record.aggregate_type,
        "aggregate_id": record.aggregate_id,
        "event_type": record.event_type,
        "actor": record.actor,
        "payload": record.payload,
        "previous_hash": record.previous_hash,
    })
    return {
        "id": record.id,
        "event_type": record.event_type,
        "actor": record.actor,
        "payload": deepcopy(record.payload),
        "previous_hash": record.previous_hash,
        "event_hash": record.event_hash,
        "expected_hash": expected_hash,
        "hash_valid": expected_hash == record.event_hash,
        "created_at": _as_utc(record.created_at).isoformat() if record.created_at else None,
    }


def _activation_notification_evidence(
    session: Session,
    activation_run_id: str,
) -> list[dict]:
    records = session.scalars(
        select(NotificationRecord)
        .where(
            NotificationRecord.dedup_key.like(
                f"authority-policy-activation:{activation_run_id}:%:blocked"
            )
        )
        .order_by(NotificationRecord.recipient_role, NotificationRecord.id)
    ).all()
    return [
        {
            "id": record.id,
            "recipient_role": record.recipient_role,
            "status": record.status,
            "severity": record.severity,
            "dedup_key": record.dedup_key,
            "created_at": _as_utc(record.created_at).isoformat() if record.created_at else None,
            "read_at": _as_utc(record.read_at).isoformat() if record.read_at else None,
        }
        for record in records
    ]


def _evidence_comparison_summary(package: dict) -> dict:
    return {
        "policy_id": package["policy"]["id"],
        "policy_version": package["policy"]["policy_version"],
        "status": package["policy"]["status"],
        "config_hash": package["policy"]["config_hash"],
        "package_hash": package["package_hash"],
        "integrity_passed": package["integrity"]["passed"],
        "lifecycle_event_count": package["audit"]["policy_lifecycle"]["event_count"],
        "activation_run_count": len(package["activation_runs"]),
        "unresolved_incident_count": package["integrity"]["unresolved_incident_count"],
    }


def _evidence_anchor_to_dict(
    session: Session,
    record: AuthorityPolicyEvidenceAnchorRecord,
    include_package: bool = False,
) -> dict:
    issued_at = _as_utc(record.issued_at)
    expected_anchor_hash = policy_config_hash({
        "id": record.id,
        "policy_id": record.policy_id,
        "policy_version": record.policy_version,
        "schema_version": record.schema_version,
        "package_hash": record.package_hash,
        "integrity_passed": record.integrity_passed,
        "issued_by": record.issued_by,
        "issued_by_name": record.issued_by_name,
        "issued_at": issued_at.isoformat(),
    })
    package_verification = verify_authority_policy_evidence_package(
        record.package_json,
        record.package_hash,
    )
    package_hash_check = next(
        (
            item
            for item in package_verification["checks"]
            if item["key"] == "package_hash"
        ),
        {"passed": False},
    )
    anchor_hash_valid = expected_anchor_hash == record.anchor_hash
    anchor_audit = _audit_chain_evidence(
        session,
        "authority_policy_evidence_anchor",
        record.id,
    )
    audit_events = anchor_audit["events"]
    issue_event = audit_events[0] if audit_events else None
    expected_audit_payload = {
        "policy_id": record.policy_id,
        "policy_version": record.policy_version,
        "package_hash": record.package_hash,
        "anchor_hash": record.anchor_hash,
        "integrity_passed": record.integrity_passed,
    }
    issue_audit_valid = bool(
        anchor_audit["valid"]
        and issue_event
        and issue_event["event_type"] == "authority_policy_evidence_anchor_issued"
        and issue_event["actor"] == record.issued_by_name
        and issue_event["payload"] == expected_audit_payload
    )
    revocation_values = [
        record.revoked_by,
        record.revoked_by_name,
        record.revoked_at,
        record.revocation_reason,
    ]
    is_revoked = record.revoked_at is not None
    revocation_metadata_valid = (
        all(value is not None for value in revocation_values)
        if is_revoked
        else all(value is None for value in revocation_values)
    )
    if is_revoked and revocation_metadata_valid:
        revocation_event = audit_events[1] if len(audit_events) == 2 else None
        revocation_audit_valid = bool(
            revocation_event
            and revocation_event["event_type"] == "authority_policy_evidence_anchor_revoked"
            and revocation_event["actor"] == record.revoked_by_name
            and revocation_event["payload"] == {
                "policy_id": record.policy_id,
                "policy_version": record.policy_version,
                "package_hash": record.package_hash,
                "anchor_hash": record.anchor_hash,
                "issued_by": record.issued_by,
                "revoked_by": record.revoked_by,
                "reason": record.revocation_reason,
            }
        )
    else:
        revocation_audit_valid = len(audit_events) == 1
    audit_valid = bool(
        issue_audit_valid
        and revocation_metadata_valid
        and revocation_audit_valid
    )
    package_unchanged = bool(package_hash_check["passed"])
    registry_valid = anchor_hash_valid and package_unchanged and audit_valid
    result = {
        "id": record.id,
        "policy_id": record.policy_id,
        "policy_version": record.policy_version,
        "schema_version": record.schema_version,
        "package_hash": record.package_hash,
        "anchor_hash": record.anchor_hash,
        "anchor_hash_valid": anchor_hash_valid,
        "package_unchanged": package_unchanged,
        "audit_valid": audit_valid,
        "registry_valid": registry_valid,
        "status": "revoked" if is_revoked else "active",
        "trust_eligible": registry_valid and not is_revoked,
        "integrity_passed": record.integrity_passed,
        "issued_by": record.issued_by,
        "issued_by_name": record.issued_by_name,
        "issued_at": issued_at.isoformat(),
        "revoked_by": record.revoked_by,
        "revoked_by_name": record.revoked_by_name,
        "revoked_at": _as_utc(record.revoked_at).isoformat() if record.revoked_at else None,
        "revocation_reason": record.revocation_reason,
        "row_version": record.row_version,
        "created_at": _as_utc(record.created_at).isoformat() if record.created_at else None,
    }
    if include_package:
        result["package"] = deepcopy(record.package_json)
        result["package_verification"] = package_verification
        result["audit"] = anchor_audit
    return result


def verify_authority_policy_evidence_package(
    package: dict,
    expected_package_hash: str | None = None,
) -> dict:
    if not isinstance(package, dict):
        return {
            "verified": False,
            "trust_level": "invalid",
            "computed_package_hash": "",
            "expected_package_hash": expected_package_hash,
            "checks": [
                _evidence_check("package_shape", "证据包结构", False, "证据包必须是 JSON 对象"),
            ],
            "note": "证据包结构无效，无法执行离线复验。",
        }
    body = {
        key: deepcopy(value)
        for key, value in package.items()
        if key not in {"generated_at", "package_hash", "package_hash_algorithm"}
    }
    computed_hash = policy_config_hash(body)
    declared_hash = str(package.get("package_hash") or "")
    normalized_expected_hash = expected_package_hash.strip().lower() if isinstance(expected_package_hash, str) else None
    expected_hash_valid = normalized_expected_hash is None or bool(re.fullmatch(r"[0-9a-f]{64}", normalized_expected_hash))
    audit = package.get("audit") if isinstance(package.get("audit"), dict) else {}
    lifecycle_chain = audit.get("policy_lifecycle")
    activation_chains = audit.get("activation_runs")
    activation_runs = package.get("activation_runs")
    activation_run_ids = {
        item["id"]
        for item in activation_runs
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    } if isinstance(activation_runs, list) else set()
    notifications_by_run = (
        package.get("notifications_by_run")
        if isinstance(package.get("notifications_by_run"), dict)
        else None
    )
    policy = package.get("policy") if isinstance(package.get("policy"), dict) else {}
    lifecycle_valid = (
        _verify_serialized_audit_chain(lifecycle_chain)
        and lifecycle_chain.get("aggregate_type") == "authority_policy"
        and lifecycle_chain.get("aggregate_id") == policy.get("id")
    )
    activation_valid = (
        isinstance(activation_chains, dict)
        and set(activation_chains) == activation_run_ids
        and all(
            _verify_serialized_audit_chain(chain)
            and chain.get("aggregate_type") == "authority_policy_activation_run"
            and chain.get("aggregate_id") == run_id
            for run_id, chain in activation_chains.items()
        )
    )
    evidence_links_valid = (
        isinstance(activation_runs, list)
        and len(activation_run_ids) == len(activation_runs)
        and isinstance(notifications_by_run, dict)
        and set(notifications_by_run) == activation_run_ids
    )
    integrity = package.get("integrity") if isinstance(package.get("integrity"), dict) else {}
    config = policy.get("config")
    impact = policy.get("impact")
    config_valid = (
        isinstance(config, dict)
        and bool(policy.get("config_hash"))
        and policy_config_hash(config) == policy.get("config_hash")
    )
    impact_valid = (
        isinstance(impact, dict)
        and bool(policy.get("impact_hash"))
        and policy_config_hash(impact) == policy.get("impact_hash")
        and impact.get("candidate_policy_version") == policy.get("policy_version")
        and impact.get("candidate_config_hash") == policy.get("config_hash")
        and impact.get("base_policy_version") == policy.get("base_policy_version")
    )
    declared_integrity = integrity.get("passed") is True
    checks = [
        _evidence_check(
            "schema_version",
            "证据包协议版本",
            package.get("schema_version") == "authority-policy-evidence-v1",
            str(package.get("schema_version") or "缺失"),
        ),
        _evidence_check(
            "hash_algorithm",
            "封印算法",
            package.get("package_hash_algorithm") == "SHA-256",
            str(package.get("package_hash_algorithm") or "缺失"),
        ),
        _evidence_check(
            "package_hash",
            "证据包内容封印",
            bool(declared_hash) and declared_hash == computed_hash,
            f"声明 {declared_hash or '缺失'} · 复算 {computed_hash}",
        ),
        _evidence_check(
            "trusted_hash_anchor",
            "可信外部哈希锚点",
            expected_hash_valid
            and (
                normalized_expected_hash is None
                or normalized_expected_hash == computed_hash
            ),
            "未提供外部哈希，仅验证包内自封印"
            if normalized_expected_hash is None
            else "外部哈希格式无效，必须为 64 位十六进制 SHA-256"
            if not expected_hash_valid
            else f"期望 {normalized_expected_hash} · 复算 {computed_hash}",
            applicable=normalized_expected_hash is not None,
        ),
        _evidence_check(
            "policy_config_hash",
            "策略配置指纹",
            config_valid,
            str(policy.get("config_hash") or "缺失"),
        ),
        _evidence_check(
            "policy_impact_hash",
            "组合影响评估指纹",
            impact_valid,
            str(policy.get("impact_hash") or "缺失"),
        ),
        _evidence_check(
            "lifecycle_audit_chain",
            "生命周期审计链",
            lifecycle_valid,
            f"{lifecycle_chain.get('event_count', 0) if isinstance(lifecycle_chain, dict) else 0} 个事件",
        ),
        _evidence_check(
            "activation_audit_chains",
            "激活运行审计链",
            activation_valid,
            f"{len(activation_chains) if isinstance(activation_chains, dict) else 0} 条运行链",
        ),
        _evidence_check(
            "evidence_references",
            "运行、审计链与告警引用",
            evidence_links_valid,
            f"{len(activation_run_ids)} 个运行编号",
        ),
        _evidence_check(
            "source_integrity",
            "生成时业务完整性结论",
            declared_integrity,
            "生成时全部业务核验通过" if declared_integrity else "生成时存在业务完整性异常",
        ),
    ]
    verified = all(item["passed"] for item in checks)
    trust_level = (
        "invalid"
        if not verified
        else "externally_anchored"
        if normalized_expected_hash
        else "self_sealed"
    )
    return {
        "verified": verified,
        "trust_level": trust_level,
        "computed_package_hash": computed_hash,
        "expected_package_hash": normalized_expected_hash,
        "checks": checks,
        "note": (
            "外部可信哈希与包内证据链均已复验通过。"
            if verified and normalized_expected_hash
            else "包内自封印与证据链已复验通过；如需确认来源真实性，请同时提供独立保存的可信哈希。"
            if verified
            else "证据包复验失败，不应作为完整审计证据使用。"
        ),
    }


def _verify_serialized_audit_chain(chain: object) -> bool:
    if not isinstance(chain, dict):
        return False
    events = chain.get("events")
    if not isinstance(events, list) or not events:
        return False
    previous_hash = ""
    for event in events:
        if not isinstance(event, dict) or event.get("previous_hash") != previous_hash:
            return False
        expected_hash = policy_config_hash({
            "id": event.get("id"),
            "aggregate_type": chain.get("aggregate_type"),
            "aggregate_id": chain.get("aggregate_id"),
            "event_type": event.get("event_type"),
            "actor": event.get("actor"),
            "payload": event.get("payload"),
            "previous_hash": previous_hash,
        })
        if (
            event.get("event_hash") != expected_hash
            or event.get("expected_hash") != expected_hash
            or event.get("hash_valid") is not True
        ):
            return False
        previous_hash = expected_hash
    return (
        chain.get("valid") is True
        and chain.get("event_count") == len(events)
        and chain.get("terminal_hash") == previous_hash
    )


def _evidence_check(
    key: str,
    label: str,
    passed: bool,
    detail: str,
    applicable: bool = True,
) -> dict:
    return {
        "key": key,
        "label": label,
        "passed": bool(passed),
        "applicable": applicable,
        "detail": detail,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def authority_policy_scheduler_run_key(
    value: datetime | None = None,
    interval_minutes: int = DEFAULT_ACTIVATION_SCAN_INTERVAL_MINUTES,
) -> str:
    if not 1 <= interval_minutes <= 60:
        raise ValueError("策略调度扫描间隔必须为 1—60 分钟")
    current = _as_utc(value or datetime.now(timezone.utc))
    bucket_seconds = interval_minutes * 60
    timestamp = int(current.timestamp())
    bucket = datetime.fromtimestamp(
        timestamp - timestamp % bucket_seconds,
        tz=timezone.utc,
    )
    return f"authority-policy-scheduler:{bucket.strftime('%Y%m%dT%H%MZ')}:{interval_minutes}m"


def _activation_scheduler_health(
    scheduled: CreditAuthorityPolicyRecord | None,
    latest_run: AuthorityPolicyActivationRunRecord | None,
    unresolved_count: int,
    checked_at: datetime,
    interval_minutes: int,
) -> dict:
    if not 1 <= interval_minutes <= 60:
        raise ValueError("策略调度扫描间隔必须为 1—60 分钟")
    latest_at = _as_utc(latest_run.started_at) if latest_run else None
    next_expected = latest_at + timedelta(minutes=interval_minutes) if latest_at else None
    effective_at = _as_utc(scheduled.effective_at) if scheduled and scheduled.effective_at else None
    overdue_seconds = max(0, int((checked_at - effective_at).total_seconds())) if effective_at else 0
    grace = timedelta(minutes=interval_minutes * 2)

    if unresolved_count:
        state = "blocked"
        message = f"{unresolved_count} 个策略激活异常尚未关闭"
    elif effective_at and effective_at <= checked_at:
        state = "overdue"
        message = f"预约策略已超过生效时间 {overdue_seconds // 60} 分钟，尚未完成切换"
    elif scheduled and (latest_at is None or checked_at - latest_at > grace):
        state = "attention"
        message = "存在待生效策略，但尚未检测到近期自动调度心跳"
    elif scheduled:
        state = "healthy"
        message = "自动调度心跳正常，待生效策略仍在预约窗口内"
    else:
        state = "idle"
        message = "当前无待生效策略，调度器处于空闲状态"

    return {
        "state": state,
        "message": message,
        "scan_interval_minutes": interval_minutes,
        "checked_at": checked_at.isoformat(),
        "last_scheduler_run": _activation_run_to_dict(latest_run) if latest_run else None,
        "next_expected_scan_at": next_expected.isoformat() if next_expected else None,
        "overdue_seconds": overdue_seconds,
    }


def _normalize_effective_at(value: datetime | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("预约生效时间必须包含时区")
    normalized = _as_utc(value)
    if normalized < now + timedelta(minutes=5):
        raise ValueError("预约生效时间必须至少晚于当前时间 5 分钟")
    if normalized > now + timedelta(days=365):
        raise ValueError("预约生效时间不能超过当前时间 365 天")
    return normalized
