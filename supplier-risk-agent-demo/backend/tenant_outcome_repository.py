"""Tenant-scoped outcome linkage and delayed supervised evaluation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import math
import random
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import (
    DecisionExecutionRecord,
    ModelChangeRecord,
    NotificationRecord,
    TenantMonitoringDiffCaseRecord,
    TenantMonitoringRunRecord,
    TenantOutcomeLabelDefinitionRecord,
    TenantOutcomeImportBatchRecord,
    TenantOutcomeLabelRecord,
    TenantRolloutPolicyRecord,
    TenantRoutingDecisionRecord,
    TenantSupervisedEvaluationRecord,
    TenantSupervisedUpgradeDecisionRecord,
)
from backend.repository import AuditRepository, NotificationRepository, _materialize_model_runtime_defaults, content_hash
from backend.tenant_rollout_repository import TenantRolloutError
from backend.tenant_rollout_repository import TenantRolloutRepository

if TYPE_CHECKING:
    from backend.security import Principal


class TenantOutcomeRepository:
    MONITORING_DIFF_SLA_RULES = {
        "critical": {"due_soon_hours": 6, "escalation_after_hours": 4},
        "warning": {"due_soon_hours": 24, "escalation_after_hours": 12},
        "info": {"due_soon_hours": 48, "escalation_after_hours": 24},
    }

    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list_monitoring_runs(self, tenant_id: str, policy_id: str) -> list[dict]:
        self._policy(tenant_id, policy_id)
        rows = self.session.scalars(select(TenantMonitoringRunRecord).where(
            TenantMonitoringRunRecord.tenant_id == tenant_id,
            TenantMonitoringRunRecord.policy_id == policy_id,
        ).order_by(TenantMonitoringRunRecord.observed_to.desc(), TenantMonitoringRunRecord.created_at.desc())).all()
        return [
            {**self._monitoring_run_view(row), "monitoring_gate": self.monitoring_gate(tenant_id, policy_id, row.id)}
            for row in rows
        ]

    def monitoring_gate(self, tenant_id: str, policy_id: str, run_id: str) -> dict:
        """Calculate a deterministic publication/runtime gate for a tenant snapshot.

        The gate is intentionally derived from the immutable run payload and the frozen
        rollout thresholds. It is not persisted as a second mutable source of truth.
        ``non_supervised`` remains diagnostic evidence and can never produce ``accepted``.
        """
        policy = self._policy(tenant_id, policy_id)
        run = self._monitoring_run(tenant_id, policy_id, run_id)
        stale_reason = None
        try:
            self._verify_monitoring_run_integrity(run)
        except TenantRolloutError as exc:
            stale_reason = exc.message

        monitoring = deepcopy(run.monitoring_json or {})
        thresholds = deepcopy(policy.thresholds_json or {})
        metrics = self._monitoring_metric_values(monitoring)
        checks = []
        threshold_specs = (
            ("challenger_failure_rate", "max_challenger_failure_rate", "max", "Challenger 失败率"),
            ("latency_increase_ratio", "max_latency_increase_ratio", "max", "延迟增幅"),
            ("score_psi", "max_score_psi", "max", "评分分布 PSI"),
            ("admission_distribution_shift", "max_admission_distribution_shift", "max", "准入分布偏移"),
            ("auc", "min_auc", "min", "AUC"),
            ("ks", "min_ks", "min", "KS"),
        )
        for metric_key, threshold_key, direction, label in threshold_specs:
            if threshold_key not in thresholds or thresholds.get(threshold_key) is None:
                continue
            threshold = self._finite_number(thresholds.get(threshold_key))
            value = self._finite_number(metrics.get(metric_key))
            testable = threshold is not None and value is not None
            passed = None if not testable else value <= threshold if direction == "max" else value >= threshold
            checks.append({
                "key": metric_key, "label": label, "direction": direction,
                "value": value, "threshold": threshold, "testable": testable, "passed": passed,
            })

        coverage = monitoring.get("coverage") or {}
        reasons = []
        if stale_reason:
            status = "evidence_stale"
            reasons.append(stale_reason)
        elif run.governance_status != "published":
            status = "blocked"
            reasons.append(f"监控快照治理状态为 {run.governance_status}，尚未发布")
        elif run.status != "completed":
            status = "blocked"
            reasons.append(f"监控运行状态为 {run.status}，不可作为当前证据")
        elif any(item["testable"] and not item["passed"] for item in checks):
            status = "blocked"
            reasons.append("至少一个冻结阈值未通过")
        else:
            untestable = [item["label"] for item in checks if not item["testable"]]
            coverage_ready = (
                self._finite_number(coverage.get("mature_verified_count")) is not None
                and int(coverage.get("event_count") or 0) >= 5
                and int(coverage.get("non_event_count") or 0) >= 5
            )
            if run.evidence_level != "supervised":
                reasons.append("无足量已核验结果标签，仅可作为非监督稳定性诊断")
            elif not coverage_ready:
                reasons.append("监督快照每侧至少需要 5 个事件和 5 个非事件样本，并提供成熟标签覆盖水位")
            if monitoring.get("degraded_reason"):
                reasons.append(str(monitoring["degraded_reason"]))
            if untestable:
                reasons.append(f"冻结阈值缺少可计算指标：{'、'.join(untestable)}")
            if run.evidence_level == "supervised" and metrics.get("auc") is None:
                reasons.append("监督证据缺少 AUC")
            if run.evidence_level == "supervised" and metrics.get("ks") is None:
                reasons.append("监督证据缺少 KS")
            if run.evidence_level != "supervised" or not coverage_ready or monitoring.get("degraded_reason") or untestable or metrics.get("auc") is None or metrics.get("ks") is None:
                status = "at_risk"
            else:
                status = "accepted"

        payload = {
            "schema_version": "tenant-monitoring-gate-v1",
            "tenant_id": tenant_id, "policy_id": policy_id, "run_id": run.id,
            "run_key": run.run_key, "evidence_hash": run.evidence_hash,
            "governance_status": run.governance_status, "run_status": run.status,
            "evidence_level": run.evidence_level, "thresholds": thresholds,
            "metrics": metrics, "checks": checks, "coverage": coverage,
            "status": status, "reasons": reasons,
        }
        return {**payload, "gate_hash": content_hash(payload)}

    @staticmethod
    def _finite_number(value) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @classmethod
    def _monitoring_metric_values(cls, monitoring: dict) -> dict:
        values = {}
        for source in (monitoring, monitoring.get("metrics") or {}, monitoring.get("online_metrics") or {}):
            if isinstance(source, dict):
                values.update({key: value for key, value in source.items() if key not in values})
        population = monitoring.get("population_stability") or {}
        if "score_psi" not in values:
            values["score_psi"] = monitoring.get("score_psi_champion_vs_challenger")
        if values.get("score_psi") is None and isinstance(population, dict):
            values["score_psi"] = population.get("value")
        if values.get("admission_distribution_shift") is None:
            values["admission_distribution_shift"] = monitoring.get("admission_distribution_shift")
        performance = monitoring.get("performance_metrics") or []
        if isinstance(performance, list):
            for item in performance:
                if isinstance(item, dict) and item.get("key") and values.get(item["key"]) is None:
                    values[item["key"]] = item.get("value")
        return {key: value for key, value in values.items() if key in {
            "challenger_failure_rate", "latency_increase_ratio", "score_psi",
            "admission_distribution_shift", "auc", "ks",
        }}

    def scan_monitoring_gates(self, tenant_id: str | None = None, actor_subject: str = "system:tenant-monitoring-gate", now: datetime | None = None) -> dict:
        """Scan published snapshots, notify responsible roles, and close recovered alerts."""
        statement = select(TenantMonitoringRunRecord).where(
            TenantMonitoringRunRecord.governance_status.in_(("published", "retracted")),
        )
        if tenant_id:
            statement = statement.where(TenantMonitoringRunRecord.tenant_id == tenant_id)
        candidates = self.session.scalars(statement.order_by(
            TenantMonitoringRunRecord.tenant_id,
            TenantMonitoringRunRecord.observed_to.desc(),
            TenantMonitoringRunRecord.created_at.desc(),
        )).all()
        latest = {}
        for run in candidates:
            latest.setdefault((run.tenant_id, run.policy_id, run.model_key, run.model_version), run)
        runs = list(latest.values())
        scan_at = self._as_utc(now or self._now())
        notifications = NotificationRepository(self.session)
        prior_statement = select(NotificationRecord).where(
            NotificationRecord.category == "tenant_monitoring_gate",
            NotificationRecord.status != "resolved",
        )
        if tenant_id:
            prior_statement = prior_statement.where(NotificationRecord.tenant_id == tenant_id)
        prior = self.session.scalars(prior_statement).all()
        created_count = resolved_count = 0
        counts = {"accepted_count": 0, "at_risk_count": 0, "blocked_count": 0, "stale_count": 0}
        current_run_ids = {run.id for run in runs}
        for notice in prior:
            prior_action = notice.action_json or {}
            if prior_action.get("run_id") in current_run_ids:
                continue
            notice.status, notice.read_at = "resolved", scan_at
            resolved_count += 1
            self.audit.append("notification", notice.id, "tenant_monitoring_gate_notification_resolved", actor_subject, {
                "tenant_id": notice.tenant_id, "policy_id": prior_action.get("policy_id"),
                "run_id": prior_action.get("run_id"), "resolution": "superseded_by_newer_snapshot",
            })
        for run in runs:
            gate = self.monitoring_gate(run.tenant_id, run.policy_id, run.id)
            status = gate["status"]
            counts[{"accepted": "accepted_count", "at_risk": "at_risk_count", "blocked": "blocked_count", "evidence_stale": "stale_count"}[status]] += 1
            action = {"page": "model-governance", "policy_id": run.policy_id, "run_id": run.id,
                      "gate_status": status, "evidence_hash": run.evidence_hash, "gate_hash": gate["gate_hash"]}
            for notice in prior:
                prior_action = notice.action_json or {}
                if prior_action.get("run_id") != run.id:
                    continue
                if status == "accepted" or prior_action.get("gate_status") != status or prior_action.get("evidence_hash") != run.evidence_hash:
                    notice.status, notice.read_at = "resolved", scan_at
                    resolved_count += 1
                    self.audit.append("notification", notice.id, "tenant_monitoring_gate_notification_resolved", actor_subject, {
                        "tenant_id": run.tenant_id, "policy_id": run.policy_id, "run_id": run.id, "gate_status": status,
                    })
            if status == "accepted":
                continue
            for role in ("model_admin", "risk_manager"):
                dedup_key = f"tenant-monitoring-gate:{run.tenant_id}:{run.policy_id}:{run.id}:{status}:{run.evidence_hash}:{role}"
                payload = {
                    "case_id": None, "counterparty_id": None, "recipient_role": role, "recipient_subject": None,
                    "category": "tenant_monitoring_gate", "level": status,
                    "severity": "critical" if status in {"blocked", "evidence_stale"} else "warning",
                    "title": {"at_risk": "租户监控快照处于风险状态", "blocked": "租户监控快照门禁未通过", "evidence_stale": "租户监控快照证据已失效"}[status],
                    "message": f"策略 {run.policy_id} 的监控快照 {run.run_key} 当前为 {status}：{'；'.join(gate['reasons']) or '请进入模型治理页复核。'}",
                    "action_json": action, "dedup_key": dedup_key, "status": "unread",
                }
                notice, created = notifications.create_if_absent(run.tenant_id, payload)
                if created:
                    created_count += 1
                    self.audit.append("notification", notice["id"], "tenant_monitoring_gate_notification_created", actor_subject, {
                        "tenant_id": run.tenant_id, "policy_id": run.policy_id, "run_id": run.id, "gate_status": status,
                        "evidence_hash": run.evidence_hash,
                    })
        self.session.commit()
        return {"scanned_count": len(runs), **counts, "notifications_created": created_count,
                "notifications_resolved": resolved_count, "scanned_at": scan_at.isoformat()}

    def generate_monitoring_runs(
        self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal", *, commit: bool = True,
    ) -> dict:
        policy = self._policy(tenant_id, policy_id)
        # Active policies must still resolve their comparison gate. Terminal policies can be
        # retained as historical evidence even after the comparison row is archived; route
        # hashes below remain the tamper-evident boundary for those snapshots.
        if policy.status in {"draft", "pending_review", "scheduled", "active", "paused"}:
            # Import locally because backend.dependencies constructs TenantOutcomeRepository itself.
            from backend.dependencies import demo_repository
            TenantRolloutRepository(self.session, demo_repository)._verify_integrity(policy)
        elif content_hash(policy.config_json) != policy.config_hash or content_hash(policy.arm_snapshot_json) != policy.assets_hash:
            raise TenantRolloutError("ROLLOUT_INTEGRITY_FAILED", "历史灰度策略配置或资产快照哈希不一致", 409)
        as_of = self._as_utc(payload.get("as_of") or self._now()).replace(microsecond=0)
        if as_of > self._now():
            raise TenantRolloutError("TENANT_MONITORING_AS_OF_INVALID", "监控截止时间不能晚于当前时间", 422)
        definition = self._definition(tenant_id, payload["label_definition_id"])
        self._verify_definition_integrity(definition)
        if definition.status not in {"published", "retired"}:
            raise TenantRolloutError("LABEL_DEFINITION_NOT_EVALUABLE", "监控运行只能使用已发布或已退役的冻结口径", 422)
        if policy.champion_model_key not in (definition.applicable_model_keys_json or []) or policy.challenger_model_key not in (definition.applicable_model_keys_json or []):
            raise TenantRolloutError("TENANT_MONITORING_LABEL_MODEL_MISMATCH", "标签口径不适用于当前灰度模型", 409)
        routes = list(self.session.scalars(select(TenantRoutingDecisionRecord).where(
            TenantRoutingDecisionRecord.tenant_id == tenant_id,
            TenantRoutingDecisionRecord.policy_id == policy_id,
            TenantRoutingDecisionRecord.created_at <= as_of,
            TenantRoutingDecisionRecord.status.in_(("completed", "failed")),
        )).all())
        for route in routes:
            if route.policy_config_hash != policy.config_hash or route.policy_assets_hash != policy.assets_hash or content_hash(route.selected_assets_json) != route.selected_assets_hash:
                raise TenantRolloutError("TENANT_MONITORING_ROUTE_DRIFTED", "灰度路由的策略或冻结资产发生变化", 409)
        labels = list(self.session.scalars(select(TenantOutcomeLabelRecord).where(
            TenantOutcomeLabelRecord.tenant_id == tenant_id,
            TenantOutcomeLabelRecord.policy_id == policy_id,
            TenantOutcomeLabelRecord.label_definition_id == definition.id,
            TenantOutcomeLabelRecord.record_status == "active",
            TenantOutcomeLabelRecord.verification_status == "verified",
            TenantOutcomeLabelRecord.observation_end <= as_of,
        )).all())
        for label in labels:
            self._verify_label_integrity(label)
        route_ids = {route.id for route in routes if route.status == "completed"}
        if any(label.routing_decision_id not in route_ids for label in labels):
            raise TenantRolloutError("TENANT_MONITORING_LABEL_ROUTE_MISSING", "成熟标签缺少截止时间内的完整路由证据", 409)
        watermark = {
            "label_count": len(labels), "label_ids": sorted(row.id for row in labels),
            "label_evidence_hashes": sorted(row.evidence_hash for row in labels),
            "routing_evidence_hashes": sorted(row.routing_evidence_hash for row in labels),
            "policy_config_hash": policy.config_hash, "policy_assets_hash": policy.assets_hash,
        }
        observed_from = min((self._as_utc(row.created_at) for row in routes), default=self._as_utc(policy.starts_at))
        if labels:
            observed_from = min(observed_from, *(self._as_utc(row.observation_end) for row in labels))
        observed_from = min(observed_from, as_of - timedelta(seconds=1))
        rollout_metrics = TenantRolloutRepository._metrics(routes)
        results = []
        for arm in ("champion", "challenger"):
            model_key = getattr(policy, f"{arm}_model_key")
            model_version = getattr(policy, f"{arm}_model_version")
            if payload.get("_model_key") and model_key != payload["_model_key"]:
                continue
            arm_labels = [row for row in labels if row.selected_arm == arm]
            events = sum(bool(row.observed_event) for row in arm_labels)
            non_events = len(arm_labels) - events
            supervised = events >= 5 and non_events >= 5
            arm_routes = [row for row in routes if row.selected_arm == arm]
            completed_routes = [row for row in arm_routes if row.status == "completed"]
            monitoring = {
                "schema_version": "tenant-monitoring-derived-v1",
                "source": "tenant_routing_and_verified_outcomes", "policy_config_hash": policy.config_hash,
                "policy_assets_hash": policy.assets_hash,
                "route_watermark": {"count": len(arm_routes), "route_ids": sorted(row.id for row in arm_routes),
                                    "evidence_hashes": sorted(row.evidence_hash for row in arm_routes)},
                "coverage": {"route_count": len(arm_routes), "completed_count": len(completed_routes),
                             "mature_verified_count": len(arm_labels), "event_count": events, "non_event_count": non_events},
                "score_distribution": rollout_metrics[arm]["score_distribution"],
                "rating_distribution": TenantRolloutRepository._distribution([row.rating or "unknown" for row in completed_routes]),
                "admission_distribution": rollout_metrics[arm]["admission_distribution"],
                "challenger_failure_rate": rollout_metrics["challenger"]["failure_rate"],
                "latency_increase_ratio": rollout_metrics["latency_increase_ratio"],
                "score_psi_champion_vs_challenger": rollout_metrics["score_psi"],
                "admission_distribution_shift": rollout_metrics["admission_distribution_shift"],
                "auc": self._auc([(float(row.risk_score), bool(row.observed_event)) for row in arm_labels]) if supervised else None,
                "ks": self._ks([(float(row.risk_score), bool(row.observed_event)) for row in arm_labels]) if supervised else None,
                "segments": self._segments(arm_labels) if arm_labels else [],
                "segment_stability": self._segment_stability(arm_labels, {"min_reliable_samples_per_arm": 30}),
                "degraded_reason": None if supervised else "每侧至少需要 5 个成熟且已核验的事件和非事件样本；AUC/KS 不可用",
                "fairness_audit": "not_evaluable",
            }
            run_key = f"tenant-monitor:{policy_id}:{definition.id}:{arm}:{as_of.strftime('%Y%m%dT%H%M%SZ')}"
            if payload.get("_run_key_suffix"):
                run_key = f"{run_key}:{payload['_run_key_suffix']}"
            result = self.create_monitoring_run(tenant_id, policy_id, {
                "run_key": run_key, "model_key": model_key, "model_version": model_version,
                "observed_from": observed_from, "observed_to": as_of,
                "dataset_id": f"rollout:{policy_id}:{definition.id}:{as_of.strftime('%Y%m%dT%H%M%SZ')}",
                "evidence_level": "supervised" if supervised else "non_supervised", "status": "completed",
                "governance_status": "draft",
                "label_definition_id": definition.id, "label_definition_version": definition.version,
                "label_definition_hash": definition.config_hash, "label_watermark": watermark,
                "monitoring": monitoring,
            }, principal, commit=False)
            results.append(result)
        if not results:
            raise TenantRolloutError("TENANT_MONITORING_MODEL_MISMATCH", "重算目标模型不属于该灰度策略冻结资产", 409)
        if commit:
            self.session.commit()
        return {"as_of": self._iso(as_of), "policy_id": policy_id, "runs": results,
                "idempotent": all(item["idempotent"] for item in results)}

    def create_monitoring_run(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal", *, commit: bool = True) -> dict:
        policy = self._policy(tenant_id, policy_id)
        observed_from = self._as_utc(payload["observed_from"])
        observed_to = self._as_utc(payload["observed_to"])
        now = self._now()
        if observed_to <= observed_from:
            raise TenantRolloutError("TENANT_MONITORING_WINDOW_INVALID", "监控观察窗口结束时间必须晚于开始时间", 422)
        if observed_to > now:
            raise TenantRolloutError("TENANT_MONITORING_WINDOW_FUTURE", "监控观察窗口不能晚于当前时间", 422)
        model_pair = {
            (policy.champion_model_key, policy.champion_model_version),
            (policy.challenger_model_key, policy.challenger_model_version),
        }
        if (payload["model_key"], payload["model_version"]) not in model_pair:
            raise TenantRolloutError("TENANT_MONITORING_MODEL_MISMATCH", "租户监控运行的模型版本不属于该灰度策略冻结资产", 409)
        definition = None
        if payload.get("label_definition_id"):
            definition = self._definition(tenant_id, payload["label_definition_id"])
            self._verify_definition_integrity(definition)
            if definition.status not in {"published", "retired"}:
                raise TenantRolloutError("LABEL_DEFINITION_NOT_EVALUABLE", "监控运行只能绑定已发布或已退役的冻结口径", 422)
            if payload.get("label_definition_version") not in (None, definition.version) or payload.get("label_definition_hash") not in (None, definition.config_hash):
                raise TenantRolloutError("TENANT_MONITORING_LABEL_DEFINITION_MISMATCH", "监控运行的标签口径版本或哈希不匹配", 409)
        watermark = deepcopy(payload.get("label_watermark") or {})
        evidence_payload = self._monitoring_run_evidence_payload(
            tenant_id, policy_id, payload["run_key"], payload["model_key"], payload["model_version"],
            observed_from, observed_to, payload["dataset_id"], payload["evidence_level"], payload["status"],
            definition, watermark, payload.get("monitoring") or {},
        )
        evidence_hash = content_hash(evidence_payload)
        existing = self.session.scalar(select(TenantMonitoringRunRecord).where(
            TenantMonitoringRunRecord.tenant_id == tenant_id,
            TenantMonitoringRunRecord.run_key == payload["run_key"],
        ))
        if existing:
            if existing.evidence_hash != evidence_hash:
                raise TenantRolloutError("TENANT_MONITORING_RUN_CONFLICT", "同一租户监控运行键已被不同快照占用", 409)
            return {**self._monitoring_run_view(existing), "idempotent": True}
        record = TenantMonitoringRunRecord(
            id=str(uuid4()), tenant_id=tenant_id, policy_id=policy_id, run_key=payload["run_key"],
            model_key=payload["model_key"], model_version=payload["model_version"], observed_from=observed_from,
            observed_to=observed_to, dataset_id=payload["dataset_id"], evidence_level=payload["evidence_level"],
            status=payload["status"], governance_status=payload.get("governance_status", "published"),
            label_definition_id=definition.id if definition else None,
            label_definition_version=definition.version if definition else None,
            label_definition_hash=definition.config_hash if definition else None,
            label_watermark_json=watermark, monitoring_json=deepcopy(payload.get("monitoring") or {}),
            evidence_hash=evidence_hash, created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("tenant_monitoring_run", record.id, "tenant_monitoring_run_created", principal.subject, {
                "tenant_id": tenant_id, "policy_id": policy_id, "run_key": record.run_key,
                "evidence_level": record.evidence_level, "evidence_hash": record.evidence_hash,
            })
            if commit:
                self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantRolloutError("TENANT_MONITORING_RUN_CONFLICT", "租户监控运行写入发生并发冲突，请刷新后重试", 409) from exc
        if commit:
            self.session.refresh(record)
        return {**self._monitoring_run_view(record), "idempotent": False}

    def submit_monitoring_run(self, tenant_id: str, policy_id: str, run_id: str, payload: dict, principal: "Principal") -> dict:
        run = self._monitoring_run(tenant_id, policy_id, run_id)
        self._check_monitoring_run_version(run, payload["expected_row_version"])
        if run.governance_status not in {"draft", "rejected"}:
            raise TenantRolloutError("TENANT_MONITORING_RUN_NOT_SUBMITTABLE", "只有草稿或已驳回的监控快照可以提交复核", 422)
        self._verify_monitoring_run_integrity(run)
        run.governance_status = "pending_review"
        run.submitted_by, run.submitted_by_name, run.submitted_at = principal.subject, principal.name, self._now()
        run.reviewed_by = run.reviewed_by_name = run.reviewed_at = run.review_comment = None
        return self._commit_monitoring_run(run, "tenant_monitoring_run_submitted", principal, {"note": payload["note"]})

    def review_monitoring_run(self, tenant_id: str, policy_id: str, run_id: str, payload: dict, principal: "Principal") -> dict:
        run = self._monitoring_run(tenant_id, policy_id, run_id)
        self._check_monitoring_run_version(run, payload["expected_row_version"])
        if run.governance_status != "pending_review":
            raise TenantRolloutError("TENANT_MONITORING_RUN_NOT_PENDING", "只有待复核的监控快照可以审批", 422)
        if run.created_by == principal.subject or run.submitted_by == principal.subject:
            raise TenantRolloutError("FOUR_EYES_REQUIRED", "监控快照创建人或提交人不能审批自己的快照", 409)
        self._verify_monitoring_run_integrity(run)
        if payload["decision"] == "approve":
            unresolved = self.session.scalar(select(TenantMonitoringDiffCaseRecord).where(
                TenantMonitoringDiffCaseRecord.tenant_id == tenant_id,
                TenantMonitoringDiffCaseRecord.policy_id == policy_id,
                TenantMonitoringDiffCaseRecord.severity == "critical",
                TenantMonitoringDiffCaseRecord.status.not_in(("resolved", "rejected")),
                or_(
                    TenantMonitoringDiffCaseRecord.base_run_id == run.id,
                    TenantMonitoringDiffCaseRecord.recomputed_run_id == run.id,
                ),
            ))
            if unresolved:
                raise TenantRolloutError(
                    "MONITORING_DIFF_CASE_UNRESOLVED",
                    "当前快照仍有关联的重大监控差异工单未关闭，不能发布",
                    409,
                )
        run.governance_status = "published" if payload["decision"] == "approve" else "rejected"
        run.reviewed_by, run.reviewed_by_name, run.reviewed_at = principal.subject, principal.name, self._now()
        run.review_comment = payload["comment"]
        return self._commit_monitoring_run(run, f"tenant_monitoring_run_{run.governance_status}", principal, {"comment": payload["comment"]})

    def retract_monitoring_run(self, tenant_id: str, policy_id: str, run_id: str, payload: dict, principal: "Principal") -> dict:
        run = self._monitoring_run(tenant_id, policy_id, run_id)
        self._check_monitoring_run_version(run, payload["expected_row_version"])
        if run.governance_status != "published":
            raise TenantRolloutError("TENANT_MONITORING_RUN_NOT_PUBLISHED", "只有已发布的监控快照可以撤回", 422)
        if run.created_by == principal.subject or run.reviewed_by == principal.subject:
            raise TenantRolloutError("FOUR_EYES_REQUIRED", "监控快照创建人或原审批人不能执行撤回", 409)
        self._verify_monitoring_run_integrity(run)
        run.governance_status = "retracted"
        run.retracted_by, run.retracted_by_name, run.retracted_at = principal.subject, principal.name, self._now()
        run.retraction_reason = payload["reason"]
        return self._commit_monitoring_run(run, "tenant_monitoring_run_retracted", principal, {"reason": payload["reason"]})

    def monitoring_run_diff(self, tenant_id: str, policy_id: str, run_id: str, against_run_id: str | None = None) -> dict:
        base = self._monitoring_run(tenant_id, policy_id, run_id)
        self._verify_monitoring_run_integrity(base)
        if against_run_id:
            against = self._monitoring_run(tenant_id, policy_id, against_run_id)
        else:
            against = self.session.scalar(select(TenantMonitoringRunRecord).where(
                TenantMonitoringRunRecord.tenant_id == tenant_id,
                TenantMonitoringRunRecord.policy_id == policy_id,
                TenantMonitoringRunRecord.model_key == base.model_key,
                TenantMonitoringRunRecord.model_version == base.model_version,
                TenantMonitoringRunRecord.observed_to < base.observed_to,
                TenantMonitoringRunRecord.id != base.id,
            ).order_by(TenantMonitoringRunRecord.observed_to.desc(), TenantMonitoringRunRecord.created_at.desc()))
        if against is None:
            raise TenantRolloutError("TENANT_MONITORING_DIFF_BASELINE_MISSING", "没有可用于比较的同模型历史监控快照", 404)
        if against.id == base.id:
            raise TenantRolloutError("TENANT_MONITORING_DIFF_SELF", "监控快照不能与自身比较", 422)
        self._verify_monitoring_run_integrity(against)
        if (base.model_key, base.model_version) != (against.model_key, against.model_version):
            raise TenantRolloutError("TENANT_MONITORING_DIFF_MODEL_MISMATCH", "差异比较必须使用相同模型和版本", 409)
        comparison = self._diff_values(against.monitoring_json or {}, base.monitoring_json or {})
        payload = {
            "schema_version": "tenant-monitoring-diff-v1",
            "tenant_id": tenant_id, "policy_id": policy_id,
            "against_run_id": against.id, "base_run_id": base.id,
            "against_evidence_hash": against.evidence_hash, "base_evidence_hash": base.evidence_hash,
            "model_key": base.model_key, "model_version": base.model_version,
            "comparison": comparison,
        }
        return {**payload, "diff_hash": content_hash(payload), "against": self._monitoring_run_view(against), "base": self._monitoring_run_view(base)}

    def list_monitoring_diff_cases(self, tenant_id: str, policy_id: str) -> list[dict]:
        self._policy(tenant_id, policy_id)
        rows = self.session.scalars(select(TenantMonitoringDiffCaseRecord).where(
            TenantMonitoringDiffCaseRecord.tenant_id == tenant_id,
            TenantMonitoringDiffCaseRecord.policy_id == policy_id,
        ).order_by(TenantMonitoringDiffCaseRecord.created_at.desc())).all()
        return [self._monitoring_diff_case_view(row) for row in rows]

    @classmethod
    def monitoring_diff_case_sla_status(cls, record: TenantMonitoringDiffCaseRecord, now: datetime) -> dict:
        if record.status in {"resolved", "rejected"}:
            return {"status": "stopped", "remaining_hours": 0.0, "overdue_hours": 0.0}
        scan_at = cls._as_utc(now)
        due_at = cls._as_utc(record.due_at)
        remaining_hours = (due_at - scan_at).total_seconds() / 3600
        rule = cls.MONITORING_DIFF_SLA_RULES.get(record.severity, cls.MONITORING_DIFF_SLA_RULES["warning"])
        if remaining_hours > rule["due_soon_hours"]:
            status = "normal"
        elif remaining_hours > 0:
            status = "due_soon"
        elif -remaining_hours >= rule["escalation_after_hours"]:
            status = "escalated"
        else:
            status = "overdue"
        return {
            "status": status,
            "remaining_hours": round(max(remaining_hours, 0), 1),
            "overdue_hours": round(max(-remaining_hours, 0), 1),
            "due_soon_hours": rule["due_soon_hours"],
            "escalation_after_hours": rule["escalation_after_hours"],
        }

    def monitoring_diff_sla_dashboard(
        self, tenant_id: str, template_key: str | None = None, now: datetime | None = None,
    ) -> dict:
        scan_at = self._as_utc(now or self._now())
        rows = self.session.scalars(select(TenantMonitoringDiffCaseRecord).where(
            TenantMonitoringDiffCaseRecord.tenant_id == tenant_id,
            TenantMonitoringDiffCaseRecord.status.in_(("open", "assigned", "recomputing", "pending_disposition")),
        ).order_by(TenantMonitoringDiffCaseRecord.due_at, TenantMonitoringDiffCaseRecord.id)).all()
        policies = {
            row.id: row for row in self.session.scalars(select(TenantRolloutPolicyRecord).where(
                TenantRolloutPolicyRecord.tenant_id == tenant_id,
            )).all()
        }
        runs = {
            row.id: row for row in self.session.scalars(select(TenantMonitoringRunRecord).where(
                TenantMonitoringRunRecord.tenant_id == tenant_id,
                TenantMonitoringRunRecord.id.in_({item.base_run_id for item in rows}),
            )).all()
        } if rows else {}
        items = []
        for row in rows:
            run = runs.get(row.base_run_id)
            policy = policies.get(row.policy_id)
            model_key = run.model_key if run else (policy.champion_model_key if policy else None)
            if template_key and model_key != template_key:
                continue
            sla = self.monitoring_diff_case_sla_status(row, scan_at)
            items.append({
                **self._monitoring_diff_case_view(row), "sla": sla,
                "model_key": model_key, "model_version": run.model_version if run else None,
                "policy_name": policy.name if policy else row.policy_id,
                "policy_status": policy.status if policy else None,
            })

        status_rank = {"escalated": 0, "overdue": 1, "due_soon": 2, "normal": 3}
        items.sort(key=lambda item: (status_rank[item["sla"]["status"]], item["due_at"], item["id"]))

        def aggregate(key_name: str, label_name: str) -> list[dict]:
            grouped: dict[str, dict] = {}
            for item in items:
                key = str(item.get(key_name) or "unknown")
                group = grouped.setdefault(key, {
                    key_name: item.get(key_name), label_name: item.get(label_name) or key,
                    "open_count": 0, "due_soon_count": 0, "overdue_count": 0,
                    "escalated_count": 0, "unassigned_count": 0,
                })
                group["open_count"] += 1
                sla_status = item["sla"]["status"]
                if sla_status != "normal":
                    group[f"{sla_status}_count"] += 1
                if not item["assigned_to"]:
                    group["unassigned_count"] += 1
            return sorted(grouped.values(), key=lambda item: (
                -item["escalated_count"], -item["overdue_count"], -item["open_count"], str(item.get(label_name) or ""),
            ))

        def aggregate_models() -> list[dict]:
            grouped: dict[tuple[str, str], dict] = {}
            for item in items:
                model_key = item.get("model_key")
                model_version = item.get("model_version")
                group_key = (str(model_key or "unknown"), str(model_version or "unknown"))
                group = grouped.setdefault(group_key, {
                    "model_key": model_key, "model_version": model_version,
                    "open_count": 0, "due_soon_count": 0, "overdue_count": 0,
                    "escalated_count": 0, "unassigned_count": 0,
                })
                group["open_count"] += 1
                sla_status = item["sla"]["status"]
                if sla_status != "normal":
                    group[f"{sla_status}_count"] += 1
                if not item["assigned_to"]:
                    group["unassigned_count"] += 1
            return sorted(grouped.values(), key=lambda item: (
                -item["escalated_count"], -item["overdue_count"], -item["open_count"],
                str(item.get("model_key") or ""), str(item.get("model_version") or ""),
            ))

        counts = {
            "open": len(items),
            "normal": sum(item["sla"]["status"] == "normal" for item in items),
            "due_soon": sum(item["sla"]["status"] == "due_soon" for item in items),
            "overdue": sum(item["sla"]["status"] == "overdue" for item in items),
            "escalated": sum(item["sla"]["status"] == "escalated" for item in items),
            "unassigned": sum(not item["assigned_to"] for item in items),
            "pending_disposition": sum(item["status"] == "pending_disposition" for item in items),
            "critical": sum(item["severity"] == "critical" for item in items),
        }
        return {
            "schema_version": "monitoring-diff-sla-dashboard-v1", "tenant_id": tenant_id,
            "template_key": template_key, "as_of": scan_at.isoformat(), "counts": counts,
            "by_policy": aggregate("policy_id", "policy_name"),
            "by_model": aggregate_models(),
            "items": items[:100],
        }

    def scan_monitoring_diff_case_sla(
        self, tenant_id: str, actor_subject: str = "system:monitoring-diff-sla", now: datetime | None = None,
    ) -> dict:
        scan_at = self._as_utc(now or self._now())
        dashboard = self.monitoring_diff_sla_dashboard(tenant_id, now=scan_at)
        notifications = NotificationRepository(self.session)
        prior = self.session.scalars(select(NotificationRecord).where(
            NotificationRecord.tenant_id == tenant_id,
            NotificationRecord.category == "monitoring_diff_case_sla",
            NotificationRecord.status != "resolved",
        )).all()
        active: dict[str, tuple[str, str, set[tuple[str, str | None]]]] = {}
        for item in dashboard["items"]:
            level = item["sla"]["status"]
            if level == "normal":
                continue
            recipients: set[tuple[str, str | None]] = {
                (item["assigned_role"], item["assigned_to"]),
            }
            if level in {"overdue", "escalated"}:
                recipients.add(("risk_manager", None))
            if level == "escalated":
                recipients.add(("admin", None))
            active[item["id"]] = (level, item["due_at"], recipients)

        resolved_count = 0
        for notice in prior:
            action = notice.action_json or {}
            case_id = action.get("diff_case_id")
            current = active.get(case_id)
            target = (notice.recipient_role, notice.recipient_subject)
            if current and action.get("sla_status") == current[0] and action.get("due_at") == current[1] and target in current[2]:
                continue
            notice.status, notice.read_at = "resolved", scan_at
            resolved_count += 1
            self.audit.append("notification", notice.id, "monitoring_diff_case_sla_notification_resolved", actor_subject, {
                "tenant_id": tenant_id, "diff_case_id": case_id,
                "resolution": "stage_changed_or_case_closed",
            })

        created_count = 0
        level_counts = {"due_soon": 0, "overdue": 0, "escalated": 0}
        item_by_id = {item["id"]: item for item in dashboard["items"]}
        for case_id, (level, due_at, recipients) in active.items():
            level_counts[level] += 1
            item = item_by_id[case_id]
            title = {"due_soon": "监控差异工单即将到期", "overdue": "监控差异工单已逾期", "escalated": "监控差异工单严重逾期升级"}[level]
            message = {
                "due_soon": f"{item['policy_name']} 的监控差异工单将在 {due_at} 到期，请及时领取、重算或处置。",
                "overdue": f"{item['policy_name']} 的监控差异工单已逾期 {item['sla']['overdue_hours']} 小时，请立即处理。",
                "escalated": f"{item['policy_name']} 的监控差异工单已严重逾期 {item['sla']['overdue_hours']} 小时，现升级至风控经理和平台管理员督办。",
            }[level]
            for role, subject in sorted(recipients, key=lambda value: (value[0], value[1] or "")):
                payload = {
                    "case_id": None, "counterparty_id": None,
                    "recipient_role": role, "recipient_subject": subject,
                    "category": "monitoring_diff_case_sla", "level": level,
                    "severity": "critical" if level in {"overdue", "escalated"} or item["severity"] == "critical" else "warning",
                    "title": title, "message": message,
                    "action_json": {
                        "page": "model-governance", "target": "tenant-rollout-governance",
                        "policy_id": item["policy_id"], "diff_case_id": case_id,
                        "model_key": item["model_key"], "sla_status": level, "due_at": due_at,
                    },
                    "dedup_key": f"monitoring-diff-sla:{case_id}:{due_at}:{level}:{role}:{subject or '*'}",
                    "status": "unread",
                }
                notice, created = notifications.create_if_absent(tenant_id, payload)
                if created:
                    created_count += 1
                    self.audit.append("notification", notice["id"], "monitoring_diff_case_sla_notification_created", actor_subject, {
                        "tenant_id": tenant_id, "diff_case_id": case_id, "sla_status": level,
                        "recipient_role": role, "recipient_subject": subject,
                    })
        result = {
            "scanned_at": scan_at.isoformat(), "items_scanned": dashboard["counts"]["open"],
            **level_counts, "notifications_created": created_count,
            "notifications_resolved": resolved_count,
        }
        self.audit.append(
            "monitoring_diff_case_sla_scan", f"{tenant_id}:{scan_at.isoformat()}",
            "monitoring_diff_case_sla_scanned", actor_subject, {"tenant_id": tenant_id, **result},
        )
        self.session.commit()
        return result

    def create_monitoring_diff_case(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        diff = self.monitoring_run_diff(tenant_id, policy_id, payload["base_run_id"], payload["against_run_id"])
        existing = self.session.scalar(select(TenantMonitoringDiffCaseRecord).where(
            TenantMonitoringDiffCaseRecord.tenant_id == tenant_id,
            TenantMonitoringDiffCaseRecord.diff_hash == diff["diff_hash"],
        ))
        if existing:
            return {**self._monitoring_diff_case_view(existing), "idempotent": True}
        gate = self.monitoring_gate(tenant_id, policy_id, payload["base_run_id"])
        severity = payload.get("severity") or (
            "critical" if gate["status"] in {"blocked", "evidence_stale"} else
            "warning" if gate["status"] == "at_risk" else "info"
        )
        now = self._now()
        due_at = self._as_utc(payload.get("due_at") or now + timedelta(hours={"critical": 24, "warning": 72, "info": 120}[severity]))
        if due_at <= now:
            raise TenantRolloutError("MONITORING_DIFF_CASE_DUE_INVALID", "差异工单处置期限必须晚于当前时间", 422)
        record = TenantMonitoringDiffCaseRecord(
            id=str(uuid4()), tenant_id=tenant_id, policy_id=policy_id,
            base_run_id=diff["base_run_id"], against_run_id=diff["against_run_id"],
            base_evidence_hash=diff["base_evidence_hash"], against_evidence_hash=diff["against_evidence_hash"],
            diff_hash=diff["diff_hash"], comparison_json=deepcopy(diff["comparison"]),
            status="open", severity=severity, reason=payload["reason"],
            assigned_role=payload.get("assigned_role") or "risk_manager", due_at=due_at,
            recompute_status="not_started", created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        return {**self._commit_monitoring_diff_case(record, "tenant_monitoring_diff_case_created", principal, {
            "diff_hash": record.diff_hash, "severity": severity, "due_at": self._iso(due_at),
        }), "idempotent": False}

    def assign_monitoring_diff_case(self, tenant_id: str, policy_id: str, case_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._monitoring_diff_case(tenant_id, policy_id, case_id)
        self._check_monitoring_diff_case_version(record, payload["expected_row_version"])
        if record.status in {"resolved", "rejected", "recomputing"}:
            raise TenantRolloutError("MONITORING_DIFF_CASE_NOT_ASSIGNABLE", "当前差异工单状态不能领取或转派", 422)
        assigned_to = payload.get("assigned_to") or principal.subject
        if assigned_to != principal.subject and "admin" not in principal.roles:
            raise TenantRolloutError("MONITORING_DIFF_CASE_ASSIGN_FORBIDDEN", "只有管理员可以将差异工单指派给其他人员", 403)
        due_at = self._as_utc(payload.get("due_at") or record.due_at)
        if due_at <= self._now():
            raise TenantRolloutError("MONITORING_DIFF_CASE_DUE_INVALID", "差异工单处置期限必须晚于当前时间", 422)
        record.assigned_to = assigned_to
        record.assigned_to_name = payload.get("assigned_to_name") or (principal.name if assigned_to == principal.subject else assigned_to)
        record.due_at = due_at
        record.status = "pending_disposition" if record.recompute_status == "completed" else "assigned"
        return self._commit_monitoring_diff_case(record, "tenant_monitoring_diff_case_assigned", principal, {
            "assigned_to": assigned_to, "due_at": self._iso(due_at), "reason": payload["reason"],
        })

    def recompute_monitoring_diff_case(self, tenant_id: str, policy_id: str, case_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._monitoring_diff_case(tenant_id, policy_id, case_id)
        self._check_monitoring_diff_case_version(record, payload["expected_row_version"])
        if record.status in {"resolved", "rejected", "recomputing"}:
            raise TenantRolloutError("MONITORING_DIFF_CASE_NOT_RECOMPUTABLE", "当前差异工单状态不能执行重算", 422)
        if record.assigned_to and record.assigned_to != principal.subject and "admin" not in principal.roles:
            raise TenantRolloutError("MONITORING_DIFF_CASE_OWNER_REQUIRED", "差异工单已由其他人员负责", 409)
        self._verify_monitoring_diff_case_integrity(record)
        base = self._monitoring_run(tenant_id, policy_id, record.base_run_id)
        if not base.label_definition_id:
            raise TenantRolloutError("MONITORING_DIFF_CASE_LABEL_REQUIRED", "原快照未冻结标签口径，无法执行受控重算", 422)
        record.assigned_to = record.assigned_to or principal.subject
        record.assigned_to_name = record.assigned_to_name or principal.name
        record.status, record.recompute_status = "recomputing", "running"
        record.recompute_error = None
        self.session.flush()
        try:
            result = self.generate_monitoring_runs(tenant_id, policy_id, {
                "label_definition_id": base.label_definition_id,
                "as_of": self._as_utc(base.observed_to),
                "_model_key": base.model_key,
                "_run_key_suffix": f"recompute-{record.id}-{record.row_version}",
            }, principal, commit=False)
            recomputed = result["runs"][0]
            recomputed_diff = self.monitoring_run_diff(tenant_id, policy_id, recomputed["id"], record.against_run_id)
            record.recomputed_run_id = recomputed["id"]
            record.recomputed_diff_hash = recomputed_diff["diff_hash"]
            record.recomputed_by, record.recomputed_by_name = principal.subject, principal.name
            record.recomputed_at = self._now()
            record.recompute_status, record.status = "completed", "pending_disposition"
            return self._commit_monitoring_diff_case(record, "tenant_monitoring_diff_case_recomputed", principal, {
                "reason": payload["reason"], "recomputed_run_id": recomputed["id"],
                "original_diff_hash": record.diff_hash, "recomputed_diff_hash": record.recomputed_diff_hash,
            })
        except TenantRolloutError as exc:
            self.session.rollback()
            record = self._monitoring_diff_case(tenant_id, policy_id, case_id)
            record.recompute_status, record.status, record.recompute_error = "failed", "assigned", exc.message
            self._commit_monitoring_diff_case(record, "tenant_monitoring_diff_case_recompute_failed", principal, {
                "reason": payload["reason"], "error_code": exc.code, "error": exc.message,
            })
            raise

    def dispose_monitoring_diff_case(self, tenant_id: str, policy_id: str, case_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._monitoring_diff_case(tenant_id, policy_id, case_id)
        self._check_monitoring_diff_case_version(record, payload["expected_row_version"])
        if record.status != "pending_disposition" or record.recompute_status != "completed":
            raise TenantRolloutError("MONITORING_DIFF_CASE_NOT_DISPOSABLE", "差异工单完成重算后才能提交处置结论", 422)
        if record.recomputed_by == principal.subject:
            raise TenantRolloutError("FOUR_EYES_REQUIRED", "重算执行人与最终处置人必须分离", 409)
        self._verify_monitoring_diff_case_integrity(record)
        record.status = "resolved"
        record.disposition, record.conclusion = payload["disposition"], payload["conclusion"]
        record.resolved_by, record.resolved_by_name, record.resolved_at = principal.subject, principal.name, self._now()
        return self._commit_monitoring_diff_case(record, "tenant_monitoring_diff_case_resolved", principal, {
            "disposition": record.disposition, "conclusion": record.conclusion,
            "original_diff_hash": record.diff_hash, "recomputed_diff_hash": record.recomputed_diff_hash,
        })

    def list_definitions(self, tenant_id: str, published_only: bool = False) -> list[dict]:
        statement = select(TenantOutcomeLabelDefinitionRecord).where(
            TenantOutcomeLabelDefinitionRecord.tenant_id == tenant_id
        )
        if published_only:
            statement = statement.where(
                TenantOutcomeLabelDefinitionRecord.status == "published",
                TenantOutcomeLabelDefinitionRecord.is_active.is_(True),
            )
        rows = self.session.scalars(statement.order_by(
            TenantOutcomeLabelDefinitionRecord.code,
            TenantOutcomeLabelDefinitionRecord.version.desc(),
        )).all()
        return [self._definition_view(row) for row in rows]

    def create_definition(self, tenant_id: str, payload: dict, principal: "Principal") -> dict:
        latest_version = self.session.scalar(
            select(TenantOutcomeLabelDefinitionRecord.version).where(
                TenantOutcomeLabelDefinitionRecord.tenant_id == tenant_id,
                TenantOutcomeLabelDefinitionRecord.code == payload["code"],
            ).order_by(TenantOutcomeLabelDefinitionRecord.version.desc())
        )
        version = int(latest_version or 0) + 1
        config = self._definition_config(payload, version)
        record = TenantOutcomeLabelDefinitionRecord(
            id=str(uuid4()), tenant_id=tenant_id, code=payload["code"], version=version,
            name=payload["name"], description=payload["description"], event_type=payload["event_type"],
            event_threshold_json=deepcopy(payload["event_threshold"]),
            observation_window_days=payload["observation_window_days"],
            maturity_grace_days=payload["maturity_grace_days"],
            source_priorities_json=deepcopy(payload["source_priorities"]),
            applicable_model_keys_json=list(payload["applicable_model_keys"]),
            require_loss_amount=payload["require_loss_amount"],
            require_exposure_amount=payload["require_exposure_amount"],
            status="draft", is_active=False, config_hash=content_hash(config),
            created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        return self._commit_definition(record, "tenant_outcome_label_definition_created", principal, {"version": version})

    def update_definition(self, tenant_id: str, definition_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._definition(tenant_id, definition_id)
        self._check_definition_version(record, payload["expected_row_version"])
        if record.status != "draft":
            raise TenantRolloutError("LABEL_DEFINITION_STATUS_INVALID", "只有草稿口径可以修改", 422)
        if record.created_by != principal.subject:
            raise TenantRolloutError("LABEL_DEFINITION_OWNER_REQUIRED", "只有草稿创建人可以修改口径", 403)
        if record.code != payload["code"]:
            raise TenantRolloutError("LABEL_DEFINITION_CODE_IMMUTABLE", "口径代码在创建后不可修改；请新建其他代码", 422)
        for field in ("name", "description", "event_type", "observation_window_days", "maturity_grace_days", "require_loss_amount", "require_exposure_amount"):
            setattr(record, field, payload[field])
        record.event_threshold_json = deepcopy(payload["event_threshold"])
        record.source_priorities_json = deepcopy(payload["source_priorities"])
        record.applicable_model_keys_json = list(payload["applicable_model_keys"])
        record.config_hash = content_hash(self._definition_config(payload, record.version))
        return self._commit_definition(record, "tenant_outcome_label_definition_updated", principal, {})

    def submit_definition(self, tenant_id: str, definition_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._definition(tenant_id, definition_id)
        self._check_definition_version(record, payload["expected_row_version"])
        if record.status != "draft":
            raise TenantRolloutError("LABEL_DEFINITION_STATUS_INVALID", "只有草稿口径可以提交复核", 422)
        if record.created_by != principal.subject:
            raise TenantRolloutError("LABEL_DEFINITION_OWNER_REQUIRED", "只有草稿创建人可以提交口径", 403)
        self._verify_definition_integrity(record)
        record.status = "pending_review"
        record.submitted_by, record.submitted_by_name = principal.subject, principal.name
        record.submitted_at = self._now()
        return self._commit_definition(record, "tenant_outcome_label_definition_submitted", principal, {"note": payload["note"]})

    def review_definition(self, tenant_id: str, definition_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._definition(tenant_id, definition_id)
        self._check_definition_version(record, payload["expected_row_version"])
        if record.status != "pending_review":
            raise TenantRolloutError("LABEL_DEFINITION_STATUS_INVALID", "只有待复核口径可以审批", 422)
        if record.created_by == principal.subject:
            raise TenantRolloutError("FOUR_EYES_REQUIRED", "标签口径创建人与审批人必须分离", 409)
        self._verify_definition_integrity(record)
        if payload["decision"] == "approve":
            current = self.session.scalars(select(TenantOutcomeLabelDefinitionRecord).where(
                TenantOutcomeLabelDefinitionRecord.tenant_id == tenant_id,
                TenantOutcomeLabelDefinitionRecord.code == record.code,
                TenantOutcomeLabelDefinitionRecord.status == "published",
                TenantOutcomeLabelDefinitionRecord.is_active.is_(True),
                TenantOutcomeLabelDefinitionRecord.id != record.id,
            )).all()
            for previous in current:
                previous.status, previous.is_active = "retired", False
            if current:
                self.session.flush()
            record.status, record.is_active = "published", True
        else:
            record.status, record.is_active = "rejected", False
        record.reviewed_by, record.reviewed_by_name = principal.subject, principal.name
        record.reviewed_at, record.review_comment = self._now(), payload["comment"]
        return self._commit_definition(record, f"tenant_outcome_label_definition_{record.status}", principal, {"comment": payload["comment"]})

    def list_labels(self, tenant_id: str, policy_id: str) -> list[dict]:
        self._policy(tenant_id, policy_id)
        rows = self.session.scalars(select(TenantOutcomeLabelRecord).where(
            TenantOutcomeLabelRecord.tenant_id == tenant_id,
            TenantOutcomeLabelRecord.policy_id == policy_id,
        ).order_by(TenantOutcomeLabelRecord.created_at.desc(), TenantOutcomeLabelRecord.id.desc())).all()
        now = self._now()
        return [self._label_view(row, now) for row in rows]

    def list_imports(self, tenant_id: str, policy_id: str) -> list[dict]:
        self._policy(tenant_id, policy_id)
        rows = self.session.scalars(select(TenantOutcomeImportBatchRecord).where(
            TenantOutcomeImportBatchRecord.tenant_id == tenant_id,
            TenantOutcomeImportBatchRecord.policy_id == policy_id,
        ).order_by(TenantOutcomeImportBatchRecord.created_at.desc(), TenantOutcomeImportBatchRecord.id.desc())).all()
        return [self._import_view(row) for row in rows]

    def create_import(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        self._policy(tenant_id, policy_id)
        definition = (
            self._published_definition(tenant_id, payload["label_definition_id"])
            if payload.get("label_definition_id")
            else self._published_definition_by_code(tenant_id, payload.get("label_definition", ""))
        )
        payload = {
            **payload,
            "label_definition": definition.code,
            "label_definition_version": definition.version,
            "label_definition_hash": definition.config_hash,
        }
        self._assert_source_allowed(definition, payload["source"])
        canonical = self._canonical_import_payload(payload)
        payload_hash = content_hash(canonical)
        existing = self.session.scalar(select(TenantOutcomeImportBatchRecord).where(
            TenantOutcomeImportBatchRecord.tenant_id == tenant_id,
            TenantOutcomeImportBatchRecord.import_key == payload["import_key"],
        ))
        if existing:
            if existing.payload_hash != payload_hash or existing.policy_id != policy_id:
                raise TenantRolloutError("OUTCOME_IMPORT_CONFLICT", "同一批次键已被不同载荷或灰度策略占用", 409)
            return {**self._import_view(existing), "idempotent": True}

        batch_id = str(uuid4())
        batch = TenantOutcomeImportBatchRecord(
            id=batch_id,
            tenant_id=tenant_id,
            policy_id=policy_id,
            import_key=payload["import_key"],
            source=payload["source"],
            label_definition=payload["label_definition"],
            label_definition_id=definition.id,
            label_definition_version=definition.version,
            label_definition_hash=definition.config_hash,
            expected_count=payload["expected_count"],
            received_count=len(payload["outcomes"]),
            created_count=0,
            idempotent_count=0,
            rejected_count=0,
            corrected_count=0,
            payload_hash=payload_hash,
            results_json=[],
            status="processing",
            evidence_hash="",
            created_by=principal.subject,
            created_by_name=principal.name,
            completed_at=None,
        )
        self.session.add(batch)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            concurrent = self.session.scalar(select(TenantOutcomeImportBatchRecord).where(
                TenantOutcomeImportBatchRecord.tenant_id == tenant_id,
                TenantOutcomeImportBatchRecord.import_key == payload["import_key"],
            ))
            if concurrent and concurrent.payload_hash == payload_hash and concurrent.policy_id == policy_id:
                return {**self._import_view(concurrent), "idempotent": True}
            raise TenantRolloutError("OUTCOME_IMPORT_CONFLICT", "结果标签批次写入发生并发冲突，请刷新后重试", 409) from exc
        results: list[dict] = []
        for index, row in enumerate(payload["outcomes"]):
            label_payload = {
                **row,
                "source": payload["source"],
                "label_definition": payload["label_definition"],
                "label_definition_id": definition.id,
            }
            try:
                with self.session.begin_nested():
                    label_record, idempotent = self._create_label_record(
                        tenant_id,
                        policy_id,
                        label_payload,
                        principal,
                        import_batch_id=batch_id,
                    )
                results.append({
                    "index": index,
                    "external_label_id": row["external_label_id"],
                    "status": "idempotent" if idempotent else "created",
                    "label_id": label_record.id,
                    "error_code": None,
                    "error": None,
                })
            except TenantRolloutError as exc:
                results.append({
                    "index": index,
                    "external_label_id": row["external_label_id"],
                    "status": "rejected",
                    "label_id": None,
                    "error_code": exc.code,
                    "error": exc.message,
                })
            except IntegrityError:
                results.append({
                    "index": index,
                    "external_label_id": row["external_label_id"],
                    "status": "rejected",
                    "label_id": None,
                    "error_code": "OUTCOME_LABEL_CONFLICT",
                    "error": "结果标签写入发生并发冲突",
                })

        created_count = sum(item["status"] == "created" for item in results)
        idempotent_count = sum(item["status"] == "idempotent" for item in results)
        rejected_count = sum(item["status"] == "rejected" for item in results)
        received_count = len(payload["outcomes"])
        status = "completed" if rejected_count == 0 and received_count == payload["expected_count"] else "completed_with_exceptions"
        completed_at = self._now()
        evidence_payload = {
            "schema_version": "tenant-outcome-import-v1",
            "tenant_id": tenant_id,
            "policy_id": policy_id,
            "import_key": payload["import_key"],
            "source": payload["source"],
            "label_definition": payload["label_definition"],
            "label_definition_id": definition.id,
            "label_definition_version": definition.version,
            "label_definition_hash": definition.config_hash,
            "expected_count": payload["expected_count"],
            "received_count": received_count,
            "created_count": created_count,
            "idempotent_count": idempotent_count,
            "rejected_count": rejected_count,
            "corrected_count": 0,
            "payload_hash": payload_hash,
            "results": results,
            "status": status,
            "completed_at": completed_at.isoformat(),
        }
        batch.received_count = received_count
        batch.created_count = created_count
        batch.idempotent_count = idempotent_count
        batch.rejected_count = rejected_count
        batch.results_json = results
        batch.status = status
        batch.evidence_hash = content_hash(evidence_payload)
        batch.completed_at = completed_at
        try:
            self.session.flush()
            self.audit.append("tenant_outcome_import", batch.id, "tenant_outcome_import_completed", principal.subject, {
                "tenant_id": tenant_id, "policy_id": policy_id, "status": status,
                "expected_count": batch.expected_count, "received_count": batch.received_count,
                "created_count": batch.created_count, "idempotent_count": batch.idempotent_count,
                "rejected_count": batch.rejected_count, "evidence_hash": batch.evidence_hash,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            concurrent = self.session.scalar(select(TenantOutcomeImportBatchRecord).where(
                TenantOutcomeImportBatchRecord.tenant_id == tenant_id,
                TenantOutcomeImportBatchRecord.import_key == payload["import_key"],
            ))
            if concurrent and concurrent.payload_hash == payload_hash and concurrent.policy_id == policy_id:
                return {**self._import_view(concurrent), "idempotent": True}
            raise TenantRolloutError("OUTCOME_IMPORT_CONFLICT", "结果标签批次写入发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(batch)
        return {**self._import_view(batch), "idempotent": False}

    def create_label(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        try:
            record, idempotent = self._create_label_record(tenant_id, policy_id, payload, principal)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("OUTCOME_LABEL_CONFLICT", "结果标签写入发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return {**self._label_view(record, self._now()), "idempotent": idempotent}

    def _create_label_record(
        self,
        tenant_id: str,
        policy_id: str,
        payload: dict,
        principal: "Principal",
        *,
        import_batch_id: str | None = None,
        supersedes_label_id: str | None = None,
        correction_reason: str | None = None,
    ) -> tuple[TenantOutcomeLabelRecord, bool]:
        policy = self._policy(tenant_id, policy_id)
        definition = (
            self._published_definition(tenant_id, payload["label_definition_id"])
            if payload.get("label_definition_id")
            else self._published_definition_by_code(tenant_id, payload.get("label_definition", ""))
        )
        payload = {
            **payload,
            "label_definition": definition.code,
            "label_definition_version": definition.version,
            "label_definition_hash": definition.config_hash,
        }
        canonical = self._canonical_label_payload(payload)
        payload_hash = content_hash(canonical)
        existing = self.session.scalar(select(TenantOutcomeLabelRecord).where(
            TenantOutcomeLabelRecord.tenant_id == tenant_id,
            TenantOutcomeLabelRecord.source == payload["source"],
            TenantOutcomeLabelRecord.external_label_id == payload["external_label_id"],
        ))
        if existing:
            if existing.label_payload_hash != payload_hash or existing.policy_id != policy_id:
                raise TenantRolloutError("OUTCOME_LABEL_CONFLICT", "同一来源的结果标签编号已被不同内容占用", 409)
            return existing, True
        duplicate_definition = self.session.scalar(select(TenantOutcomeLabelRecord).where(
            TenantOutcomeLabelRecord.tenant_id == tenant_id,
            TenantOutcomeLabelRecord.routing_decision_id == payload["routing_decision_id"],
            TenantOutcomeLabelRecord.label_definition == payload["label_definition"],
            TenantOutcomeLabelRecord.record_status == "active",
        ))
        if duplicate_definition:
            raise TenantRolloutError("OUTCOME_LABEL_CONFLICT", "该历史路由已回流相同口径的结果标签", 409)

        route = self.session.scalar(select(TenantRoutingDecisionRecord).where(
            TenantRoutingDecisionRecord.id == payload["routing_decision_id"],
            TenantRoutingDecisionRecord.tenant_id == tenant_id,
            TenantRoutingDecisionRecord.policy_id == policy_id,
        ))
        if route is None:
            raise TenantRolloutError("OUTCOME_ROUTE_NOT_FOUND", "租户内对应的历史灰度路由不存在", 404)
        self._validate_route(route)
        if hashlib.sha256(payload["counterparty_id"].encode("utf-8")).hexdigest() != route.routing_key_hash:
            raise TenantRolloutError("OUTCOME_COUNTERPARTY_MISMATCH", "结果标签的企业编号与历史路由键不一致", 409)
        observation_end = self._as_utc(payload["observation_end"])
        if observation_end <= self._as_utc(route.created_at):
            raise TenantRolloutError("OUTCOME_WINDOW_INVALID", "观察截止时间必须晚于历史预测时间", 422)
        minimum_observation_end = self._as_utc(route.created_at) + timedelta(
            days=definition.observation_window_days + definition.maturity_grace_days
        )
        if observation_end < minimum_observation_end:
            raise TenantRolloutError(
                "OUTCOME_WINDOW_DEFINITION_MISMATCH",
                f"观察截止时间未达到口径要求的 {definition.observation_window_days} 天观察期",
                422,
                {"minimum_observation_end": minimum_observation_end.isoformat()},
            )
        if payload.get("loss_amount") is not None and payload.get("exposure_amount") is not None and payload["loss_amount"] > payload["exposure_amount"]:
            raise TenantRolloutError("OUTCOME_AMOUNT_INVALID", "损失金额不能高于风险暴露金额", 422)

        model = deepcopy((route.selected_assets_json or {}).get("model") or {})
        model_key, model_version = str(model.get("key") or ""), str(model.get("version") or "")
        if not model_key or not model_version:
            raise TenantRolloutError("OUTCOME_ASSET_EVIDENCE_INVALID", "历史路由缺少冻结模型标识", 409)
        expected = (
            (policy.champion_model_key, policy.champion_model_version)
            if route.selected_arm == "champion"
            else (policy.challenger_model_key, policy.challenger_model_version)
        )
        if (model_key, model_version) != expected:
            raise TenantRolloutError("OUTCOME_MODEL_MISMATCH", "历史路由模型版本与灰度选边不一致", 409)
        self._assert_definition_applicable(definition, payload["source"], model_key, payload)

        execution = self._linked_execution(route, payload["counterparty_id"], model_key, model_version)
        score = Decimal(str(route.score))
        risk_score = self._risk_score(model, score)
        evidence_payload = self._canonical_evidence_payload(
            tenant_id=tenant_id, policy_id=policy_id, routing_decision_id=route.id,
            decision_execution_id=execution.id if execution else None, source=payload["source"],
            external_label_id=payload["external_label_id"], counterparty_id=payload["counterparty_id"],
            label_definition=payload["label_definition"], label_definition_id=definition.id,
            label_definition_version=definition.version, label_definition_hash=definition.config_hash,
            observed_event=payload["observed_event"], observation_end=observation_end,
            loss_amount=payload.get("loss_amount"), exposure_amount=payload.get("exposure_amount"),
            evidence_reference=payload["evidence_reference"], selected_arm=route.selected_arm,
            model_key=model_key, model_version=model_version, predicted_score=score, risk_score=risk_score,
            routing_evidence_hash=route.evidence_hash,
            execution_evidence_hash=execution.evidence_hash if execution else None,
            selected_assets_hash=route.selected_assets_hash, import_batch_id=import_batch_id,
            supersedes_label_id=supersedes_label_id, correction_reason=correction_reason,
        )
        record = TenantOutcomeLabelRecord(
            id=str(uuid4()), tenant_id=tenant_id, policy_id=policy_id, routing_decision_id=route.id,
            decision_execution_id=execution.id if execution else None, source=payload["source"],
            external_label_id=payload["external_label_id"], counterparty_id=payload["counterparty_id"],
            label_definition=payload["label_definition"], observed_event=payload["observed_event"],
            label_definition_id=definition.id, label_definition_version=definition.version,
            label_definition_hash=definition.config_hash,
            observation_end=observation_end,
            loss_amount=Decimal(str(payload["loss_amount"])) if payload.get("loss_amount") is not None else None,
            exposure_amount=Decimal(str(payload["exposure_amount"])) if payload.get("exposure_amount") is not None else None,
            evidence_reference=payload["evidence_reference"],
            link_status="decision_execution" if execution else "route_only", selected_arm=route.selected_arm,
            model_key=model_key, model_version=model_version, predicted_score=score, risk_score=risk_score,
            rating=route.rating, admission=route.admission, routing_evidence_hash=str(route.evidence_hash),
            execution_evidence_hash=execution.evidence_hash if execution else None,
            selected_assets_hash=route.selected_assets_hash, label_payload_hash=payload_hash,
            evidence_hash=content_hash(evidence_payload), evidence_schema_version=evidence_payload["schema_version"],
            canonical_evidence_json=deepcopy(evidence_payload), import_batch_id=import_batch_id,
            record_status="active", supersedes_label_id=supersedes_label_id,
            correction_reason=correction_reason,
            corrected_by=principal.subject if supersedes_label_id else None,
            corrected_at=self._now() if supersedes_label_id else None,
            created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        self.session.flush()
        self.audit.append(
            "tenant_outcome_label",
            record.id,
            "tenant_outcome_label_correction_created" if supersedes_label_id else "tenant_outcome_label_ingested",
            principal.subject,
            {
                "tenant_id": tenant_id, "policy_id": policy_id, "routing_decision_id": route.id,
                "link_status": record.link_status, "import_batch_id": import_batch_id,
                "supersedes_label_id": supersedes_label_id, "evidence_hash": record.evidence_hash,
            },
        )
        return record, False

    def verify_label(self, tenant_id: str, policy_id: str, label_id: str, payload: dict, principal: "Principal") -> dict:
        record = self.session.scalar(select(TenantOutcomeLabelRecord).where(
            TenantOutcomeLabelRecord.id == label_id,
            TenantOutcomeLabelRecord.tenant_id == tenant_id,
            TenantOutcomeLabelRecord.policy_id == policy_id,
        ))
        if record is None:
            raise TenantRolloutError("OUTCOME_LABEL_NOT_FOUND", "结果标签不存在", 404)
        if record.row_version != payload["expected_row_version"]:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"结果标签版本已变化，当前版本为 {record.row_version}", 409)
        if record.verification_status != "pending_verification":
            raise TenantRolloutError("OUTCOME_LABEL_ALREADY_REVIEWED", "只有待核验标签可以执行复核", 422)
        if record.record_status != "active":
            raise TenantRolloutError("OUTCOME_LABEL_SUPERSEDED", "已被冲正替代的标签不能再次核验", 422)
        if record.created_by == principal.subject:
            raise TenantRolloutError("FOUR_EYES_REQUIRED", "结果标签录入人与核验人必须分离", 409)
        self._verify_label_integrity(record)
        record.verification_status = "verified" if payload["decision"] == "verify" else "rejected"
        record.verified_by, record.verified_by_name = principal.subject, principal.name
        record.verified_at, record.verification_note = self._now(), payload["note"]
        try:
            self.session.flush()
            self.audit.append("tenant_outcome_label", record.id, f"tenant_outcome_label_{record.verification_status}", principal.subject, {
                "tenant_id": tenant_id, "policy_id": policy_id, "note": payload["note"],
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("ROW_VERSION_CONFLICT", "结果标签复核发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._label_view(record, self._now())

    def correct_label(self, tenant_id: str, policy_id: str, label_id: str, payload: dict, principal: "Principal") -> dict:
        record = self.session.scalar(select(TenantOutcomeLabelRecord).where(
            TenantOutcomeLabelRecord.id == label_id,
            TenantOutcomeLabelRecord.tenant_id == tenant_id,
            TenantOutcomeLabelRecord.policy_id == policy_id,
        ))
        if record is None:
            raise TenantRolloutError("OUTCOME_LABEL_NOT_FOUND", "结果标签不存在", 404)
        if record.row_version != payload["expected_row_version"]:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"结果标签版本已变化，当前版本为 {record.row_version}", 409)
        if record.record_status != "active":
            raise TenantRolloutError("OUTCOME_LABEL_SUPERSEDED", "只有当前活动标签可以发起冲正", 422)
        self._verify_label_integrity(record)
        corrected_payload = {
            "source": record.source,
            "external_label_id": payload["external_label_id"],
            "routing_decision_id": record.routing_decision_id,
            "counterparty_id": record.counterparty_id,
            "label_definition": record.label_definition,
            "label_definition_id": record.label_definition_id,
            "observed_event": payload["observed_event"],
            "observation_end": payload["observation_end"],
            "loss_amount": payload.get("loss_amount"),
            "exposure_amount": payload.get("exposure_amount"),
            "evidence_reference": payload["evidence_reference"],
        }
        now = self._now()
        record.record_status = "superseded"
        record.correction_reason = payload["reason"]
        record.corrected_by = principal.subject
        record.corrected_at = now
        try:
            self.session.flush()
            replacement, idempotent = self._create_label_record(
                tenant_id,
                policy_id,
                corrected_payload,
                principal,
                supersedes_label_id=record.id,
                correction_reason=payload["reason"],
            )
            if idempotent and replacement.supersedes_label_id != record.id:
                raise TenantRolloutError("OUTCOME_LABEL_CONFLICT", "冲正标签编号已用于其他结果事实", 409)
            record.superseded_by_label_id = replacement.id
            self.session.flush()
            self.audit.append("tenant_outcome_label", record.id, "tenant_outcome_label_superseded", principal.subject, {
                "tenant_id": tenant_id, "policy_id": policy_id, "superseded_by_label_id": replacement.id,
                "reason": payload["reason"],
            })
            self.session.commit()
        except TenantRolloutError:
            self.session.rollback()
            raise
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("OUTCOME_LABEL_CONFLICT", "结果标签冲正发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(replacement)
        return self._label_view(replacement, self._now())

    def list_evaluations(self, tenant_id: str, policy_id: str) -> list[dict]:
        self._policy(tenant_id, policy_id)
        rows = self.session.scalars(select(TenantSupervisedEvaluationRecord).where(
            TenantSupervisedEvaluationRecord.tenant_id == tenant_id,
            TenantSupervisedEvaluationRecord.policy_id == policy_id,
        ).order_by(TenantSupervisedEvaluationRecord.created_at.desc(), TenantSupervisedEvaluationRecord.id.desc())).all()
        decisions = self.session.scalars(select(TenantSupervisedUpgradeDecisionRecord).where(
            TenantSupervisedUpgradeDecisionRecord.tenant_id == tenant_id,
            TenantSupervisedUpgradeDecisionRecord.policy_id == policy_id,
        )).all()
        by_evaluation = {item.evaluation_id: item for item in decisions}
        return [self._evaluation_view(row, by_evaluation.get(row.id)) for row in rows]

    def verification_report(self, tenant_id: str, policy_id: str, evaluation_id: str) -> dict:
        """Build a deterministic, read-only verification report from one frozen evaluation."""
        record = self._evaluation(tenant_id, policy_id, evaluation_id)
        self._verify_evaluation_integrity(record)
        evaluation = self._evaluation_view(record)
        policy = self._policy(tenant_id, policy_id)
        metrics = deepcopy(record.metrics_json or {})
        coverage = deepcopy(record.coverage_json or {})
        caveats = [
            "本报告来自不可变监督评估快照，不会重新读取或修改历史预测结果。",
            "监督证据不足时，AUC/KS/混淆矩阵不会使用代理标签补齐。",
            "AUC/KS bootstrap 区间和双模型差异信号用于统计验证线索，不替代独立验证、业务收益评估或发布审批。",
            "评级/准入分群只反映业务稳定性；当前快照未绑定受保护属性，不构成公平性通过或不通过结论。",
        ]
        if record.evidence_level != "supervised":
            caveats.append("当前评估为降级证据，仅可用于观察和治理讨论，不构成模型晋级依据。")
        if (metrics.get("comparison") or {}).get("promotion_readiness") != "ready":
            caveats.append("当前双模型比较未达到统计可靠的晋级门槛。")
        payload = {
            "schema_version": "tenant-supervised-verification-report-v1",
            "report_type": "supervised_model_validation",
            "generated_at": self._iso(record.created_at),
            "tenant_id": tenant_id,
            "policy": {
                "id": policy.id,
                "name": policy.name,
                "status": policy.status,
                "champion_model_key": policy.champion_model_key,
                "champion_model_version": policy.champion_model_version,
                "challenger_model_key": policy.challenger_model_key,
                "challenger_model_version": policy.challenger_model_version,
                "config_hash": policy.config_hash,
                "assets_hash": policy.assets_hash,
            },
            "evaluation": evaluation,
            "coverage": coverage,
            "metrics": metrics,
            "caveats": caveats,
            "report_template": {"id": "supervised-model-validation", "version": "v2", "locale": "zh-CN"},
            "signature": {"status": "unsigned", "issuer": None, "signed_at": None, "algorithm": "SHA-256", "note": "签发主体和外部签名在独立验证与发布审批阶段补录。"},
            "attachments": [],
            "governance_boundary": {
                "model_change_created": bool(evaluation.get("upgrade_decision")),
                "auto_submitted": False,
                "auto_published": False,
                "traffic_changed": False,
            },
        }
        report_hash = content_hash(payload)
        return {**payload, "report_hash": report_hash}

    def evaluate(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        policy = self._policy(tenant_id, policy_id)
        requested_as_of = payload.get("evaluation_as_of")
        if requested_as_of is None and payload.get("tenant_monitoring_run_id"):
            bound_run = self.session.scalar(select(TenantMonitoringRunRecord).where(
                TenantMonitoringRunRecord.id == payload["tenant_monitoring_run_id"],
                TenantMonitoringRunRecord.tenant_id == tenant_id,
                TenantMonitoringRunRecord.policy_id == policy_id,
            ))
            if bound_run is not None:
                requested_as_of = bound_run.observed_to
        as_of = self._as_utc(requested_as_of or self._now())
        if as_of > self._now():
            raise TenantRolloutError("SUPERVISED_AS_OF_INVALID", "评估截止时间不能晚于当前时间", 422)
        rows = list(self.session.scalars(select(TenantOutcomeLabelRecord).where(
            TenantOutcomeLabelRecord.tenant_id == tenant_id,
            TenantOutcomeLabelRecord.policy_id == policy_id,
        )).all())
        for row in rows:
            self._verify_label_integrity(row)
        active = [row for row in rows if row.record_status == "active"]
        verified = [row for row in active if row.verification_status == "verified"]
        definition_ids = {row.label_definition_id for row in verified}
        requested_definition_id = payload.get("label_definition_id")
        if requested_definition_id:
            definition = self._definition(tenant_id, requested_definition_id)
            self._verify_definition_integrity(definition)
            if definition.status not in {"published", "retired"}:
                raise TenantRolloutError("LABEL_DEFINITION_NOT_EVALUABLE", "监督评估只能使用已发布或已退役的冻结口径", 422)
            active = [row for row in active if row.label_definition_id == definition.id]
            verified = [row for row in verified if row.label_definition_id == definition.id]
        elif len(definition_ids) == 1 and None not in definition_ids:
            definition = self._definition(tenant_id, str(next(iter(definition_ids))))
            self._verify_definition_integrity(definition)
        elif not verified or definition_ids == {None}:
            definition = None
        else:
            raise TenantRolloutError(
                "SUPERVISED_LABEL_DEFINITION_AMBIGUOUS",
                "存在多个标签口径或新旧口径混用，请明确选择单一口径后再评估",
                422,
            )
        mature = [row for row in verified if self._as_utc(row.observation_end) <= as_of]
        immature = [row for row in verified if self._as_utc(row.observation_end) > as_of]
        config = {
            "min_mature_samples": payload["min_mature_samples"], "min_events": payload["min_events"],
            "min_non_events": payload["min_non_events"],
            "min_reliable_samples_per_arm": payload["min_reliable_samples_per_arm"],
            "high_risk_threshold": payload["high_risk_threshold"],
            "bootstrap_resamples": payload["bootstrap_resamples"],
            "label_definition_id": definition.id if definition else None,
        }
        arm_rows = {arm: [row for row in mature if row.selected_arm == arm] for arm in ("champion", "challenger")}
        arm_metrics = {arm: self._arm_metrics(arm_rows[arm], config) for arm in ("champion", "challenger")}
        total_events = sum(row.observed_event for row in mature)
        coverage = {
            "submitted_count": len(active), "superseded_count": len(rows) - len(active),
            "verified_count": len(verified), "rejected_count": sum(row.verification_status == "rejected" for row in active),
            "pending_verification_count": sum(row.verification_status == "pending_verification" for row in active),
            "mature_count": len(mature), "immature_count": len(immature), "event_count": total_events,
            "non_event_count": len(mature) - total_events,
            "execution_linked_count": sum(row.link_status == "decision_execution" for row in mature),
            "route_only_count": sum(row.link_status == "route_only" for row in mature),
        }
        supervised_ready = (
            len(mature) >= config["min_mature_samples"]
            and all(arm_metrics[arm]["auc"] is not None and arm_metrics[arm]["ks"] is not None for arm in arm_metrics)
        )
        evidence_level = "supervised" if supervised_ready else "insufficient_maturity" if immature else "insufficient_labels"
        comparison = self._comparison(arm_metrics, arm_rows, config) if supervised_ready else None
        metrics = {
            **arm_metrics, "comparison": comparison, "supervised_metrics_available": supervised_ready,
            "degraded_reason": None if supervised_ready else self._degraded_reason(coverage, config, arm_metrics),
            "note": "历史预测分值来自冻结路由证据；监督评估不会自动恢复或重新激活灰度策略。",
        }
        watermark = {
            "label_count": len(mature), "label_ids": sorted(row.id for row in mature),
            "label_evidence_hashes": sorted(row.evidence_hash for row in mature),
            "routing_evidence_hashes": sorted(row.routing_evidence_hash for row in mature),
            "label_definition_id": definition.id if definition else None,
            "label_definition_version": definition.version if definition else None,
            "label_definition_hash": definition.config_hash if definition else None,
            "policy_config_hash": policy.config_hash, "policy_assets_hash": policy.assets_hash,
        }
        monitoring_run = None
        monitoring_run_id = payload.get("tenant_monitoring_run_id")
        if monitoring_run_id:
            monitoring_run = self._bind_monitoring_run(
                tenant_id, policy, monitoring_run_id, as_of, mature, definition,
            )
        watermark["tenant_monitoring_run_id"] = monitoring_run["id"] if monitoring_run else None
        watermark["tenant_monitoring_evidence_hash"] = monitoring_run["evidence_hash"] if monitoring_run else None
        evidence_payload = {
            "schema_version": "tenant-supervised-evaluation-v2" if definition else "tenant-supervised-evaluation-v1",
            "tenant_id": tenant_id, "policy_id": policy_id,
            "evaluation_as_of": as_of.isoformat(), "config": config, "coverage": coverage,
            "metrics": metrics, "evidence_level": evidence_level, "label_watermark": watermark,
        }
        if monitoring_run:
            evidence_payload.update(
                tenant_monitoring_run_id=monitoring_run["id"],
                tenant_monitoring_evidence_hash=monitoring_run["evidence_hash"],
            )
        record = TenantSupervisedEvaluationRecord(
            id=str(uuid4()), tenant_id=tenant_id, policy_id=policy_id, evaluation_as_of=as_of,
            config_json=config, coverage_json=coverage, metrics_json=metrics, evidence_level=evidence_level,
            label_watermark_json=watermark, evidence_hash=content_hash(evidence_payload),
            label_definition_id=definition.id if definition else None,
            label_definition_version=definition.version if definition else None,
            label_definition_hash=definition.config_hash if definition else None,
            tenant_monitoring_run_id=monitoring_run["id"] if monitoring_run else None,
            tenant_monitoring_evidence_hash=monitoring_run["evidence_hash"] if monitoring_run else None,
            status="draft",
            created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        self.session.flush()
        self.audit.append("tenant_supervised_evaluation", record.id, "tenant_supervised_evaluation_created", principal.subject, {
            "tenant_id": tenant_id, "policy_id": policy_id, "evidence_level": evidence_level,
            "mature_count": len(mature), "tenant_monitoring_run_id": record.tenant_monitoring_run_id,
            "evidence_hash": record.evidence_hash,
        })
        self.session.commit()
        self.session.refresh(record)
        return self._evaluation_view(record)

    def submit_evaluation(self, tenant_id: str, policy_id: str, evaluation_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._evaluation(tenant_id, policy_id, evaluation_id)
        self._verify_evaluation_integrity(record)
        if record.row_version != payload["expected_row_version"]:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"监督评估版本已变化，当前版本为 {record.row_version}", 409)
        if record.status != "draft":
            raise TenantRolloutError("SUPERVISED_STATUS_INVALID", "只有草稿监督评估可以提交复核", 422)
        if record.evidence_level != "supervised":
            raise TenantRolloutError("SUPERVISED_EVIDENCE_INSUFFICIENT", "降级证据只能查看，不能提交模型治理审批", 422)
        record.status = "pending_review"
        record.submitted_by = principal.subject
        record.submitted_by_name = principal.name
        record.submitted_at = self._now()
        self._commit_evaluation(record, "tenant_supervised_evaluation_submitted", principal, {
            "tenant_id": tenant_id, "policy_id": policy_id, "note": payload["note"],
        })
        return self._evaluation_view(record)

    def review_evaluation(self, tenant_id: str, policy_id: str, evaluation_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._evaluation(tenant_id, policy_id, evaluation_id)
        self._verify_evaluation_integrity(record)
        if record.row_version != payload["expected_row_version"]:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"监督评估版本已变化，当前版本为 {record.row_version}", 409)
        if record.status != "pending_review":
            raise TenantRolloutError("SUPERVISED_STATUS_INVALID", "只有待复核监督评估可以审批", 422)
        if record.created_by == principal.subject:
            raise TenantRolloutError("FOUR_EYES_REQUIRED", "监督评估创建人与审批人必须分离", 409)
        record.status = "approved" if payload["decision"] == "approve" else "rejected"
        record.governance_decision = payload.get("governance_decision") if payload["decision"] == "approve" else None
        record.reviewed_by = principal.subject
        record.reviewed_by_name = principal.name
        record.reviewed_at = self._now()
        record.review_comment = payload["comment"]
        self._commit_evaluation(record, f"tenant_supervised_evaluation_{record.status}", principal, {
            "tenant_id": tenant_id, "policy_id": policy_id,
            "governance_decision": record.governance_decision,
            "comment": payload["comment"],
            "policy_mutated": False,
        })
        return self._evaluation_view(record)

    def create_upgrade_draft(
        self,
        tenant_id: str,
        policy_id: str,
        evaluation_id: str,
        payload: dict,
        principal: "Principal",
        demo_repository,
        governance_repository,
    ) -> dict:
        from backend.model_governance import validate_and_assess
        from rating.enterprise_indicator_pool import get_model_indicator_selection

        policy = self._policy(tenant_id, policy_id)
        record = self._evaluation(tenant_id, policy_id, evaluation_id)
        self._verify_evaluation_integrity(record)
        if record.evidence_hash != payload["expected_evidence_hash"]:
            raise TenantRolloutError("SUPERVISED_EVIDENCE_CONFLICT", "监督评估证据哈希已变化，请刷新后重试", 409)
        if record.status != "approved" or record.governance_decision != "promote_candidate":
            raise TenantRolloutError("SUPERVISED_PROMOTION_NOT_APPROVED", "只有已批准且治理意见为建议晋级的监督评估才能生成变更草稿", 422)
        comparison = (record.metrics_json or {}).get("comparison") or {}
        if comparison.get("promotion_readiness") != "ready":
            raise TenantRolloutError("SUPERVISED_RELIABILITY_INSUFFICIENT", "监督证据仍为方向性结论，未达到升级草稿的统计可靠性门槛", 422)
        existing = self.session.scalar(select(TenantSupervisedUpgradeDecisionRecord).where(
            TenantSupervisedUpgradeDecisionRecord.tenant_id == tenant_id,
            TenantSupervisedUpgradeDecisionRecord.evaluation_id == evaluation_id,
        ))
        if existing:
            return {**self._upgrade_view(existing, governance_repository), "idempotent": True}
        if content_hash(policy.arm_snapshot_json) != policy.assets_hash:
            raise TenantRolloutError("ROLLOUT_INTEGRITY_FAILED", "灰度策略资产快照完整性校验失败", 409)
        challenger = deepcopy((policy.arm_snapshot_json or {}).get("challenger") or {})
        challenger_model = deepcopy(challenger.get("model") or {})
        if str(challenger_model.get("key")) != policy.challenger_model_key or str(challenger_model.get("version")) != policy.challenger_model_version:
            raise TenantRolloutError("SUPERVISED_CANDIDATE_DRIFTED", "Challenger 冻结模型标识与灰度策略不一致", 409)
        candidate = deepcopy(challenger_model.get("config") or {})
        if not candidate:
            raise TenantRolloutError("SUPERVISED_CANDIDATE_CONFIG_MISSING", "Challenger 快照缺少模型配置，不能生成治理草稿", 409)
        candidate = _materialize_model_runtime_defaults(candidate)
        candidate["indicator_selection"] = deepcopy(
            candidate.get("indicator_selection") or get_model_indicator_selection(candidate)
        )
        candidate["version"] = policy.challenger_model_version
        base = governance_repository.get_config(demo_repository, policy.champion_model_key)
        if not base:
            raise TenantRolloutError("SUPERVISED_BASELINE_MISSING", "当前 Champion 模型基线不存在", 409)
        if str(base.get("version")) != policy.champion_model_version:
            raise TenantRolloutError("SUPERVISED_BASELINE_DRIFTED", "当前模型基线已变化，请重新开展回放与灰度验证", 409)
        validation, impact = validate_and_assess(
            base,
            candidate,
            demo_repository.list_counterparties(),
            policy.champion_model_key,
        )
        if not validation["valid"]:
            raise TenantRolloutError("SUPERVISED_CANDIDATE_INVALID", "Challenger 冻结配置未通过当前模型校验", 422, {"errors": validation["errors"]})
        report = self.verification_report(tenant_id, policy_id, evaluation_id)
        supervised_binding = {
            "schema_version": "model-supervised-validation-binding-v1",
            "tenant_id": tenant_id, "policy_id": policy_id, "evaluation_id": evaluation_id,
            "evaluation_evidence_hash": record.evidence_hash, "report_hash": report["report_hash"],
            "report_template_version": "supervised-model-validation-v2",
            "evidence_level": record.evidence_level, "candidate_version": policy.challenger_model_version,
            "risk_classification": {"proposed_level": "medium", "method": "supervised_evidence_v1", "manual_confirmation_required": True},
            "independent_validation": {"status": "pending"},
            "release_approval": {"status": "pending"}, "attachments": [],
            "bound_by": principal.subject, "bound_by_name": principal.name,
        }
        try:
            change = governance_repository.create_change(
                {
                    "template_key": policy.champion_model_key,
                    "base_version": policy.champion_model_version,
                    "candidate_version": policy.challenger_model_version,
                    "config": candidate,
                    "validation": validation,
                    "impact": impact,
                    "change_reason": payload["change_reason"],
                    "supervised_validation_evidence": supervised_binding,
                },
                principal.subject,
                principal.name,
                commit=False,
            )
            supervised_binding["model_change_id"] = change["id"]
            change_record = self.session.get(ModelChangeRecord, change["id"])
            if change_record is None:
                raise ValueError("模型变更草稿创建后无法绑定监督验证证据")
            change_record.supervised_validation_evidence_json = supervised_binding
            change_record.supervised_validation_binding_hash = content_hash(supervised_binding)
            evidence = {
                "schema_version": "tenant-supervised-upgrade-decision-v1",
                "tenant_id": tenant_id,
                "policy_id": policy_id,
                "evaluation_id": evaluation_id,
                "evaluation_evidence_hash": record.evidence_hash,
                "label_definition_hash": record.label_definition_hash,
                "candidate_version": policy.challenger_model_version,
                "model_change_id": change["id"],
                "decision": "promote_candidate",
            }
            decision = TenantSupervisedUpgradeDecisionRecord(
                id=str(uuid4()), tenant_id=tenant_id, policy_id=policy_id, evaluation_id=evaluation_id,
                decision="promote_candidate", status="draft_created", evidence_hash=content_hash(evidence),
                model_change_id=change["id"], candidate_version=policy.challenger_model_version,
                created_by=principal.subject, created_by_name=principal.name,
            )
            self.session.add(decision)
            self.session.flush()
            self.audit.append("tenant_supervised_upgrade_decision", decision.id, "tenant_supervised_upgrade_draft_created", principal.subject, {
                **evidence,
                "upgrade_evidence_hash": decision.evidence_hash,
                "auto_submitted": False,
                "auto_published": False,
                "traffic_changed": False,
            })
            self.session.commit()
        except ValueError as exc:
            self.session.rollback()
            raise TenantRolloutError("SUPERVISED_MODEL_CHANGE_CONFLICT", str(exc), 409) from exc
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("SUPERVISED_UPGRADE_CONFLICT", "监督升级决策发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(decision)
        return {**self._upgrade_view(decision, governance_repository), "idempotent": False}

    def _commit_evaluation(self, record: TenantSupervisedEvaluationRecord, event_type: str, principal: "Principal", payload: dict) -> None:
        try:
            self.session.flush()
            self.audit.append("tenant_supervised_evaluation", record.id, event_type, principal.subject, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("ROW_VERSION_CONFLICT", "监督评估审批发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)

    def _linked_execution(self, route: TenantRoutingDecisionRecord, counterparty_id: str, model_key: str, model_version: str) -> DecisionExecutionRecord | None:
        if route.channel != "decision_api":
            return None
        execution = self.session.scalar(select(DecisionExecutionRecord).where(
            DecisionExecutionRecord.tenant_id == route.tenant_id,
            DecisionExecutionRecord.request_id == route.request_ref,
        ))
        if execution is None:
            raise TenantRolloutError("OUTCOME_EXECUTION_MISSING", "Decision API 路由缺少对应的历史执行证据", 409)
        if execution.counterparty_id != counterparty_id or execution.model_key != model_key or execution.model_version != model_version:
            raise TenantRolloutError("OUTCOME_EXECUTION_MISMATCH", "历史执行与标签企业或冻结模型版本不一致", 409)
        if execution.result_hash != route.result_hash:
            raise TenantRolloutError("OUTCOME_EXECUTION_DRIFTED", "历史执行结果哈希与灰度路由不一致", 409)
        return execution

    @staticmethod
    def _risk_score(model: dict, score: Decimal) -> Decimal:
        config = model.get("config") or {}
        scale = config.get("score_scale") or ((model.get("scorecard") or {}).get("config") or {}).get("score_scale") or {}
        minimum = Decimal(str(scale.get("min", 0)))
        maximum = Decimal(str(scale.get("max", 100)))
        if maximum <= minimum:
            raise TenantRolloutError("OUTCOME_SCORE_SCALE_INVALID", "冻结模型的评分范围无效，不能生成风险方向分值", 409)
        normalized = max(Decimal("0"), min(Decimal("1"), (score - minimum) / (maximum - minimum)))
        risk = Decimal("1") - normalized if bool(scale.get("higher_is_better", True)) else normalized
        return risk.quantize(Decimal("0.000001"))

    def _bind_monitoring_run(
        self,
        tenant_id: str,
        policy: TenantRolloutPolicyRecord,
        run_id: str,
        evaluation_as_of: datetime,
        mature: list[TenantOutcomeLabelRecord],
        definition: TenantOutcomeLabelDefinitionRecord | None,
    ) -> dict:
        run = self.session.scalar(select(TenantMonitoringRunRecord).where(
            TenantMonitoringRunRecord.id == run_id,
            TenantMonitoringRunRecord.tenant_id == tenant_id,
            TenantMonitoringRunRecord.policy_id == policy.id,
        ))
        if run is None:
            raise TenantRolloutError("TENANT_MONITORING_RUN_NOT_FOUND", "当前租户和灰度策略下不存在该监控运行", 404)
        if run.status != "completed":
            raise TenantRolloutError("TENANT_MONITORING_RUN_NOT_COMPLETED", "只有已完成的租户监控运行可以绑定监督评估", 409)
        if run.governance_status != "published":
            raise TenantRolloutError("TENANT_MONITORING_RUN_NOT_PUBLISHED", "只有已发布的租户监控运行可以绑定监督评估", 409)
        if self.monitoring_run_evidence_hash(run) != run.evidence_hash:
            raise TenantRolloutError("TENANT_MONITORING_EVIDENCE_DRIFTED", "租户监控运行快照完整性校验失败", 409)
        if (run.model_key, run.model_version) not in {
            (policy.champion_model_key, policy.champion_model_version),
            (policy.challenger_model_key, policy.challenger_model_version),
        }:
            raise TenantRolloutError("TENANT_MONITORING_MODEL_MISMATCH", "租户监控运行模型版本不属于当前灰度策略", 409)
        if self._as_utc(run.observed_to) < evaluation_as_of:
            raise TenantRolloutError("TENANT_MONITORING_WINDOW_INCOMPLETE", "租户监控观察窗口未覆盖监督评估截止时间", 409)
        if mature and self._as_utc(run.observed_from) > min(self._as_utc(row.observation_end) for row in mature):
            raise TenantRolloutError("TENANT_MONITORING_WINDOW_INCOMPLETE", "租户监控观察窗口未覆盖成熟标签水位", 409)
        if definition:
            if (run.label_definition_id != definition.id
                or run.label_definition_version != definition.version
                or run.label_definition_hash != definition.config_hash):
                raise TenantRolloutError("TENANT_MONITORING_LABEL_DEFINITION_MISMATCH", "租户监控运行与监督评估标签口径不一致", 409)
        elif run.label_definition_id:
            raise TenantRolloutError("TENANT_MONITORING_LABEL_DEFINITION_MISMATCH", "未指定标签口径的评估不能绑定带口径的监控运行", 409)
        watermark = run.label_watermark_json or {}
        if mature and watermark.get("label_count") is None:
            raise TenantRolloutError("TENANT_MONITORING_LABEL_WATERMARK_MISSING", "租户监控运行缺少覆盖成熟标签的水位快照", 409)
        if watermark.get("label_count") is not None and int(watermark["label_count"]) != len(mature):
            raise TenantRolloutError("TENANT_MONITORING_LABEL_WATERMARK_MISMATCH", "租户监控运行标签数量与评估快照不一致", 409)
        if watermark.get("label_ids") is not None and sorted(watermark.get("label_ids") or []) != sorted(row.id for row in mature):
            raise TenantRolloutError("TENANT_MONITORING_LABEL_WATERMARK_MISMATCH", "租户监控运行标签水位与评估快照不一致", 409)
        if watermark.get("label_evidence_hashes") is not None and sorted(watermark.get("label_evidence_hashes") or []) != sorted(row.evidence_hash for row in mature):
            raise TenantRolloutError("TENANT_MONITORING_LABEL_WATERMARK_MISMATCH", "租户监控运行标签证据哈希与评估快照不一致", 409)
        return self._monitoring_run_view(run)

    def _verify_label_integrity(self, record: TenantOutcomeLabelRecord) -> None:
        if record.evidence_schema_version == "tenant-outcome-label-v4":
            canonical = self._canonical_evidence_payload(
                tenant_id=record.tenant_id, policy_id=record.policy_id,
                routing_decision_id=record.routing_decision_id,
                decision_execution_id=record.decision_execution_id, source=record.source,
                external_label_id=record.external_label_id, counterparty_id=record.counterparty_id,
                label_definition=record.label_definition, label_definition_id=record.label_definition_id or "",
                label_definition_version=record.label_definition_version or 0,
                label_definition_hash=record.label_definition_hash or "",
                observed_event=record.observed_event, observation_end=record.observation_end,
                loss_amount=record.loss_amount, exposure_amount=record.exposure_amount,
                evidence_reference=record.evidence_reference, selected_arm=record.selected_arm,
                model_key=record.model_key, model_version=record.model_version,
                predicted_score=record.predicted_score, risk_score=record.risk_score,
                routing_evidence_hash=record.routing_evidence_hash,
                execution_evidence_hash=record.execution_evidence_hash,
                selected_assets_hash=record.selected_assets_hash,
                import_batch_id=record.import_batch_id, supersedes_label_id=record.supersedes_label_id,
                correction_reason=record.correction_reason,
            )
            if record.canonical_evidence_json != canonical or content_hash(record.canonical_evidence_json or {}) != record.evidence_hash:
                raise TenantRolloutError("OUTCOME_EVIDENCE_DRIFTED", "结果标签规范化证据载荷与冻结哈希不一致", 409)
        route = self.session.get(TenantRoutingDecisionRecord, record.routing_decision_id)
        if route is None or route.tenant_id != record.tenant_id or route.policy_id != record.policy_id:
            raise TenantRolloutError("OUTCOME_EVIDENCE_DRIFTED", "标签绑定的历史路由已缺失或越出租户范围", 409)
        self._validate_route(route)
        if route.evidence_hash != record.routing_evidence_hash or route.selected_assets_hash != record.selected_assets_hash:
            raise TenantRolloutError("OUTCOME_EVIDENCE_DRIFTED", "标签绑定后的历史路由证据发生变化", 409)
        if (
            route.selected_arm != record.selected_arm
            or Decimal(str(route.score)) != record.predicted_score
            or route.rating != record.rating
            or route.admission != record.admission
        ):
            raise TenantRolloutError("OUTCOME_EVIDENCE_DRIFTED", "标签绑定后的历史预测结果发生变化", 409)
        model = (route.selected_assets_json or {}).get("model") or {}
        if str(model.get("key")) != record.model_key or str(model.get("version")) != record.model_version:
            raise TenantRolloutError("OUTCOME_EVIDENCE_DRIFTED", "标签绑定后的冻结模型版本发生变化", 409)
        if record.decision_execution_id:
            execution = self.session.get(DecisionExecutionRecord, record.decision_execution_id)
            if execution is None or execution.tenant_id != record.tenant_id or execution.evidence_hash != record.execution_evidence_hash or execution.result_hash != route.result_hash:
                raise TenantRolloutError("OUTCOME_EVIDENCE_DRIFTED", "标签绑定后的 Decision API 执行证据发生变化", 409)
        if record.label_definition_id:
            definition = self._definition(record.tenant_id, record.label_definition_id)
            self._verify_definition_integrity(definition)
            if definition.version != record.label_definition_version or definition.config_hash != record.label_definition_hash:
                raise TenantRolloutError("OUTCOME_LABEL_DEFINITION_DRIFTED", "标签绑定的口径版本或哈希不再匹配", 409)

    def _verify_evaluation_integrity(self, record: TenantSupervisedEvaluationRecord) -> None:
        evidence_payload = {
            "schema_version": "tenant-supervised-evaluation-v2" if record.label_definition_id else "tenant-supervised-evaluation-v1",
            "tenant_id": record.tenant_id,
            "policy_id": record.policy_id,
            "evaluation_as_of": self._iso(record.evaluation_as_of),
            "config": record.config_json,
            "coverage": record.coverage_json,
            "metrics": record.metrics_json,
            "evidence_level": record.evidence_level,
            "label_watermark": record.label_watermark_json,
        }
        if record.tenant_monitoring_run_id:
            evidence_payload.update(
                tenant_monitoring_run_id=record.tenant_monitoring_run_id,
                tenant_monitoring_evidence_hash=record.tenant_monitoring_evidence_hash,
            )
        if content_hash(evidence_payload) != record.evidence_hash:
            raise TenantRolloutError("SUPERVISED_EVIDENCE_DRIFTED", "监督评估快照完整性校验失败，不能提交或审批", 409)
        if record.tenant_monitoring_run_id:
            run = self.session.scalar(select(TenantMonitoringRunRecord).where(
                TenantMonitoringRunRecord.id == record.tenant_monitoring_run_id,
                TenantMonitoringRunRecord.tenant_id == record.tenant_id,
                TenantMonitoringRunRecord.policy_id == record.policy_id,
            ))
            if run is None or self.monitoring_run_evidence_hash(run) != record.tenant_monitoring_evidence_hash:
                raise TenantRolloutError("TENANT_MONITORING_EVIDENCE_DRIFTED", "监督评估绑定的租户监控运行不存在或证据已变化", 409)

    @staticmethod
    def _validate_route(route: TenantRoutingDecisionRecord) -> None:
        if route.status != "completed" or route.score is None or not route.evidence_hash or not route.result_hash:
            raise TenantRolloutError("OUTCOME_ROUTE_INCOMPLETE", "只有已完成且证据封印完整的历史路由可以绑定结果标签", 409)
        if content_hash(route.selected_assets_json) != route.selected_assets_hash:
            raise TenantRolloutError("OUTCOME_ROUTE_DRIFTED", "历史路由或冻结资产的完整性校验失败", 409)

    @classmethod
    def _arm_metrics(cls, rows: list[TenantOutcomeLabelRecord], config: dict) -> dict:
        events = sum(row.observed_event for row in rows)
        non_events = len(rows) - events
        enough_classes = events >= config["min_events"] and non_events >= config["min_non_events"]
        reliable_sample = len(rows) >= config["min_reliable_samples_per_arm"]
        risks = [(float(row.risk_score), bool(row.observed_event)) for row in rows]
        loss_rows = [row for row in rows if row.loss_amount is not None and row.exposure_amount is not None]
        total_loss = sum((Decimal(row.loss_amount) for row in loss_rows), Decimal("0"))
        total_exposure = sum((Decimal(row.exposure_amount) for row in loss_rows), Decimal("0"))
        loss_rate = float(total_loss / total_exposure) if total_exposure > 0 else None
        loss_ratios = [float(Decimal(row.loss_amount) / Decimal(row.exposure_amount)) for row in loss_rows if Decimal(row.exposure_amount) > 0]
        reliability_reasons = []
        if not reliable_sample:
            reliability_reasons.append(f"样本量 {len(rows)} 低于每侧可靠性门槛 {config['min_reliable_samples_per_arm']}")
        if not enough_classes:
            reliability_reasons.append("事件或非事件样本未达到监督区分度门槛")
        if len(loss_rows) != len(rows):
            reliability_reasons.append("部分样本缺少损失金额或风险暴露")
        threshold = config["high_risk_threshold"]
        confusion = {
            "true_positive": sum(event and risk >= threshold for risk, event in risks),
            "false_positive": sum(not event and risk >= threshold for risk, event in risks),
            "true_negative": sum(not event and risk < threshold for risk, event in risks),
            "false_negative": sum(event and risk < threshold for risk, event in risks),
            "threshold": threshold,
        }
        return {
            "sample_count": len(rows), "event_count": events, "non_event_count": non_events,
            "event_rate": round(events / len(rows), 6) if rows else None,
            "event_rate_confidence_interval": cls._wilson_interval(events, len(rows)),
            "auc": cls._auc(risks) if enough_classes else None,
            "ks": cls._ks(risks) if enough_classes else None,
            "auc_confidence_interval": cls._bootstrap_metric_interval(rows, "auc", config) if enough_classes else None,
            "ks_confidence_interval": cls._bootstrap_metric_interval(rows, "ks", config) if enough_classes else None,
            "bootstrap_resamples": config["bootstrap_resamples"],
            "bootstrap_method": "stratified_percentile" if enough_classes else None,
            "confusion_matrix": confusion,
            "average_score": round(sum(float(row.predicted_score) for row in rows) / len(rows), 4) if rows else None,
            "observed_loss_count": len(loss_rows),
            "total_loss_amount": round(float(total_loss), 2),
            "total_exposure_amount": round(float(total_exposure), 2),
            "loss_rate": round(loss_rate, 6) if loss_rate is not None else None,
            "loss_rate_confidence_interval": cls._normal_interval(loss_ratios),
            "average_loss_amount": round(float(total_loss) / len(loss_rows), 2) if loss_rows else None,
            "segments": cls._segments(rows),
            "segment_stability": cls._segment_stability(rows, config),
            "stability_trend": cls._stability_trend(rows, config),
            "metrics_ready": enough_classes,
            "statistical_reliability": "statistically_reliable" if reliable_sample and enough_classes else "directional",
            "reliability_reasons": reliability_reasons,
        }

    @staticmethod
    def _wilson_interval(events: int, sample_count: int) -> dict | None:
        if sample_count == 0:
            return None
        z = 1.959963984540054
        rate = events / sample_count
        denominator = 1 + z * z / sample_count
        center = (rate + z * z / (2 * sample_count)) / denominator
        margin = z * math.sqrt(rate * (1 - rate) / sample_count + z * z / (4 * sample_count * sample_count)) / denominator
        return {"lower": round(max(0.0, center - margin), 6), "upper": round(min(1.0, center + margin), 6), "confidence": 0.95, "method": "wilson"}

    @staticmethod
    def _normal_interval(values: list[float]) -> dict | None:
        if not values:
            return None
        mean = sum(values) / len(values)
        if len(values) == 1:
            return {"lower": round(mean, 6), "upper": round(mean, 6), "confidence": 0.95, "method": "single_observation"}
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        margin = 1.959963984540054 * math.sqrt(variance / len(values))
        return {"lower": round(max(0.0, mean - margin), 6), "upper": round(min(1.0, mean + margin), 6), "confidence": 0.95, "method": "normal_approximation"}

    @staticmethod
    def _auc(values: list[tuple[float, bool]]) -> float:
        bad = [score for score, event in values if event]
        good = [score for score, event in values if not event]
        wins = sum(1 if left > right else 0.5 if left == right else 0 for left in bad for right in good)
        return round(wins / (len(bad) * len(good)), 6)

    @staticmethod
    def _ks(values: list[tuple[float, bool]]) -> float:
        bad_total = sum(event for _, event in values)
        good_total = len(values) - bad_total
        maximum = 0.0
        for threshold in sorted({score for score, _ in values}):
            bad_cdf = sum(event and score <= threshold for score, event in values) / bad_total
            good_cdf = sum((not event) and score <= threshold for score, event in values) / good_total
            maximum = max(maximum, abs(bad_cdf - good_cdf))
        return round(maximum, 6)

    @staticmethod
    def _segments(rows: list[TenantOutcomeLabelRecord]) -> list[dict]:
        segments = []
        for dimension, accessor in (("rating", lambda row: row.rating or "unknown"), ("admission", lambda row: row.admission or "unknown")):
            for value in sorted({accessor(row) for row in rows}):
                selected = [row for row in rows if accessor(row) == value]
                event_count = sum(row.observed_event for row in selected)
                segments.append({
                    "dimension": dimension, "value": value, "sample_count": len(selected),
                    "event_count": event_count, "event_rate": round(event_count / len(selected), 6),
                    "average_score": round(sum(float(row.predicted_score) for row in selected) / len(selected), 4),
                })
        return segments

    @staticmethod
    def _comparison(metrics: dict, arm_rows: dict[str, list[TenantOutcomeLabelRecord]], config: dict) -> dict:
        champion, challenger = metrics["champion"], metrics["challenger"]
        reliable = all(item["statistical_reliability"] == "statistically_reliable" for item in (champion, challenger))
        auc_difference_interval = TenantOutcomeRepository._bootstrap_difference_interval(arm_rows, "auc", config)
        ks_difference_interval = TenantOutcomeRepository._bootstrap_difference_interval(arm_rows, "ks", config)
        auc_signal = TenantOutcomeRepository._difference_signal(auc_difference_interval)
        ks_signal = TenantOutcomeRepository._difference_signal(ks_difference_interval)
        return {
            "auc_delta": round(challenger["auc"] - champion["auc"], 6),
            "ks_delta": round(challenger["ks"] - champion["ks"], 6),
            "event_rate_delta": round(challenger["event_rate"] - champion["event_rate"], 6),
            "loss_rate_delta": round(challenger["loss_rate"] - champion["loss_rate"], 6) if champion["loss_rate"] is not None and challenger["loss_rate"] is not None else None,
            "auc_difference_confidence_interval": auc_difference_interval,
            "ks_difference_confidence_interval": ks_difference_interval,
            "auc_difference_signal": auc_signal,
            "ks_difference_signal": ks_signal,
            "confidence_interval_overlap": {
                "auc": TenantOutcomeRepository._intervals_overlap(champion.get("auc_confidence_interval"), challenger.get("auc_confidence_interval")),
                "ks": TenantOutcomeRepository._intervals_overlap(champion.get("ks_confidence_interval"), challenger.get("ks_confidence_interval")),
            },
            "stability_summary": TenantOutcomeRepository._comparison_stability_summary(metrics),
            "promotion_readiness": "ready" if reliable else "directional_only",
            "reliability_reasons": champion["reliability_reasons"] + challenger["reliability_reasons"],
            "conclusion": "Challenger 监督区分度更优" if challenger["auc"] >= champion["auc"] and challenger["ks"] >= champion["ks"] else "Challenger 尚未同时改善 AUC 与 KS",
        }

    @classmethod
    def _bootstrap_metric_interval(cls, rows: list[TenantOutcomeLabelRecord], metric: str, config: dict) -> dict | None:
        """Calculate a deterministic stratified bootstrap interval from the frozen labels.

        Stratification keeps both observed classes present in every resample. This is
        deliberately reported as directional when the configured arm sample gate is
        not met; the interval itself never upgrades a small sample into approval.
        """
        events = [row for row in rows if row.observed_event]
        non_events = [row for row in rows if not row.observed_event]
        if not events or not non_events:
            return None
        resamples = int(config["bootstrap_resamples"])
        seed = cls._bootstrap_seed(rows, metric)
        rng = random.Random(seed)
        values = []
        for _ in range(resamples):
            sampled = [events[rng.randrange(len(events))] for _ in events]
            sampled.extend(non_events[rng.randrange(len(non_events))] for _ in non_events)
            risks = [(float(row.risk_score), bool(row.observed_event)) for row in sampled]
            values.append(cls._auc(risks) if metric == "auc" else cls._ks(risks))
        return cls._bootstrap_result(values, resamples, seed)

    @classmethod
    def _bootstrap_difference_interval(cls, arm_rows: dict[str, list[TenantOutcomeLabelRecord]], metric: str, config: dict) -> dict | None:
        champion = arm_rows["champion"]
        challenger = arm_rows["challenger"]
        champion_events = [row for row in champion if row.observed_event]
        champion_non_events = [row for row in champion if not row.observed_event]
        challenger_events = [row for row in challenger if row.observed_event]
        challenger_non_events = [row for row in challenger if not row.observed_event]
        if not champion_events or not champion_non_events or not challenger_events or not challenger_non_events:
            return None
        resamples = int(config["bootstrap_resamples"])
        seed = cls._bootstrap_seed(champion + challenger, f"difference:{metric}")
        rng = random.Random(seed)
        values = []
        for _ in range(resamples):
            champion_sample = [champion_events[rng.randrange(len(champion_events))] for _ in champion_events]
            champion_sample.extend(champion_non_events[rng.randrange(len(champion_non_events))] for _ in champion_non_events)
            challenger_sample = [challenger_events[rng.randrange(len(challenger_events))] for _ in challenger_events]
            challenger_sample.extend(challenger_non_events[rng.randrange(len(challenger_non_events))] for _ in challenger_non_events)
            champion_values = [(float(row.risk_score), bool(row.observed_event)) for row in champion_sample]
            challenger_values = [(float(row.risk_score), bool(row.observed_event)) for row in challenger_sample]
            calculate = cls._auc if metric == "auc" else cls._ks
            values.append(calculate(challenger_values) - calculate(champion_values))
        return cls._bootstrap_result(values, resamples, seed)

    @staticmethod
    def _bootstrap_seed(rows: list[TenantOutcomeLabelRecord], metric: str) -> int:
        material = "|".join(sorted(f"{getattr(row, 'id', '')}:{getattr(row, 'evidence_hash', '')}" for row in rows))
        digest = hashlib.sha256(f"{metric}|{material}".encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    @staticmethod
    def _bootstrap_result(values: list[float], resamples: int, seed: int) -> dict | None:
        if not values:
            return None
        ordered = sorted(values)
        def percentile(fraction: float) -> float:
            position = (len(ordered) - 1) * fraction
            lower = math.floor(position)
            upper = math.ceil(position)
            if lower == upper:
                return ordered[lower]
            return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        return {
            "lower": round(percentile(0.025), 6), "upper": round(percentile(0.975), 6),
            "confidence": 0.95, "method": "stratified_bootstrap_percentile",
            "resamples": resamples, "valid_resamples": len(values), "seed": f"{seed:016x}"[:16],
        }

    @staticmethod
    def _difference_signal(interval: dict | None) -> str:
        if interval is None:
            return "not_evaluable"
        if interval["lower"] > 0:
            return "significant_challenger_better"
        if interval["upper"] < 0:
            return "significant_champion_better"
        return "directional_only"

    @staticmethod
    def _intervals_overlap(left: dict | None, right: dict | None) -> bool | None:
        if not left or not right:
            return None
        return max(left["lower"], right["lower"]) <= min(left["upper"], right["upper"])

    @classmethod
    def _stability_trend(cls, rows: list[TenantOutcomeLabelRecord], config: dict) -> dict:
        periods: dict[str, list[TenantOutcomeLabelRecord]] = {}
        for row in rows:
            period = cls._as_utc(row.observation_end).strftime("%Y-%m")
            periods.setdefault(period, []).append(row)
        snapshots = []
        for period in sorted(periods):
            selected = periods[period]
            risks = [(float(row.risk_score), bool(row.observed_event)) for row in selected]
            events = sum(row.observed_event for row in selected)
            enough_classes = any(row.observed_event for row in selected) and any(not row.observed_event for row in selected)
            snapshots.append({
                "period": period, "sample_count": len(selected), "event_count": events,
                "event_rate": round(events / len(selected), 6),
                "auc": cls._auc(risks) if enough_classes else None,
                "ks": cls._ks(risks) if enough_classes else None,
                "metrics_ready": enough_classes and len(selected) >= config["min_reliable_samples_per_arm"],
            })
        if len(snapshots) < 2:
            direction = "insufficient_periods"
            delta = None
        else:
            delta = round(snapshots[-1]["event_rate"] - snapshots[0]["event_rate"], 6)
            direction = "increasing" if delta > 0.05 else "decreasing" if delta < -0.05 else "stable"
        return {"granularity": "month", "periods": snapshots, "period_count": len(snapshots), "event_rate_delta": delta, "direction": direction}

    @classmethod
    def _segment_stability(cls, rows: list[TenantOutcomeLabelRecord], config: dict) -> dict:
        dimensions = {}
        for dimension in ("rating", "admission"):
            groups = [item for item in cls._segments(rows) if item["dimension"] == dimension]
            rates = [item["event_rate"] for item in groups]
            scores = [item["average_score"] for item in groups]
            dimensions[dimension] = {
                "group_count": len(groups), "min_group_sample_count": min((item["sample_count"] for item in groups), default=0),
                "max_event_rate_gap": round(max(rates) - min(rates), 6) if rates else None,
                "max_average_score_gap": round(max(scores) - min(scores), 4) if scores else None,
                "reliability": "statistically_reliable" if groups and min(item["sample_count"] for item in groups) >= config["min_reliable_samples_per_arm"] else "directional",
            }
        return {
            "dimensions": dimensions,
            "fairness_audit": "not_evaluable",
            "fairness_reason": "当前标签未绑定受保护属性或公平性分组，以上仅为业务分群稳定性，不构成公平性结论。",
        }

    @staticmethod
    def _comparison_stability_summary(metrics: dict) -> dict:
        trends = {arm: metrics[arm].get("stability_trend") for arm in ("champion", "challenger")}
        directions = {arm: (trend or {}).get("direction") for arm, trend in trends.items()}
        return {"arms": trends, "direction_alignment": "aligned" if directions["champion"] == directions["challenger"] else "divergent"}

    @staticmethod
    def _degraded_reason(coverage: dict, config: dict, metrics: dict) -> str:
        if coverage["mature_count"] < config["min_mature_samples"]:
            return f"成熟且已核验标签不足：当前 {coverage['mature_count']}，至少需要 {config['min_mature_samples']}"
        incomplete = [arm for arm in ("champion", "challenger") if not metrics[arm]["metrics_ready"]]
        return f"{', '.join(incomplete)} 缺少足量事件或非事件样本，KS/AUC 保持为空"

    @staticmethod
    def _canonical_label_payload(payload: dict) -> dict:
        return {
            "source": payload["source"], "external_label_id": payload["external_label_id"],
            "routing_decision_id": payload["routing_decision_id"], "counterparty_id": payload["counterparty_id"],
            "label_definition": payload["label_definition"], "observed_event": payload["observed_event"],
            "label_definition_id": payload.get("label_definition_id"),
            "label_definition_version": payload.get("label_definition_version"),
            "label_definition_hash": payload.get("label_definition_hash"),
            "observation_end": TenantOutcomeRepository._as_utc(payload["observation_end"]).isoformat(),
            "loss_amount": TenantOutcomeRepository._decimal_text(payload.get("loss_amount")),
            "exposure_amount": TenantOutcomeRepository._decimal_text(payload.get("exposure_amount")),
            "evidence_reference": payload["evidence_reference"],
        }

    @classmethod
    def _canonical_evidence_payload(cls, *, tenant_id: str, policy_id: str, routing_decision_id: str,
                                     decision_execution_id: str | None, source: str, external_label_id: str,
                                     counterparty_id: str, label_definition: str, label_definition_id: str,
                                     label_definition_version: int, label_definition_hash: str,
                                     observed_event: bool, observation_end: datetime, loss_amount,
                                     exposure_amount, evidence_reference: str, selected_arm: str,
                                     model_key: str, model_version: str, predicted_score, risk_score,
                                     routing_evidence_hash: str, execution_evidence_hash: str | None,
                                     selected_assets_hash: str, import_batch_id: str | None = None,
                                     supersedes_label_id: str | None = None,
                                     correction_reason: str | None = None) -> dict:
        payload = {
            "schema_version": "tenant-outcome-label-v4",
            "tenant_id": tenant_id, "policy_id": policy_id,
            "routing_decision_id": routing_decision_id, "decision_execution_id": decision_execution_id,
            "source": source, "external_label_id": external_label_id, "counterparty_id": counterparty_id,
            "label_definition": label_definition, "label_definition_id": label_definition_id,
            "label_definition_version": label_definition_version, "label_definition_hash": label_definition_hash,
            "observed_event": bool(observed_event), "observation_end": cls._as_utc(observation_end).isoformat(),
            "loss_amount": cls._fixed_decimal_text(loss_amount, 2),
            "exposure_amount": cls._fixed_decimal_text(exposure_amount, 2),
            "evidence_reference": evidence_reference, "selected_arm": selected_arm,
            "model_key": model_key, "model_version": model_version,
            "predicted_score": cls._fixed_decimal_text(predicted_score, 4),
            "risk_score": cls._fixed_decimal_text(risk_score, 6),
            "routing_evidence_hash": routing_evidence_hash,
            "execution_evidence_hash": execution_evidence_hash,
            "selected_assets_hash": selected_assets_hash,
        }
        if import_batch_id or supersedes_label_id:
            payload.update({"import_batch_id": import_batch_id, "supersedes_label_id": supersedes_label_id,
                            "correction_reason": correction_reason})
        return payload

    @staticmethod
    def _canonical_import_payload(payload: dict) -> dict:
        return {
            "import_key": payload["import_key"],
            "source": payload["source"],
            "label_definition": payload["label_definition"],
            "label_definition_id": payload.get("label_definition_id"),
            "label_definition_version": payload.get("label_definition_version"),
            "label_definition_hash": payload.get("label_definition_hash"),
            "expected_count": payload["expected_count"],
            "outcomes": [TenantOutcomeRepository._canonical_label_payload({
                **row,
                "source": payload["source"],
                "label_definition": payload["label_definition"],
                "label_definition_id": payload.get("label_definition_id"),
                "label_definition_version": payload.get("label_definition_version"),
                "label_definition_hash": payload.get("label_definition_hash"),
            }) for row in payload["outcomes"]],
        }

    @staticmethod
    def _decimal_text(value) -> str | None:
        return str(Decimal(str(value))) if value is not None else None

    @staticmethod
    def _fixed_decimal_text(value, places: int) -> str | None:
        if value is None:
            return None
        quantum = Decimal(1).scaleb(-places)
        return format(Decimal(str(value)).quantize(quantum), f".{places}f")

    @staticmethod
    def _definition_config(payload: dict, version: int) -> dict:
        return {
            "code": payload["code"], "version": version, "name": payload["name"],
            "description": payload["description"], "event_type": payload["event_type"],
            "event_threshold": deepcopy(payload["event_threshold"]),
            "observation_window_days": payload["observation_window_days"],
            "maturity_grace_days": payload["maturity_grace_days"],
            "source_priorities": deepcopy(payload["source_priorities"]),
            "applicable_model_keys": list(payload["applicable_model_keys"]),
            "require_loss_amount": payload["require_loss_amount"],
            "require_exposure_amount": payload["require_exposure_amount"],
        }

    @classmethod
    def _definition_config_from_record(cls, record: TenantOutcomeLabelDefinitionRecord) -> dict:
        return cls._definition_config({
            "code": record.code, "name": record.name, "description": record.description,
            "event_type": record.event_type, "event_threshold": record.event_threshold_json,
            "observation_window_days": record.observation_window_days,
            "maturity_grace_days": record.maturity_grace_days,
            "source_priorities": record.source_priorities_json,
            "applicable_model_keys": record.applicable_model_keys_json,
            "require_loss_amount": record.require_loss_amount,
            "require_exposure_amount": record.require_exposure_amount,
        }, record.version)

    def _definition(self, tenant_id: str, definition_id: str) -> TenantOutcomeLabelDefinitionRecord:
        record = self.session.scalar(select(TenantOutcomeLabelDefinitionRecord).where(
            TenantOutcomeLabelDefinitionRecord.id == definition_id,
            TenantOutcomeLabelDefinitionRecord.tenant_id == tenant_id,
        ))
        if record is None:
            raise TenantRolloutError("LABEL_DEFINITION_NOT_FOUND", "标签口径不存在", 404)
        return record

    def _published_definition(self, tenant_id: str, definition_id: str) -> TenantOutcomeLabelDefinitionRecord:
        record = self._definition(tenant_id, definition_id)
        if record.status != "published" or not record.is_active:
            raise TenantRolloutError("LABEL_DEFINITION_NOT_PUBLISHED", "结果标签只能引用当前已发布口径", 422)
        self._verify_definition_integrity(record)
        return record

    def _published_definition_by_code(self, tenant_id: str, code: str) -> TenantOutcomeLabelDefinitionRecord:
        record = self.session.scalar(select(TenantOutcomeLabelDefinitionRecord).where(
            TenantOutcomeLabelDefinitionRecord.tenant_id == tenant_id,
            TenantOutcomeLabelDefinitionRecord.code == code,
            TenantOutcomeLabelDefinitionRecord.status == "published",
            TenantOutcomeLabelDefinitionRecord.is_active.is_(True),
        ))
        if record is None:
            raise TenantRolloutError("LABEL_DEFINITION_NOT_PUBLISHED", "历史标签冲正需要存在同代码的当前已发布口径", 422)
        self._verify_definition_integrity(record)
        return record

    @classmethod
    def _verify_definition_integrity(cls, record: TenantOutcomeLabelDefinitionRecord) -> None:
        if content_hash(cls._definition_config_from_record(record)) != record.config_hash:
            raise TenantRolloutError("LABEL_DEFINITION_DRIFTED", "标签口径配置完整性校验失败", 409)

    @staticmethod
    def _check_definition_version(record: TenantOutcomeLabelDefinitionRecord, expected: int) -> None:
        if record.row_version != expected:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"标签口径版本已变化，当前版本为 {record.row_version}", 409)

    def _commit_definition(self, record: TenantOutcomeLabelDefinitionRecord, event_type: str, principal: "Principal", payload: dict) -> dict:
        try:
            self.session.flush()
            self.audit.append("tenant_outcome_label_definition", record.id, event_type, principal.subject, {
                "tenant_id": record.tenant_id, "code": record.code, "version": record.version,
                "status": record.status, "config_hash": record.config_hash, **payload,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("LABEL_DEFINITION_CONFLICT", "标签口径写入发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._definition_view(record)

    @staticmethod
    def _assert_source_allowed(definition: TenantOutcomeLabelDefinitionRecord, source: str) -> None:
        sources = {str(item.get("source") or "") for item in definition.source_priorities_json or []}
        if source not in sources:
            raise TenantRolloutError("OUTCOME_SOURCE_NOT_ALLOWED", "结果来源不在标签口径允许的来源清单中", 422, {"allowed_sources": sorted(sources)})

    @classmethod
    def _assert_definition_applicable(cls, definition: TenantOutcomeLabelDefinitionRecord, source: str, model_key: str, payload: dict) -> None:
        cls._assert_source_allowed(definition, source)
        if model_key not in set(definition.applicable_model_keys_json or []):
            raise TenantRolloutError("OUTCOME_MODEL_NOT_APPLICABLE", "标签口径不适用于历史路由的模型", 422, {"model_key": model_key})
        if definition.require_loss_amount and payload.get("loss_amount") is None:
            raise TenantRolloutError("OUTCOME_LOSS_REQUIRED", "该标签口径要求提供损失金额", 422)
        if definition.require_exposure_amount and payload.get("exposure_amount") is None:
            raise TenantRolloutError("OUTCOME_EXPOSURE_REQUIRED", "该标签口径要求提供风险暴露金额", 422)

    @classmethod
    def _definition_view(cls, record: TenantOutcomeLabelDefinitionRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "code": record.code,
            "version": record.version, "name": record.name, "description": record.description,
            "event_type": record.event_type, "event_threshold": deepcopy(record.event_threshold_json),
            "observation_window_days": record.observation_window_days,
            "maturity_grace_days": record.maturity_grace_days,
            "source_priorities": deepcopy(record.source_priorities_json),
            "applicable_model_keys": list(record.applicable_model_keys_json or []),
            "require_loss_amount": record.require_loss_amount,
            "require_exposure_amount": record.require_exposure_amount,
            "status": record.status, "is_active": record.is_active,
            "config_hash": record.config_hash, "submitted_by": record.submitted_by,
            "submitted_by_name": record.submitted_by_name, "submitted_at": cls._iso(record.submitted_at),
            "reviewed_by": record.reviewed_by, "reviewed_by_name": record.reviewed_by_name,
            "reviewed_at": cls._iso(record.reviewed_at), "review_comment": record.review_comment,
            "row_version": record.row_version, "created_by": record.created_by,
            "created_by_name": record.created_by_name, "created_at": cls._iso(record.created_at),
            "updated_at": cls._iso(record.updated_at),
        }

    @classmethod
    def _upgrade_view(cls, record: TenantSupervisedUpgradeDecisionRecord, governance_repository) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "evaluation_id": record.evaluation_id, "decision": record.decision, "status": record.status,
            "evidence_hash": record.evidence_hash, "model_change_id": record.model_change_id,
            "candidate_version": record.candidate_version,
            "model_change": governance_repository.get_change(record.model_change_id) if record.model_change_id else None,
            "auto_submitted": False, "auto_published": False, "traffic_changed": False,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "created_at": cls._iso(record.created_at),
        }

    def _policy(self, tenant_id: str, policy_id: str) -> TenantRolloutPolicyRecord:
        record = self.session.scalar(select(TenantRolloutPolicyRecord).where(
            TenantRolloutPolicyRecord.tenant_id == tenant_id,
            TenantRolloutPolicyRecord.id == policy_id,
        ))
        if record is None:
            raise TenantRolloutError("ROLLOUT_NOT_FOUND", "灰度策略不存在", 404)
        return record

    def _monitoring_run(self, tenant_id: str, policy_id: str, run_id: str) -> TenantMonitoringRunRecord:
        self._policy(tenant_id, policy_id)
        record = self.session.scalar(select(TenantMonitoringRunRecord).where(
            TenantMonitoringRunRecord.id == run_id,
            TenantMonitoringRunRecord.tenant_id == tenant_id,
            TenantMonitoringRunRecord.policy_id == policy_id,
        ))
        if record is None:
            raise TenantRolloutError("TENANT_MONITORING_RUN_NOT_FOUND", "当前租户和灰度策略下不存在该监控运行", 404)
        return record

    def _monitoring_diff_case(self, tenant_id: str, policy_id: str, case_id: str) -> TenantMonitoringDiffCaseRecord:
        self._policy(tenant_id, policy_id)
        record = self.session.scalar(select(TenantMonitoringDiffCaseRecord).where(
            TenantMonitoringDiffCaseRecord.id == case_id,
            TenantMonitoringDiffCaseRecord.tenant_id == tenant_id,
            TenantMonitoringDiffCaseRecord.policy_id == policy_id,
        ))
        if record is None:
            raise TenantRolloutError("MONITORING_DIFF_CASE_NOT_FOUND", "当前租户和灰度策略下不存在该差异工单", 404)
        return record

    @staticmethod
    def _check_monitoring_diff_case_version(record: TenantMonitoringDiffCaseRecord, expected: int) -> None:
        if record.row_version != expected:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"差异工单版本已变化，当前版本为 {record.row_version}", 409)

    def _verify_monitoring_diff_case_integrity(self, record: TenantMonitoringDiffCaseRecord) -> None:
        current = self.monitoring_run_diff(record.tenant_id, record.policy_id, record.base_run_id, record.against_run_id)
        if (
            current["base_evidence_hash"] != record.base_evidence_hash
            or current["against_evidence_hash"] != record.against_evidence_hash
            or current["diff_hash"] != record.diff_hash
            or current["comparison"] != (record.comparison_json or {})
        ):
            raise TenantRolloutError("MONITORING_DIFF_CASE_EVIDENCE_DRIFTED", "差异工单冻结证据与当前快照不一致", 409)
        if record.recomputed_run_id and record.recomputed_diff_hash:
            recomputed = self.monitoring_run_diff(
                record.tenant_id, record.policy_id, record.recomputed_run_id, record.against_run_id,
            )
            if recomputed["diff_hash"] != record.recomputed_diff_hash:
                raise TenantRolloutError("MONITORING_DIFF_CASE_EVIDENCE_DRIFTED", "重算差异证据完整性校验失败", 409)

    def _commit_monitoring_diff_case(
        self, record: TenantMonitoringDiffCaseRecord, event_type: str, principal: "Principal", payload: dict,
    ) -> dict:
        try:
            self.session.flush()
            self.audit.append("tenant_monitoring_diff_case", record.id, event_type, principal.subject, {
                "tenant_id": record.tenant_id, "policy_id": record.policy_id,
                "status": record.status, "row_version": record.row_version, **payload,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("ROW_VERSION_CONFLICT", "差异工单治理发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._monitoring_diff_case_view(record)

    @staticmethod
    def _check_monitoring_run_version(record: TenantMonitoringRunRecord, expected: int) -> None:
        if record.row_version != expected:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"监控快照版本已变化，当前版本为 {record.row_version}", 409)

    @classmethod
    def _verify_monitoring_run_integrity(cls, record: TenantMonitoringRunRecord) -> None:
        if cls.monitoring_run_evidence_hash(record) != record.evidence_hash:
            raise TenantRolloutError("TENANT_MONITORING_EVIDENCE_DRIFTED", "租户监控运行快照完整性校验失败", 409)

    def _commit_monitoring_run(self, record: TenantMonitoringRunRecord, event_type: str, principal: "Principal", payload: dict) -> dict:
        try:
            self.session.flush()
            self.audit.append("tenant_monitoring_run", record.id, event_type, principal.subject, {
                "tenant_id": record.tenant_id, "policy_id": record.policy_id,
                "run_key": record.run_key, "governance_status": record.governance_status,
                **payload,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("ROW_VERSION_CONFLICT", "监控快照治理发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return {**self._monitoring_run_view(record), "idempotent": False}

    @classmethod
    def _diff_values(cls, before, after, path: str = "") -> dict:
        if isinstance(before, dict) and isinstance(after, dict):
            keys = sorted(set(before) | set(after))
            return {key: cls._diff_values(before.get(key), after.get(key), f"{path}.{key}".strip(".")) for key in keys if before.get(key) != after.get(key)}
        if isinstance(before, (int, float)) and isinstance(after, (int, float)) and not isinstance(before, bool) and not isinstance(after, bool):
            return {"before": before, "after": after, "delta": after - before}
        if before != after:
            return {"before": before, "after": after}
        return {}

    @classmethod
    def _monitoring_run_evidence_payload(
        cls,
        tenant_id: str,
        policy_id: str,
        run_key: str,
        model_key: str,
        model_version: str,
        observed_from: datetime,
        observed_to: datetime,
        dataset_id: str,
        evidence_level: str,
        status: str,
        definition: TenantOutcomeLabelDefinitionRecord | None,
        watermark: dict,
        monitoring: dict,
    ) -> dict:
        return {
            "schema_version": "tenant-monitoring-run-v1",
            "tenant_id": tenant_id,
            "policy_id": policy_id,
            "run_key": run_key,
            "model_key": model_key,
            "model_version": model_version,
            "observed_from": cls._iso(observed_from),
            "observed_to": cls._iso(observed_to),
            "dataset_id": dataset_id,
            "evidence_level": evidence_level,
            "status": status,
            "label_definition_id": definition.id if definition else None,
            "label_definition_version": definition.version if definition else None,
            "label_definition_hash": definition.config_hash if definition else None,
            "label_watermark": deepcopy(watermark),
            "monitoring": deepcopy(monitoring),
        }

    @classmethod
    def monitoring_run_evidence_hash(cls, record: TenantMonitoringRunRecord) -> str:
        # The persisted definition fields are already part of the canonical payload;
        # avoid re-reading mutable definition state when checking the run itself.
        payload = {
            "schema_version": "tenant-monitoring-run-v1",
            "tenant_id": record.tenant_id,
            "policy_id": record.policy_id,
            "run_key": record.run_key,
            "model_key": record.model_key,
            "model_version": record.model_version,
            "observed_from": cls._iso(record.observed_from),
            "observed_to": cls._iso(record.observed_to),
            "dataset_id": record.dataset_id,
            "evidence_level": record.evidence_level,
            "status": record.status,
            "label_definition_id": record.label_definition_id,
            "label_definition_version": record.label_definition_version,
            "label_definition_hash": record.label_definition_hash,
            "label_watermark": deepcopy(record.label_watermark_json or {}),
            "monitoring": deepcopy(record.monitoring_json or {}),
        }
        return content_hash(payload)

    @classmethod
    def _monitoring_run_view(cls, record: TenantMonitoringRunRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "run_key": record.run_key, "model_key": record.model_key, "model_version": record.model_version,
            "observed_from": cls._iso(record.observed_from), "observed_to": cls._iso(record.observed_to),
            "dataset_id": record.dataset_id, "evidence_level": record.evidence_level, "status": record.status,
            "governance_status": record.governance_status,
            "label_definition_id": record.label_definition_id,
            "label_definition_version": record.label_definition_version,
            "label_definition_hash": record.label_definition_hash,
            "label_watermark": deepcopy(record.label_watermark_json or {}),
            "monitoring": deepcopy(record.monitoring_json or {}),
            "evidence_hash": record.evidence_hash, "submitted_by": record.submitted_by,
            "submitted_by_name": record.submitted_by_name, "submitted_at": cls._iso(record.submitted_at),
            "reviewed_by": record.reviewed_by, "reviewed_by_name": record.reviewed_by_name,
            "reviewed_at": cls._iso(record.reviewed_at), "review_comment": record.review_comment,
            "retracted_by": record.retracted_by, "retracted_by_name": record.retracted_by_name,
            "retracted_at": cls._iso(record.retracted_at), "retraction_reason": record.retraction_reason,
            "row_version": record.row_version, "evidence_hash": record.evidence_hash, "created_by": record.created_by,
            "created_by_name": record.created_by_name, "created_at": cls._iso(record.created_at),
        }

    @classmethod
    def _monitoring_diff_case_view(cls, record: TenantMonitoringDiffCaseRecord) -> dict:
        due_at = cls._as_utc(record.due_at)
        return {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "base_run_id": record.base_run_id, "against_run_id": record.against_run_id,
            "base_evidence_hash": record.base_evidence_hash,
            "against_evidence_hash": record.against_evidence_hash,
            "diff_hash": record.diff_hash, "comparison": deepcopy(record.comparison_json or {}),
            "status": record.status, "severity": record.severity, "reason": record.reason,
            "assigned_role": record.assigned_role, "assigned_to": record.assigned_to,
            "assigned_to_name": record.assigned_to_name, "due_at": cls._iso(due_at),
            "overdue": record.status not in {"resolved", "rejected"} and due_at <= cls._now(),
            "recompute_status": record.recompute_status, "recomputed_run_id": record.recomputed_run_id,
            "recomputed_diff_hash": record.recomputed_diff_hash, "recomputed_by": record.recomputed_by,
            "recomputed_by_name": record.recomputed_by_name, "recomputed_at": cls._iso(record.recomputed_at),
            "recompute_error": record.recompute_error, "disposition": record.disposition,
            "conclusion": record.conclusion, "resolved_by": record.resolved_by,
            "resolved_by_name": record.resolved_by_name, "resolved_at": cls._iso(record.resolved_at),
            "row_version": record.row_version, "created_by": record.created_by,
            "created_by_name": record.created_by_name, "created_at": cls._iso(record.created_at),
            "updated_at": cls._iso(record.updated_at),
        }

    def _evaluation(self, tenant_id: str, policy_id: str, evaluation_id: str) -> TenantSupervisedEvaluationRecord:
        self._policy(tenant_id, policy_id)
        record = self.session.scalar(select(TenantSupervisedEvaluationRecord).where(
            TenantSupervisedEvaluationRecord.id == evaluation_id,
            TenantSupervisedEvaluationRecord.tenant_id == tenant_id,
            TenantSupervisedEvaluationRecord.policy_id == policy_id,
        ))
        if record is None:
            raise TenantRolloutError("SUPERVISED_EVALUATION_NOT_FOUND", "监督评估不存在", 404)
        return record

    @classmethod
    def _import_view(cls, record: TenantOutcomeImportBatchRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "import_key": record.import_key, "source": record.source,
            "label_definition": record.label_definition, "expected_count": record.expected_count,
            "label_definition_id": record.label_definition_id,
            "label_definition_version": record.label_definition_version,
            "label_definition_hash": record.label_definition_hash,
            "received_count": record.received_count, "created_count": record.created_count,
            "idempotent_count": record.idempotent_count, "rejected_count": record.rejected_count,
            "corrected_count": record.corrected_count, "payload_hash": record.payload_hash,
            "results": deepcopy(record.results_json), "status": record.status,
            "evidence_hash": record.evidence_hash, "created_by": record.created_by,
            "created_by_name": record.created_by_name, "completed_at": cls._iso(record.completed_at),
            "created_at": cls._iso(record.created_at),
        }

    @classmethod
    def _label_view(cls, record: TenantOutcomeLabelRecord, now: datetime) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "routing_decision_id": record.routing_decision_id, "decision_execution_id": record.decision_execution_id,
            "source": record.source, "external_label_id": record.external_label_id,
            "counterparty_id": record.counterparty_id, "label_definition": record.label_definition,
            "label_definition_id": record.label_definition_id,
            "label_definition_version": record.label_definition_version,
            "label_definition_hash": record.label_definition_hash,
            "observed_event": record.observed_event, "observation_end": cls._iso(record.observation_end),
            "maturity_status": "mature" if cls._as_utc(record.observation_end) <= now else "immature",
            "loss_amount": float(record.loss_amount) if record.loss_amount is not None else None,
            "exposure_amount": float(record.exposure_amount) if record.exposure_amount is not None else None,
            "evidence_reference": record.evidence_reference, "link_status": record.link_status,
            "selected_arm": record.selected_arm, "model_key": record.model_key, "model_version": record.model_version,
            "predicted_score": float(record.predicted_score), "risk_score": float(record.risk_score),
            "rating": record.rating, "admission": record.admission,
            "routing_evidence_hash": record.routing_evidence_hash,
            "execution_evidence_hash": record.execution_evidence_hash,
            "selected_assets_hash": record.selected_assets_hash, "evidence_hash": record.evidence_hash,
            "evidence_schema_version": record.evidence_schema_version,
            "import_batch_id": record.import_batch_id, "record_status": record.record_status,
            "supersedes_label_id": record.supersedes_label_id,
            "superseded_by_label_id": record.superseded_by_label_id,
            "correction_reason": record.correction_reason, "corrected_by": record.corrected_by,
            "corrected_at": cls._iso(record.corrected_at),
            "verification_status": record.verification_status, "verified_by": record.verified_by,
            "verified_by_name": record.verified_by_name, "verified_at": cls._iso(record.verified_at),
            "verification_note": record.verification_note, "row_version": record.row_version,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "created_at": cls._iso(record.created_at),
        }

    @classmethod
    def _evaluation_view(cls, record: TenantSupervisedEvaluationRecord, upgrade: TenantSupervisedUpgradeDecisionRecord | None = None) -> dict:
        result = {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "evaluation_as_of": cls._iso(record.evaluation_as_of), "config": deepcopy(record.config_json),
            "coverage": deepcopy(record.coverage_json), "metrics": deepcopy(record.metrics_json),
            "evidence_level": record.evidence_level, "label_watermark": deepcopy(record.label_watermark_json),
            "label_definition_id": record.label_definition_id,
            "label_definition_version": record.label_definition_version,
            "label_definition_hash": record.label_definition_hash,
            "tenant_monitoring_run_id": record.tenant_monitoring_run_id,
            "tenant_monitoring_evidence_hash": record.tenant_monitoring_evidence_hash,
            "evidence_hash": record.evidence_hash, "status": record.status,
            "governance_decision": record.governance_decision,
            "submitted_by": record.submitted_by, "submitted_by_name": record.submitted_by_name,
            "submitted_at": cls._iso(record.submitted_at), "reviewed_by": record.reviewed_by,
            "reviewed_by_name": record.reviewed_by_name, "reviewed_at": cls._iso(record.reviewed_at),
            "review_comment": record.review_comment, "row_version": record.row_version,
            "created_by": record.created_by,
            "created_by_name": record.created_by_name, "created_at": cls._iso(record.created_at),
        }
        result["upgrade_decision"] = None if upgrade is None else {
            "id": upgrade.id, "status": upgrade.status, "model_change_id": upgrade.model_change_id,
            "candidate_version": upgrade.candidate_version, "evidence_hash": upgrade.evidence_hash,
            "auto_submitted": False, "auto_published": False, "traffic_changed": False,
        }
        return result

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @classmethod
    def _iso(cls, value: datetime | None) -> str | None:
        return cls._as_utc(value).isoformat() if value else None
