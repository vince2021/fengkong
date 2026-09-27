"""Tenant rollout policy governance, stable routing, and automatic circuit breaking."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import math
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import ModelChangeRecord, ModelReleaseRecord, NotificationRecord, TenantRolloutEvaluationRecord, TenantRolloutPolicyRecord, TenantRolloutScanRecord, TenantRoutingDecisionRecord
from backend.repository import AuditRepository, DemoRepository, NotificationRepository, RuleCenterReplayComparisonRepository, content_hash
from backend.tenant_asset_repository import TenantAssetError, TenantAssetRepository
from backend.tenant_runtime_assets import TenantRuntimeAssetResolver

if TYPE_CHECKING:
    from backend.security import Principal


class TenantRolloutError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class TenantRolloutRepository:
    def __init__(self, session: Session, demo_repository: DemoRepository) -> None:
        self.session = session
        self.demo_repository = demo_repository
        self.audit = AuditRepository(session)

    def list_policies(self, tenant_id: str, model_key: str | None = None) -> list[dict]:
        statement = select(TenantRolloutPolicyRecord).where(TenantRolloutPolicyRecord.tenant_id == tenant_id)
        if model_key:
            statement = statement.where(TenantRolloutPolicyRecord.champion_model_key == model_key)
        rows = self.session.scalars(statement.order_by(TenantRolloutPolicyRecord.created_at.desc())).all()
        return [self._view(row) for row in rows]

    def create_policy(self, tenant_id: str, payload: dict, principal: "Principal") -> dict:
        comparison = self._verified_comparison(tenant_id, payload["comparison_run_id"])
        arm_snapshot = self._resolve_arms(tenant_id, comparison)
        config = self._policy_config(payload, comparison)
        record = TenantRolloutPolicyRecord(
            id=str(uuid4()), tenant_id=tenant_id, name=payload["name"],
            comparison_run_id=comparison["id"], comparison_evidence_hash=comparison["evidence_hash"],
            comparison_assets_hash=comparison["assets_hash"],
            champion_model_key=comparison["champion_model_key"], champion_model_version=comparison["champion_model_version"],
            champion_pipeline_code=comparison["champion_pipeline_code"], champion_pipeline_version=comparison["champion_pipeline_version"],
            challenger_model_key=comparison["challenger_model_key"], challenger_model_version=comparison["challenger_model_version"],
            challenger_pipeline_code=comparison["challenger_pipeline_code"], challenger_pipeline_version=comparison["challenger_pipeline_version"],
            routing_key_field=payload["routing_key_field"], traffic_basis_points=payload["traffic_basis_points"],
            observation_window_minutes=payload["observation_window_minutes"], min_sample_size=payload["min_sample_size"],
            thresholds_json=deepcopy(payload["thresholds"]), config_json=config, config_hash=content_hash(config),
            arm_snapshot_json=arm_snapshot, assets_hash=content_hash(arm_snapshot), status="draft",
            starts_at=self._as_utc(payload["starts_at"]).astimezone(timezone.utc),
            ends_at=self._as_utc(payload["ends_at"]).astimezone(timezone.utc), change_reason=payload["reason"],
            created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        return self._commit(record, "tenant_rollout_policy_created", principal, payload["reason"])

    def submit(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._policy(tenant_id, policy_id)
        self._check(record, payload["expected_row_version"])
        if record.status != "draft":
            raise TenantRolloutError("ROLLOUT_NOT_DRAFT", "只有草稿灰度策略可以提交复核", 422)
        if record.created_by != principal.subject:
            raise TenantRolloutError("ROLLOUT_SUBMITTER_INVALID", "只能由草稿创建人提交复核", 403)
        self._verify_integrity(record)
        before = self._snapshot(record)
        record.status = "pending_review"
        record.submitted_at = self._now()
        return self._commit(record, "tenant_rollout_policy_submitted", principal, payload["reason"], before)

    def review(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._policy(tenant_id, policy_id)
        self._check(record, payload["expected_row_version"])
        if record.status != "pending_review":
            raise TenantRolloutError("ROLLOUT_NOT_PENDING", "灰度策略不在待复核状态", 422)
        if record.created_by == principal.subject:
            raise TenantRolloutError("FOUR_EYES_REQUIRED", "灰度策略创建人与复核人必须分离", 409)
        before = self._snapshot(record)
        now = self._now()
        record.reviewed_by = principal.subject
        record.reviewed_by_name = principal.name
        record.reviewed_at = now
        record.review_comment = payload["comment"]
        if payload["decision"] == "reject":
            record.status = "rejected"
        else:
            self._verify_integrity(record)
            if self._as_utc(record.ends_at) <= now:
                raise TenantRolloutError("ROLLOUT_WINDOW_EXPIRED", "灰度观察窗口已经结束", 409)
            if self._as_utc(record.starts_at) > now:
                record.status = "scheduled"
            else:
                self._activate(record, now)
        return self._commit(record, "tenant_rollout_policy_reviewed", principal, payload["comment"], before)

    def change_status(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._policy(tenant_id, policy_id)
        self._check(record, payload["expected_row_version"])
        self._verify_integrity(record)
        before = self._snapshot(record)
        now = self._now()
        action = payload["action"]
        if action == "activate":
            if record.status != "scheduled" or self._as_utc(record.starts_at) > now:
                raise TenantRolloutError("ROLLOUT_NOT_READY", "灰度策略尚未到排期激活时间", 409)
            self._activate(record, now)
        elif action == "pause":
            if record.status != "active":
                raise TenantRolloutError("ROLLOUT_NOT_ACTIVE", "只有生效中的灰度策略可以暂停", 422)
            record.status, record.paused_at = "paused", now
        elif action == "resume":
            if record.status != "paused" or self._as_utc(record.ends_at) <= now:
                raise TenantRolloutError("ROLLOUT_NOT_RESUMABLE", "灰度策略当前不能恢复", 422)
            self._activate(record, now)
        elif action == "rollback":
            if record.status not in {"active", "paused"}:
                raise TenantRolloutError("ROLLOUT_NOT_ROLLBACKABLE", "灰度策略当前不能回滚", 422)
            record.status, record.rolled_back_at, record.terminal_reason = "rolled_back", now, payload["reason"]
        elif action == "complete":
            if record.status not in {"active", "paused"}:
                raise TenantRolloutError("ROLLOUT_NOT_COMPLETABLE", "灰度策略当前不能结束", 422)
            record.status, record.completed_at, record.terminal_reason = "completed", now, payload["reason"]
        return self._commit(record, f"tenant_rollout_policy_{action}", principal, payload["reason"], before)

    def restart_after_release(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        previous = self._policy(tenant_id, policy_id)
        self._check(previous, payload["expected_row_version"])
        if previous.status not in {"rolled_back", "completed"}:
            raise TenantRolloutError("ROLLOUT_RESTART_STATUS_INVALID", "只有已回滚或已结束的灰度策略可以在发布后重启观察", 422)
        change = self.session.get(ModelChangeRecord, payload["model_change_id"])
        if not change or change.entity_type != "model":
            raise TenantRolloutError("ROLLOUT_RESTART_CHANGE_NOT_FOUND", "关联模型变更单不存在", 404)
        evidence = deepcopy(change.supervised_validation_evidence_json or {})
        if evidence.get("tenant_id") != tenant_id or evidence.get("policy_id") != policy_id:
            raise TenantRolloutError("ROLLOUT_RESTART_EVIDENCE_MISMATCH", "模型变更单与原灰度策略的监督证据不匹配", 409)
        if change.status != "published" or evidence.get("release_approval", {}).get("status") != "approved" or evidence.get("independent_validation", {}).get("status") != "approved":
            raise TenantRolloutError("ROLLOUT_RESTART_RELEASE_NOT_APPROVED", "模型尚未完成独立验证和发布审批，不能重启灰度观察", 409)
        release = self.session.scalar(select(ModelReleaseRecord).where(
            ModelReleaseRecord.template_key == change.template_key,
            ModelReleaseRecord.model_version == change.candidate_version,
            ModelReleaseRecord.is_active.is_(True),
        ))
        if release is None:
            raise TenantRolloutError("ROLLOUT_RESTART_RELEASE_NOT_ACTIVE", "候选模型尚未成为当前生效发布版本", 409)
        now = self._now()
        restarted = self.create_policy(tenant_id, {
            "name": f"{previous.name} · 发布后重启观察",
            "comparison_run_id": previous.comparison_run_id,
            "routing_key_field": previous.routing_key_field,
            "traffic_basis_points": previous.traffic_basis_points,
            "observation_window_minutes": previous.observation_window_minutes,
            "min_sample_size": previous.min_sample_size,
            "thresholds": deepcopy(previous.thresholds_json),
            "starts_at": now,
            "ends_at": now + timedelta(minutes=previous.observation_window_minutes),
            "reason": payload["reason"],
        }, principal)
        self.audit.append("tenant_rollout_policy", restarted["id"], "tenant_rollout_policy_restart_requested", principal.subject, {
            "tenant_id": tenant_id, "previous_policy_id": policy_id, "model_change_id": change.id,
            "release_id": release.id, "evidence_hash": content_hash(evidence), "traffic_changed": False,
        })
        self.session.commit()
        return {"previous_policy_id": policy_id, "model_change_id": change.id, "release_id": release.id, "traffic_changed": False, "policy": restarted}

    def list_routes(self, tenant_id: str, policy_id: str, limit: int = 100) -> list[dict]:
        self._policy(tenant_id, policy_id)
        rows = self.session.scalars(select(TenantRoutingDecisionRecord).where(
            TenantRoutingDecisionRecord.tenant_id == tenant_id,
            TenantRoutingDecisionRecord.policy_id == policy_id,
        ).order_by(TenantRoutingDecisionRecord.created_at.desc()).limit(limit)).all()
        return [self._route_view(row) for row in rows]

    def list_evaluations(self, tenant_id: str, policy_id: str) -> list[dict]:
        self._policy(tenant_id, policy_id)
        rows = self.session.scalars(select(TenantRolloutEvaluationRecord).where(
            TenantRolloutEvaluationRecord.tenant_id == tenant_id,
            TenantRolloutEvaluationRecord.policy_id == policy_id,
        ).order_by(TenantRolloutEvaluationRecord.created_at.desc())).all()
        return [self._evaluation_view(row) for row in rows]

    def evaluate(self, tenant_id: str, policy_id: str, principal: "Principal", trigger_type: str = "manual") -> dict:
        policy = self._policy(tenant_id, policy_id)
        if policy.status != "active" or self._as_utc(policy.ends_at) <= self._now():
            raise TenantRolloutError("ROLLOUT_NOT_ACTIVE", "只能评估观察期内的生效策略；到期请运行周期扫描", 409)
        self._verify_integrity(policy)
        return self._evaluate(policy, principal.subject, principal.name, trigger_type, commit=True)

    def list_scans(self, tenant_id: str, limit: int = 20) -> list[dict]:
        rows = self.session.scalars(select(TenantRolloutScanRecord).where(
            TenantRolloutScanRecord.tenant_id == tenant_id,
        ).order_by(TenantRolloutScanRecord.created_at.desc()).limit(limit)).all()
        return [self._scan_view(row) for row in rows]

    def scan(self, tenant_id: str | None, principal: "Principal", *, now: datetime | None = None, run_key: str | None = None, trigger_type: str = "manual") -> dict:
        scan_at = self._as_utc(now or self._now())
        bucket = scan_at.replace(minute=(scan_at.minute // 5) * 5, second=0, microsecond=0)
        key = run_key or (f"tenant-rollout:{tenant_id or 'all'}:{bucket.strftime('%Y%m%dT%H%MZ')}" if trigger_type == "scheduler" else f"tenant-rollout:manual:{uuid4()}")
        existing = self.session.scalar(select(TenantRolloutScanRecord).where(TenantRolloutScanRecord.run_key == key))
        if existing:
            if existing.tenant_id != tenant_id:
                raise TenantRolloutError("ROLLOUT_SCAN_KEY_CONFLICT", "扫描任务键已由其他租户使用", 409)
            return {"idempotent": True, "run": self._scan_view(existing)}
        record = TenantRolloutScanRecord(
            id=str(uuid4()), run_key=key, tenant_id=tenant_id, trigger_type=trigger_type,
            status="no_due", scan_at=scan_at, results_json=[], evidence_hash=content_hash([]),
        )
        self.session.add(record)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantRolloutError("ROLLOUT_SCAN_CONFLICT", "同一时间窗口已有扫描正在执行，请刷新运行台账", 409) from exc
        statement = select(TenantRolloutPolicyRecord).where(
            TenantRolloutPolicyRecord.status.in_(("scheduled", "active")),
            TenantRolloutPolicyRecord.starts_at <= scan_at,
        )
        if tenant_id is not None:
            statement = statement.where(TenantRolloutPolicyRecord.tenant_id == tenant_id)
        policies = self.session.scalars(statement).all()
        policies.sort(key=lambda policy: (policy.tenant_id, policy.status != "active", self._as_utc(policy.starts_at), policy.id))
        results = []
        for policy in policies:
            if policy.status not in {"active", "scheduled"}:
                continue
            if policy.status == "active" and self._as_utc(policy.ends_at) > scan_at:
                last = self.session.scalar(select(TenantRolloutEvaluationRecord).where(
                    TenantRolloutEvaluationRecord.tenant_id == policy.tenant_id,
                    TenantRolloutEvaluationRecord.policy_id == policy.id,
                ).order_by(TenantRolloutEvaluationRecord.created_at.desc()))
                completed = self._window_rows(policy, ended=scan_at)
                if not completed or (last and not any(self._as_utc(row.completed_at) > self._as_utc(last.created_at) for row in completed)):
                    continue
            action = "activate" if policy.status == "scheduled" and self._as_utc(policy.ends_at) > scan_at else "close" if self._as_utc(policy.ends_at) <= scan_at else "evaluate"
            try:
                with self.session.begin_nested():
                    before = self._snapshot(policy)
                    if action == "activate":
                        self._verify_integrity(policy)
                        self._activate(policy, scan_at)
                    elif action == "close" and policy.status == "scheduled":
                        policy.status, policy.completed_at, policy.terminal_reason = "completed", scan_at, "排期观察窗口已结束，未接入 Challenger 流量"
                    else:
                        evaluation = self._evaluate(policy, principal.subject, principal.name, "scheduler", commit=False, now=min(scan_at, self._as_utc(policy.ends_at)))
                        if action == "close" and policy.status == "active":
                            policy.status, policy.completed_at = "completed", scan_at
                            policy.terminal_reason = "观察期结束，在线证据不足，未验证通过" if evaluation["action"] == "insufficient_evidence" else "观察期结束，在线保护阈值通过"
                    self.session.flush()
                    self.audit.append("tenant_rollout_policy", policy.id, f"tenant_rollout_scan_{action}", principal.subject, {
                        "tenant_id": policy.tenant_id, "run_key": key, "before": before, "after": self._snapshot(policy),
                    })
                results.append({"tenant_id": policy.tenant_id, "policy_id": policy.id, "action": action, "status": "completed", "policy_status": policy.status})
            except Exception as exc:
                self.session.expire(policy)
                results.append({"tenant_id": policy.tenant_id, "policy_id": policy.id, "action": action, "status": "failed", "error_type": type(exc).__name__})
        failed = sum(item["status"] == "failed" for item in results)
        record.status = "partial" if failed and failed < len(results) else "failed" if failed else "completed" if results else "no_due"
        record.results_json = results
        record.evidence_hash = content_hash({"run_key": key, "tenant_id": tenant_id, "trigger_type": trigger_type, "scan_at": scan_at.isoformat(), "status": record.status, "results": results})
        if failed:
            notifier = NotificationRepository(self.session)
            for affected_tenant in sorted({item["tenant_id"] for item in results if item["status"] == "failed"}):
                for role in ("model_admin", "risk_manager"):
                    notifier.create_if_absent(affected_tenant, {
                        "case_id": None, "counterparty_id": None, "recipient_role": role, "recipient_subject": None,
                        "category": "model_governance", "level": "critical", "severity": "critical",
                        "title": "灰度周期扫描执行异常",
                        "message": "灰度排期或评估动作执行失败，请检查运行台账；失败策略保持原有状态，观察期门禁仍会停止过期流量。",
                        "action_json": {"view": "model-governance", "run_id": record.id},
                        "dedup_key": f"tenant-rollout-scan:{record.id}:{role}:failed",
                    })
        self.session.commit()
        self.session.refresh(record)
        return {"idempotent": False, "run": self._scan_view(record)}

    def incident_action(self, tenant_id: str, policy_id: str, payload: dict, principal: "Principal") -> dict:
        policy = self._policy(tenant_id, policy_id)
        self._check(policy, payload["expected_row_version"])
        action = payload["action"]
        allowed = {"acknowledge": "open", "request_resolution": "acknowledged", "approve_resolution": "resolution_pending"}
        if policy.incident_status != allowed[action]:
            raise TenantRolloutError("ROLLOUT_INCIDENT_STATUS_INVALID", "灰度事故状态不允许执行当前操作", 409)
        before = self._snapshot(policy)
        now = self._now()
        if action == "acknowledge":
            policy.incident_status, policy.acknowledged_by, policy.acknowledged_at, policy.acknowledgement_note = "acknowledged", principal.subject, now, payload["reason"]
        elif action == "request_resolution":
            policy.incident_status, policy.resolution_requested_by, policy.resolution_requested_at, policy.resolution_note = "resolution_pending", principal.subject, now, payload["reason"]
        else:
            if policy.resolution_requested_by == principal.subject:
                raise TenantRolloutError("FOUR_EYES_REQUIRED", "整改提交人与独立复核人必须不同", 409)
            policy.incident_status, policy.resolved_by, policy.resolved_at = "resolved", principal.subject, now
            notifications = self.session.scalars(select(NotificationRecord).where(
                NotificationRecord.tenant_id == tenant_id,
                NotificationRecord.dedup_key.like(f"tenant-rollout:{policy.id}:rollback:%"),
            )).all()
            for notification in notifications:
                notification.status = "resolved"
                notification.read_at = notification.read_at or now
        return self._commit(policy, f"tenant_rollout_incident_{action}", principal, payload["reason"], before)

    def route(
        self, tenant_id: str, model_key: str, routing_key: str, channel: str, request_ref: str,
        *, explicit_selection: bool = False, requested_pipeline_code: str | None = None,
    ) -> dict | None:
        if explicit_selection:
            return None
        now = self._now()
        policy = self.session.scalars(select(TenantRolloutPolicyRecord).where(
            TenantRolloutPolicyRecord.tenant_id == tenant_id,
            TenantRolloutPolicyRecord.champion_model_key == model_key,
            TenantRolloutPolicyRecord.status == "active",
            TenantRolloutPolicyRecord.starts_at <= now,
            TenantRolloutPolicyRecord.ends_at > now,
        )).first()
        if policy is None:
            return None
        if requested_pipeline_code and requested_pipeline_code.strip().upper() != policy.champion_pipeline_code.strip().upper():
            return None
        self._verify_integrity(policy)
        existing = self.session.scalars(select(TenantRoutingDecisionRecord).where(
            TenantRoutingDecisionRecord.tenant_id == tenant_id,
            TenantRoutingDecisionRecord.channel == channel,
            TenantRoutingDecisionRecord.request_ref == request_ref,
        )).first()
        if existing:
            if existing.policy_id != policy.id or content_hash(existing.selected_assets_json) != existing.selected_assets_hash:
                raise TenantRolloutError("ROUTING_EVIDENCE_CONFLICT", "既有路由证据与当前策略不一致", 409)
            return self._decorate_assets(deepcopy(existing.selected_assets_json), existing)

        routing_key_hash = hashlib.sha256(routing_key.encode("utf-8")).hexdigest()
        bucket = int(hashlib.sha256(f"{tenant_id}:{policy.id}:{routing_key}".encode("utf-8")).hexdigest(), 16) % 10000
        arm = "challenger" if bucket < policy.traffic_basis_points else "champion"
        selected = deepcopy(policy.arm_snapshot_json[arm])
        record = TenantRoutingDecisionRecord(
            id=str(uuid4()), tenant_id=tenant_id, policy_id=policy.id,
            policy_config_hash=policy.config_hash, policy_assets_hash=policy.assets_hash,
            channel=channel, request_ref=request_ref, routing_key_hash=routing_key_hash,
            bucket=bucket, selected_arm=arm, selected_assets_json=selected,
            selected_assets_hash=content_hash(selected), status="selected",
        )
        self.session.add(record)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantRolloutError("ROUTING_EVIDENCE_CONFLICT", "路由请求编号发生并发冲突", 409) from exc
        return self._decorate_assets(selected, record)

    def complete_route(self, assets: dict, result: dict | None, elapsed_ms: int, error_code: str | None = None) -> dict | None:
        route = assets.get("routing") if isinstance(assets, dict) else None
        if not route or not route.get("decision_id"):
            return None
        record = self.session.get(TenantRoutingDecisionRecord, route["decision_id"])
        if record is None or record.tenant_id != route.get("tenant_id"):
            raise TenantRolloutError("ROUTING_EVIDENCE_MISSING", "灰度路由证据不存在", 409)
        if record.status != "selected":
            return self._route_view(record)
        record.status = "failed" if error_code else "completed"
        record.elapsed_ms = max(0, int(elapsed_ms))
        record.score = self._score(result)
        record.rating = str((result or {}).get("rating")) if (result or {}).get("rating") is not None else None
        record.admission = self._admission(result)
        record.error_code = error_code
        record.result_hash = content_hash(result) if result is not None else None
        record.completed_at = self._now()
        record.evidence_hash = content_hash({
            "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "policy_config_hash": record.policy_config_hash, "policy_assets_hash": record.policy_assets_hash,
            "routing_key_hash": record.routing_key_hash, "bucket": record.bucket,
            "selected_arm": record.selected_arm, "selected_assets_hash": record.selected_assets_hash,
            "status": record.status, "elapsed_ms": record.elapsed_ms, "score": str(record.score) if record.score is not None else None,
            "rating": record.rating, "admission": record.admission, "error_code": record.error_code,
            "result_hash": record.result_hash,
        })
        self.session.flush()
        policy = self.session.get(TenantRolloutPolicyRecord, record.policy_id)
        if policy and policy.status == "active":
            completed = self._window_rows(policy)
            if len(completed) >= policy.min_sample_size and len(completed) % policy.min_sample_size == 0:
                self._evaluate(policy, "rollout-circuit-breaker", "灰度自动熔断器", "automatic", commit=False)
        return self._route_view(record)

    def _evaluate(self, policy: TenantRolloutPolicyRecord, actor: str, actor_name: str, trigger_type: str, commit: bool, now: datetime | None = None) -> dict:
        now = now or self._now()
        started = max(self._as_utc(policy.starts_at), now - timedelta(minutes=policy.observation_window_minutes))
        rows = self._window_rows(policy, started, now)
        metrics = self._metrics(rows)
        thresholds = deepcopy(policy.thresholds_json)
        eligible = len(rows) >= policy.min_sample_size and metrics["challenger"]["sample_count"] > 0 and metrics["champion"]["sample_count"] > 0
        checks = [
            self._check_metric("challenger_failure_rate", "Challenger 失败率", metrics["challenger"]["failure_rate"], thresholds["max_challenger_failure_rate"]),
            self._check_metric("latency_increase_ratio", "延迟增幅", metrics["latency_increase_ratio"], thresholds["max_latency_increase_ratio"]),
            self._check_metric("score_psi", "评分分布 PSI", metrics["score_psi"], thresholds["max_score_psi"]),
            self._check_metric("admission_distribution_shift", "准入分布偏移", metrics["admission_distribution_shift"], thresholds["max_admission_distribution_shift"]),
        ]
        violations = [item for item in checks if item["testable"] and not item["passed"]]
        passed = eligible and not violations
        action = "continue" if passed else "insufficient_evidence" if not eligible else "automatic_rollback"
        gate = {
            "eligible": eligible, "passed": passed, "checks": checks, "violations": violations,
            "summary": "在线保护阈值通过" if passed else "样本不足，继续观察" if not eligible else "触发自动熔断并切回 Champion",
        }
        payload = {
            "tenant_id": policy.tenant_id, "policy_id": policy.id, "policy_config_hash": policy.config_hash,
            "window_started_at": started.isoformat(), "window_ended_at": now.isoformat(),
            "sample_count": len(rows), "evidence_level": "unlabeled_online", "metrics": metrics,
            "gate": gate, "action": action,
        }
        evaluation = TenantRolloutEvaluationRecord(
            id=str(uuid4()), tenant_id=policy.tenant_id, policy_id=policy.id, trigger_type=trigger_type,
            window_started_at=started, window_ended_at=now, sample_count=len(rows),
            evidence_level="unlabeled_online", metrics_json=metrics, gate_json=gate, action=action,
            evidence_hash=content_hash(payload), created_by=actor, created_by_name=actor_name,
        )
        self.session.add(evaluation)
        if action == "automatic_rollback" and policy.status == "active":
            policy.status = "rolled_back"
            policy.rolled_back_at = now
            policy.terminal_reason = gate["summary"]
            policy.incident_status = "open"
            policy.incident_evaluation_id = evaluation.id
            notifier = NotificationRepository(self.session)
            for role in ("model_admin", "risk_manager"):
                notifier.create_if_absent(policy.tenant_id, {
                    "case_id": None, "counterparty_id": None, "recipient_role": role, "recipient_subject": None,
                    "category": "model_governance", "level": "critical", "severity": "critical",
                    "title": "灰度保护已切回 Champion",
                    "message": f"策略 {policy.name} 已触发自动熔断，请查看在线证据并确认事故。整改须独立复核；原策略不会自动恢复 Challenger 流量。",
                    "action_json": {"view": "model-governance", "policy_id": policy.id, "evaluation_id": evaluation.id},
                    "dedup_key": f"tenant-rollout:{policy.id}:rollback:{role}",
                })
        self.session.flush()
        self.audit.append("tenant_rollout_evaluation", evaluation.id, "tenant_rollout_evaluated", actor, {
            "tenant_id": policy.tenant_id, "policy_id": policy.id, "trigger_type": trigger_type,
            "action": action, "evidence_hash": evaluation.evidence_hash,
        })
        if commit:
            self.session.commit()
            self.session.refresh(evaluation)
        return self._evaluation_view(evaluation)

    def _resolve_arms(self, tenant_id: str, comparison: dict) -> dict:
        resolver = TenantRuntimeAssetResolver(TenantAssetRepository(self.session), self.demo_repository)
        try:
            champion = resolver.resolve_graph(
                tenant_id, comparison["champion_model_key"], model_version=comparison["champion_model_version"],
                pipeline_code=comparison["champion_pipeline_code"], pipeline_version=comparison["champion_pipeline_version"],
                allow_historical=True,
            )
            challenger = resolver.resolve_graph(
                tenant_id, comparison["challenger_model_key"], model_version=comparison["challenger_model_version"],
                pipeline_code=comparison["challenger_pipeline_code"], pipeline_version=comparison["challenger_pipeline_version"],
                allow_historical=True,
            )
        except TenantAssetError as exc:
            raise TenantRolloutError(exc.code, exc.message, exc.status_code, exc.details) from exc
        return {"schema_version": "tenant-rollout-arms-v1", "champion": champion, "challenger": challenger}

    def _verified_comparison(self, tenant_id: str, comparison_run_id: str) -> dict:
        repository = RuleCenterReplayComparisonRepository(self.session)
        try:
            comparison = repository._to_dict(repository._verified_comparison(tenant_id, comparison_run_id))
        except (LookupError, ValueError) as exc:
            raise TenantRolloutError("ROLLOUT_COMPARISON_INVALID", str(exc), 409) from exc
        if comparison["effective_status"] not in {"passed", "exception_approved"}:
            raise TenantRolloutError("ROLLOUT_COMPARISON_BLOCKED", "双模型固定快照比较尚未通过门禁或有效例外", 409)
        return comparison

    def _verify_integrity(self, record: TenantRolloutPolicyRecord) -> None:
        comparison = self._verified_comparison(record.tenant_id, record.comparison_run_id)
        if comparison["evidence_hash"] != record.comparison_evidence_hash or comparison["assets_hash"] != record.comparison_assets_hash:
            raise TenantRolloutError("ROLLOUT_COMPARISON_DRIFTED", "灰度策略绑定的回放比较证据已变化", 409)
        frozen_config = {
            "comparison_run_id": record.comparison_run_id,
            "comparison_evidence_hash": record.comparison_evidence_hash,
            "comparison_assets_hash": record.comparison_assets_hash,
            "routing_key_field": record.routing_key_field,
            "traffic_basis_points": record.traffic_basis_points,
            "observation_window_minutes": record.observation_window_minutes,
            "min_sample_size": record.min_sample_size,
            "thresholds": record.thresholds_json,
            "starts_at": self._as_utc(record.starts_at).isoformat(),
            "ends_at": self._as_utc(record.ends_at).isoformat(),
        }
        if record.config_json != frozen_config or content_hash(frozen_config) != record.config_hash or content_hash(record.arm_snapshot_json) != record.assets_hash:
            raise TenantRolloutError("ROLLOUT_INTEGRITY_FAILED", "灰度策略配置或资产快照哈希不一致", 409)

    def _activate(self, record: TenantRolloutPolicyRecord, now: datetime) -> None:
        active = self.session.scalars(select(TenantRolloutPolicyRecord).where(
            TenantRolloutPolicyRecord.tenant_id == record.tenant_id,
            TenantRolloutPolicyRecord.champion_model_key == record.champion_model_key,
            TenantRolloutPolicyRecord.status == "active",
            TenantRolloutPolicyRecord.id != record.id,
        )).all()
        for previous in active:
            previous.status, previous.completed_at, previous.terminal_reason = "completed", now, f"由策略 {record.id} 替代"
        if active:
            self.session.flush()
        record.status = "active"
        record.activated_at = now
        record.paused_at = None

    def _window_rows(self, policy: TenantRolloutPolicyRecord, started: datetime | None = None, ended: datetime | None = None) -> list[TenantRoutingDecisionRecord]:
        ended = ended or self._now()
        started = started or max(self._as_utc(policy.starts_at), ended - timedelta(minutes=policy.observation_window_minutes))
        return list(self.session.scalars(select(TenantRoutingDecisionRecord).where(
            TenantRoutingDecisionRecord.tenant_id == policy.tenant_id,
            TenantRoutingDecisionRecord.policy_id == policy.id,
            TenantRoutingDecisionRecord.created_at >= started,
            TenantRoutingDecisionRecord.created_at <= ended,
            TenantRoutingDecisionRecord.status.in_(("completed", "failed")),
        )).all())

    @classmethod
    def _metrics(cls, rows: list[TenantRoutingDecisionRecord]) -> dict:
        sides = {}
        for arm in ("champion", "challenger"):
            selected = [row for row in rows if row.selected_arm == arm]
            completed = [row for row in selected if row.status == "completed"]
            sides[arm] = {
                "sample_count": len(selected), "completed_count": len(completed),
                "failed_count": len(selected) - len(completed),
                "failure_rate": (len(selected) - len(completed)) / len(selected) if selected else None,
                "average_latency_ms": sum(row.elapsed_ms or 0 for row in selected) / len(selected) if selected else None,
                "score_distribution": cls._score_distribution(completed),
                "admission_distribution": cls._distribution([row.admission or "unknown" for row in completed]),
            }
        champion_latency = sides["champion"]["average_latency_ms"]
        challenger_latency = sides["challenger"]["average_latency_ms"]
        latency_ratio = (challenger_latency / champion_latency - 1) if champion_latency and challenger_latency is not None else None
        return {
            "sample_count": len(rows), **sides,
            "latency_increase_ratio": latency_ratio,
            "score_psi": cls._psi(sides["champion"]["score_distribution"], sides["challenger"]["score_distribution"]),
            "admission_distribution_shift": cls._distribution_shift(sides["champion"]["admission_distribution"], sides["challenger"]["admission_distribution"]),
            "supervised_metrics_available": False,
            "degraded_reason": "在线样本未携带成熟标签，KS 与混淆矩阵不参与自动熔断",
        }

    @staticmethod
    def _score_distribution(rows: list[TenantRoutingDecisionRecord]) -> dict[str, float]:
        labels = [f"{start}-{start + 9}" for start in range(0, 100, 10)] + ["100"]
        counts = {label: 0 for label in labels}
        for row in rows:
            if row.score is None:
                continue
            value = max(0, min(100, float(row.score)))
            label = "100" if value == 100 else f"{int(value // 10) * 10}-{int(value // 10) * 10 + 9}"
            counts[label] += 1
        total = sum(counts.values())
        return {key: value / total if total else 0 for key, value in counts.items()}

    @staticmethod
    def _distribution(values: list[str]) -> dict[str, float]:
        total = len(values)
        counts = {value: values.count(value) for value in sorted(set(values))}
        return {key: value / total for key, value in counts.items()} if total else {}

    @staticmethod
    def _psi(expected: dict[str, float], actual: dict[str, float]) -> float | None:
        if not any(expected.values()) or not any(actual.values()):
            return None
        epsilon = 0.0001
        return round(sum((max(actual.get(key, 0), epsilon) - max(expected.get(key, 0), epsilon)) * math.log(max(actual.get(key, 0), epsilon) / max(expected.get(key, 0), epsilon)) for key in set(expected) | set(actual)), 6)

    @staticmethod
    def _distribution_shift(left: dict[str, float], right: dict[str, float]) -> float | None:
        if not left or not right:
            return None
        return round(sum(abs(left.get(key, 0) - right.get(key, 0)) for key in set(left) | set(right)) / 2, 6)

    @staticmethod
    def _check_metric(key: str, label: str, actual: float | None, threshold: float) -> dict:
        return {"key": key, "label": label, "actual": actual, "threshold": threshold, "testable": actual is not None, "passed": actual is None or actual <= threshold}

    @staticmethod
    def _decorate_assets(assets: dict, record: TenantRoutingDecisionRecord) -> dict:
        evidence = {
            "schema_version": "tenant-rollout-routing-v1", "tenant_id": record.tenant_id,
            "decision_id": record.id, "policy_id": record.policy_id,
            "policy_config_hash": record.policy_config_hash, "policy_assets_hash": record.policy_assets_hash,
            "routing_key_hash": record.routing_key_hash, "bucket": record.bucket,
            "selected_arm": record.selected_arm, "selected_assets_hash": record.selected_assets_hash,
        }
        evidence["routing_evidence_hash"] = content_hash(evidence)
        assets["routing"] = evidence
        assets["resolution_hash"] = content_hash({"base": assets.get("resolution_hash"), "routing": evidence["routing_evidence_hash"]})
        return assets

    @staticmethod
    def _policy_config(payload: dict, comparison: dict) -> dict:
        return {
            "comparison_run_id": comparison["id"], "comparison_evidence_hash": comparison["evidence_hash"],
            "comparison_assets_hash": comparison["assets_hash"], "routing_key_field": payload["routing_key_field"],
            "traffic_basis_points": payload["traffic_basis_points"], "observation_window_minutes": payload["observation_window_minutes"],
            "min_sample_size": payload["min_sample_size"], "thresholds": deepcopy(payload["thresholds"]),
            "starts_at": TenantRolloutRepository._as_utc(payload["starts_at"]).astimezone(timezone.utc).isoformat(),
            "ends_at": TenantRolloutRepository._as_utc(payload["ends_at"]).astimezone(timezone.utc).isoformat(),
        }

    def _policy(self, tenant_id: str, policy_id: str) -> TenantRolloutPolicyRecord:
        record = self.session.scalars(select(TenantRolloutPolicyRecord).where(
            TenantRolloutPolicyRecord.tenant_id == tenant_id, TenantRolloutPolicyRecord.id == policy_id,
        )).first()
        if record is None:
            raise TenantRolloutError("ROLLOUT_NOT_FOUND", "灰度策略不存在", 404)
        return record

    @staticmethod
    def _check(record: TenantRolloutPolicyRecord, expected: int) -> None:
        if record.row_version != expected:
            raise TenantRolloutError("ROW_VERSION_CONFLICT", f"灰度策略版本已变化，当前版本为 {record.row_version}", 409)

    def _commit(self, record: TenantRolloutPolicyRecord, event: str, principal: "Principal", reason: str, before: dict | None = None) -> dict:
        try:
            self.session.flush()
            self.audit.append("tenant_rollout_policy", record.id, event, principal.subject, {
                "tenant_id": record.tenant_id, "reason": reason, "before": before, "after": self._snapshot(record),
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantRolloutError("ROW_VERSION_CONFLICT", "灰度策略发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._view(record)

    def _snapshot(self, record: TenantRolloutPolicyRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "name": record.name, "status": record.status,
            "comparison_run_id": record.comparison_run_id, "comparison_evidence_hash": record.comparison_evidence_hash,
            "comparison_assets_hash": record.comparison_assets_hash,
            "champion_model_key": record.champion_model_key, "champion_model_version": record.champion_model_version,
            "challenger_model_key": record.challenger_model_key, "challenger_model_version": record.challenger_model_version,
            "routing_key_field": record.routing_key_field, "traffic_basis_points": record.traffic_basis_points,
            "observation_window_minutes": record.observation_window_minutes, "min_sample_size": record.min_sample_size,
            "thresholds": deepcopy(record.thresholds_json), "config_hash": record.config_hash, "assets_hash": record.assets_hash,
            "starts_at": self._iso(record.starts_at), "ends_at": self._iso(record.ends_at), "row_version": record.row_version,
            "incident_status": record.incident_status, "incident_evaluation_id": record.incident_evaluation_id,
            "acknowledged_by": record.acknowledged_by, "acknowledged_at": self._iso(record.acknowledged_at),
            "acknowledgement_note": record.acknowledgement_note, "resolution_requested_by": record.resolution_requested_by,
            "resolution_requested_at": self._iso(record.resolution_requested_at), "resolution_note": record.resolution_note,
            "resolved_by": record.resolved_by, "resolved_at": self._iso(record.resolved_at),
        }

    def _view(self, record: TenantRolloutPolicyRecord) -> dict:
        now = self._now()
        effective = "ready_to_activate" if record.status == "scheduled" and self._as_utc(record.starts_at) <= now else "window_ended" if record.status == "active" and self._as_utc(record.ends_at) <= now else record.status
        return {
            **self._snapshot(record), "effective_status": effective,
            "champion": {"model_key": record.champion_model_key, "model_version": record.champion_model_version, "pipeline_code": record.champion_pipeline_code, "pipeline_version": record.champion_pipeline_version},
            "challenger": {"model_key": record.challenger_model_key, "model_version": record.challenger_model_version, "pipeline_code": record.challenger_pipeline_code, "pipeline_version": record.challenger_pipeline_version},
            "comparison": {"run_id": record.comparison_run_id, "evidence_hash": record.comparison_evidence_hash, "assets_hash": record.comparison_assets_hash},
            "traffic_percent": record.traffic_basis_points / 100,
            "change_reason": record.change_reason, "created_by": record.created_by, "created_by_name": record.created_by_name,
            "submitted_at": self._iso(record.submitted_at), "reviewed_by": record.reviewed_by, "reviewed_by_name": record.reviewed_by_name,
            "reviewed_at": self._iso(record.reviewed_at), "review_comment": record.review_comment,
            "activated_at": self._iso(record.activated_at), "paused_at": self._iso(record.paused_at),
            "rolled_back_at": self._iso(record.rolled_back_at), "completed_at": self._iso(record.completed_at),
            "terminal_reason": record.terminal_reason, "created_at": self._iso(record.created_at), "updated_at": self._iso(record.updated_at),
        }

    @staticmethod
    def _route_view(record: TenantRoutingDecisionRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "channel": record.channel, "request_ref": record.request_ref, "routing_key_hash": record.routing_key_hash,
            "bucket": record.bucket, "selected_arm": record.selected_arm, "selected_assets_hash": record.selected_assets_hash,
            "status": record.status, "elapsed_ms": record.elapsed_ms, "score": float(record.score) if record.score is not None else None,
            "rating": record.rating, "admission": record.admission, "error_code": record.error_code,
            "result_hash": record.result_hash, "evidence_hash": record.evidence_hash,
            "created_at": TenantRolloutRepository._iso(record.created_at), "completed_at": TenantRolloutRepository._iso(record.completed_at),
        }

    @staticmethod
    def _scan_view(record: TenantRolloutScanRecord) -> dict:
        return {
            "id": record.id, "run_key": record.run_key, "tenant_id": record.tenant_id,
            "trigger_type": record.trigger_type, "status": record.status,
            "scan_at": TenantRolloutRepository._iso(record.scan_at), "results": deepcopy(record.results_json),
            "evidence_hash": record.evidence_hash, "created_at": TenantRolloutRepository._iso(record.created_at),
        }

    @staticmethod
    def _evaluation_view(record: TenantRolloutEvaluationRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "policy_id": record.policy_id,
            "trigger_type": record.trigger_type, "window_started_at": TenantRolloutRepository._iso(record.window_started_at),
            "window_ended_at": TenantRolloutRepository._iso(record.window_ended_at), "sample_count": record.sample_count,
            "evidence_level": record.evidence_level, "metrics": deepcopy(record.metrics_json), "gate": deepcopy(record.gate_json),
            "action": record.action, "evidence_hash": record.evidence_hash,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "created_at": TenantRolloutRepository._iso(record.created_at),
        }

    @staticmethod
    def _score(result: dict | None) -> Decimal | None:
        value = (result or {}).get("total_score")
        try:
            return Decimal(str(value)) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def _admission(result: dict | None) -> str | None:
        value = (result or {}).get("final_admission") or (result or {}).get("access_strategy")
        return str(value) if value is not None else None

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None
