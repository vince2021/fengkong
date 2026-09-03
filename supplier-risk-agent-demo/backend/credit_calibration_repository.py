from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import CreditCalibrationPlan, CreditCalibrationRun, RuleCenterReplayDatasetSnapshot
from backend.repository import AuditRepository, ConcurrentUpdateError, content_hash


class CreditCalibrationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    @staticmethod
    def configuration_hash(payload: dict) -> str:
        return content_hash({
            "template_key": payload["template_key"],
            "candidate": payload["candidate"],
            "positive_labels": sorted(set(payload["positive_labels"])),
            "sample_limit": payload["sample_limit"],
        })

    def list_plans(self) -> list[dict]:
        records = self.session.scalars(
            select(CreditCalibrationPlan).order_by(CreditCalibrationPlan.created_at.desc(), CreditCalibrationPlan.id.desc())
        ).all()
        return [self._plan(record) for record in records]

    def get_plan(self, plan_id: str) -> dict:
        record = self.session.get(CreditCalibrationPlan, plan_id)
        if record is None:
            raise LookupError("校准方案不存在")
        return self._plan(record)

    def create_plan(self, payload: dict, actor: str, actor_name: str) -> dict:
        pending = self.session.scalars(select(CreditCalibrationPlan).where(
            CreditCalibrationPlan.code == payload["code"], CreditCalibrationPlan.status == "pending_review"
        )).first()
        if pending:
            raise ValueError("同一方案编码已有待复核版本，请先完成复核")
        version = (self.session.scalar(select(func.max(CreditCalibrationPlan.version)).where(CreditCalibrationPlan.code == payload["code"])) or 0) + 1
        candidate = deepcopy(payload["candidate"])
        sample_policy = {"positive_labels": sorted(set(payload["positive_labels"])), "sample_limit": payload["sample_limit"]}
        config_hash = self.configuration_hash({**payload, "candidate": candidate, **sample_policy})
        record = CreditCalibrationPlan(
            id=str(uuid4()), code=payload["code"], name=payload["name"], version=version,
            template_key=payload["template_key"], candidate_json=candidate,
            sample_policy_json=sample_policy, business_basis=payload["business_basis"],
            config_hash=config_hash, created_by=actor, created_by_name=actor_name,
        )
        self.session.add(record)
        return self._commit(record, "credit_calibration_plan_created", actor_name, {"code": record.code, "version": version, "config_hash": config_hash})

    def update_plan(self, plan_id: str, expected_row_version: int, payload: dict, actor: str, is_admin: bool) -> dict:
        record = self._versioned(plan_id, expected_row_version)
        if record.status not in {"draft", "rejected"}:
            raise ValueError("只有草稿或已驳回方案可以修改")
        if record.created_by != actor and not is_admin:
            raise PermissionError("仅方案创建人可以修改草稿")
        candidate = deepcopy(payload["candidate"])
        sample_policy = {"positive_labels": sorted(set(payload["positive_labels"])), "sample_limit": payload["sample_limit"]}
        record.name = payload["name"]
        record.candidate_json = candidate
        record.sample_policy_json = sample_policy
        record.business_basis = payload["business_basis"]
        record.config_hash = self.configuration_hash({**payload, "candidate": candidate, **sample_policy})
        record.status = "draft"
        record.submitted_at = None
        record.reviewed_by = None
        record.reviewed_by_name = None
        record.review_comment = None
        record.reviewed_at = None
        return self._commit(record, "credit_calibration_plan_updated", actor, {"config_hash": record.config_hash})

    def create_run(self, plan_id: str, expected_row_version: int, analysis: dict, actor: str, actor_name: str) -> dict:
        plan = self._versioned(plan_id, expected_row_version)
        if plan.status not in {"draft", "rejected"}:
            raise ValueError("只有草稿或已驳回方案可以运行校准")
        now = datetime.now(timezone.utc)
        record = CreditCalibrationRun(
            id=str(uuid4()), plan_id=plan.id, plan_config_hash=plan.config_hash,
            base_model_version=analysis["model"]["version"], baseline_config_hash=analysis["model"]["baseline_config_hash"],
            dataset_snapshot_id=analysis["snapshot"]["id"], dataset_snapshot_hash=analysis["snapshot"]["content_hash"],
            status="completed", report_json=deepcopy(analysis), evidence_hash=analysis["evidence_hash"],
            evidence_level=analysis["sample"]["evidence_level"], created_by=actor, created_by_name=actor_name,
            started_at=now, completed_at=now,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("credit_calibration_plan", plan.id, "credit_calibration_run_completed", actor_name, {
                "run_id": record.id, "evidence_hash": record.evidence_hash, "evidence_level": record.evidence_level,
                "dataset_snapshot_id": record.dataset_snapshot_id, "plan_config_hash": record.plan_config_hash,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("校准运行写入发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return self._run(record, plan)

    def submit_plan(self, plan_id: str, expected_row_version: int, actor: str, is_admin: bool) -> dict:
        record = self._versioned(plan_id, expected_row_version)
        if record.status not in {"draft", "rejected"}:
            raise ValueError("当前方案状态不能提交复核")
        if record.created_by != actor and not is_admin:
            raise PermissionError("仅方案创建人可以提交复核")
        run = self._latest_current_run(record)
        if run is None:
            raise ValueError("提交前必须在当前方案配置上完成一次校准运行")
        record.status = "pending_review"
        record.submitted_at = datetime.now(timezone.utc)
        return self._commit(record, "credit_calibration_plan_submitted", actor, {"run_id": run.id, "evidence_hash": run.evidence_hash})

    def review_plan(self, plan_id: str, expected_row_version: int, decision: str, comment: str, actor: str, actor_name: str) -> dict:
        record = self._versioned(plan_id, expected_row_version)
        if record.status != "pending_review":
            raise ValueError("只有待复核方案可以执行复核")
        if record.created_by == actor:
            raise PermissionError("创建人与复核人必须分离")
        run = self._latest_current_run(record)
        if run is None:
            raise ValueError("当前方案的校准证据已失效，请退回后重新运行")
        record.status = "approved" if decision == "approve" else "rejected"
        record.reviewed_by = actor
        record.reviewed_by_name = actor_name
        record.review_comment = comment
        record.reviewed_at = datetime.now(timezone.utc)
        return self._commit(record, f"credit_calibration_plan_{record.status}", actor_name, {"comment": comment, "run_id": run.id, "evidence_hash": run.evidence_hash})

    def approved_run(self, plan_id: str, expected_row_version: int, run_id: str) -> tuple[dict, dict]:
        record = self._versioned(plan_id, expected_row_version)
        if record.status != "approved":
            raise ValueError("只有已批准校准方案可以生成模型变更草稿")
        run = self.session.get(CreditCalibrationRun, run_id)
        if run is None or run.plan_id != record.id:
            raise LookupError("校准运行不存在")
        latest = self._latest_current_run(record)
        if latest is None or latest.id != run.id:
            raise ValueError("仅允许使用当前方案的最新有效运行生成模型草稿")
        return self._plan(record), self._run(run, record)

    def compare(self, plan_ids: list[str]) -> dict:
        if len(set(plan_ids)) != len(plan_ids):
            raise ValueError("比较方案不能重复")
        plans = []
        for plan_id in plan_ids:
            record = self.session.get(CreditCalibrationPlan, plan_id)
            if record is None:
                raise LookupError("校准方案不存在")
            run = self._latest_current_run(record)
            if run is None:
                raise ValueError(f"方案 {record.code} v{record.version} 缺少当前有效运行")
            plans.append((record, run))
        reference = plans[0][1]
        same_snapshot = all(run.dataset_snapshot_hash == reference.dataset_snapshot_hash for _, run in plans)
        same_baseline = all(run.baseline_config_hash == reference.baseline_config_hash for _, run in plans)
        comparable = same_snapshot and same_baseline
        return {
            "comparable": comparable,
            "compatibility": {"same_snapshot": same_snapshot, "same_baseline": same_baseline},
            "message": "方案使用相同固定快照与模型基线，可直接比较" if comparable else "方案快照或模型基线不一致，只能并列查看，不能据此排序采纳",
            "items": [self._comparison_item(plan, run) for plan, run in plans],
        }

    def _latest_current_run(self, plan: CreditCalibrationPlan) -> CreditCalibrationRun | None:
        run = self.session.scalars(select(CreditCalibrationRun).where(
            CreditCalibrationRun.plan_id == plan.id,
            CreditCalibrationRun.plan_config_hash == plan.config_hash,
            CreditCalibrationRun.status == "completed",
        ).order_by(CreditCalibrationRun.created_at.desc(), CreditCalibrationRun.id.desc())).first()
        return run if run and self._run_is_valid(run) else None

    def _run_is_valid(self, run: CreditCalibrationRun) -> bool:
        snapshot = self.session.get(RuleCenterReplayDatasetSnapshot, run.dataset_snapshot_id)
        return bool(
            snapshot and snapshot.content_hash == run.dataset_snapshot_hash
            and run.report_json.get("evidence_hash") == run.evidence_hash
            and run.report_json.get("model", {}).get("baseline_config_hash") == run.baseline_config_hash
        )

    def _plan(self, record: CreditCalibrationPlan) -> dict:
        runs = self.session.scalars(select(CreditCalibrationRun).where(
            CreditCalibrationRun.plan_id == record.id
        ).order_by(CreditCalibrationRun.created_at.desc(), CreditCalibrationRun.id.desc())).all()
        result = {
            "id": record.id, "code": record.code, "name": record.name, "version": record.version,
            "template_key": record.template_key, "status": record.status, "candidate": deepcopy(record.candidate_json),
            "positive_labels": deepcopy(record.sample_policy_json.get("positive_labels", [])),
            "sample_limit": record.sample_policy_json.get("sample_limit", 500), "business_basis": record.business_basis,
            "config_hash": record.config_hash, "created_by": record.created_by, "created_by_name": record.created_by_name,
            "submitted_at": _iso(record.submitted_at), "reviewed_by": record.reviewed_by,
            "reviewed_by_name": record.reviewed_by_name, "review_comment": record.review_comment,
            "reviewed_at": _iso(record.reviewed_at), "row_version": record.row_version,
            "created_at": _iso(record.created_at), "updated_at": _iso(record.updated_at),
        }
        result["runs"] = [self._run(run, record) for run in runs]
        result["latest_valid_run_id"] = next((run["id"] for run in result["runs"] if run["current_valid"]), None)
        return result

    def _run(self, record: CreditCalibrationRun, plan: CreditCalibrationPlan) -> dict:
        current_valid = record.plan_config_hash == plan.config_hash and self._run_is_valid(record)
        return {
            "id": record.id, "plan_id": record.plan_id, "plan_config_hash": record.plan_config_hash,
            "base_model_version": record.base_model_version, "baseline_config_hash": record.baseline_config_hash,
            "dataset_snapshot_id": record.dataset_snapshot_id, "dataset_snapshot_hash": record.dataset_snapshot_hash,
            "status": record.status, "report": deepcopy(record.report_json), "evidence_hash": record.evidence_hash,
            "evidence_level": record.evidence_level, "current_valid": current_valid,
            "error_message": record.error_message, "created_by": record.created_by, "created_by_name": record.created_by_name,
            "started_at": _iso(record.started_at), "completed_at": _iso(record.completed_at), "created_at": _iso(record.created_at),
        }

    @staticmethod
    def _comparison_item(plan: CreditCalibrationPlan, run: CreditCalibrationRun) -> dict:
        report = run.report_json
        metrics = report["candidate"]
        return {
            "plan_id": plan.id, "code": plan.code, "name": plan.name, "version": plan.version,
            "status": plan.status, "run_id": run.id, "evidence_level": run.evidence_level,
            "snapshot_hash": run.dataset_snapshot_hash, "baseline_config_hash": run.baseline_config_hash,
            "metrics": {key: metrics.get(key) for key in (
                "automatic_approval_rate", "manual_review_rate", "reject_rate", "average_limit",
                "total_limit", "average_payment_term_days", "event_exposure_ratio", "restricted_event_capture_rate",
            )},
            "migration": deepcopy(report.get("migration", {})),
        }

    def _versioned(self, plan_id: str, expected_row_version: int) -> CreditCalibrationPlan:
        record = self.session.get(CreditCalibrationPlan, plan_id)
        if record is None:
            raise LookupError("校准方案不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("校准方案已被其他用户更新，请刷新后重试")
        return record

    def _commit(self, record: CreditCalibrationPlan, event_type: str, actor: str, payload: dict) -> dict:
        try:
            self.session.flush()
            self.audit.append("credit_calibration_plan", record.id, event_type, actor, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("校准方案写入发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return self._plan(record)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
