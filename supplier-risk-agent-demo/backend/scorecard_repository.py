from __future__ import annotations

import csv
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import DecisionPipelineDefinition, ModelChangeRecord, ModelReleaseRecord, ModelSnapshotRecord, RuleCenterReleasePackage, RuleCenterReleasePackageMember, RuleCenterReplayDataset, RuleCenterReplayDatasetSnapshot, RuleDefinition, RuleSetDefinition, ScorecardDefinition, ScorecardDevelopmentRun, ScorecardMonitoringSavedView, ScorecardMonitoringSchedulerLease, ScorecardMonitoringSchedulerRun, ScorecardMonitoringSlaPolicy, ScorecardValidationMonitoringEvent, ScorecardValidationMonitoringPlan, ScorecardValidationPolicy
from backend.repository import AuditRepository, ConcurrentUpdateError, NotificationRepository, RuleCenterReplayDatasetRepository, content_hash
from backend.scorecard_development import DEFAULT_VALIDATION_THRESHOLDS, analyze_scorecard_validation
from backend.scorecard_validation import validate_scorecard


class ScorecardRepository:
    DEFAULT_MONITORING_SLA_RULES = {
        "critical": {"response_hours": 24, "due_soon_ratio": 0.25, "escalation_after_hours": 4},
        "warning": {"response_hours": 72, "due_soon_ratio": 0.25, "escalation_after_hours": 4},
    }
    MONITORING_SCHEDULER_LEASE_KEY = "scorecard-continuous-validation"
    MONITORING_SCHEDULER_LEASE_MINUTES = 15
    MONITORING_SCHEDULER_EXPECTED_CADENCE_MINUTES = 5
    MONITORING_SCHEDULER_STALE_AFTER_MINUTES = 20
    MONITORING_SCHEDULER_MAX_ATTEMPTS = 3

    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list_assets(self) -> list[dict]:
        records = self.session.scalars(
            select(ScorecardDefinition).order_by(ScorecardDefinition.code, ScorecardDefinition.version.desc())
        ).all()
        return [self._asset(record) for record in records]

    def binding_for_asset(self, asset_id: str) -> dict:
        record = self.session.get(ScorecardDefinition, asset_id)
        if record is None or record.status != "published":
            raise LookupError("已发布评分卡资产不存在")
        if content_hash(record.config_json) != record.config_hash:
            raise ValueError("评分卡资产配置哈希不一致")
        return {
            "scorecard_asset_id": record.id,
            "code": record.code,
            "version": record.version,
            "config_hash": record.config_hash,
            "config": deepcopy(record.config_json),
        }

    def approved_validation_evidence(self, run_id: str, scorecard_binding: dict) -> dict:
        record = self.session.get(ScorecardDevelopmentRun, run_id)
        if record is None:
            raise LookupError("评分卡开发验证运行不存在")
        run = self._development_run(record)
        gate = run["report"].get("validation_gate") or {}
        if run["report"].get("schema_version") != "scorecard-development-report-v4":
            raise ValueError("评分卡开发验证不是当前 v4 门禁证据，请重新运行")
        if not run["integrity_valid"]:
            raise ValueError("评分卡开发验证证据完整性校验失败")
        if run["review_status"] != "approved" or not run["review_integrity_valid"]:
            raise ValueError("评分卡开发验证尚未完成有效的独立批准")
        if not gate.get("passed"):
            raise ValueError("评分卡开发验证门禁未通过，不能绑定模型候选")
        expected = {
            "scorecard_asset_id": scorecard_binding.get("scorecard_asset_id"),
            "scorecard_code": scorecard_binding.get("code"),
            "scorecard_version": scorecard_binding.get("version"),
            "scorecard_config_hash": scorecard_binding.get("config_hash"),
        }
        for key, value in expected.items():
            if run.get(key) != value:
                raise ValueError(f"评分卡开发验证与模型候选固定资产不一致：{key}")
        return {
            "validation_run_id": run["id"],
            **expected,
            "dataset_snapshot_id": run["dataset_snapshot_id"],
            "dataset_snapshot_hash": run["dataset_snapshot_hash"],
            "validation_snapshot_id": run.get("validation_snapshot_id"),
            "validation_snapshot_hash": run.get("validation_snapshot_hash"),
            "oot_snapshot_id": run.get("oot_snapshot_id"),
            "oot_snapshot_hash": run.get("oot_snapshot_hash"),
            "report_schema_version": run["report"]["schema_version"],
            "evidence_level": run["evidence_level"],
            "evidence_hash": run["evidence_hash"],
            "validation_gate_hash": content_hash(gate),
            "validation_gate_summary": gate.get("summary"),
            "review_hash": run["review_hash"],
            "reviewed_by": run["reviewed_by"],
            "reviewed_by_name": run["reviewed_by_name"],
            "reviewed_at": run["reviewed_at"],
        }

    def list_development_runs(self) -> list[dict]:
        rows = self.session.scalars(
            select(ScorecardDevelopmentRun).order_by(ScorecardDevelopmentRun.created_at.desc(), ScorecardDevelopmentRun.id.desc())
        ).all()
        return [self._development_run(row) for row in rows]

    def development_trends(self, scorecard_code: str | None = None, max_runs: int = 200) -> dict:
        statement = select(ScorecardDevelopmentRun)
        if scorecard_code:
            statement = statement.where(ScorecardDevelopmentRun.scorecard_code == scorecard_code)
        rows = self.session.scalars(
            statement.order_by(ScorecardDevelopmentRun.created_at.desc(), ScorecardDevelopmentRun.id.desc()).limit(max_runs)
        ).all()
        points = [self._development_trend_point(self._development_run(row)) for row in reversed(rows)]
        grouped: dict[str, list[dict]] = {}
        for point in points:
            grouped.setdefault(point["scorecard_code"], []).append(point)
        series = []
        for code, code_points in sorted(grouped.items()):
            valid_gates = [point for point in code_points if point["status"] in {"pass", "block"}]
            latest = code_points[-1]
            series.append({
                "scorecard_code": code,
                "scorecard_versions": sorted({point["scorecard_version"] for point in code_points}),
                "point_count": len(code_points),
                "pass_rate": round(sum(point["status"] == "pass" for point in valid_gates) / len(valid_gates), 6) if valid_gates else None,
                "latest_status": latest["status"],
                "latest_run_id": latest["run_id"],
                "points": code_points,
            })
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "run_count": len(points), "scorecard_count": len(series),
                "pass_count": sum(point["status"] == "pass" for point in points),
                "block_count": sum(point["status"] == "block" for point in points),
                "invalid_count": sum(point["status"] == "invalid" for point in points),
                "pending_review_count": sum(point["review_status"] == "pending_review" for point in points),
            },
            "series": series,
        }

    def portfolio_stability(self) -> dict:
        assets = self.session.scalars(
            select(ScorecardDefinition).order_by(
                ScorecardDefinition.code, ScorecardDefinition.version.desc()
            )
        ).all()
        runs = self.session.scalars(
            select(ScorecardDevelopmentRun).order_by(
                ScorecardDevelopmentRun.created_at.desc(), ScorecardDevelopmentRun.id.desc()
            )
        ).all()
        plans = self.session.scalars(select(ScorecardValidationMonitoringPlan)).all()
        events = self.session.scalars(
            select(ScorecardValidationMonitoringEvent).where(
                ScorecardValidationMonitoringEvent.status != "closed"
            )
        ).all()

        assets_by_code: dict[str, list[ScorecardDefinition]] = {}
        for asset in assets:
            assets_by_code.setdefault(asset.code, []).append(asset)
        points_by_code: dict[str, list[dict]] = {}
        for record in runs:
            point = self._development_trend_point(self._development_run(record))
            points_by_code.setdefault(point["scorecard_code"], []).append(point)
        plans_by_code: dict[str, list[ScorecardValidationMonitoringPlan]] = {}
        plan_code_by_id: dict[str, str] = {}
        asset_code_by_id = {asset.id: asset.code for asset in assets}
        for plan in plans:
            code = asset_code_by_id.get(plan.scorecard_asset_id)
            if not code:
                continue
            plans_by_code.setdefault(code, []).append(plan)
            plan_code_by_id[plan.id] = code
        events_by_code: dict[str, list[ScorecardValidationMonitoringEvent]] = {}
        for event in events:
            code = plan_code_by_id.get(event.plan_id)
            if code:
                events_by_code.setdefault(code, []).append(event)

        rows = []
        all_codes = sorted(set(assets_by_code) | set(points_by_code) | set(plans_by_code))
        for code in all_codes:
            code_assets = assets_by_code.get(code, [])
            active_asset = next((item for item in code_assets if item.is_active), None)
            latest_asset = active_asset or (code_assets[0] if code_assets else None)
            code_points = points_by_code.get(code, [])
            latest = code_points[0] if code_points else None
            previous = code_points[1] if len(code_points) > 1 else None
            code_plans = plans_by_code.get(code, [])
            enabled_plans = [item for item in code_plans if item.enabled]
            code_events = events_by_code.get(code, [])
            event_payloads = [self._monitoring_event(item) for item in code_events]
            metric_health = self._portfolio_metric_health(latest)
            near_threshold_count = sum(item["status"] == "near" for item in metric_health.values())
            breach_count = sum(item["status"] == "breach" for item in metric_health.values())
            overdue_count = sum(item["sla_status"] in {"overdue", "escalated"} for item in event_payloads)
            critical_count = sum(item["severity"] == "critical" for item in event_payloads)
            failed_plan_count = sum(item.last_status == "failed" for item in enabled_plans)

            if latest and latest["status"] == "invalid":
                status = "invalid"
                reason = "最新验证证据或固定策略完整性校验失败"
            elif latest and latest["status"] == "block":
                status = "blocked"
                reason = latest.get("gate_summary") or "最新机构验证门禁未通过"
            elif not latest or not enabled_plans:
                status = "unmonitored"
                reason = "缺少固定验证运行" if not latest else "尚未启用持续验证计划"
            elif critical_count or overdue_count or failed_plan_count or near_threshold_count or breach_count:
                status = "attention"
                reason = "存在严重/逾期预警、运行失败或指标临近门槛"
            else:
                status = "healthy"
                reason = "最新门禁通过，持续验证计划及预警状态正常"

            latest_metrics = deepcopy(latest["metrics"]) if latest else {}
            previous_metrics = deepcopy(previous["metrics"]) if previous else {}
            deltas = {
                key: round(value - previous_metrics[key], 6)
                if isinstance(value, (int, float)) and isinstance(previous_metrics.get(key), (int, float))
                else None
                for key, value in latest_metrics.items()
            }
            rows.append({
                "scorecard_code": code,
                "scorecard_name": latest_asset.name if latest_asset else code,
                "latest_version": latest_asset.version if latest_asset else (latest["scorecard_version"] if latest else None),
                "active_asset_id": latest_asset.id if latest_asset else None,
                "status": status,
                "status_reason": reason,
                "latest_run_id": latest["run_id"] if latest else None,
                "latest_run_at": latest.get("created_at") if latest else None,
                "latest_run_status": latest["status"] if latest else None,
                "previous_run_id": previous["run_id"] if previous else None,
                "evidence_level": latest.get("evidence_level") if latest else None,
                "integrity_valid": latest.get("integrity_valid") if latest else None,
                "review_status": latest.get("review_status") if latest else None,
                "metrics": latest_metrics,
                "deltas": deltas,
                "metric_health": metric_health,
                "threshold_signal_count": near_threshold_count + breach_count,
                "monitoring": {
                    "plan_count": len(code_plans),
                    "enabled_plan_count": len(enabled_plans),
                    "failed_plan_count": failed_plan_count,
                    "next_run_at": min(
                        (self._iso_utc(item.next_run_at) for item in enabled_plans),
                        default=None,
                    ),
                    "latest_plan_run_at": max(
                        (self._iso_utc(item.last_run_at) for item in code_plans if item.last_run_at),
                        default=None,
                    ),
                },
                "open_events": {
                    "total": len(event_payloads),
                    "critical": critical_count,
                    "warning": sum(item["severity"] == "warning" for item in event_payloads),
                    "overdue": overdue_count,
                    "due_soon": sum(item["sla_status"] == "due_soon" for item in event_payloads),
                },
            })

        status_counts = {key: sum(row["status"] == key for row in rows) for key in ("healthy", "attention", "blocked", "invalid", "unmonitored")}
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "scorecard_count": len(rows),
                **{f"{key}_count": value for key, value in status_counts.items()},
                "open_event_count": sum(row["open_events"]["total"] for row in rows),
                "overdue_event_count": sum(row["open_events"]["overdue"] for row in rows),
                "enabled_plan_count": sum(row["monitoring"]["enabled_plan_count"] for row in rows),
            },
            "rows": rows,
        }

    @staticmethod
    def _portfolio_metric_health(point: dict | None) -> dict:
        if not point:
            return {}
        minimum_metrics = {"validation_auc", "validation_ks", "oot_auc", "oot_ks"}
        result = {}
        for key, value in point.get("metrics", {}).items():
            threshold = point.get("thresholds", {}).get(key)
            if not isinstance(value, (int, float)) or not isinstance(threshold, (int, float)):
                result[key] = {"value": value, "threshold": threshold, "direction": "min" if key in minimum_metrics else "max", "ratio": None, "status": "untestable"}
                continue
            direction = "min" if key in minimum_metrics else "max"
            if direction == "min":
                ratio = value / threshold if threshold else None
                breached = value < threshold
            else:
                ratio = threshold / value if value else None
                breached = value > threshold
            near = not breached and ratio is not None and ratio <= 1.1
            result[key] = {
                "value": value, "threshold": threshold, "direction": direction,
                "ratio": round(ratio, 6) if ratio is not None else None,
                "status": "breach" if breached else "near" if near else "healthy",
            }
        return result

    def list_monitoring_plans(self) -> list[dict]:
        rows = self.session.scalars(
            select(ScorecardValidationMonitoringPlan).order_by(
                ScorecardValidationMonitoringPlan.next_run_at, ScorecardValidationMonitoringPlan.code
            )
        ).all()
        return [self._monitoring_plan(row) for row in rows]

    def create_monitoring_plan(self, payload: dict, actor: str) -> dict:
        plan = self._validated_monitoring_plan_payload(payload)
        record = ScorecardValidationMonitoringPlan(
            id=str(uuid4()), code=plan["code"], name=plan["name"], description=plan["description"],
            scorecard_asset_id=plan["scorecard_asset_id"], validation_policy_id=plan["validation_policy_id"],
            training_dataset_id=plan["training_dataset_id"], validation_dataset_id=plan.get("validation_dataset_id"),
            oot_dataset_id=plan.get("oot_dataset_id"), run_config_json=plan["run_config"], cadence=plan["cadence"],
            timezone_name=plan["timezone_name"], enabled=plan["enabled"], next_run_at=self._as_utc(plan["next_run_at"]),
            owner=plan["owner"], created_by=actor, updated_by=actor,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("scorecard_validation_monitoring_plan", record.id, "monitoring_plan_created", actor, {"code": record.code, "scorecard_asset_id": record.scorecard_asset_id, "validation_policy_id": record.validation_policy_id, "cadence": record.cadence, "next_run_at": record.next_run_at.isoformat()})
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("持续验证计划编码已存在") from exc
        self.session.refresh(record)
        return self._monitoring_plan(record)

    def update_monitoring_plan(self, plan_id: str, expected: int, payload: dict, actor: str) -> dict:
        record = self._get_monitoring_plan(plan_id, expected)
        plan = self._validated_monitoring_plan_payload(payload)
        if plan["code"] != record.code:
            raise ValueError("持续验证计划编码创建后不可修改")
        for key in ("name", "description", "scorecard_asset_id", "validation_policy_id", "training_dataset_id", "validation_dataset_id", "oot_dataset_id", "cadence", "timezone_name", "enabled", "owner"):
            setattr(record, key, plan.get(key))
        record.run_config_json = plan["run_config"]
        record.next_run_at = self._as_utc(plan["next_run_at"])
        record.updated_by = actor
        self.audit.append("scorecard_validation_monitoring_plan", record.id, "monitoring_plan_updated", actor, {"code": record.code, "enabled": record.enabled, "cadence": record.cadence, "next_run_at": record.next_run_at.isoformat()})
        self._commit("持续验证计划更新发生并发冲突")
        self.session.refresh(record)
        return self._monitoring_plan(record)

    def run_monitoring_plan(self, plan_id: str, expected: int, actor: str, actor_name: str, *, scheduled_for: datetime | None = None, advance: bool = False) -> dict:
        record = self._get_monitoring_plan(plan_id, expected)
        due_at = self._as_utc(scheduled_for or datetime.now(timezone.utc))
        run_key = f"{record.id}:{due_at.isoformat()}"
        if record.last_run_key == run_key and record.last_run_id:
            run = self.session.get(ScorecardDevelopmentRun, record.last_run_id)
            return {"plan": self._monitoring_plan(record), "run": self._development_run(run) if run else None, "events": [], "idempotent": True}
        try:
            snapshot_ids = {
                "dataset_snapshot_id": self._latest_dataset_snapshot(record.training_dataset_id, due_at).id,
                "validation_snapshot_id": self._latest_dataset_snapshot(record.validation_dataset_id, due_at).id if record.validation_dataset_id else None,
                "oot_snapshot_id": self._latest_dataset_snapshot(record.oot_dataset_id, due_at).id if record.oot_dataset_id else None,
            }
            payload = {
                **deepcopy(record.run_config_json), **snapshot_ids,
                "scorecard_asset_id": record.scorecard_asset_id, "validation_policy_id": record.validation_policy_id,
                "validation_thresholds": {}, "observation_start": None, "observation_end": None,
            }
            run = self.create_development_run(payload, actor, actor_name)
            events = self._scan_monitoring_run(record, run, actor)
            record = self.session.get(ScorecardValidationMonitoringPlan, plan_id)
            record.last_scheduled_for = due_at if advance else record.last_scheduled_for
            record.last_run_at = datetime.now(timezone.utc)
            record.last_run_id = run["id"]
            record.last_run_key = run_key
            record.last_status = "completed"
            record.last_error = None
            if advance:
                next_run = self._advance_schedule(due_at, record.cadence)
                while next_run <= due_at:
                    next_run = self._advance_schedule(next_run, record.cadence)
                record.next_run_at = next_run
            record.updated_by = actor
            self.audit.append("scorecard_validation_monitoring_plan", record.id, "monitoring_plan_executed", actor, {"scheduled_for": due_at.isoformat(), "run_id": run["id"], "event_ids": [item["id"] for item in events], "advance": advance})
            self._commit("持续验证计划执行状态更新发生并发冲突")
            self.session.refresh(record)
            return {"plan": self._monitoring_plan(record), "run": run, "events": events, "idempotent": False}
        except (LookupError, ValueError) as exc:
            self.session.rollback()
            record = self.session.get(ScorecardValidationMonitoringPlan, plan_id)
            record.last_scheduled_for = due_at if advance else record.last_scheduled_for
            record.last_run_at = datetime.now(timezone.utc)
            record.last_run_key = run_key
            record.last_status = "failed"
            record.last_error = str(exc)[:2000]
            record.updated_by = actor
            event = self._upsert_monitoring_event(record, None, actor, "scheduled_run_failed", "critical", "持续验证运行失败", str(exc), dedup_suffix=run_key, details={"scheduled_for": due_at.isoformat()})
            self._commit("持续验证失败状态写入发生并发冲突")
            self.session.refresh(record)
            return {"plan": self._monitoring_plan(record), "run": None, "events": [event], "idempotent": False}

    def run_due_monitoring_plans(self, as_of: datetime, max_plans: int, actor: str, actor_name: str, *, progress_callback=None) -> dict:
        point = self._as_utc(as_of)
        rows = self.session.scalars(select(ScorecardValidationMonitoringPlan).where(
            ScorecardValidationMonitoringPlan.enabled.is_(True), ScorecardValidationMonitoringPlan.next_run_at <= point,
        ).order_by(ScorecardValidationMonitoringPlan.next_run_at, ScorecardValidationMonitoringPlan.id).limit(max_plans)).all()
        results = []
        for index, row in enumerate(rows, start=1):
            result = self.run_monitoring_plan(row.id, row.row_version, actor, actor_name, scheduled_for=row.next_run_at, advance=True)
            results.append(result)
            if progress_callback:
                progress_callback(index, len(rows), result)
        return {"as_of": point.isoformat(), "due_count": len(rows), "completed_count": sum(item["plan"]["last_status"] == "completed" for item in results), "failed_count": sum(item["plan"]["last_status"] == "failed" for item in results), "results": results}

    def run_monitoring_scheduler(
        self,
        as_of: datetime,
        max_plans: int,
        actor: str,
        actor_name: str,
        *,
        run_key: str | None = None,
        trigger_type: str = "manual",
        recovery_of_run_id: str | None = None,
        recovery_reason: str | None = None,
        attempt_number: int = 1,
    ) -> dict:
        point = self._as_utc(as_of)
        if trigger_type not in {"manual", "scheduler", "retry", "recovery"}:
            raise ValueError("持续验证调度触发类型无效")
        effective_key = run_key or self.monitoring_scheduler_run_key(point)
        if not 5 <= len(effective_key) <= 128:
            raise ValueError("持续验证调度运行键长度必须为 5—128 个字符")
        existing = self.session.scalars(select(ScorecardMonitoringSchedulerRun).where(ScorecardMonitoringSchedulerRun.run_key == effective_key)).first()
        if existing:
            return {"run": self._monitoring_scheduler_run(existing), "tick": deepcopy(existing.details_json).get("tick"), "deduplicated": True}

        execution_id = str(uuid4())
        lease = self._acquire_monitoring_scheduler_lease(execution_id, effective_key, actor, trigger_type, point)
        if lease["status"] == "busy":
            return {"run": None, "tick": None, "deduplicated": False, "status": "skipped", "skip_reason": "scheduler_busy", "active_lease": lease}

        backlog_before, oldest_due_at = self._monitoring_backlog(point)
        started_at = datetime.now(timezone.utc)
        scheduler_run = ScorecardMonitoringSchedulerRun(
            id=str(uuid4()), run_key=effective_key, trigger_type=trigger_type, status="running", as_of=point,
            started_at=started_at, last_heartbeat_at=started_at, actor=actor, attempt_number=attempt_number,
            recovery_of_run_id=recovery_of_run_id, recovery_reason=recovery_reason,
            backlog_before=backlog_before, oldest_due_at=oldest_due_at, details_json={"max_plans": max_plans},
        )
        self.session.add(scheduler_run)
        self.audit.append("scorecard_monitoring_scheduler_run", scheduler_run.id, "scheduler_run_started", actor, {
            "run_key": effective_key, "trigger_type": trigger_type, "as_of": point.isoformat(),
            "attempt_number": attempt_number, "backlog_before": backlog_before,
        })
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            self._release_monitoring_scheduler_lease(execution_id)
            concurrent = self.session.scalars(select(ScorecardMonitoringSchedulerRun).where(ScorecardMonitoringSchedulerRun.run_key == effective_key)).first()
            if concurrent:
                return {"run": self._monitoring_scheduler_run(concurrent), "tick": deepcopy(concurrent.details_json).get("tick"), "deduplicated": True}
            raise

        try:
            tick = self.run_due_monitoring_plans(
                point, max_plans, actor, actor_name,
                progress_callback=lambda completed, total, result: self._heartbeat_monitoring_scheduler(
                    execution_id, scheduler_run.id, completed, total, result
                ),
            )
            backlog_after, _ = self._monitoring_backlog(point)
            scheduler_run = self.session.get(ScorecardMonitoringSchedulerRun, scheduler_run.id)
            scheduler_run.due_count = tick["due_count"]
            scheduler_run.completed_count = tick["completed_count"]
            scheduler_run.failed_count = tick["failed_count"]
            scheduler_run.backlog_after = backlog_after
            scheduler_run.last_heartbeat_at = datetime.now(timezone.utc)
            scheduler_run.completed_at = datetime.now(timezone.utc)
            scheduler_run.status = (
                "completed" if tick["failed_count"] == 0
                else "dead_letter" if attempt_number >= self.MONITORING_SCHEDULER_MAX_ATTEMPTS
                else "partial_failed"
            )
            scheduler_run.details_json = {
                "max_plans": max_plans,
                "progress": deepcopy(scheduler_run.details_json or {}).get("progress"),
                "tick": tick,
            }
            self.audit.append("scorecard_monitoring_scheduler_run", scheduler_run.id, "scheduler_run_finished", actor, {
                "status": scheduler_run.status, "due_count": tick["due_count"], "completed_count": tick["completed_count"],
                "failed_count": tick["failed_count"], "backlog_after": backlog_after,
            })
            self._release_monitoring_scheduler_lease(execution_id, commit=False)
            self.session.commit()
            self.session.refresh(scheduler_run)
            return {"run": self._monitoring_scheduler_run(scheduler_run), "tick": tick, "deduplicated": False}
        except Exception as exc:
            self.session.rollback()
            scheduler_run = self.session.get(ScorecardMonitoringSchedulerRun, scheduler_run.id)
            scheduler_run.status = "dead_letter" if attempt_number >= self.MONITORING_SCHEDULER_MAX_ATTEMPTS else "failed"
            scheduler_run.error_type = type(exc).__name__
            scheduler_run.error_message = str(exc)[:2000]
            scheduler_run.completed_at = datetime.now(timezone.utc)
            scheduler_run.last_heartbeat_at = scheduler_run.completed_at
            backlog_after, _ = self._monitoring_backlog(point)
            scheduler_run.backlog_after = backlog_after
            self.audit.append("scorecard_monitoring_scheduler_run", scheduler_run.id, "scheduler_run_failed", actor, {
                "status": scheduler_run.status, "error_type": scheduler_run.error_type,
                "error_message": scheduler_run.error_message, "backlog_after": backlog_after,
            })
            self._release_monitoring_scheduler_lease(execution_id, commit=False)
            self.session.commit()
            self.session.refresh(scheduler_run)
            return {"run": self._monitoring_scheduler_run(scheduler_run), "tick": None, "deduplicated": False}

    def retry_monitoring_scheduler_run(self, run_id: str, reason: str, actor: str, actor_name: str, max_plans: int = 50) -> dict:
        record = self.session.get(ScorecardMonitoringSchedulerRun, run_id)
        if record is None:
            raise LookupError("持续验证调度运行不存在")
        normalized_reason = reason.strip()
        if not 5 <= len(normalized_reason) <= 1000:
            raise ValueError("恢复原因长度必须为 5—1000 个字符")
        if record.status not in {"partial_failed", "failed", "dead_letter"}:
            raise ValueError("只有失败或死信运行可以恢复")
        is_dead_letter = record.status == "dead_letter"
        if is_dead_letter and self.session.scalar(select(func.count()).select_from(ScorecardMonitoringSchedulerRun).where(
            ScorecardMonitoringSchedulerRun.recovery_of_run_id == record.id,
            ScorecardMonitoringSchedulerRun.trigger_type == "recovery",
        )):
            raise ValueError("该死信运行已经发起人工恢复，不能重复执行")
        if not is_dead_letter and record.attempt_number >= self.MONITORING_SCHEDULER_MAX_ATTEMPTS:
            raise ValueError("自动重试次数已用尽，请从死信执行人工恢复")
        next_attempt = 1 if is_dead_letter else record.attempt_number + 1
        trigger_type = "recovery" if is_dead_letter else "retry"
        run_key = f"scorecard-recovery:{record.id}:{trigger_type}:{next_attempt}"
        return self.run_monitoring_scheduler(
            datetime.now(timezone.utc), max_plans, actor, actor_name, run_key=run_key,
            trigger_type=trigger_type, recovery_of_run_id=record.id,
            recovery_reason=normalized_reason, attempt_number=next_attempt,
        )

    def monitoring_scheduler_health(self, as_of: datetime | None = None, max_runs: int = 20) -> dict:
        point = self._as_utc(as_of or datetime.now(timezone.utc))
        backlog_count, oldest_due_at = self._monitoring_backlog(point)
        rows = self.session.scalars(select(ScorecardMonitoringSchedulerRun).order_by(
            ScorecardMonitoringSchedulerRun.started_at.desc(), ScorecardMonitoringSchedulerRun.id.desc()
        ).limit(max_runs)).all()
        runs = [self._monitoring_scheduler_run(row) for row in rows]
        lease = self._monitoring_scheduler_lease(point)
        scheduler_runs = [row for row in rows if row.trigger_type == "scheduler"]
        latest_scheduler = scheduler_runs[0] if scheduler_runs else None
        latest_scheduler_at = self._as_utc(latest_scheduler.started_at) if latest_scheduler else None
        minutes_since_scheduler = max(0, int((point - latest_scheduler_at).total_seconds() // 60)) if latest_scheduler_at else None
        recovered_dead_letters = select(ScorecardMonitoringSchedulerRun.recovery_of_run_id).where(
            ScorecardMonitoringSchedulerRun.trigger_type == "recovery",
            ScorecardMonitoringSchedulerRun.recovery_of_run_id.is_not(None),
        )
        dead_letter_count = self.session.scalar(select(func.count()).select_from(ScorecardMonitoringSchedulerRun).where(
            ScorecardMonitoringSchedulerRun.status == "dead_letter",
            ScorecardMonitoringSchedulerRun.id.not_in(recovered_dead_letters),
        )) or 0
        failed_unrecovered = sum(item["status"] in {"partial_failed", "failed"} for item in runs)
        health = (
            "blocked" if dead_letter_count or lease["status"] == "expired"
            else "degraded" if backlog_count or failed_unrecovered or (minutes_since_scheduler is not None and minutes_since_scheduler > self.MONITORING_SCHEDULER_STALE_AFTER_MINUTES)
            else "never" if latest_scheduler is None
            else "healthy"
        )
        oldest_age_seconds = max(0, int((point - self._as_utc(oldest_due_at)).total_seconds())) if oldest_due_at else 0
        return {
            "generated_at": point.isoformat(), "health": health,
            "expected_cadence_minutes": self.MONITORING_SCHEDULER_EXPECTED_CADENCE_MINUTES,
            "stale_after_minutes": self.MONITORING_SCHEDULER_STALE_AFTER_MINUTES,
            "max_attempts": self.MONITORING_SCHEDULER_MAX_ATTEMPTS,
            "lease": lease,
            "backlog": {"count": backlog_count, "oldest_due_at": self._iso_utc(oldest_due_at), "oldest_age_seconds": oldest_age_seconds},
            "scheduler": {
                "last_run_at": self._iso_utc(latest_scheduler.started_at) if latest_scheduler else None,
                "last_status": latest_scheduler.status if latest_scheduler else None,
                "minutes_since_last_run": minutes_since_scheduler,
                "next_expected_at": self._iso_utc(latest_scheduler_at + timedelta(minutes=self.MONITORING_SCHEDULER_EXPECTED_CADENCE_MINUTES)) if latest_scheduler_at else None,
            },
            "summary": {
                "returned_runs": len(runs), "completed": sum(item["status"] == "completed" for item in runs),
                "failed": sum(item["status"] in {"partial_failed", "failed"} for item in runs),
                "dead_letter": dead_letter_count, "running": sum(item["status"] == "running" for item in runs),
            },
            "runs": runs,
        }

    @classmethod
    def monitoring_scheduler_run_key(cls, as_of: datetime) -> str:
        point = cls._as_utc(as_of)
        minute = point.minute - point.minute % cls.MONITORING_SCHEDULER_EXPECTED_CADENCE_MINUTES
        window = point.replace(minute=minute, second=0, microsecond=0)
        return f"scorecard-monitoring:{window.strftime('%Y%m%dT%H%MZ')}"

    def list_monitoring_events(
        self, status: str | None = None, plan_id: str | None = None, *, severity: str | None = None,
        event_type: str | None = None, assignee: str | None = None, scorecard_code: str | None = None,
        sla_status: str | None = None,
    ) -> list[dict]:
        statement = select(ScorecardValidationMonitoringEvent)
        if status:
            statement = statement.where(ScorecardValidationMonitoringEvent.status == status)
        if plan_id:
            statement = statement.where(ScorecardValidationMonitoringEvent.plan_id == plan_id)
        if severity:
            statement = statement.where(ScorecardValidationMonitoringEvent.severity == severity)
        if event_type:
            statement = statement.where(ScorecardValidationMonitoringEvent.event_type == event_type)
        if assignee:
            statement = statement.where(ScorecardValidationMonitoringEvent.assignee == assignee)
        if scorecard_code:
            statement = statement.join(
                ScorecardValidationMonitoringPlan,
                ScorecardValidationMonitoringPlan.id == ScorecardValidationMonitoringEvent.plan_id,
            ).join(
                ScorecardDefinition,
                ScorecardDefinition.id == ScorecardValidationMonitoringPlan.scorecard_asset_id,
            ).where(ScorecardDefinition.code == scorecard_code)
        rows = self.session.scalars(statement.order_by(ScorecardValidationMonitoringEvent.created_at.desc(), ScorecardValidationMonitoringEvent.id.desc())).all()
        events = [self._monitoring_event(row) for row in rows]
        return [item for item in events if not sla_status or item["sla_status"] == sla_status]

    def bulk_assign_monitoring_events(self, items: list[dict], assignee: str, reason: str, actor: str, actor_name: str) -> dict:
        ids = [item["event_id"] for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("批量分派不能包含重复预警")
        records = {record.id: record for record in self.session.scalars(
            select(ScorecardValidationMonitoringEvent).where(ScorecardValidationMonitoringEvent.id.in_(ids))
        ).all()}
        for item in items:
            record = records.get(item["event_id"])
            if record is None:
                raise LookupError(f"持续验证预警不存在：{item['event_id']}")
            if record.row_version != item["expected_row_version"]:
                raise ConcurrentUpdateError(f"预警 {record.id} 已被更新，请刷新后重试")
            if record.status == "closed":
                raise ValueError(f"已关闭预警不能重新分派：{record.id}")
        batch_id = str(uuid4())
        for item in items:
            record = records[item["event_id"]]
            previous_assignee = record.assignee
            record.assignee = assignee
            self.audit.append("scorecard_validation_monitoring_event", record.id, "monitoring_event_bulk_assigned", actor, {
                "batch_id": batch_id, "previous_assignee": previous_assignee, "assignee": assignee,
                "reason": reason, "actor_name": actor_name,
            })
        self.audit.append("scorecard_monitoring_bulk_assignment", batch_id, "monitoring_events_bulk_assigned", actor, {
            "event_ids": ids, "count": len(ids), "assignee": assignee, "reason": reason, "actor_name": actor_name,
        })
        self._commit("批量分派发生并发冲突，请刷新后重试")
        for record in records.values():
            self.session.refresh(record)
        return {"batch_id": batch_id, "assigned_count": len(ids), "assignee": assignee, "events": [self._monitoring_event(records[item["event_id"]]) for item in items]}

    def export_monitoring_events_csv(self, filters: dict) -> str:
        events = self.list_monitoring_events(**filters)
        plan_ids = {item["plan_id"] for item in events}
        plans = {item.id: item for item in self.session.scalars(select(ScorecardValidationMonitoringPlan).where(
            ScorecardValidationMonitoringPlan.id.in_(plan_ids)
        )).all()} if plan_ids else {}
        asset_ids = {item.scorecard_asset_id for item in plans.values()}
        assets = {item.id: item for item in self.session.scalars(select(ScorecardDefinition).where(
            ScorecardDefinition.id.in_(asset_ids)
        )).all()} if asset_ids else {}
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["预警编号", "计划编码", "评分卡", "预警类型", "严重级别", "处置状态", "责任人", "SLA状态", "SLA开始", "SLA截止", "升级级别", "SLA策略", "SLA快照哈希", "指标", "指标值", "阈值", "运行编号", "证据哈希", "创建时间"])
        for event in events:
            plan = plans.get(event["plan_id"])
            asset = assets.get(plan.scorecard_asset_id) if plan else None
            snapshot = event.get("sla_policy_snapshot") or {}
            writer.writerow([
                event["id"], plan.code if plan else "", f"{asset.code}@v{asset.version}" if asset else "",
                event["event_type"], event["severity"], event["status"], event["assignee"] or "", event["sla_status"],
                event["sla_started_at"], event["sla_due_at"], event["escalation_level"],
                f"{snapshot.get('code', '')}@v{snapshot.get('version', '')}", event["sla_policy_snapshot_hash"] or "",
                event["metric_key"] or "", event["metric_value"] if event["metric_value"] is not None else "",
                f"{event['threshold_operator'] or ''}{event['threshold_value'] if event['threshold_value'] is not None else ''}",
                event["run_id"] or "", event["evidence_hash"] or "", event["created_at"],
            ])
        return "\ufeff" + output.getvalue()

    def list_monitoring_saved_views(self, owner_subject: str) -> list[dict]:
        rows = self.session.scalars(select(ScorecardMonitoringSavedView).where(
            ScorecardMonitoringSavedView.owner_subject == owner_subject
        ).order_by(ScorecardMonitoringSavedView.is_default.desc(), ScorecardMonitoringSavedView.name)).all()
        return [self._monitoring_saved_view(row) for row in rows]

    def create_monitoring_saved_view(self, payload: dict, owner_subject: str) -> dict:
        count = self.session.scalar(select(func.count(ScorecardMonitoringSavedView.id)).where(
            ScorecardMonitoringSavedView.owner_subject == owner_subject
        )) or 0
        if count >= 20:
            raise ValueError("每位用户最多保存 20 个预警视图")
        if payload["is_default"]:
            self._clear_default_monitoring_view(owner_subject)
        record = ScorecardMonitoringSavedView(
            id=str(uuid4()), owner_subject=owner_subject, name=payload["name"],
            filters_json=deepcopy(payload["filters"]), is_default=payload["is_default"],
        )
        self.session.add(record)
        self.audit.append("scorecard_monitoring_saved_view", record.id, "monitoring_saved_view_created", owner_subject, {"name": record.name, "filters": record.filters_json, "is_default": record.is_default})
        self._commit("保存视图名称已存在，请使用其他名称")
        self.session.refresh(record)
        return self._monitoring_saved_view(record)

    def update_monitoring_saved_view(self, view_id: str, expected: int, payload: dict, owner_subject: str) -> dict:
        record = self._owned_monitoring_saved_view(view_id, owner_subject)
        if record.row_version != expected:
            raise ConcurrentUpdateError("保存视图已被更新，请刷新后重试")
        if payload["is_default"]:
            self._clear_default_monitoring_view(owner_subject, exclude_id=record.id)
        record.name, record.filters_json, record.is_default = payload["name"], deepcopy(payload["filters"]), payload["is_default"]
        self.audit.append("scorecard_monitoring_saved_view", record.id, "monitoring_saved_view_updated", owner_subject, {"name": record.name, "filters": record.filters_json, "is_default": record.is_default})
        self._commit("保存视图更新发生冲突")
        self.session.refresh(record)
        return self._monitoring_saved_view(record)

    def delete_monitoring_saved_view(self, view_id: str, expected: int, owner_subject: str) -> None:
        record = self._owned_monitoring_saved_view(view_id, owner_subject)
        if record.row_version != expected:
            raise ConcurrentUpdateError("保存视图已被更新，请刷新后重试")
        self.audit.append("scorecard_monitoring_saved_view", record.id, "monitoring_saved_view_deleted", owner_subject, {"name": record.name})
        self.session.delete(record)
        self._commit("保存视图删除发生冲突")

    def _owned_monitoring_saved_view(self, view_id: str, owner_subject: str) -> ScorecardMonitoringSavedView:
        record = self.session.get(ScorecardMonitoringSavedView, view_id)
        if record is None or record.owner_subject != owner_subject:
            raise LookupError("保存视图不存在")
        return record

    def _clear_default_monitoring_view(self, owner_subject: str, exclude_id: str | None = None) -> None:
        statement = select(ScorecardMonitoringSavedView).where(
            ScorecardMonitoringSavedView.owner_subject == owner_subject,
            ScorecardMonitoringSavedView.is_default.is_(True),
        )
        if exclude_id:
            statement = statement.where(ScorecardMonitoringSavedView.id != exclude_id)
        for record in self.session.scalars(statement).all():
            record.is_default = False

    def action_monitoring_event(self, event_id: str, expected: int, payload: dict, actor: str, actor_name: str) -> dict:
        record = self.session.get(ScorecardValidationMonitoringEvent, event_id)
        if record is None:
            raise LookupError("持续验证预警不存在")
        if record.row_version != expected:
            raise ConcurrentUpdateError("持续验证预警已被更新，请刷新后重试")
        action = payload["action"]
        now = datetime.now(timezone.utc)
        if action == "assign":
            if not payload.get("assignee") or record.status == "closed":
                raise ValueError("仅未关闭预警可以分派，且必须指定责任人")
            record.assignee = payload["assignee"]
        elif action == "acknowledge":
            if record.status not in {"open", "acknowledged"}:
                raise ValueError("只有待确认预警可以确认")
            record.status, record.acknowledged_by, record.acknowledged_at = "acknowledged", actor, now
        elif action == "remediate":
            if record.status not in {"open", "acknowledged", "in_remediation"} or not payload.get("remediation_plan"):
                raise ValueError("进入处置必须提供整改计划")
            record.status, record.remediation_plan = "in_remediation", payload["remediation_plan"]
            if payload.get("assignee"):
                record.assignee = payload["assignee"]
        elif action == "submit_revalidation":
            if record.status != "in_remediation" or not payload.get("remediation_result") or not payload.get("revalidation_run_id"):
                raise ValueError("只有处置中的预警可以提交复验，且必须填写整改结果并选择新验证运行")
            run_record = self.session.get(ScorecardDevelopmentRun, payload["revalidation_run_id"])
            if run_record is None:
                raise LookupError("复验运行不存在")
            run = self._development_run(run_record)
            plan = self.session.get(ScorecardValidationMonitoringPlan, record.plan_id)
            if plan is None or run["scorecard_asset_id"] != plan.scorecard_asset_id:
                raise ValueError("复验运行必须属于预警计划固定的评分卡版本")
            if run["id"] == record.run_id:
                raise ValueError("复验必须选择预警发生后重新生成的验证运行")
            if run.get("validation_policy_id") != plan.validation_policy_id or not run.get("validation_policy_integrity_valid"):
                raise ValueError("复验运行必须固定预警计划的验证策略且策略证据完整")
            if not run.get("integrity_valid"):
                raise ValueError("复验运行证据完整性校验失败")
            if not ((run.get("report") or {}).get("validation_gate") or {}).get("passed"):
                raise ValueError("复验运行门禁未通过，不能提交独立复验")
            record.status, record.remediation_result = "pending_revalidation", payload["remediation_result"]
            record.remediated_by, record.remediated_at = actor, now
            record.revalidation_run_id, record.revalidation_evidence_hash = run["id"], run["evidence_hash"]
            self._notify_monitoring_event(record, plan, "pending_revalidation")
        elif action == "review_revalidation":
            if record.status != "pending_revalidation" or payload.get("decision") not in {"pass", "fail"} or not payload.get("conclusion"):
                raise ValueError("只有待复验预警可以审核，且必须填写复验结论")
            if actor == record.remediated_by:
                raise PermissionError("整改执行人与独立复验人必须分离")
            record.revalidation_conclusion = payload["conclusion"]
            record.revalidated_by, record.revalidated_by_name, record.revalidated_at = actor, actor_name, now
            if payload["decision"] == "pass":
                record.status, record.closed_by, record.closed_at = "closed", actor, now
                plan = self.session.get(ScorecardValidationMonitoringPlan, record.plan_id)
                if plan:
                    self._notify_monitoring_event(record, plan, "closed")
            else:
                record.status, record.closed_by, record.closed_at = "in_remediation", None, None
        else:
            raise ValueError("未知持续验证预警动作")
        self.audit.append("scorecard_validation_monitoring_event", record.id, f"monitoring_event_{action}", actor, {
            "assignee": record.assignee, "status": record.status, "revalidation_run_id": record.revalidation_run_id,
            "decision": payload.get("decision"),
        })
        self._commit("持续验证预警处置发生并发冲突")
        self.session.refresh(record)
        return self._monitoring_event(record)

    def scan_monitoring_event_sla(self, as_of: datetime, actor: str, *, commit: bool = True) -> dict:
        scan_time = self._as_utc(as_of)
        rows = self.session.scalars(select(ScorecardValidationMonitoringEvent).where(
            ScorecardValidationMonitoringEvent.status != "closed",
            ScorecardValidationMonitoringEvent.sla_due_at.is_not(None),
        ).order_by(ScorecardValidationMonitoringEvent.sla_due_at, ScorecardValidationMonitoringEvent.id)).all()
        plans = {item.id: item for item in self.session.scalars(select(ScorecardValidationMonitoringPlan).where(
            ScorecardValidationMonitoringPlan.id.in_({item.plan_id for item in rows})
        )).all()} if rows else {}
        counts: dict[str, int] = {"due_soon": 0, "overdue": 0, "escalated": 0}
        notification_count = 0
        for record in rows:
            level = self.monitoring_event_sla_level(record, scan_time)
            if level == "normal":
                continue
            counts[level] += 1
            if level == "overdue" and record.escalation_level < 1:
                record.escalation_level = 1
            elif level == "escalated" and record.escalation_level < 2:
                record.escalation_level = 2
                record.last_escalated_at = scan_time
            plan = plans.get(record.plan_id)
            created = self._notify_monitoring_event(record, plan, level) if plan else 0
            notification_count += created
            if created:
                self.audit.append("scorecard_validation_monitoring_event", record.id, f"monitoring_event_sla_{level}", actor, {
                    "sla_due_at": self._iso_utc(record.sla_due_at), "escalation_level": record.escalation_level,
                    "notifications_created": created,
                })
        if commit:
            self._commit("持续验证预警 SLA 扫描发生并发冲突")
        return {
            "events_scanned": len(rows), "due_soon": counts["due_soon"], "overdue": counts["overdue"],
            "escalated": counts["escalated"], "notifications_created": notification_count,
        }

    @classmethod
    def monitoring_event_sla_level(cls, record: ScorecardValidationMonitoringEvent, now: datetime) -> str:
        due_at = cls._as_utc(record.sla_due_at)
        started_at = cls._as_utc(record.sla_started_at)
        remaining = (due_at - cls._as_utc(now)).total_seconds()
        snapshot = record.sla_policy_snapshot_json or {}
        rules = snapshot.get("severity_rules") or cls.DEFAULT_MONITORING_SLA_RULES
        rule = rules.get(record.severity) or rules.get("warning") or cls.DEFAULT_MONITORING_SLA_RULES["warning"]
        escalation_after_seconds = float(rule.get("escalation_after_hours", 4)) * 3600
        if remaining <= -escalation_after_seconds:
            return "escalated"
        if remaining < 0:
            return "overdue"
        total = max(1, (due_at - started_at).total_seconds())
        return "due_soon" if remaining <= total * float(rule.get("due_soon_ratio", 0.25)) else "normal"

    def list_monitoring_sla_policies(self) -> list[dict]:
        rows = self.session.scalars(select(ScorecardMonitoringSlaPolicy).order_by(
            ScorecardMonitoringSlaPolicy.code, ScorecardMonitoringSlaPolicy.version.desc()
        )).all()
        return [self._monitoring_sla_policy(row) for row in rows]

    def create_monitoring_sla_policy(self, payload: dict, reason: str, actor: str, actor_name: str) -> dict:
        config = self._normalized_monitoring_sla_policy(payload)
        inflight = self.session.scalars(select(ScorecardMonitoringSlaPolicy).where(
            ScorecardMonitoringSlaPolicy.code == config["code"],
            ScorecardMonitoringSlaPolicy.status.in_({"draft", "submitted"}),
        )).first()
        if inflight:
            raise ValueError(f"SLA 策略 {config['code']} 已存在在途版本")
        latest = self.session.scalar(select(func.max(ScorecardMonitoringSlaPolicy.version)).where(
            ScorecardMonitoringSlaPolicy.code == config["code"]
        )) or 0
        record = ScorecardMonitoringSlaPolicy(
            id=str(uuid4()), code=config["code"], name=config["name"], description=config["description"],
            version=latest + 1, status="draft", is_active=False, is_default=config["is_default"],
            applicable_scorecard_codes=config["applicable_scorecard_codes"],
            applicable_event_types=config["applicable_event_types"], severity_rules_json=config["severity_rules"],
            config_hash=content_hash(config), change_reason=reason, created_by=actor, created_by_name=actor_name,
        )
        self.session.add(record)
        self.audit.append("scorecard_monitoring_sla_policy", record.id, "monitoring_sla_policy_draft_created", actor_name, {"code": record.code, "version": record.version, "config_hash": record.config_hash})
        self._commit("SLA 策略草稿创建发生并发冲突")
        self.session.refresh(record)
        return self._monitoring_sla_policy(record)

    def update_monitoring_sla_policy(self, policy_id: str, expected: int, payload: dict, reason: str, actor: str, is_admin: bool) -> dict:
        record = self._get_monitoring_sla_policy(policy_id)
        self._check_policy_version(record, expected)
        if record.status != "draft":
            raise ValueError("只有草稿状态可以修改")
        if record.created_by != actor and not is_admin:
            raise PermissionError("只能修改本人创建的 SLA 策略草稿")
        config = self._normalized_monitoring_sla_policy(payload)
        if config["code"] != record.code:
            raise ValueError("SLA 策略编码创建后不可修改")
        record.name, record.description = config["name"], config["description"]
        record.is_default = config["is_default"]
        record.applicable_scorecard_codes = config["applicable_scorecard_codes"]
        record.applicable_event_types = config["applicable_event_types"]
        record.severity_rules_json, record.config_hash, record.change_reason = config["severity_rules"], content_hash(config), reason
        self.audit.append("scorecard_monitoring_sla_policy", record.id, "monitoring_sla_policy_draft_updated", actor, {"config_hash": record.config_hash})
        self._commit("SLA 策略草稿更新发生并发冲突")
        self.session.refresh(record)
        return self._monitoring_sla_policy(record)

    def submit_monitoring_sla_policy(self, policy_id: str, expected: int, actor: str, is_admin: bool) -> dict:
        record = self._get_monitoring_sla_policy(policy_id)
        self._check_policy_version(record, expected)
        if record.status != "draft":
            raise ValueError("只有草稿状态可以提交")
        if record.created_by != actor and not is_admin:
            raise PermissionError("只能提交本人创建的 SLA 策略草稿")
        if record.config_hash != content_hash(self._monitoring_sla_policy_config(record)):
            raise ValueError("SLA 策略配置哈希不一致")
        record.status, record.submitted_at = "submitted", datetime.now(timezone.utc)
        self.audit.append("scorecard_monitoring_sla_policy", record.id, "monitoring_sla_policy_submitted", actor, {"config_hash": record.config_hash})
        self._commit("SLA 策略提交发生并发冲突")
        self.session.refresh(record)
        return self._monitoring_sla_policy(record)

    def review_monitoring_sla_policy(self, policy_id: str, expected: int, decision: str, comment: str, actor: str, actor_name: str) -> dict:
        record = self._get_monitoring_sla_policy(policy_id)
        self._check_policy_version(record, expected)
        if record.status != "submitted":
            raise ValueError("只有待复核 SLA 策略可以审核")
        if record.created_by == actor:
            raise PermissionError("提交人不能复核自己的 SLA 策略")
        if record.config_hash != content_hash(self._monitoring_sla_policy_config(record)):
            raise ValueError("SLA 策略配置哈希不一致")
        now = datetime.now(timezone.utc)
        record.reviewed_by, record.reviewed_by_name = actor, actor_name
        record.review_comment, record.reviewed_at = comment, now
        if decision == "reject":
            record.status = "rejected"
        else:
            active_records = list(self.session.scalars(select(ScorecardMonitoringSlaPolicy).where(
                ScorecardMonitoringSlaPolicy.code == record.code, ScorecardMonitoringSlaPolicy.is_active.is_(True)
            )).all())
            if record.is_default:
                active_records.extend(self.session.scalars(select(ScorecardMonitoringSlaPolicy).where(
                    ScorecardMonitoringSlaPolicy.is_active.is_(True), ScorecardMonitoringSlaPolicy.is_default.is_(True),
                    ScorecardMonitoringSlaPolicy.code != record.code,
                )).all())
            for item in {item.id: item for item in active_records}.values():
                item.is_active = False
            self.session.flush()
            record.status, record.is_active, record.published_at = "published", True, now
        self.audit.append("scorecard_monitoring_sla_policy", record.id, f"monitoring_sla_policy_{record.status}", actor_name, {"comment": comment, "config_hash": record.config_hash})
        self._commit("SLA 策略审核发生并发冲突")
        self.session.refresh(record)
        return self._monitoring_sla_policy(record)

    def list_validation_policies(self) -> list[dict]:
        rows = self.session.scalars(
            select(ScorecardValidationPolicy).order_by(
                ScorecardValidationPolicy.code, ScorecardValidationPolicy.version.desc()
            )
        ).all()
        return [self._validation_policy(row) for row in rows]

    def create_validation_policy(self, payload: dict, reason: str, actor: str, actor_name: str) -> dict:
        config = self._normalized_validation_policy(payload)
        inflight = self.session.scalars(select(ScorecardValidationPolicy).where(
            ScorecardValidationPolicy.code == config["code"],
            ScorecardValidationPolicy.status.in_({"draft", "submitted"}),
        )).first()
        if inflight:
            raise ValueError(f"验证策略 {config['code']} 已存在在途版本")
        latest = self.session.scalar(select(func.max(ScorecardValidationPolicy.version)).where(ScorecardValidationPolicy.code == config["code"])) or 0
        record = ScorecardValidationPolicy(
            id=str(uuid4()), code=config["code"], name=config["name"], description=config["description"],
            version=latest + 1, status="draft", is_active=False, is_default=config["is_default"],
            applicable_scorecard_codes=config["applicable_scorecard_codes"], thresholds_json=config["thresholds"],
            config_hash=content_hash(config), change_reason=reason, created_by=actor, created_by_name=actor_name,
        )
        self.session.add(record)
        self.audit.append("scorecard_validation_policy", record.id, "validation_policy_draft_created", actor_name, {"code": record.code, "version": record.version, "config_hash": record.config_hash})
        self._commit("验证策略草稿创建发生并发冲突")
        self.session.refresh(record)
        return self._validation_policy(record)

    def update_validation_policy(self, policy_id: str, expected: int, payload: dict, reason: str, actor: str, is_admin: bool) -> dict:
        record = self._get_validation_policy(policy_id)
        self._check_policy_version(record, expected)
        if record.status != "draft":
            raise ValueError("只有草稿状态可以修改")
        if record.created_by != actor and not is_admin:
            raise PermissionError("只能修改本人创建的验证策略草稿")
        config = self._normalized_validation_policy(payload)
        if config["code"] != record.code:
            raise ValueError("验证策略编码创建后不可修改")
        record.name, record.description = config["name"], config["description"]
        record.is_default = config["is_default"]
        record.applicable_scorecard_codes = config["applicable_scorecard_codes"]
        record.thresholds_json, record.config_hash, record.change_reason = config["thresholds"], content_hash(config), reason
        self.audit.append("scorecard_validation_policy", record.id, "validation_policy_draft_updated", actor, {"config_hash": record.config_hash})
        self._commit("验证策略草稿更新发生并发冲突")
        self.session.refresh(record)
        return self._validation_policy(record)

    def submit_validation_policy(self, policy_id: str, expected: int, actor: str, is_admin: bool) -> dict:
        record = self._get_validation_policy(policy_id)
        self._check_policy_version(record, expected)
        if record.status != "draft":
            raise ValueError("只有草稿状态可以提交")
        if record.created_by != actor and not is_admin:
            raise PermissionError("只能提交本人创建的验证策略草稿")
        if record.config_hash != content_hash(self._policy_config(record)):
            raise ValueError("验证策略配置哈希不一致")
        record.status, record.submitted_at = "submitted", datetime.now(timezone.utc)
        self.audit.append("scorecard_validation_policy", record.id, "validation_policy_submitted", actor, {"config_hash": record.config_hash})
        self._commit("验证策略提交发生并发冲突")
        self.session.refresh(record)
        return self._validation_policy(record)

    def review_validation_policy(self, policy_id: str, expected: int, decision: str, comment: str, actor: str, actor_name: str) -> dict:
        record = self._get_validation_policy(policy_id)
        self._check_policy_version(record, expected)
        if record.status != "submitted":
            raise ValueError("只有待复核验证策略可以审核")
        if record.created_by == actor:
            raise PermissionError("提交人不能复核自己的验证策略")
        if record.config_hash != content_hash(self._policy_config(record)):
            raise ValueError("验证策略配置哈希不一致")
        now = datetime.now(timezone.utc)
        record.reviewed_by, record.reviewed_by_name = actor, actor_name
        record.review_comment, record.reviewed_at = comment, now
        if decision == "reject":
            record.status = "rejected"
        else:
            for item in self.session.scalars(select(ScorecardValidationPolicy).where(
                ScorecardValidationPolicy.code == record.code, ScorecardValidationPolicy.is_active.is_(True)
            )).all():
                item.is_active = False
            if record.is_default:
                for item in self.session.scalars(select(ScorecardValidationPolicy).where(
                    ScorecardValidationPolicy.is_active.is_(True), ScorecardValidationPolicy.is_default.is_(True)
                )).all():
                    item.is_active = False
            record.status, record.is_active, record.published_at = "published", True, now
        self.audit.append("scorecard_validation_policy", record.id, f"validation_policy_{record.status}", actor_name, {"comment": comment, "config_hash": record.config_hash})
        self._commit("验证策略审核发生并发冲突")
        self.session.refresh(record)
        return self._validation_policy(record)

    def create_development_run(self, payload: dict, actor: str, actor_name: str) -> dict:
        asset = self.session.get(ScorecardDefinition, payload["scorecard_asset_id"])
        if asset is None or asset.status != "published":
            raise LookupError("已发布评分卡资产不存在")
        if content_hash(asset.config_json) != asset.config_hash:
            raise ValueError("评分卡资产配置哈希不一致")
        snapshot = self._verified_snapshot(payload["dataset_snapshot_id"], "训练集")
        validation_snapshot = self._verified_snapshot(payload.get("validation_snapshot_id"), "验证集") if payload.get("validation_snapshot_id") else None
        oot_snapshot = self._verified_snapshot(payload.get("oot_snapshot_id"), "时间外集") if payload.get("oot_snapshot_id") else None
        selected_ids = [item.id for item in (snapshot, validation_snapshot, oot_snapshot) if item]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("训练、验证和时间外集合必须选择不同的不可变快照")
        if payload.get("observation_start") and payload.get("observation_end") and payload["observation_start"] > payload["observation_end"]:
            raise ValueError("观察窗口开始日期不能晚于结束日期")
        segment_fields = payload.get("segment_fields") or []
        sensitive_fields = payload.get("sensitive_attribute_fields") or []
        if len(segment_fields) != len(set(segment_fields)) or len(sensitive_fields) != len(set(sensitive_fields)):
            raise ValueError("分群字段和敏感属性字段不能重复")
        if not set(sensitive_fields).issubset(segment_fields):
            raise ValueError("敏感属性字段必须同时包含在分群字段中")
        validation_policy = self._resolve_validation_policy(payload.get("validation_policy_id"), asset.code)
        policy = deepcopy(payload)
        policy.pop("scorecard_asset_id", None)
        policy.pop("validation_policy_id", None)
        policy.pop("dataset_snapshot_id", None)
        policy.pop("validation_snapshot_id", None)
        policy.pop("oot_snapshot_id", None)
        policy["observation_start"] = policy["observation_start"].isoformat() if policy.get("observation_start") else None
        policy["observation_end"] = policy["observation_end"].isoformat() if policy.get("observation_end") else None
        if validation_policy:
            policy["validation_thresholds"] = deepcopy(validation_policy.thresholds_json)
            policy["validation_policy"] = self._policy_snapshot(validation_policy)
        else:
            policy["validation_thresholds"] = {**DEFAULT_VALIDATION_THRESHOLDS, **(policy.get("validation_thresholds") or {})}
        snapshots = {
            "training": self._snapshot_payload(snapshot),
            "validation": self._snapshot_payload(validation_snapshot) if validation_snapshot else None,
            "oot": self._snapshot_payload(oot_snapshot) if oot_snapshot else None,
        }
        report = analyze_scorecard_validation(deepcopy(asset.config_json), snapshots, policy)
        evidence = {
            "scorecard_asset_id": asset.id, "scorecard_code": asset.code, "scorecard_version": asset.version,
            "scorecard_config_hash": asset.config_hash, "dataset_snapshot_id": snapshot.id,
            "dataset_snapshot_hash": snapshot.content_hash,
            "validation_snapshot_id": validation_snapshot.id if validation_snapshot else None,
            "validation_snapshot_hash": validation_snapshot.content_hash if validation_snapshot else None,
            "oot_snapshot_id": oot_snapshot.id if oot_snapshot else None,
            "oot_snapshot_hash": oot_snapshot.content_hash if oot_snapshot else None,
            "label_policy": policy, "report": report,
        }
        if validation_policy:
            evidence.update({"validation_policy_id": validation_policy.id, "validation_policy_hash": validation_policy.config_hash})
        record = ScorecardDevelopmentRun(
            id=str(uuid4()), scorecard_asset_id=asset.id, scorecard_code=asset.code,
            scorecard_version=asset.version, scorecard_config_hash=asset.config_hash,
            validation_policy_id=validation_policy.id if validation_policy else None,
            validation_policy_hash=validation_policy.config_hash if validation_policy else None,
            dataset_snapshot_id=snapshot.id, dataset_snapshot_hash=snapshot.content_hash,
            validation_snapshot_id=validation_snapshot.id if validation_snapshot else None,
            validation_snapshot_hash=validation_snapshot.content_hash if validation_snapshot else None,
            oot_snapshot_id=oot_snapshot.id if oot_snapshot else None,
            oot_snapshot_hash=oot_snapshot.content_hash if oot_snapshot else None,
            label_policy_json=policy, report_json=report, evidence_hash=content_hash(evidence),
            evidence_level=report["evidence_level"], review_status="pending_review",
            created_by=actor, created_by_name=actor_name,
        )
        self.session.add(record)
        self.session.flush()
        self.audit.append("scorecard_development_run", record.id, "scorecard_development_run_created", actor_name, {"scorecard_code": asset.code, "scorecard_version": asset.version, "dataset_snapshot_id": snapshot.id, "evidence_level": record.evidence_level, "evidence_hash": record.evidence_hash})
        self.session.commit()
        self.session.refresh(record)
        return self._development_run(record)

    def review_development_run(self, run_id: str, expected: int, decision: str, comment: str, actor: str, actor_name: str) -> dict:
        record = self.session.get(ScorecardDevelopmentRun, run_id)
        if record is None:
            raise LookupError("评分卡开发验证运行不存在")
        if record.row_version != expected:
            raise ConcurrentUpdateError("评分卡验证审核已被其他用户更新，请刷新后重试")
        if record.review_status != "pending_review":
            raise ValueError("只有待独立复核的验证运行可以审核")
        if record.created_by == actor:
            raise PermissionError("验证运行创建人不能复核自己的证据")
        current = self._development_run(record)
        if not current["integrity_valid"]:
            raise ValueError("验证证据完整性校验失败，不能审核")
        gate = record.report_json.get("validation_gate") or {}
        if decision == "approve" and not gate.get("passed"):
            raise ValueError("验证门禁未通过，不能批准；请驳回并重新运行验证")
        record.review_status = "approved" if decision == "approve" else "rejected"
        record.reviewed_by = actor
        record.reviewed_by_name = actor_name
        record.review_comment = comment
        record.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record.review_hash = content_hash(self._review_evidence(record))
        self.audit.append("scorecard_development_run", record.id, f"scorecard_development_{record.review_status}", actor_name, {"evidence_hash": record.evidence_hash, "review_hash": record.review_hash, "gate_passed": bool(gate.get("passed"))})
        self._commit("评分卡验证审核发生并发冲突")
        self.session.refresh(record)
        return self._development_run(record)

    def _validated_monitoring_plan_payload(self, payload: dict) -> dict:
        plan = deepcopy(payload)
        plan["code"] = str(plan["code"]).strip().upper()
        asset = self.session.get(ScorecardDefinition, plan["scorecard_asset_id"])
        if asset is None or asset.status != "published":
            raise LookupError("持续验证计划绑定的已发布评分卡不存在")
        policy = self._resolve_validation_policy(plan["validation_policy_id"], asset.code)
        if policy is None:
            raise ValueError("持续验证计划必须绑定生效验证策略")
        dataset_ids = [plan.get(key) for key in ("training_dataset_id", "validation_dataset_id", "oot_dataset_id") if plan.get(key)]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("训练、验证和时间外计划必须绑定不同数据集")
        for dataset_id in dataset_ids:
            dataset = self.session.get(RuleCenterReplayDataset, dataset_id)
            if dataset is None or dataset.status != "active":
                raise LookupError("持续验证计划绑定的数据集不存在或未启用")
        config = plan.get("run_config") or {}
        segment_fields = config.get("segment_fields") or []
        sensitive_fields = config.get("sensitive_attribute_fields") or []
        if len(segment_fields) != len(set(segment_fields)) or len(sensitive_fields) != len(set(sensitive_fields)):
            raise ValueError("计划的分群字段和敏感属性字段不能重复")
        if not set(sensitive_fields).issubset(segment_fields):
            raise ValueError("计划的敏感属性字段必须同时包含在分群字段中")
        plan["run_config"] = config
        return plan

    def _get_monitoring_plan(self, plan_id: str, expected: int | None = None) -> ScorecardValidationMonitoringPlan:
        record = self.session.get(ScorecardValidationMonitoringPlan, plan_id)
        if record is None:
            raise LookupError("持续验证计划不存在")
        if expected is not None and record.row_version != expected:
            raise ConcurrentUpdateError("持续验证计划已被更新，请刷新后重试")
        return record

    def _latest_dataset_snapshot(self, dataset_id: str, as_of: datetime) -> RuleCenterReplayDatasetSnapshot:
        snapshot = self.session.scalars(select(RuleCenterReplayDatasetSnapshot).where(
            RuleCenterReplayDatasetSnapshot.dataset_id == dataset_id,
            RuleCenterReplayDatasetSnapshot.as_of_date <= self._as_utc(as_of).date(),
        ).order_by(RuleCenterReplayDatasetSnapshot.as_of_date.desc(), RuleCenterReplayDatasetSnapshot.version.desc(), RuleCenterReplayDatasetSnapshot.created_at.desc())).first()
        if snapshot is None:
            raise LookupError("数据集在计划执行截面前没有可用不可变快照")
        return self._verified_snapshot(snapshot.id, "计划选择的")

    def _scan_monitoring_run(self, plan: ScorecardValidationMonitoringPlan, run: dict, actor: str) -> list[dict]:
        events: list[dict] = []
        if not run.get("validation_policy_integrity_valid", True):
            events.append(self._upsert_monitoring_event(plan, run, actor, "policy_integrity_failed", "critical", "验证策略证据完整性异常", "运行固定的策略快照与策略哈希不一致，指标不得作为正常趋势证据。"))
        if not run.get("integrity_valid"):
            events.append(self._upsert_monitoring_event(plan, run, actor, "evidence_integrity_failed", "critical", "验证证据完整性异常", "评分卡、数据快照或报告证据无法通过哈希复算，指标已从趋势证据中隔离。"))
            return events
        gate = (run.get("report") or {}).get("validation_gate") or {}
        for violation in gate.get("violations") or []:
            events.append(self._upsert_monitoring_event(
                plan, run, actor, "gate_failed", "critical", f"{violation.get('scope')} {violation.get('label')} 未通过",
                violation.get("detail") or "持续验证指标未达到机构门槛", metric_key=violation.get("key"),
                metric_label=violation.get("label"), metric_value=violation.get("actual"), threshold_value=violation.get("threshold"),
                threshold_operator=violation.get("operator"), details={"scope": violation.get("scope"), "testable": violation.get("testable")},
            ))
        rows = self.session.scalars(select(ScorecardDevelopmentRun).where(
            ScorecardDevelopmentRun.scorecard_asset_id == plan.scorecard_asset_id,
        ).order_by(ScorecardDevelopmentRun.created_at.desc(), ScorecardDevelopmentRun.id.desc()).limit(8)).all()
        points = [self._development_trend_point(self._development_run(item)) for item in reversed(rows)]
        valid = [point for point in points if point["status"] in {"pass", "block"}]
        if len(valid) >= 3:
            labels = {"oot_auc": "OOT AUC", "oot_ks": "OOT KS", "oot_brier": "OOT Brier", "oot_score_psi": "OOT 分数 PSI"}
            for key, direction in (("oot_auc", "down"), ("oot_ks", "down"), ("oot_brier", "up"), ("oot_score_psi", "up")):
                values = [point["metrics"].get(key) for point in valid[-3:]]
                if any(value is None for value in values):
                    continue
                deteriorated = values[0] > values[1] > values[2] if direction == "down" else values[0] < values[1] < values[2]
                if deteriorated:
                    events.append(self._upsert_monitoring_event(
                        plan, run, actor, "consecutive_deterioration", "warning", f"{labels[key]} 连续恶化",
                        f"最近三次有效运行的 {labels[key]} 为 " + " → ".join(f"{value:.4f}" for value in values),
                        metric_key=key, metric_label=labels[key], metric_value=values[-1],
                        details={"run_ids": [point["run_id"] for point in valid[-3:]], "values": values, "direction": direction},
                    ))
        return events

    def _upsert_monitoring_event(self, plan: ScorecardValidationMonitoringPlan, run: dict | None, actor: str, event_type: str, severity: str, title: str, description: str, *, metric_key: str | None = None, metric_label: str | None = None, metric_value: float | None = None, threshold_value: float | None = None, threshold_operator: str | None = None, dedup_suffix: str | None = None, details: dict | None = None) -> dict:
        run_id = run.get("id") if run else None
        suffix = dedup_suffix or run_id or "none"
        dedup_key = f"{plan.id}:{suffix}:{event_type}:{metric_key or 'general'}"
        record = self.session.scalars(select(ScorecardValidationMonitoringEvent).where(ScorecardValidationMonitoringEvent.dedup_key == dedup_key)).first()
        if record is None:
            opened_at = datetime.now(timezone.utc)
            sla_policy = self._resolve_monitoring_sla_policy(plan, event_type)
            sla_snapshot = self._monitoring_sla_policy_snapshot(sla_policy) if sla_policy else {
                "id": None, "code": "BUILTIN_COMPATIBLE_SLA", "name": "兼容内置 SLA", "version": 1,
                "config_hash": content_hash(self.DEFAULT_MONITORING_SLA_RULES),
                "applicable_scorecard_codes": [], "applicable_event_types": [],
                "severity_rules": deepcopy(self.DEFAULT_MONITORING_SLA_RULES),
            }
            sla_rule = sla_snapshot["severity_rules"].get(severity) or sla_snapshot["severity_rules"]["warning"]
            sla_hours = int(sla_rule["response_hours"])
            record = ScorecardValidationMonitoringEvent(
                id=str(uuid4()), plan_id=plan.id, run_id=run_id, evidence_hash=run.get("evidence_hash") if run else None,
                event_type=event_type, severity=severity, metric_key=metric_key, metric_label=metric_label,
                metric_value=Decimal(str(metric_value)) if metric_value is not None else None,
                threshold_value=Decimal(str(threshold_value)) if threshold_value is not None else None,
                threshold_operator=threshold_operator, title=title, description=description, details_json=details or {},
                dedup_key=dedup_key, status="open", assignee=plan.owner, created_by=actor,
                sla_policy_id=sla_policy.id if sla_policy else None,
                sla_policy_snapshot_json=sla_snapshot, sla_policy_snapshot_hash=content_hash(sla_snapshot),
                sla_started_at=opened_at, sla_due_at=opened_at + timedelta(hours=sla_hours), escalation_level=0,
            )
            self.session.add(record)
            self.session.flush()
            self.audit.append("scorecard_validation_monitoring_event", record.id, "monitoring_event_opened", actor, {"plan_id": plan.id, "run_id": run_id, "event_type": event_type, "severity": severity, "metric_key": metric_key, "sla_policy_id": record.sla_policy_id, "sla_policy_snapshot_hash": record.sla_policy_snapshot_hash})
            self._notify_monitoring_event(record, plan, "opened")
        return self._monitoring_event(record)

    def _notify_monitoring_event(self, record: ScorecardValidationMonitoringEvent, plan: ScorecardValidationMonitoringPlan, stage: str) -> int:
        recipients: list[tuple[str, str | None]] = []
        target = record.assignee or plan.owner
        if stage in {"opened", "due_soon"} and target:
            recipients.append(("personal", target))
        elif stage == "overdue":
            if target:
                recipients.append(("personal", target))
            recipients.append(("model_admin", None))
        elif stage in {"escalated", "pending_revalidation"}:
            recipients.append(("risk_manager", None))
        elif stage == "closed":
            for subject in dict.fromkeys(item for item in (record.remediated_by, plan.owner) if item):
                recipients.append(("personal", subject))

        titles = {
            "opened": "持续验证预警待处置", "due_soon": "持续验证预警即将超时",
            "overdue": "持续验证预警已超时", "escalated": "持续验证预警升级督办",
            "pending_revalidation": "持续验证整改待独立复验", "closed": "持续验证预警已闭环",
        }
        sla_snapshot = record.sla_policy_snapshot_json or {}
        sla_rule = (sla_snapshot.get("severity_rules") or self.DEFAULT_MONITORING_SLA_RULES).get(record.severity) or self.DEFAULT_MONITORING_SLA_RULES["warning"]
        messages = {
            "opened": f"{plan.name} 生成{record.title}，请在 {self._iso_utc(record.sla_due_at)} 前确认并处置。",
            "due_soon": f"{plan.name} 的{record.title}即将到达处置时限 {self._iso_utc(record.sla_due_at)}。",
            "overdue": f"{plan.name} 的{record.title}已超过处置时限，请立即跟进。",
            "escalated": f"{plan.name} 的{record.title}逾期超过 {sla_rule.get('escalation_after_hours', 4)} 小时，已升级至风控经理督办。",
            "pending_revalidation": f"{plan.name} 的整改已提交，请独立复核新验证运行 {record.revalidation_run_id}。",
            "closed": f"{plan.name} 的{record.title}已通过独立复验并关闭。",
        }
        severity = "critical" if stage in {"overdue", "escalated"} or record.severity == "critical" else "warning"
        created_count = 0
        notifications = NotificationRepository(self.session)
        for role, subject in recipients:
            _, created = notifications.create_if_absent({
                "case_id": None, "counterparty_id": None,
                "recipient_role": role, "recipient_subject": subject,
                "category": "scorecard_monitoring", "level": stage, "severity": severity,
                "title": titles[stage], "message": messages[stage],
                "action_json": {"page": "indicators", "monitoring_event_id": record.id, "run_id": record.run_id, "plan_id": record.plan_id},
                "dedup_key": f"scorecard-monitoring:{record.id}:{stage}:{role}:{subject or 'broadcast'}",
                "status": "unread",
            })
            created_count += int(created)
        return created_count

    def _monitoring_plan(self, record: ScorecardValidationMonitoringPlan) -> dict:
        asset = self.session.get(ScorecardDefinition, record.scorecard_asset_id)
        policy = self.session.get(ScorecardValidationPolicy, record.validation_policy_id)
        datasets = {item.id: item for item in self.session.scalars(select(RuleCenterReplayDataset).where(RuleCenterReplayDataset.id.in_([value for value in (record.training_dataset_id, record.validation_dataset_id, record.oot_dataset_id) if value]))).all()}
        return {
            "id": record.id, "code": record.code, "name": record.name, "description": record.description,
            "scorecard_asset_id": record.scorecard_asset_id,
            "scorecard": {"code": asset.code, "name": asset.name, "version": asset.version, "config_hash": asset.config_hash} if asset else None,
            "validation_policy_id": record.validation_policy_id,
            "validation_policy": {"code": policy.code, "name": policy.name, "version": policy.version, "config_hash": policy.config_hash, "active": policy.is_active} if policy else None,
            "training_dataset_id": record.training_dataset_id, "validation_dataset_id": record.validation_dataset_id, "oot_dataset_id": record.oot_dataset_id,
            "datasets": {key: ({"id": value, "code": datasets[value].code, "name": datasets[value].name} if value in datasets else None) for key, value in {"training": record.training_dataset_id, "validation": record.validation_dataset_id, "oot": record.oot_dataset_id}.items()},
            "run_config": deepcopy(record.run_config_json), "cadence": record.cadence, "timezone_name": record.timezone_name,
            "enabled": record.enabled, "next_run_at": self._iso_utc(record.next_run_at), "owner": record.owner,
            "last_scheduled_for": self._iso_utc(record.last_scheduled_for),
            "last_run_at": self._iso_utc(record.last_run_at), "last_run_id": record.last_run_id,
            "last_status": record.last_status, "last_error": record.last_error, "row_version": record.row_version,
            "created_by": record.created_by, "updated_by": record.updated_by,
            "created_at": self._iso_utc(record.created_at),
            "updated_at": self._iso_utc(record.updated_at),
        }

    @staticmethod
    def _monitoring_event(record: ScorecardValidationMonitoringEvent) -> dict:
        return {
            "id": record.id, "plan_id": record.plan_id, "run_id": record.run_id, "evidence_hash": record.evidence_hash,
            "event_type": record.event_type, "severity": record.severity, "metric_key": record.metric_key,
            "metric_label": record.metric_label, "metric_value": float(record.metric_value) if record.metric_value is not None else None,
            "threshold_value": float(record.threshold_value) if record.threshold_value is not None else None,
            "threshold_operator": record.threshold_operator, "title": record.title, "description": record.description,
            "details": deepcopy(record.details_json or {}), "status": record.status, "assignee": record.assignee,
            "sla_policy_id": record.sla_policy_id,
            "sla_policy_snapshot": deepcopy(record.sla_policy_snapshot_json),
            "sla_policy_snapshot_hash": record.sla_policy_snapshot_hash,
            "sla_policy_integrity_valid": bool(record.sla_policy_snapshot_json and record.sla_policy_snapshot_hash == content_hash(record.sla_policy_snapshot_json)),
            "sla_started_at": ScorecardRepository._iso_utc(record.sla_started_at),
            "sla_due_at": ScorecardRepository._iso_utc(record.sla_due_at),
            "sla_status": ScorecardRepository.monitoring_event_sla_level(record, datetime.now(timezone.utc)),
            "escalation_level": record.escalation_level, "last_escalated_at": ScorecardRepository._iso_utc(record.last_escalated_at),
            "acknowledged_by": record.acknowledged_by, "acknowledged_at": ScorecardRepository._iso_utc(record.acknowledged_at),
            "remediation_plan": record.remediation_plan, "remediation_result": record.remediation_result,
            "remediated_by": record.remediated_by, "remediated_at": ScorecardRepository._iso_utc(record.remediated_at),
            "revalidation_run_id": record.revalidation_run_id, "revalidation_evidence_hash": record.revalidation_evidence_hash,
            "revalidation_conclusion": record.revalidation_conclusion, "revalidated_by": record.revalidated_by,
            "revalidated_by_name": record.revalidated_by_name, "revalidated_at": ScorecardRepository._iso_utc(record.revalidated_at),
            "closed_by": record.closed_by, "closed_at": ScorecardRepository._iso_utc(record.closed_at),
            "row_version": record.row_version, "created_by": record.created_by,
            "created_at": ScorecardRepository._iso_utc(record.created_at),
            "updated_at": ScorecardRepository._iso_utc(record.updated_at),
        }

    @staticmethod
    def _monitoring_saved_view(record: ScorecardMonitoringSavedView) -> dict:
        return {
            "id": record.id, "owner_subject": record.owner_subject, "name": record.name,
            "filters": deepcopy(record.filters_json or {}), "is_default": record.is_default,
            "row_version": record.row_version,
            "created_at": ScorecardRepository._iso_utc(record.created_at),
            "updated_at": ScorecardRepository._iso_utc(record.updated_at),
        }

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _iso_utc(value: datetime | None) -> str | None:
        return ScorecardRepository._as_utc(value).isoformat() if value else None

    def _monitoring_backlog(self, as_of: datetime) -> tuple[int, datetime | None]:
        statement = select(
            func.count(ScorecardValidationMonitoringPlan.id),
            func.min(ScorecardValidationMonitoringPlan.next_run_at),
        ).where(
            ScorecardValidationMonitoringPlan.enabled.is_(True),
            ScorecardValidationMonitoringPlan.next_run_at <= self._as_utc(as_of),
        )
        count, oldest = self.session.execute(statement).one()
        return int(count or 0), oldest

    def _acquire_monitoring_scheduler_lease(
        self, execution_id: str, run_key: str, actor: str, trigger_type: str, acquired_at: datetime
    ) -> dict:
        point = self._as_utc(acquired_at)
        lease = self.session.get(ScorecardMonitoringSchedulerLease, self.MONITORING_SCHEDULER_LEASE_KEY)
        if lease is None:
            self.session.add(ScorecardMonitoringSchedulerLease(lease_key=self.MONITORING_SCHEDULER_LEASE_KEY))
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
        result = self.session.execute(
            update(ScorecardMonitoringSchedulerLease).where(
                ScorecardMonitoringSchedulerLease.lease_key == self.MONITORING_SCHEDULER_LEASE_KEY,
                or_(
                    ScorecardMonitoringSchedulerLease.execution_id.is_(None),
                    ScorecardMonitoringSchedulerLease.expires_at.is_(None),
                    ScorecardMonitoringSchedulerLease.expires_at <= point,
                ),
            ).values(
                execution_id=execution_id, run_key=run_key, actor=actor, trigger_type=trigger_type,
                acquired_at=point, expires_at=point + timedelta(minutes=self.MONITORING_SCHEDULER_LEASE_MINUTES),
                last_heartbeat_at=point, heartbeat_count=0,
            ).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self.session.rollback()
            return {**self._monitoring_scheduler_lease(point), "status": "busy"}
        self.session.commit()
        return self._monitoring_scheduler_lease(point)

    def _heartbeat_monitoring_scheduler(
        self, execution_id: str, scheduler_run_id: str, completed: int, total: int, result: dict
    ) -> None:
        now = datetime.now(timezone.utc)
        renewed = self.session.execute(
            update(ScorecardMonitoringSchedulerLease).where(
                ScorecardMonitoringSchedulerLease.lease_key == self.MONITORING_SCHEDULER_LEASE_KEY,
                ScorecardMonitoringSchedulerLease.execution_id == execution_id,
            ).values(
                expires_at=now + timedelta(minutes=self.MONITORING_SCHEDULER_LEASE_MINUTES),
                last_heartbeat_at=now,
                heartbeat_count=ScorecardMonitoringSchedulerLease.heartbeat_count + 1,
            )
        )
        if renewed.rowcount != 1:
            self.session.rollback()
            raise RuntimeError("持续验证调度租约已丢失，旧执行已停止写入")
        scheduler_run = self.session.get(ScorecardMonitoringSchedulerRun, scheduler_run_id)
        if scheduler_run is None or scheduler_run.status != "running":
            self.session.rollback()
            raise RuntimeError("持续验证调度运行状态已变化，当前执行停止")
        scheduler_run.last_heartbeat_at = now
        scheduler_run.due_count = total
        failed = int(result["plan"]["last_status"] == "failed")
        scheduler_run.completed_count += 1 - failed
        scheduler_run.failed_count += failed
        scheduler_run.details_json = {
            **deepcopy(scheduler_run.details_json or {}),
            "progress": {"completed": completed, "total": total, "last_plan_id": result["plan"]["id"]},
        }
        self.session.commit()

    def _release_monitoring_scheduler_lease(self, execution_id: str, *, commit: bool = True) -> None:
        self.session.execute(
            update(ScorecardMonitoringSchedulerLease).where(
                ScorecardMonitoringSchedulerLease.lease_key == self.MONITORING_SCHEDULER_LEASE_KEY,
                ScorecardMonitoringSchedulerLease.execution_id == execution_id,
            ).values(
                execution_id=None, run_key=None, actor=None, trigger_type=None,
                acquired_at=None, expires_at=None, last_heartbeat_at=None, heartbeat_count=0,
            )
        )
        if commit:
            self.session.commit()

    def _monitoring_scheduler_lease(self, as_of: datetime) -> dict:
        point = self._as_utc(as_of)
        lease = self.session.get(ScorecardMonitoringSchedulerLease, self.MONITORING_SCHEDULER_LEASE_KEY)
        if lease is None or lease.execution_id is None:
            return {
                "status": "idle", "execution_id": None, "run_key": None, "actor": None, "trigger_type": None,
                "acquired_at": None, "expires_at": None, "last_heartbeat_at": None,
                "heartbeat_count": 0, "heartbeat_age_seconds": None, "remaining_seconds": 0,
            }
        expires_at = self._as_utc(lease.expires_at) if lease.expires_at else None
        heartbeat_at = self._as_utc(lease.last_heartbeat_at) if lease.last_heartbeat_at else None
        remaining = max(0, int((expires_at - point).total_seconds())) if expires_at else 0
        heartbeat_age = max(0, int((point - heartbeat_at).total_seconds())) if heartbeat_at else None
        return {
            "status": "active" if expires_at and expires_at > point else "expired",
            "execution_id": lease.execution_id, "run_key": lease.run_key, "actor": lease.actor,
            "trigger_type": lease.trigger_type, "acquired_at": self._iso_utc(lease.acquired_at),
            "expires_at": self._iso_utc(lease.expires_at), "last_heartbeat_at": self._iso_utc(lease.last_heartbeat_at),
            "heartbeat_count": lease.heartbeat_count or 0, "heartbeat_age_seconds": heartbeat_age,
            "remaining_seconds": remaining,
        }

    def _monitoring_scheduler_run(self, record: ScorecardMonitoringSchedulerRun) -> dict:
        recovered = bool(record.status == "dead_letter" and self.session.scalar(
            select(func.count()).select_from(ScorecardMonitoringSchedulerRun).where(
                ScorecardMonitoringSchedulerRun.recovery_of_run_id == record.id,
                ScorecardMonitoringSchedulerRun.trigger_type == "recovery",
            )
        ))
        return {
            "id": record.id, "run_key": record.run_key, "trigger_type": record.trigger_type,
            "status": record.status, "as_of": self._iso_utc(record.as_of),
            "started_at": self._iso_utc(record.started_at), "last_heartbeat_at": self._iso_utc(record.last_heartbeat_at),
            "completed_at": self._iso_utc(record.completed_at), "actor": record.actor,
            "attempt_number": record.attempt_number, "max_attempts": self.MONITORING_SCHEDULER_MAX_ATTEMPTS,
            "recovery_of_run_id": record.recovery_of_run_id, "recovery_reason": record.recovery_reason,
            "due_count": record.due_count, "completed_count": record.completed_count, "failed_count": record.failed_count,
            "backlog_before": record.backlog_before, "backlog_after": record.backlog_after,
            "oldest_due_at": self._iso_utc(record.oldest_due_at),
            "error_type": record.error_type, "error_message": record.error_message,
            "progress": deepcopy(record.details_json or {}).get("progress"),
            "can_retry": record.status in {"partial_failed", "failed"} and record.attempt_number < self.MONITORING_SCHEDULER_MAX_ATTEMPTS,
            "can_recover": record.status == "dead_letter" and not recovered,
        }

    @staticmethod
    def _advance_schedule(value: datetime, cadence: str) -> datetime:
        months = 1 if cadence == "monthly" else 3
        month_index = value.month - 1 + months
        year, month = value.year + month_index // 12, month_index % 12 + 1
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        month_days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        return value.replace(year=year, month=month, day=min(value.day, month_days[month - 1]))

    def _verified_snapshot(self, snapshot_id: str, label: str) -> RuleCenterReplayDatasetSnapshot:
        snapshot = self.session.get(RuleCenterReplayDatasetSnapshot, snapshot_id)
        if snapshot is None:
            raise LookupError(f"{label}不可变数据快照不存在")
        if RuleCenterReplayDatasetRepository.snapshot_content_hash(snapshot) != snapshot.content_hash:
            raise ValueError(f"{label}数据快照内容哈希不一致")
        return snapshot

    @staticmethod
    def _snapshot_payload(snapshot: RuleCenterReplayDatasetSnapshot) -> dict:
        return {
            "id": snapshot.id, "content_hash": snapshot.content_hash,
            "as_of_date": snapshot.as_of_date.isoformat(), "sample_count": snapshot.sample_count,
            "samples": deepcopy(snapshot.samples_json), "label_field": snapshot.label_field,
            "observed_at_field": snapshot.observed_at_field, "coverage": deepcopy(snapshot.coverage_json),
        }

    def list_changes(self) -> list[dict]:
        records = self.session.scalars(
            select(ModelChangeRecord)
            .where(ModelChangeRecord.entity_type == "scorecard")
            .order_by(ModelChangeRecord.created_at.desc())
        ).all()
        return [self._change(record) for record in records]

    def create_draft(self, definition: dict, reason: str, actor: str, actor_name: str) -> dict:
        validation = validate_scorecard(definition)
        code = definition["code"]
        existing_draft = self.session.scalars(
            select(ModelChangeRecord).where(
                ModelChangeRecord.entity_type == "scorecard",
                ModelChangeRecord.template_key == code,
                ModelChangeRecord.status.in_(["draft", "submitted"]),
            )
        ).first()
        if existing_draft:
            raise ValueError(f"评分卡 {code} 已存在在途变更")
        latest = self.session.scalars(
            select(ScorecardDefinition)
            .where(ScorecardDefinition.code == code)
            .order_by(ScorecardDefinition.version.desc())
        ).first()
        candidate = (latest.version if latest else 0) + 1
        record = ModelChangeRecord(
            id=str(uuid4()), template_key=code, base_version=str(latest.version if latest else 0),
            candidate_version=str(candidate), status="draft", entity_type="scorecard",
            config_json=deepcopy(definition), validation_json=validation,
            impact_json=self._impact(definition), change_reason=reason,
            created_by=actor, created_by_name=actor_name, row_version=1,
        )
        self.session.add(record)
        self.audit.append("scorecard_change", record.id, "scorecard_draft_created", actor_name, {"code": code, "candidate_version": candidate})
        self._commit("评分卡草稿创建发生并发冲突")
        self.session.refresh(record)
        return self._change(record)

    def update_draft(self, change_id: str, expected: int, definition: dict, reason: str, actor: str, is_admin: bool) -> dict:
        record = self._get(change_id)
        self._check_version(record, expected)
        if record.status != "draft":
            raise ValueError("只有草稿状态可以修改")
        if record.created_by != actor and not is_admin:
            raise PermissionError("只能修改本人创建的评分卡草稿")
        if definition["code"] != record.template_key:
            raise ValueError("评分卡编码创建后不可修改")
        record.config_json = deepcopy(definition)
        record.validation_json = validate_scorecard(definition)
        record.impact_json = self._impact(definition)
        record.change_reason = reason
        self.audit.append("scorecard_change", record.id, "scorecard_draft_updated", actor, {"config_hash": content_hash(definition)})
        self._commit("评分卡草稿更新发生并发冲突")
        self.session.refresh(record)
        return self._change(record)

    def submit(self, change_id: str, expected: int, actor: str, is_admin: bool) -> dict:
        record = self._get(change_id)
        self._check_version(record, expected)
        if record.status != "draft":
            raise ValueError("只有草稿状态可以提交")
        if record.created_by != actor and not is_admin:
            raise PermissionError("只能提交本人创建的评分卡草稿")
        validation = validate_scorecard(record.config_json)
        record.validation_json = validation
        record.impact_json = self._impact(record.config_json)
        if not validation["valid"]:
            raise ValueError("评分卡校验未通过：" + "；".join(validation["errors"]))
        record.status = "submitted"
        record.submitted_at = datetime.now(timezone.utc)
        self.audit.append("scorecard_change", record.id, "scorecard_submitted", actor, {"config_hash": content_hash(record.config_json)})
        self._commit("评分卡提交发生并发冲突")
        self.session.refresh(record)
        return self._change(record)

    def review(self, change_id: str, expected: int, decision: str, comment: str, actor: str, actor_name: str) -> dict:
        record = self._get(change_id)
        self._check_version(record, expected)
        if record.status != "submitted":
            raise ValueError("只有待复核评分卡可以审核")
        if record.created_by == actor:
            raise PermissionError("提交人不能复核自己的评分卡变更")
        now = datetime.now(timezone.utc)
        record.reviewed_by, record.reviewed_by_name = actor, actor_name
        record.reviewed_at, record.review_comment = now, comment
        if decision == "reject":
            record.status = "rejected"
        else:
            validation = validate_scorecard(record.config_json)
            if not validation["valid"]:
                raise ValueError("发布前校验未通过：" + "；".join(validation["errors"]))
            current_impact = self._impact(record.config_json)
            if current_impact["dependency_graph_hash"] != (record.impact_json or {}).get("dependency_graph_hash"):
                raise ValueError("评分卡依赖图已变化，请由创建人重新提交并复核最新影响范围")
            active = self.session.scalars(select(ScorecardDefinition).where(ScorecardDefinition.code == record.template_key, ScorecardDefinition.is_active.is_(True))).all()
            for item in active:
                item.is_active = False
            asset = ScorecardDefinition(
                id=str(uuid4()), code=record.template_key, name=record.config_json["name"],
                description=record.config_json.get("description", ""), version=int(record.candidate_version),
                status="published", is_active=True, config_json=deepcopy(record.config_json),
                config_hash=content_hash(record.config_json), change_id=record.id,
                created_by=record.created_by, created_by_name=record.created_by_name,
                created_at=record.created_at, published_at=now,
            )
            record.status, record.published_at = "published", now
            self.session.add(asset)
        self.audit.append("scorecard_change", record.id, f"scorecard_{record.status}", actor_name, {"comment": comment, "config_hash": content_hash(record.config_json)})
        self._commit("评分卡审核发生并发冲突")
        self.session.refresh(record)
        return self._change(record)

    def _impact(self, definition: dict) -> dict:
        indicator_codes = {item["indicator_code"] for item in definition.get("indicators", [])}
        affected_models: set[str] = set()
        draft_models: set[str] = set()
        scorecard_code = str(definition.get("code") or "")
        nodes: dict[str, dict] = {}
        edges: dict[tuple[str, str, str], dict] = {}

        def add_node(node_id: str, node_type: str, code: str, name: str, version, status: str, lifecycle: str, **extra) -> str:
            nodes[node_id] = {
                "id": node_id, "type": node_type, "code": code, "name": name,
                "version": str(version) if version is not None else None,
                "status": status, "lifecycle": lifecycle, **extra,
            }
            return node_id

        def add_edge(source: str, target: str, relation: str, direct: bool = False) -> None:
            edges[(source, target, relation)] = {
                "source": source, "target": target, "relation": relation, "direct": direct,
            }

        root_id = add_node(
            f"scorecard:{scorecard_code}", "scorecard", scorecard_code,
            str(definition.get("name") or scorecard_code), "candidate", "draft", "candidate",
            config_hash=content_hash(definition),
        )
        indicator_ids: dict[str, str] = {}
        for item in sorted(definition.get("indicators", []), key=lambda row: (row.get("indicator_code", ""), row.get("indicator_version", ""))):
            code = str(item.get("indicator_code") or "")
            node_id = add_node(
                f"indicator:{code}@{item.get('indicator_version')}", "indicator", code,
                str(item.get("indicator_name") or code), item.get("indicator_version"), "fixed", "dependency",
                field_path=item.get("field_path"),
            )
            indicator_ids[code] = node_id
            add_edge(root_id, node_id, "contains_indicator", True)

        pipeline_sources: dict[str, set[str]] = {}

        def model_relations(config: dict) -> tuple[set[str], bool]:
            selected = {
                str(item.get("indicator_id") or item.get("indicator_code") or "")
                for item in config.get("indicator_selection", [])
                if item.get("enabled", True)
            }
            binding = config.get("scorecard_binding") or {}
            return indicator_codes & selected, str(binding.get("code") or "") == scorecard_code

        def add_model(node_id: str, template_key: str, name: str, version, status: str, lifecycle: str, config: dict, model_kind: str) -> None:
            shared, bound = model_relations(config)
            if not shared and not bound:
                return
            add_node(node_id, "model", template_key, name, version, status, lifecycle, model_kind=model_kind, directly_bound=bound)
            affected_models.add(template_key)
            if lifecycle == "inflight":
                draft_models.add(template_key)
            if bound:
                add_edge(root_id, node_id, "fixed_scorecard_binding", True)
            for code in sorted(shared):
                if code in indicator_ids:
                    add_edge(indicator_ids[code], node_id, "uses_indicator", False)
            pipeline_code = str(config.get("decision_pipeline_code") or "").strip().upper()
            if pipeline_code and pipeline_code != "LEGACY-SCORECARD":
                pipeline_sources.setdefault(pipeline_code, set()).add(node_id)

        releases = self.session.scalars(select(ModelReleaseRecord).where(ModelReleaseRecord.is_active.is_(True))).all()
        for item in releases:
            add_model(f"model_release:{item.id}", item.template_key, item.template_key, item.model_version, "active", "active", item.config_json or {}, "release")
        snapshots = self.session.scalars(select(ModelSnapshotRecord)).all()
        for item in snapshots:
            add_model(f"model_snapshot:{item.id}", item.template_key, item.model_name, item.model_version, "frozen", "evidence", item.config_json or {}, "snapshot")
        inflight_statuses = {"draft", "submitted", "pending_review", "scheduled", "package_draft"}
        changes = self.session.scalars(select(ModelChangeRecord).where(ModelChangeRecord.entity_type == "model", ModelChangeRecord.status.in_(inflight_statuses))).all()
        for item in changes:
            add_model(f"model_change:{item.id}", item.template_key, item.template_key, item.candidate_version, item.status, "inflight", item.config_json or {}, "change")

        rule_set_codes: set[str] = set()
        rule_codes: set[str] = set()

        for code in sorted(pipeline_sources):
            definitions = self.session.scalars(select(DecisionPipelineDefinition).where(DecisionPipelineDefinition.code == code, DecisionPipelineDefinition.is_active.is_(True))).all()
            candidates = self.session.scalars(select(ModelChangeRecord).where(ModelChangeRecord.entity_type == "pipeline", ModelChangeRecord.template_key == code, ModelChangeRecord.status.in_(inflight_statuses))).all()
            for lifecycle, config, version, status, name, node_id in [
                *(("active", {"stages_json": row.stages_json}, row.version, row.status, row.name, f"pipeline:{row.id}") for row in definitions),
                *(("inflight", row.config_json or {}, row.candidate_version, row.status, str((row.config_json or {}).get("name") or code), f"pipeline_change:{row.id}") for row in candidates),
            ]:
                add_node(node_id, "pipeline", code, name, version, status, lifecycle)
                for source in sorted(pipeline_sources[code]):
                    add_edge(source, node_id, "executes_pipeline", lifecycle == "active")
                for stage in config.get("stages_json", []):
                    reference = str(stage.get("rule_set_code") or "").strip()
                    if reference:
                        rule_set_codes.add(reference)

        rule_set_sources: dict[str, set[str]] = {code: set() for code in rule_set_codes}
        for node_id, node in list(nodes.items()):
            if node["type"] != "pipeline":
                continue
            config = None
            if node_id.startswith("pipeline_change:"):
                record = self.session.get(ModelChangeRecord, node_id.split(":", 1)[1])
                config = record.config_json if record else {}
            else:
                record = self.session.get(DecisionPipelineDefinition, node_id.split(":", 1)[1])
                config = {"stages_json": record.stages_json} if record else {}
            for stage in (config or {}).get("stages_json", []):
                reference = str(stage.get("rule_set_code") or "").strip()
                if reference:
                    rule_set_sources.setdefault(reference, set()).add(node_id)

        for code in sorted(rule_set_sources):
            definitions = self.session.scalars(select(RuleSetDefinition).where(RuleSetDefinition.code == code, RuleSetDefinition.is_active.is_(True))).all()
            candidates = self.session.scalars(select(ModelChangeRecord).where(ModelChangeRecord.entity_type == "rule_set", ModelChangeRecord.template_key == code, ModelChangeRecord.status.in_(inflight_statuses))).all()
            for lifecycle, config, version, status, name, node_id in [
                *(("active", {"rule_codes": row.rule_codes}, row.version, row.status, row.name, f"rule_set:{row.id}") for row in definitions),
                *(("inflight", row.config_json or {}, row.candidate_version, row.status, str((row.config_json or {}).get("name") or code), f"rule_set_change:{row.id}") for row in candidates),
            ]:
                add_node(node_id, "rule_set", code, name, version, status, lifecycle)
                for source in sorted(rule_set_sources[code]):
                    add_edge(source, node_id, "references_rule_set", lifecycle == "active")
                rule_codes.update(str(item) for item in config.get("rule_codes", []) if str(item).strip())

        rule_sources: dict[str, set[str]] = {code: set() for code in rule_codes}
        for node_id, node in list(nodes.items()):
            if node["type"] != "rule_set":
                continue
            if node_id.startswith("rule_set_change:"):
                record = self.session.get(ModelChangeRecord, node_id.split(":", 1)[1])
                codes = (record.config_json or {}).get("rule_codes", []) if record else []
            else:
                record = self.session.get(RuleSetDefinition, node_id.split(":", 1)[1])
                codes = record.rule_codes if record else []
            for code in codes:
                rule_sources.setdefault(str(code), set()).add(node_id)

        for code in sorted(rule_sources):
            definitions = self.session.scalars(select(RuleDefinition).where(RuleDefinition.code == code, RuleDefinition.is_active.is_(True))).all()
            candidates = self.session.scalars(select(ModelChangeRecord).where(ModelChangeRecord.entity_type == "rule", ModelChangeRecord.template_key == code, ModelChangeRecord.status.in_(inflight_statuses))).all()
            for lifecycle, version, status, name, node_id in [
                *(("active", row.version, row.status, row.name, f"rule:{row.id}") for row in definitions),
                *(("inflight", row.candidate_version, row.status, str((row.config_json or {}).get("name") or code), f"rule_change:{row.id}") for row in candidates),
            ]:
                add_node(node_id, "rule", code, name, version, status, lifecycle)
                for source in sorted(rule_sources[code]):
                    add_edge(source, node_id, "contains_rule", lifecycle == "active")

        relevant_changes = {
            node_id.split(":", 1)[1]: node_id
            for node_id in nodes
            if node_id.startswith(("pipeline_change:", "rule_set_change:", "rule_change:"))
        }
        members = self.session.scalars(select(RuleCenterReleasePackageMember).where(RuleCenterReleasePackageMember.change_id.in_(relevant_changes))).all() if relevant_changes else []
        for member in members:
            package = self.session.get(RuleCenterReleasePackage, member.package_id)
            if package is None or package.status not in {"draft", "pending_review"}:
                continue
            package_id = f"release_package:{package.id}"
            add_node(package_id, "release_package", package.id, package.name, package.row_version, package.status, "inflight")
            add_edge(relevant_changes[member.change_id], package_id, "included_in_package", True)

        sorted_nodes = sorted(nodes.values(), key=lambda row: (row["type"], row["code"], row["version"] or "", row["id"]))
        sorted_edges = sorted(edges.values(), key=lambda row: (row["source"], row["target"], row["relation"]))
        counts = {node_type: sum(item["type"] == node_type for item in sorted_nodes) for node_type in ("indicator", "model", "pipeline", "rule_set", "rule", "release_package")}
        directly_bound = [item["id"] for item in sorted_nodes if item["type"] == "model" and item.get("directly_bound")]
        inflight_models = [item["id"] for item in sorted_nodes if item["type"] == "model" and item["lifecycle"] == "inflight"]
        inflight_rule_assets = [item["id"] for item in sorted_nodes if item["type"] in {"pipeline", "rule_set", "rule"} and item["lifecycle"] == "inflight"]
        missing_pipelines = sorted(set(pipeline_sources) - {item["code"] for item in sorted_nodes if item["type"] == "pipeline"})
        risks = []
        for key, severity, label, node_ids in (
            ("direct_model_binding", "high", "已发布或在途模型固定绑定当前评分卡版本", directly_bound),
            ("inflight_model_change", "medium", "在途模型候选需要确认是否继续固定旧评分卡", inflight_models),
            ("inflight_rule_asset", "medium", "关联决策链存在在途规则资产", inflight_rule_assets),
            ("inflight_release_package", "medium", "关联决策链已进入发布包", [item["id"] for item in sorted_nodes if item["type"] == "release_package"]),
            ("missing_pipeline", "high", "受影响模型引用的决策管线未发布且无在途候选", [f"pipeline:{code}" for code in missing_pipelines]),
        ):
            if node_ids:
                risks.append({"key": key, "severity": severity, "label": label, "count": len(node_ids), "node_ids": sorted(node_ids)})
        actions = []
        if affected_models:
            actions.append("评分卡发布不会自动切换模型；采用新版本必须创建模型候选并重新完成开发验证与 Champion/Challenger 比较")
        if inflight_models:
            actions.append("复核在途模型候选的固定评分卡版本，必要时基于新评分卡重新创建候选")
        if inflight_rule_assets or counts["release_package"]:
            actions.append("重新评估关联规则资产和发布包的依赖快照与回放证据")
        graph_payload = {
            "schema_version": "scorecard-dependency-graph-v1",
            "root_id": root_id,
            "nodes": sorted_nodes,
            "edges": sorted_edges,
        }
        graph_hash = content_hash(graph_payload)
        return {
            "indicator_codes": sorted(indicator_codes),
            "affected_models": sorted(affected_models),
            "inflight_model_drafts": sorted(draft_models),
            "dependency_graph": {**graph_payload, "summary": counts, "risks": risks, "required_actions": actions, "graph_hash": graph_hash},
            "dependency_graph_hash": graph_hash,
        }

    def _get(self, change_id: str) -> ModelChangeRecord:
        record = self.session.get(ModelChangeRecord, change_id)
        if record is None or record.entity_type != "scorecard":
            raise LookupError("评分卡变更不存在")
        return record

    @staticmethod
    def _check_version(record: ModelChangeRecord, expected: int) -> None:
        if record.row_version != expected:
            raise ConcurrentUpdateError("评分卡已被其他用户更新，请刷新后重试")

    def _commit(self, message: str) -> None:
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError(message) from exc

    def _change(self, record: ModelChangeRecord) -> dict:
        impact = deepcopy(record.impact_json or {})
        legacy_graph = not impact.get("dependency_graph_hash")
        if legacy_graph:
            impact.update(self._impact(record.config_json))
        impact["dependency_graph_legacy"] = legacy_graph
        if record.status == "submitted" and not legacy_graph:
            current = self._impact(record.config_json)
            impact["dependency_graph_current_hash"] = current["dependency_graph_hash"]
            impact["dependency_graph_drifted"] = current["dependency_graph_hash"] != impact["dependency_graph_hash"]
        else:
            impact["dependency_graph_current_hash"] = impact.get("dependency_graph_hash")
            impact["dependency_graph_drifted"] = record.status == "submitted" and legacy_graph
        return {
            "id": record.id, "code": record.template_key, "base_version": record.base_version,
            "candidate_version": record.candidate_version, "status": record.status,
            "definition": record.config_json, "validation": record.validation_json,
            "impact": impact, "change_reason": record.change_reason,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "reviewed_by_name": record.reviewed_by_name, "review_comment": record.review_comment,
            "row_version": record.row_version,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
            "published_at": record.published_at.isoformat() if record.published_at else None,
        }

    @staticmethod
    def _asset(record: ScorecardDefinition) -> dict:
        return {"id": record.id, "code": record.code, "name": record.name, "description": record.description, "version": record.version, "status": record.status, "is_active": record.is_active, "config": record.config_json, "config_hash": record.config_hash, "change_id": record.change_id, "created_by_name": record.created_by_name, "published_at": record.published_at.isoformat() if record.published_at else None}

    @classmethod
    def _normalized_monitoring_sla_policy(cls, payload: dict) -> dict:
        scorecard_codes = sorted({str(code).strip().upper() for code in payload.get("applicable_scorecard_codes", []) if str(code).strip()})
        allowed_event_types = {"gate_failed", "consecutive_deterioration", "evidence_integrity_failed", "policy_integrity_failed", "scheduled_run_failed"}
        event_types = sorted({str(item).strip() for item in payload.get("applicable_event_types", []) if str(item).strip()})
        unknown = set(event_types) - allowed_event_types
        if unknown:
            raise ValueError("SLA 策略包含未知预警类型：" + "、".join(sorted(unknown)))
        if payload.get("is_default") and (scorecard_codes or event_types):
            raise ValueError("机构默认 SLA 策略必须适用于全部评分卡和预警类型")
        raw_rules = payload.get("severity_rules") or {}
        rules: dict[str, dict] = {}
        for severity in ("critical", "warning"):
            raw = raw_rules.get(severity) or cls.DEFAULT_MONITORING_SLA_RULES[severity]
            response_hours = int(raw.get("response_hours", cls.DEFAULT_MONITORING_SLA_RULES[severity]["response_hours"]))
            due_soon_ratio = float(raw.get("due_soon_ratio", 0.25))
            escalation_after_hours = int(raw.get("escalation_after_hours", 4))
            if not 1 <= response_hours <= 720:
                raise ValueError(f"{severity} 响应时限必须为 1—720 小时")
            if not 0.05 <= due_soon_ratio <= 0.9:
                raise ValueError(f"{severity} 临期比例必须为 0.05—0.9")
            if not 1 <= escalation_after_hours <= 168:
                raise ValueError(f"{severity} 逾期升级窗口必须为 1—168 小时")
            rules[severity] = {
                "response_hours": response_hours,
                "due_soon_ratio": due_soon_ratio,
                "escalation_after_hours": escalation_after_hours,
            }
        return {
            "code": str(payload["code"]).strip().upper(), "name": str(payload["name"]).strip(),
            "description": str(payload["description"]).strip(),
            "applicable_scorecard_codes": scorecard_codes, "applicable_event_types": event_types,
            "is_default": bool(payload.get("is_default")), "severity_rules": rules,
        }

    @staticmethod
    def _monitoring_sla_policy_config(record: ScorecardMonitoringSlaPolicy) -> dict:
        return {
            "code": record.code, "name": record.name, "description": record.description,
            "applicable_scorecard_codes": record.applicable_scorecard_codes or [],
            "applicable_event_types": record.applicable_event_types or [],
            "is_default": record.is_default, "severity_rules": record.severity_rules_json,
        }

    def _monitoring_sla_policy_snapshot(self, record: ScorecardMonitoringSlaPolicy) -> dict:
        return {
            "id": record.id, "code": record.code, "name": record.name, "version": record.version,
            "config_hash": record.config_hash,
            "applicable_scorecard_codes": deepcopy(record.applicable_scorecard_codes or []),
            "applicable_event_types": deepcopy(record.applicable_event_types or []),
            "severity_rules": deepcopy(record.severity_rules_json),
        }

    def _monitoring_sla_policy(self, record: ScorecardMonitoringSlaPolicy) -> dict:
        return {
            "id": record.id, **self._monitoring_sla_policy_config(record), "version": record.version,
            "status": record.status, "is_active": record.is_active, "config_hash": record.config_hash,
            "change_reason": record.change_reason, "created_by": record.created_by,
            "created_by_name": record.created_by_name, "reviewed_by_name": record.reviewed_by_name,
            "review_comment": record.review_comment, "row_version": record.row_version,
            "created_at": self._iso_utc(record.created_at), "submitted_at": self._iso_utc(record.submitted_at),
            "published_at": self._iso_utc(record.published_at),
        }

    def _get_monitoring_sla_policy(self, policy_id: str) -> ScorecardMonitoringSlaPolicy:
        record = self.session.get(ScorecardMonitoringSlaPolicy, policy_id)
        if record is None:
            raise LookupError("持续验证 SLA 策略不存在")
        return record

    def _resolve_monitoring_sla_policy(self, plan: ScorecardValidationMonitoringPlan, event_type: str) -> ScorecardMonitoringSlaPolicy | None:
        asset = self.session.get(ScorecardDefinition, plan.scorecard_asset_id)
        scorecard_code = asset.code if asset else ""
        rows = self.session.scalars(select(ScorecardMonitoringSlaPolicy).where(
            ScorecardMonitoringSlaPolicy.status == "published", ScorecardMonitoringSlaPolicy.is_active.is_(True)
        )).all()
        candidates = []
        defaults = []
        for record in rows:
            if record.config_hash != content_hash(self._monitoring_sla_policy_config(record)):
                continue
            codes, types = set(record.applicable_scorecard_codes or []), set(record.applicable_event_types or [])
            if record.is_default:
                defaults.append(record)
            elif (not codes or scorecard_code in codes) and (not types or event_type in types):
                candidates.append((int(bool(codes)) + int(bool(types)), record))
        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1].published_at or item[1].created_at), reverse=True)
            if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
                raise ValueError(f"评分卡 {scorecard_code} 的预警类型 {event_type} 匹配多个同优先级 SLA 策略")
            return candidates[0][1]
        if len(defaults) > 1:
            raise ValueError("存在多个当前生效的机构默认 SLA 策略")
        return defaults[0] if defaults else None

    @staticmethod
    def _normalized_validation_policy(payload: dict) -> dict:
        codes = sorted({str(code).strip().upper() for code in payload.get("applicable_scorecard_codes", []) if str(code).strip()})
        if payload.get("is_default") and codes:
            raise ValueError("机构默认策略必须适用于全部评分卡，不能限定评分卡编码")
        return {
            "code": str(payload["code"]).strip().upper(), "name": str(payload["name"]).strip(),
            "description": str(payload["description"]).strip(), "applicable_scorecard_codes": codes,
            "is_default": bool(payload.get("is_default")),
            "thresholds": {**DEFAULT_VALIDATION_THRESHOLDS, **deepcopy(payload.get("thresholds") or {})},
        }

    @staticmethod
    def _policy_config(record: ScorecardValidationPolicy) -> dict:
        return {
            "code": record.code, "name": record.name, "description": record.description,
            "applicable_scorecard_codes": record.applicable_scorecard_codes or [],
            "is_default": record.is_default, "thresholds": record.thresholds_json,
        }

    def _policy_snapshot(self, record: ScorecardValidationPolicy) -> dict:
        return {
            "id": record.id, "code": record.code, "name": record.name, "version": record.version,
            "config_hash": record.config_hash, "is_default": record.is_default,
            "applicable_scorecard_codes": deepcopy(record.applicable_scorecard_codes or []),
            "thresholds": deepcopy(record.thresholds_json),
        }

    def _validation_policy(self, record: ScorecardValidationPolicy) -> dict:
        return {
            "id": record.id, **self._policy_config(record), "version": record.version,
            "status": record.status, "is_active": record.is_active, "config_hash": record.config_hash,
            "change_reason": record.change_reason, "created_by": record.created_by,
            "created_by_name": record.created_by_name, "reviewed_by_name": record.reviewed_by_name,
            "review_comment": record.review_comment, "row_version": record.row_version,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
            "published_at": record.published_at.isoformat() if record.published_at else None,
        }

    def _get_validation_policy(self, policy_id: str) -> ScorecardValidationPolicy:
        record = self.session.get(ScorecardValidationPolicy, policy_id)
        if record is None:
            raise LookupError("评分卡验证策略不存在")
        return record

    @staticmethod
    def _check_policy_version(record: ScorecardValidationPolicy | ScorecardMonitoringSlaPolicy, expected: int) -> None:
        if record.row_version != expected:
            raise ConcurrentUpdateError("验证策略已被其他用户更新，请刷新后重试")

    def _resolve_validation_policy(self, policy_id: str | None, scorecard_code: str) -> ScorecardValidationPolicy | None:
        if policy_id:
            record = self._get_validation_policy(policy_id)
        else:
            record = self.session.scalars(select(ScorecardValidationPolicy).where(
                ScorecardValidationPolicy.status == "published", ScorecardValidationPolicy.is_active.is_(True),
                ScorecardValidationPolicy.is_default.is_(True),
            )).first()
        if record is None:
            return None
        if record.status != "published" or not record.is_active:
            raise ValueError("只能使用当前生效的验证策略")
        if record.config_hash != content_hash(self._policy_config(record)):
            raise ValueError("验证策略配置哈希不一致")
        applicable = set(record.applicable_scorecard_codes or [])
        if applicable and scorecard_code not in applicable:
            raise ValueError(f"验证策略不适用于评分卡 {scorecard_code}")
        return record

    def _development_run(self, record: ScorecardDevelopmentRun) -> dict:
        evidence = {
            "scorecard_asset_id": record.scorecard_asset_id, "scorecard_code": record.scorecard_code,
            "scorecard_version": record.scorecard_version, "scorecard_config_hash": record.scorecard_config_hash,
            "dataset_snapshot_id": record.dataset_snapshot_id, "dataset_snapshot_hash": record.dataset_snapshot_hash,
            "label_policy": record.label_policy_json, "report": record.report_json,
        }
        has_supplemental_snapshots = record.report_json.get("schema_version") in {"scorecard-development-report-v2", "scorecard-development-report-v3", "scorecard-development-report-v4"}
        if has_supplemental_snapshots:
            evidence.update({
                "validation_snapshot_id": record.validation_snapshot_id,
                "validation_snapshot_hash": record.validation_snapshot_hash,
                "oot_snapshot_id": record.oot_snapshot_id,
                "oot_snapshot_hash": record.oot_snapshot_hash,
            })
        if record.validation_policy_id:
            evidence.update({"validation_policy_id": record.validation_policy_id, "validation_policy_hash": record.validation_policy_hash})
        asset = self.session.get(ScorecardDefinition, record.scorecard_asset_id)
        snapshot = self.session.get(RuleCenterReplayDatasetSnapshot, record.dataset_snapshot_id)
        validation_snapshot = self.session.get(RuleCenterReplayDatasetSnapshot, record.validation_snapshot_id) if record.validation_snapshot_id else None
        oot_snapshot = self.session.get(RuleCenterReplayDatasetSnapshot, record.oot_snapshot_id) if record.oot_snapshot_id else None
        validation_policy = self.session.get(ScorecardValidationPolicy, record.validation_policy_id) if record.validation_policy_id else None
        policy_snapshot = (record.label_policy_json or {}).get("validation_policy")
        policy_valid = not record.validation_policy_id and not record.validation_policy_hash
        if validation_policy and policy_snapshot:
            policy_valid = bool(
                validation_policy.config_hash == record.validation_policy_hash
                and content_hash(self._policy_config(validation_policy)) == record.validation_policy_hash
                and policy_snapshot.get("id") == record.validation_policy_id
                and policy_snapshot.get("config_hash") == record.validation_policy_hash
            )
        supplemental_valid = (
            (not record.validation_snapshot_id or validation_snapshot is not None and RuleCenterReplayDatasetRepository.snapshot_content_hash(validation_snapshot) == record.validation_snapshot_hash)
            and (not record.oot_snapshot_id or oot_snapshot is not None and RuleCenterReplayDatasetRepository.snapshot_content_hash(oot_snapshot) == record.oot_snapshot_hash)
        )
        integrity_valid = bool(
            asset and snapshot and content_hash(asset.config_json) == record.scorecard_config_hash
            and RuleCenterReplayDatasetRepository.snapshot_content_hash(snapshot) == record.dataset_snapshot_hash
            and supplemental_valid
            and policy_valid
            and content_hash(evidence) == record.evidence_hash
        )
        review_integrity_valid = record.review_status in {"pending_review", "not_required"} and record.review_hash is None
        if record.review_status in {"approved", "rejected"}:
            review_integrity_valid = bool(record.review_hash and content_hash(self._review_evidence(record)) == record.review_hash)
        return {
            "id": record.id, **evidence, "evidence_hash": record.evidence_hash,
            "validation_policy": policy_snapshot, "validation_policy_integrity_valid": policy_valid,
            "evidence_level": record.evidence_level, "integrity_valid": integrity_valid,
            "review_status": record.review_status, "reviewed_by": record.reviewed_by,
            "reviewed_by_name": record.reviewed_by_name, "review_comment": record.review_comment,
            "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
            "review_hash": record.review_hash, "review_integrity_valid": review_integrity_valid,
            "row_version": record.row_version,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    @staticmethod
    def _development_trend_point(run: dict) -> dict:
        report = run.get("report") or {}
        performance = report.get("performance") or {}
        fairness = report.get("fairness") or {}
        gate = report.get("validation_gate") or {}
        gate_thresholds = gate.get("thresholds") or {}

        def split_metric(split: str, key: str) -> float | None:
            value = (performance.get(split) or {}).get(key)
            return float(value) if isinstance(value, (int, float)) else None

        def maximum_disparity(key: str) -> float | None:
            values = []
            for split in ("validation", "oot"):
                for field in ((fairness.get("splits") or {}).get(split) or {}).values():
                    value = (field.get("disparities") or {}).get(key)
                    if isinstance(value, (int, float)):
                        values.append(float(value))
            return max(values) if values else None

        def maximum_group_psi() -> float | None:
            values = []
            for split in ("validation", "oot"):
                for field in ((fairness.get("splits") or {}).get(split) or {}).values():
                    values.extend(float(group["score_psi"]) for group in field.get("groups") or [] if isinstance(group.get("score_psi"), (int, float)))
            return max(values) if values else None

        metrics = {
            "validation_auc": split_metric("validation", "auc"),
            "validation_ks": split_metric("validation", "ks"),
            "validation_brier": split_metric("validation", "brier"),
            "validation_score_psi": split_metric("validation", "score_psi"),
            "oot_auc": split_metric("oot", "auc"),
            "oot_ks": split_metric("oot", "ks"),
            "oot_brier": split_metric("oot", "brier"),
            "oot_score_psi": split_metric("oot", "score_psi"),
            "max_group_score_psi": maximum_group_psi(),
            "max_event_rate_gap": maximum_disparity("event_rate_gap"),
            "max_average_score_gap": maximum_disparity("average_score_gap"),
        }
        thresholds = {
            "validation_auc": gate_thresholds.get("min_auc"), "validation_ks": gate_thresholds.get("min_ks"),
            "validation_brier": gate_thresholds.get("max_brier"), "validation_score_psi": gate_thresholds.get("max_score_psi"),
            "oot_auc": gate_thresholds.get("min_auc"), "oot_ks": gate_thresholds.get("min_ks"),
            "oot_brier": gate_thresholds.get("max_brier"), "oot_score_psi": gate_thresholds.get("max_score_psi"),
            "max_group_score_psi": gate_thresholds.get("max_score_psi"),
            "max_event_rate_gap": gate_thresholds.get("max_event_rate_gap"),
            "max_average_score_gap": gate_thresholds.get("max_average_score_gap"),
        }
        evidence_valid = bool(run.get("integrity_valid") and run.get("validation_policy_integrity_valid", True))
        status = "invalid" if not evidence_valid else "pass" if gate.get("passed") is True else "block" if gate else "legacy"
        split_snapshots = (report.get("split_evidence") or {}).get("snapshots") or {}
        snapshot_dates = {key: (split_snapshots.get(key) or {}).get("as_of_date") for key in ("training", "validation", "oot")}
        if not evidence_valid:
            metrics = {key: None for key in metrics}
        return {
            "run_id": run["id"], "scorecard_asset_id": run["scorecard_asset_id"],
            "scorecard_code": run["scorecard_code"], "scorecard_version": run["scorecard_version"],
            "scorecard_config_hash": run["scorecard_config_hash"], "created_at": run.get("created_at"),
            "snapshot_dates": snapshot_dates, "status": status, "evidence_level": run.get("evidence_level"),
            "integrity_valid": evidence_valid, "review_status": run.get("review_status"),
            "violation_count": len(gate.get("violations") or []), "gate_summary": gate.get("summary"),
            "validation_policy": deepcopy(run.get("validation_policy")), "metrics": metrics, "thresholds": thresholds,
        }

    @staticmethod
    def _review_evidence(record: ScorecardDevelopmentRun) -> dict:
        reviewed_at = record.reviewed_at
        if reviewed_at and reviewed_at.tzinfo:
            reviewed_at = reviewed_at.astimezone(timezone.utc).replace(tzinfo=None)
        return {
            "development_run_id": record.id, "evidence_hash": record.evidence_hash,
            "review_status": record.review_status, "reviewed_by": record.reviewed_by,
            "reviewed_by_name": record.reviewed_by_name, "review_comment": record.review_comment,
            "reviewed_at": reviewed_at.isoformat(timespec="microseconds") if reviewed_at else None,
        }
