from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import ApprovalCaseRecord, AuditEventRecord, AuthorityPolicyActivationRunRecord, AuthorityPolicyEvidenceAnchorRecord, CreditAuthorityPolicyRecord, CreditFacilityRecord, CreditReportRecord, CreditUsageRecord, DecisionVarianceRecord, DocumentCorrectionRecord, DocumentRecord, EnterpriseDataFieldRecord, EnterpriseDataImportRecord, EnterpriseDataResolutionRecord, EnterpriseIndicatorObservationRecord, FacilityAlertRecord, ModelChangeRecord, ModelGovernanceNotificationRecord, ModelMonitoringIssueRecord, ModelMonitoringRunRecord, ModelMonitoringScheduleRecord, ModelOutcomeImportRecord, ModelOutcomeRecord, ModelReleaseRecord, ModelSnapshotRecord, NotificationRecord, PortfolioRatingBatchRecord, RatingRunRecord, RiskEventRecord
from backend.document_correction_sla import MAX_CORRECTION_EXTENSION_COUNT, MAX_TOTAL_CORRECTION_EXTENSION_HOURS, MIN_MANUAL_REMINDER_INTERVAL_SECONDS, as_utc as correction_as_utc, correction_sla_snapshot, correction_sla_window
from backend.enterprise_data_governance import SOURCE_PRIORITIES, build_quality_summary, choose_effective_field, flatten_payload, freshness_days, freshness_status, source_priority, unflatten_fields, value_type
from backend.security import APPROVAL_STAGE_ROLES
from backend.task_lease import assignment_is_active, clear_assignment
from rating.approval_workflow import STAGE_SLA_HOURS, stage_label
from rating.risk_screening_policy import get_risk_screening_policy
from rating.template_resolver import resolve_template


BASE_DIR = Path(__file__).resolve().parents[1]


class ConcurrentUpdateError(RuntimeError):
    pass


class TaskOwnershipConflict(RuntimeError):
    pass


def content_hash(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _materialize_model_runtime_defaults(config: dict) -> dict:
    materialized = deepcopy(config)
    materialized["risk_screening_policy"] = get_risk_screening_policy(materialized)
    return materialized


class DemoRepository:
    def __init__(self) -> None:
        self._counterparties = self._load_json(BASE_DIR / "data" / "counterparties.json")
        self._templates = self._load_json(BASE_DIR / "data" / "model_templates.json")["templates"]
        monitoring_path = BASE_DIR / "data" / "model_monitoring_history.json"
        self._model_monitoring = self._load_json(monitoring_path).get("datasets", {}) if monitoring_path.exists() else {}

    def list_counterparties(self) -> list[dict]:
        return deepcopy(self._counterparties)

    def get_counterparty(self, counterparty_id: str) -> dict | None:
        item = next((row for row in self._counterparties if row["id"] == counterparty_id), None)
        return deepcopy(item) if item else None

    def get_raw_profile(self, counterparty_id: str) -> dict | None:
        counterparty = self.get_counterparty(counterparty_id)
        profile_id = (counterparty or {}).get("data_quality", {}).get("raw_profile_id")
        if not profile_id:
            return None
        profile_dir = BASE_DIR / "data" / "raw_enterprise_profiles"
        for path in profile_dir.glob("*.json"):
            profile = self._load_json(path)
            if profile.get("profile_id") == profile_id:
                return deepcopy(profile)
        return None

    def get_model_monitoring_dataset(self, template_key: str) -> dict | None:
        dataset = self._model_monitoring.get(template_key)
        return deepcopy(dataset) if dataset else None

    def get_template(self, template_key: str) -> dict | None:
        if template_key not in self._templates:
            return None
        return resolve_template(template_key, self._templates)

    def list_templates(self) -> list[dict]:
        return [
            {
                "key": key,
                "name": resolve_template(key, self._templates)["name"],
                "version": resolve_template(key, self._templates)["version"],
            }
            for key in self._templates
        ]

    @staticmethod
    def _load_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))


class EnterpriseDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def create_import(self, payload: dict, actor: str) -> tuple[dict, bool]:
        payload_hash = content_hash({key: value for key, value in payload.items() if key != "import_key"})
        existing = self.session.scalars(select(EnterpriseDataImportRecord).where(EnterpriseDataImportRecord.import_key == payload["import_key"])).first()
        if existing:
            if existing.payload_hash != payload_hash:
                raise ValueError("导入任务编号已存在，但载荷内容不一致")
            return _enterprise_import_to_dict(existing), True

        flat = flatten_payload(payload["payload"])
        import_source_priority = SOURCE_PRIORITIES[payload["source_type"]]
        observed_at = payload["as_of_date"]
        existing_rows = self.list_fields(payload["counterparty_id"])
        grouped: dict[str, list[dict]] = {}
        for item in existing_rows:
            grouped.setdefault(item["field_path"], []).append(item)
        evidence_map = payload.get("field_evidence", {})
        field_rows: list[dict] = []
        for field_path, value in flat.items():
            field_source_priority = source_priority(payload["source_type"], field_path)
            value_hash = content_hash(value)
            previous = choose_effective_field(grouped.get(field_path, []))
            if not previous or previous["value_hash"] == value_hash:
                conflict = "none"
            elif field_source_priority > int(previous["source_priority"]):
                conflict = "overrides_lower_priority"
            else:
                conflict = "requires_review"
            evidence = evidence_map.get(field_path, {})
            field_rows.append({
                "id": str(uuid4()),
                "counterparty_id": payload["counterparty_id"],
                "field_path": field_path,
                "value": deepcopy(value),
                "value_hash": value_hash,
                "value_type": value_type(value),
                "source_type": payload["source_type"],
                "source_name": payload["source_name"],
                "source_priority": field_source_priority,
                "evidence_reference": str(evidence.get("reference") or payload["evidence_reference"]),
                "evidence_locator": str(evidence.get("locator") or "") or None,
                "observed_at": observed_at,
                "freshness_days": freshness_days(field_path),
                "freshness_status": freshness_status(field_path, observed_at),
                "validation_status": "valid",
                "conflict_status": conflict,
            })
        all_paths = set(grouped) | set(flat)
        quality = build_quality_summary(field_rows, all_paths)
        status = "accepted_with_conflicts" if quality["conflict_count"] else "accepted"
        record = EnterpriseDataImportRecord(
            id=str(uuid4()), import_key=payload["import_key"], counterparty_id=payload["counterparty_id"],
            source_type=payload["source_type"], source_name=payload["source_name"], source_priority=import_source_priority,
            schema_version=payload["schema_version"], as_of_date=observed_at,
            evidence_reference=payload["evidence_reference"], payload_hash=payload_hash, status=status,
            field_count=quality["field_count"], conflict_count=quality["conflict_count"], stale_count=quality["stale_count"],
            invalid_count=quality["invalid_count"], quality_score=Decimal(str(quality["quality_score"])),
            quality_json=deepcopy(quality), created_by=actor,
        )
        try:
            self.session.add(record)
            self.session.flush()
            for item in field_rows:
                self.session.add(EnterpriseDataFieldRecord(
                    id=item["id"], import_id=record.id, counterparty_id=item["counterparty_id"], field_path=item["field_path"],
                    value_json=deepcopy(item["value"]), value_hash=item["value_hash"], value_type=item["value_type"],
                    source_type=item["source_type"], source_name=item["source_name"], source_priority=item["source_priority"],
                    evidence_reference=item["evidence_reference"], evidence_locator=item["evidence_locator"], observed_at=item["observed_at"],
                    freshness_days=item["freshness_days"], freshness_status=item["freshness_status"], validation_status=item["validation_status"],
                    conflict_status=item["conflict_status"],
                ))
            self.session.flush()
            self.audit.append("enterprise_data_import", record.id, "enterprise_data_imported", actor, {
                "import_key": record.import_key, "counterparty_id": record.counterparty_id, "source_type": record.source_type,
                "status": record.status, "field_count": record.field_count, "conflict_count": record.conflict_count,
                "stale_count": record.stale_count, "quality_score": float(record.quality_score), "payload_hash": record.payload_hash,
            })
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            concurrent = self.session.scalars(select(EnterpriseDataImportRecord).where(EnterpriseDataImportRecord.import_key == payload["import_key"])).first()
            if concurrent and concurrent.payload_hash == payload_hash:
                return _enterprise_import_to_dict(concurrent), True
            raise ConcurrentUpdateError("企业数据导入发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _enterprise_import_to_dict(record), False

    def list_imports(self, counterparty_id: str | None = None, limit: int = 50) -> list[dict]:
        statement = select(EnterpriseDataImportRecord).order_by(EnterpriseDataImportRecord.created_at.desc(), EnterpriseDataImportRecord.id.desc())
        if counterparty_id:
            statement = statement.where(EnterpriseDataImportRecord.counterparty_id == counterparty_id)
        return [_enterprise_import_to_dict(item) for item in self.session.scalars(statement.limit(limit)).all()]

    def list_fields(self, counterparty_id: str, field_path: str | None = None) -> list[dict]:
        statement = select(EnterpriseDataFieldRecord).where(EnterpriseDataFieldRecord.counterparty_id == counterparty_id)
        if field_path:
            statement = statement.where(EnterpriseDataFieldRecord.field_path == field_path)
        statement = statement.order_by(EnterpriseDataFieldRecord.observed_at.desc(), EnterpriseDataFieldRecord.created_at.desc(), EnterpriseDataFieldRecord.id.desc())
        return [_enterprise_field_to_dict(item) for item in self.session.scalars(statement).all()]

    def list_resolutions(self, counterparty_id: str, field_path: str | None = None) -> list[dict]:
        statement = select(EnterpriseDataResolutionRecord).where(EnterpriseDataResolutionRecord.counterparty_id == counterparty_id)
        if field_path:
            statement = statement.where(EnterpriseDataResolutionRecord.field_path == field_path)
        statement = statement.order_by(EnterpriseDataResolutionRecord.created_at.desc(), EnterpriseDataResolutionRecord.id.desc())
        return [_enterprise_resolution_to_dict(item) for item in self.session.scalars(statement).all()]

    def get_resolution(self, resolution_id: str) -> dict | None:
        record = self.session.get(EnterpriseDataResolutionRecord, resolution_id)
        return _enterprise_resolution_to_dict(record) if record else None

    def list_conflicts(self, counterparty_id: str) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for item in self.list_fields(counterparty_id):
            grouped.setdefault(item["field_path"], []).append(item)
        resolutions_by_path: dict[str, list[dict]] = {}
        for item in self.list_resolutions(counterparty_id):
            resolutions_by_path.setdefault(item["field_path"], []).append(item)
        conflicts = []
        for field_path, candidates in sorted(grouped.items()):
            if len({item["value_hash"] for item in candidates}) <= 1:
                continue
            snapshot_hash = _candidate_snapshot_hash(candidates)
            resolutions = resolutions_by_path.get(field_path, [])
            approved = next((item for item in resolutions if item["status"] == "approved" and item["candidate_snapshot_hash"] == snapshot_hash), None)
            pending = next((item for item in resolutions if item["status"] == "pending_review" and item["candidate_snapshot_hash"] == snapshot_hash), None)
            automatic = choose_effective_field(candidates)
            effective_id = approved["selected_field_id"] if approved else automatic["id"] if automatic else None
            prior_approved = next((item for item in resolutions if item["status"] == "approved"), None)
            status = "resolved" if approved else "pending_review" if pending else "reopened" if prior_approved else "unresolved"
            current_resolution = approved or pending or prior_approved
            conflicts.append({
                "counterparty_id": counterparty_id,
                "field_path": field_path,
                "status": status,
                "candidate_snapshot_hash": snapshot_hash,
                "automatic_field_id": automatic["id"] if automatic else None,
                "effective_field_id": effective_id,
                "is_resolved": bool(approved),
                "is_pending": bool(pending),
                "resolution": {**current_resolution, "is_current_snapshot": current_resolution["candidate_snapshot_hash"] == snapshot_hash} if current_resolution else None,
                "candidates": [{**item, "is_effective": item["id"] == effective_id} for item in candidates],
            })
        return conflicts

    def create_resolution(self, payload: dict, actor: str, actor_name: str) -> tuple[dict, bool]:
        candidates = self.list_fields(payload["counterparty_id"], payload["field_path"])
        if len({item["value_hash"] for item in candidates}) <= 1:
            raise ValueError("当前字段不存在需要裁决的候选值冲突")
        selected = next((item for item in candidates if item["id"] == payload["selected_field_id"]), None)
        if not selected:
            raise ValueError("所选候选值不属于当前企业与字段")
        snapshot_hash = _candidate_snapshot_hash(candidates)
        pending = self.session.scalars(
            select(EnterpriseDataResolutionRecord).where(
                EnterpriseDataResolutionRecord.counterparty_id == payload["counterparty_id"],
                EnterpriseDataResolutionRecord.field_path == payload["field_path"],
                EnterpriseDataResolutionRecord.status == "pending_review",
            )
        ).first()
        if pending:
            if pending.candidate_snapshot_hash != snapshot_hash:
                pending.status = "superseded"
                self.audit.append("enterprise_data_resolution", pending.id, "enterprise_data_resolution_expired", actor, {
                    "counterparty_id": pending.counterparty_id, "field_path": pending.field_path,
                    "previous_candidate_snapshot_hash": pending.candidate_snapshot_hash,
                    "current_candidate_snapshot_hash": snapshot_hash,
                    "reason": "new_candidate_evidence",
                })
                self.session.flush()
            elif pending.selected_field_id == selected["id"] and pending.created_by == actor:
                return _enterprise_resolution_to_dict(pending), True
            else:
                raise ValueError("该字段已有待审核裁决，请先完成审核")
        current_approved = self.session.scalars(
            select(EnterpriseDataResolutionRecord).where(
                EnterpriseDataResolutionRecord.counterparty_id == payload["counterparty_id"],
                EnterpriseDataResolutionRecord.field_path == payload["field_path"],
                EnterpriseDataResolutionRecord.status == "approved",
                EnterpriseDataResolutionRecord.candidate_snapshot_hash == snapshot_hash,
            )
        ).first()
        if current_approved:
            raise ValueError("当前候选值快照已经完成裁决")
        record = EnterpriseDataResolutionRecord(
            id=str(uuid4()), counterparty_id=payload["counterparty_id"], field_path=payload["field_path"],
            selected_field_id=selected["id"], selected_value_json=deepcopy(selected["value"]), selected_value_hash=selected["value_hash"],
            candidate_snapshot_hash=snapshot_hash, candidate_count=len(candidates), reason_category=payload["reason_category"],
            rationale=payload["rationale"], status="pending_review", created_by=actor, created_by_name=actor_name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("enterprise_data_resolution", record.id, "enterprise_data_resolution_submitted", actor, {
                "counterparty_id": record.counterparty_id, "field_path": record.field_path,
                "selected_field_id": record.selected_field_id, "selected_value_hash": record.selected_value_hash,
                "candidate_snapshot_hash": record.candidate_snapshot_hash, "reason_category": record.reason_category,
            })
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("字段冲突裁决提交发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _enterprise_resolution_to_dict(record), False

    def review_resolution(self, resolution_id: str, expected_row_version: int, decision: str, comment: str, actor: str, actor_name: str) -> dict:
        record = self.session.get(EnterpriseDataResolutionRecord, resolution_id)
        if not record:
            raise LookupError("字段冲突裁决不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("字段冲突裁决已被更新，请刷新后重试")
        if record.status != "pending_review":
            raise ValueError("只有待审核的字段冲突裁决可以评审")
        if record.created_by == actor:
            raise PermissionError("字段冲突裁决的提议人与审核人必须分离")
        candidates = self.list_fields(record.counterparty_id, record.field_path)
        if _candidate_snapshot_hash(candidates) != record.candidate_snapshot_hash:
            raise ConcurrentUpdateError("候选值集合已发生变化，请重新发起字段冲突裁决")
        if decision == "approve":
            previous = self.session.scalars(
                select(EnterpriseDataResolutionRecord).where(
                    EnterpriseDataResolutionRecord.counterparty_id == record.counterparty_id,
                    EnterpriseDataResolutionRecord.field_path == record.field_path,
                    EnterpriseDataResolutionRecord.status == "approved",
                )
            ).all()
            for item in previous:
                item.status = "superseded"
            record.status = "approved"
        else:
            record.status = "rejected"
        record.reviewed_by = actor
        record.reviewed_by_name = actor_name
        record.reviewed_at = datetime.now(timezone.utc)
        record.review_comment = comment
        try:
            self.session.flush()
            self.audit.append("enterprise_data_resolution", record.id, "enterprise_data_resolution_approved" if decision == "approve" else "enterprise_data_resolution_rejected", actor, {
                "counterparty_id": record.counterparty_id, "field_path": record.field_path,
                "selected_field_id": record.selected_field_id, "candidate_snapshot_hash": record.candidate_snapshot_hash,
                "decision": decision, "comment": comment,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("字段冲突裁决审核发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _enterprise_resolution_to_dict(record)

    def build_profile(self, counterparty_id: str) -> dict:
        fields = self.list_fields(counterparty_id)
        grouped: dict[str, list[dict]] = {}
        for item in fields:
            grouped.setdefault(item["field_path"], []).append(item)
        resolutions_by_path: dict[str, list[dict]] = {}
        for item in self.list_resolutions(counterparty_id):
            resolutions_by_path.setdefault(item["field_path"], []).append(item)
        effective_rows = []
        unresolved_conflicts = []
        resolved_conflicts = []
        pending_resolutions = []
        all_conflicts = []
        for field_path, candidates in grouped.items():
            distinct_values = len({item["value_hash"] for item in candidates}) > 1
            snapshot_hash = _candidate_snapshot_hash(candidates)
            resolutions = resolutions_by_path.get(field_path, [])
            approved = next((item for item in resolutions if item["status"] == "approved" and item["candidate_snapshot_hash"] == snapshot_hash), None)
            pending = next((item for item in resolutions if item["status"] == "pending_review" and item["candidate_snapshot_hash"] == snapshot_hash), None)
            automatic = choose_effective_field(candidates)
            selected = next((item for item in candidates if approved and item["id"] == approved["selected_field_id"]), None) or automatic
            if not selected:
                continue
            if distinct_values:
                all_conflicts.append(field_path)
                if approved:
                    resolved_conflicts.append(field_path)
                else:
                    unresolved_conflicts.append(field_path)
                if pending:
                    pending_resolutions.append(field_path)
            effective_rows.append({
                **selected,
                "selection_method": "approved_resolution" if approved else "automatic",
                "resolution_id": approved["id"] if approved else None,
                "unresolved_conflict": bool(distinct_values and not approved),
            })
        effective_rows.sort(key=lambda item: item["field_path"])
        effective_ids = {item["id"] for item in effective_rows}
        conflict_paths = sorted(unresolved_conflicts)
        quality = build_quality_summary(effective_rows, set(grouped), conflict_count=len(conflict_paths))
        sections: dict[str, int] = {}
        for item in effective_rows:
            section = item["field_path"].split(".", 1)[0]
            sections[section] = sections.get(section, 0) + 1
        imports = self.list_imports(counterparty_id)
        return {
            "counterparty_id": counterparty_id,
            "profile": unflatten_fields(effective_rows),
            "summary": {
                **quality, "import_count": len(imports), "source_count": len({item["source_name"] for item in fields}), "sections": sections,
                "total_conflict_count": len(all_conflicts), "resolved_conflict_count": len(resolved_conflicts),
                "pending_resolution_count": len(pending_resolutions), "resolution_count": sum(len(items) for items in resolutions_by_path.values()),
            },
            "effective_fields": [{**item, "is_effective": item["id"] in effective_ids} for item in effective_rows],
            "conflict_paths": conflict_paths,
            "all_conflict_paths": sorted(all_conflicts),
            "resolved_conflict_paths": sorted(resolved_conflicts),
            "pending_resolution_paths": sorted(pending_resolutions),
            "stale_fields": [item for item in effective_rows if item["freshness_status"] == "stale"],
            "recent_imports": imports[:10],
        }

    def lineage(self, counterparty_id: str, field_path: str) -> dict:
        candidates = self.list_fields(counterparty_id, field_path)
        snapshot_hash = _candidate_snapshot_hash(candidates)
        resolutions = self.list_resolutions(counterparty_id, field_path)
        approved = next((item for item in resolutions if item["status"] == "approved" and item["candidate_snapshot_hash"] == snapshot_hash), None)
        pending = next((item for item in resolutions if item["status"] == "pending_review" and item["candidate_snapshot_hash"] == snapshot_hash), None)
        automatic = choose_effective_field(candidates)
        effective = next((item for item in candidates if approved and item["id"] == approved["selected_field_id"]), None) or automatic
        return {
            "counterparty_id": counterparty_id,
            "field_path": field_path,
            "effective_field_id": effective["id"] if effective else None,
            "automatic_field_id": automatic["id"] if automatic else None,
            "candidate_snapshot_hash": snapshot_hash,
            "resolution": approved or pending,
            "resolution_status": "resolved" if approved else "pending_review" if pending else "unresolved",
            "candidates": [{**item, "is_effective": bool(effective and item["id"] == effective["id"])} for item in candidates],
        }


class EnterpriseIndicatorObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list(self, counterparty_id: str, indicator_id: str | None = None) -> list[dict]:
        statement = select(EnterpriseIndicatorObservationRecord).where(EnterpriseIndicatorObservationRecord.counterparty_id == counterparty_id)
        if indicator_id:
            statement = statement.where(EnterpriseIndicatorObservationRecord.indicator_id == indicator_id)
        statement = statement.order_by(EnterpriseIndicatorObservationRecord.created_at.desc(), EnterpriseIndicatorObservationRecord.id.desc())
        return [_indicator_observation_to_dict(item) for item in self.session.scalars(statement).all()]

    def get(self, observation_id: str) -> dict | None:
        record = self.session.get(EnterpriseIndicatorObservationRecord, observation_id)
        return _indicator_observation_to_dict(record) if record else None

    def effective(self, counterparty_id: str) -> list[dict]:
        rows = self.session.scalars(
            select(EnterpriseIndicatorObservationRecord)
            .where(
                EnterpriseIndicatorObservationRecord.counterparty_id == counterparty_id,
                EnterpriseIndicatorObservationRecord.status == "verified",
            )
            .order_by(EnterpriseIndicatorObservationRecord.reviewed_at.desc(), EnterpriseIndicatorObservationRecord.created_at.desc())
        ).all()
        selected: dict[str, EnterpriseIndicatorObservationRecord] = {}
        for row in rows:
            selected.setdefault(row.indicator_id, row)
        return [_indicator_observation_to_dict(item) for item in selected.values()]

    def create(self, payload: dict, actor: str, actor_name: str) -> dict:
        pending = self.session.scalars(
            select(EnterpriseIndicatorObservationRecord).where(
                EnterpriseIndicatorObservationRecord.counterparty_id == payload["counterparty_id"],
                EnterpriseIndicatorObservationRecord.indicator_id == payload["indicator_id"],
                EnterpriseIndicatorObservationRecord.status == "pending_review",
            )
        ).first()
        if pending:
            raise ValueError("该企业指标已有待复核数据，请先完成复核")
        record = EnterpriseIndicatorObservationRecord(
            id=str(uuid4()), counterparty_id=payload["counterparty_id"], indicator_id=payload["indicator_id"],
            indicator_name=payload["indicator_name"], values_json=deepcopy(payload["values"]),
            values_hash=content_hash(payload["values"]), evidence_document_id=payload.get("evidence_document_id"),
            evidence_reference=payload["evidence_reference"], observed_at=payload["observed_at"],
            status="pending_review", created_by=actor, created_by_name=actor_name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("enterprise_indicator_observation", record.id, "indicator_observation_submitted", actor, {
                "counterparty_id": record.counterparty_id, "indicator_id": record.indicator_id,
                "values_hash": record.values_hash, "evidence_document_id": record.evidence_document_id,
            })
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("指标数据提交发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _indicator_observation_to_dict(record)

    def review(self, observation_id: str, expected_row_version: int, decision: str, comment: str, actor: str, actor_name: str) -> dict:
        record = self.session.get(EnterpriseIndicatorObservationRecord, observation_id)
        if not record:
            raise LookupError("指标数据记录不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("指标数据已被更新，请刷新后重试")
        if record.status != "pending_review":
            raise ValueError("只有待复核指标数据可以审核")
        if record.created_by == actor:
            raise PermissionError("指标数据提交人与复核人必须分离")
        if decision == "verify":
            previous = self.session.scalars(
                select(EnterpriseIndicatorObservationRecord).where(
                    EnterpriseIndicatorObservationRecord.counterparty_id == record.counterparty_id,
                    EnterpriseIndicatorObservationRecord.indicator_id == record.indicator_id,
                    EnterpriseIndicatorObservationRecord.status == "verified",
                )
            ).all()
            for item in previous:
                item.status = "superseded"
            record.status = "verified"
        else:
            record.status = "rejected"
        record.reviewed_by = actor
        record.reviewed_by_name = actor_name
        record.reviewed_at = datetime.now(timezone.utc)
        record.review_comment = comment
        try:
            self.session.flush()
            self.audit.append("enterprise_indicator_observation", record.id, f"indicator_observation_{record.status}", actor, {
                "counterparty_id": record.counterparty_id, "indicator_id": record.indicator_id,
                "decision": decision, "comment": comment, "values_hash": record.values_hash,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("指标数据复核发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _indicator_observation_to_dict(record)


class _ModelGovernanceRepositoryBase:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def get_config(self, demo_repository: DemoRepository, template_key: str, version: str | None = None) -> dict | None:
        statement = select(ModelReleaseRecord).where(ModelReleaseRecord.template_key == template_key)
        if version:
            statement = statement.where(ModelReleaseRecord.model_version == version)
        else:
            statement = statement.where(ModelReleaseRecord.is_active.is_(True))
        release = self.session.scalars(statement.order_by(ModelReleaseRecord.published_at.desc())).first()
        if release:
            config = deepcopy(release.config_json)
            return _materialize_model_runtime_defaults(config)
        base = demo_repository.get_template(template_key)
        if not base or (version and base.get("version") != version):
            return None
        return _materialize_model_runtime_defaults(base)

    def list_changes(self, template_key: str | None = None) -> list[dict]:
        statement = select(ModelChangeRecord).order_by(ModelChangeRecord.created_at.desc(), ModelChangeRecord.id.desc())
        if template_key:
            statement = statement.where(ModelChangeRecord.template_key == template_key)
        return [_model_change_to_dict(record) for record in self.session.scalars(statement).all()]

    def get_change(self, change_id: str) -> dict | None:
        record = self.session.get(ModelChangeRecord, change_id)
        return _model_change_to_dict(record) if record else None

    def create_change(self, payload: dict, actor_subject: str, actor_name: str) -> dict:
        record = ModelChangeRecord(
            id=str(uuid4()),
            template_key=payload["template_key"],
            base_version=payload["base_version"],
            candidate_version=payload["candidate_version"],
            config_json=deepcopy(payload["config"]),
            validation_json=deepcopy(payload["validation"]),
            impact_json=deepcopy(payload["impact"]),
            change_reason=payload["change_reason"],
            created_by=actor_subject,
            created_by_name=actor_name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("model_change", record.id, "model_change_created", actor_name, {"template_key": record.template_key, "base_version": record.base_version, "candidate_version": record.candidate_version, "config_hash": record.validation_json["config_hash"]})
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("同一模型下候选版本不能重复") from exc
        self.session.refresh(record)
        return _model_change_to_dict(record)


class ModelMonitoringRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list_outcomes(self, template_key: str | None = None) -> list[dict]:
        statement = select(ModelOutcomeRecord).order_by(ModelOutcomeRecord.population_period, ModelOutcomeRecord.created_at, ModelOutcomeRecord.id)
        if template_key:
            statement = statement.where(ModelOutcomeRecord.template_key == template_key)
        return [_model_outcome_to_dict(record) for record in self.session.scalars(statement).all()]

    def create_outcome(self, payload: dict, actor: str) -> dict:
        existing = self.session.scalars(
            select(ModelOutcomeRecord).where(
                ModelOutcomeRecord.source == payload["source"],
                ModelOutcomeRecord.external_observation_id == payload["external_observation_id"],
            )
        ).first()
        if existing:
            if not _model_outcome_matches(existing, payload):
                raise ValueError("同一来源的观察编号已被不同结果占用")
            return {**_model_outcome_to_dict(existing), "idempotent": True}
        if _as_utc(payload["observation_end"]) <= _as_utc(payload["prediction_at"]):
            raise ValueError("观察截止时间必须晚于模型预测时间")
        if _as_utc(payload["observation_end"]) > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("观察截止时间不能晚于当前时间")
        record = ModelOutcomeRecord(
            id=str(uuid4()),
            external_observation_id=payload["external_observation_id"],
            source=payload["source"],
            template_key=payload["template_key"],
            model_version=payload["model_version"],
            counterparty_id=payload["counterparty_id"],
            population_period=payload["population_period"],
            predicted_score=Decimal(str(payload["predicted_score"])),
            predicted_pd=Decimal(str(payload["predicted_pd"])),
            observed_event=payload["observed_event"],
            prediction_at=_as_utc(payload["prediction_at"]),
            observation_end=_as_utc(payload["observation_end"]),
            evidence_reference=payload["evidence_reference"],
            created_by=actor,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("model_outcome", record.id, "model_outcome_ingested", actor, {"template_key": record.template_key, "model_version": record.model_version, "counterparty_id": record.counterparty_id, "population_period": record.population_period, "observed_event": record.observed_event, "source": record.source, "external_observation_id": record.external_observation_id})
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("观察结果写入发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return {**_model_outcome_to_dict(record), "idempotent": False}

    def list_outcome_imports(self, template_key: str | None = None, limit: int = 20) -> list[dict]:
        statement = select(ModelOutcomeImportRecord).order_by(ModelOutcomeImportRecord.created_at.desc(), ModelOutcomeImportRecord.id.desc())
        if template_key:
            statement = statement.where(ModelOutcomeImportRecord.template_key == template_key)
        return [_outcome_import_to_dict(record) for record in self.session.scalars(statement.limit(limit)).all()]

    def begin_outcome_import(self, payload: dict, actor: str) -> dict:
        existing = self.session.scalars(select(ModelOutcomeImportRecord).where(ModelOutcomeImportRecord.import_key == payload["import_key"])).first()
        if existing:
            if existing.payload_hash != payload["payload_hash"]:
                raise ValueError("结果导入任务编号已被不同数据占用")
            if existing.status == "failed":
                existing.status = "processing"
                existing.error_message = None
                existing.completed_at = None
                self.audit.append("model_outcome_import", existing.id, "outcome_import_retried", actor, {"import_key": existing.import_key})
                self.session.commit()
                self.session.refresh(existing)
            return {**_outcome_import_to_dict(existing), "idempotent": True}
        record = ModelOutcomeImportRecord(
            id=str(uuid4()), import_key=payload["import_key"], source=payload["source"], template_key=payload["template_key"],
            population_period=payload["population_period"], payload_hash=payload["payload_hash"], expected_count=payload["expected_count"],
            received_count=payload["received_count"], created_by=actor,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("model_outcome_import", record.id, "outcome_import_started", actor, {"import_key": record.import_key, "source": record.source, "template_key": record.template_key, "population_period": record.population_period, "expected_count": record.expected_count, "received_count": record.received_count})
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            concurrent = self.session.scalars(select(ModelOutcomeImportRecord).where(ModelOutcomeImportRecord.import_key == payload["import_key"])).first()
            if concurrent and concurrent.payload_hash == payload["payload_hash"]:
                return {**_outcome_import_to_dict(concurrent), "idempotent": True}
            raise ConcurrentUpdateError("结果导入任务创建发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return {**_outcome_import_to_dict(record), "idempotent": False}

    def complete_outcome_import(self, import_id: str, results: list[dict], actor: str) -> dict:
        record = self.session.get(ModelOutcomeImportRecord, import_id)
        if not record:
            raise LookupError("结果导入任务不存在")
        if record.status != "processing":
            return _outcome_import_to_dict(record)
        record.results_json = deepcopy(results)
        record.created_count = sum(item["status"] == "created" for item in results)
        record.idempotent_count = sum(item["status"] == "idempotent" for item in results)
        record.rejected_count = sum(item["status"] == "rejected" for item in results)
        count_matches = record.expected_count == record.received_count
        record.status = "completed" if count_matches and record.rejected_count == 0 else "completed_with_exceptions"
        record.completed_at = datetime.now(timezone.utc)
        try:
            self.session.flush()
            self.audit.append("model_outcome_import", record.id, "outcome_import_completed", actor, {"status": record.status, "expected_count": record.expected_count, "received_count": record.received_count, "created_count": record.created_count, "idempotent_count": record.idempotent_count, "rejected_count": record.rejected_count})
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("结果导入任务完成发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _outcome_import_to_dict(record)

    def fail_outcome_import(self, import_id: str, error_message: str, actor: str) -> dict:
        record = self.session.get(ModelOutcomeImportRecord, import_id)
        if not record:
            raise LookupError("结果导入任务不存在")
        record.status = "failed"
        record.error_message = error_message[:2000]
        record.completed_at = datetime.now(timezone.utc)
        self.audit.append("model_outcome_import", record.id, "outcome_import_failed", actor, {"error": record.error_message})
        self.session.commit()
        self.session.refresh(record)
        return _outcome_import_to_dict(record)

    def verify_outcome(self, outcome_id: str, expected_row_version: int, decision: str, note: str, actor: str) -> dict:
        record = self.session.get(ModelOutcomeRecord, outcome_id)
        if not record:
            raise LookupError("结果观察记录不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("结果观察记录已被更新，请刷新后重试")
        if record.verification_status != "pending_verification":
            raise ValueError("只有待核验的结果观察记录可以执行核验")
        if record.created_by == actor:
            raise PermissionError("结果录入人与证据核验人必须分离")
        record.verification_status = "verified" if decision == "verify" else "rejected"
        record.verified_by = actor
        record.verified_at = datetime.now(timezone.utc)
        record.verification_note = note
        try:
            self.session.flush()
            self.audit.append("model_outcome", record.id, "model_outcome_verified" if decision == "verify" else "model_outcome_rejected", actor, {"decision": decision, "note": note})
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("结果观察核验发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _model_outcome_to_dict(record)

    def list_issues(self, template_key: str | None = None) -> list[dict]:
        statement = select(ModelMonitoringIssueRecord).order_by(ModelMonitoringIssueRecord.created_at.desc(), ModelMonitoringIssueRecord.id.desc())
        if template_key:
            statement = statement.where(ModelMonitoringIssueRecord.template_key == template_key)
        return [_monitoring_issue_to_dict(record) for record in self.session.scalars(statement).all()]

    def list_runs(self, template_key: str | None = None, limit: int = 20) -> list[dict]:
        statement = select(ModelMonitoringRunRecord).order_by(ModelMonitoringRunRecord.created_at.desc(), ModelMonitoringRunRecord.id.desc())
        if template_key:
            statement = statement.where(ModelMonitoringRunRecord.template_key == template_key)
        return [_monitoring_run_to_dict(record) for record in self.session.scalars(statement.limit(limit)).all()]

    def get_run_by_key(self, run_key: str) -> dict | None:
        record = self.session.scalars(select(ModelMonitoringRunRecord).where(ModelMonitoringRunRecord.run_key == run_key)).first()
        return _monitoring_run_to_dict(record) if record else None

    def list_schedules(self, template_key: str | None = None) -> list[dict]:
        statement = select(ModelMonitoringScheduleRecord).order_by(ModelMonitoringScheduleRecord.template_key, ModelMonitoringScheduleRecord.created_at)
        if template_key:
            statement = statement.where(ModelMonitoringScheduleRecord.template_key == template_key)
        return [_monitoring_schedule_to_dict(record) for record in self.session.scalars(statement).all()]

    def list_due_schedules(self, as_of: datetime) -> list[dict]:
        statement = select(ModelMonitoringScheduleRecord).where(ModelMonitoringScheduleRecord.enabled.is_(True), ModelMonitoringScheduleRecord.next_run_at <= _as_utc(as_of)).order_by(ModelMonitoringScheduleRecord.next_run_at, ModelMonitoringScheduleRecord.id)
        return [_monitoring_schedule_to_dict(record) for record in self.session.scalars(statement).all()]

    def create_schedule(self, payload: dict, actor: str) -> dict:
        record = ModelMonitoringScheduleRecord(
            id=str(uuid4()), template_key=payload["template_key"], cadence=payload["cadence"], timezone_name=payload["timezone_name"],
            enabled=payload["enabled"], next_run_at=_as_utc(payload["next_run_at"]), created_by=actor, updated_by=actor,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("model_monitoring_schedule", record.id, "monitoring_schedule_created", actor, {"template_key": record.template_key, "cadence": record.cadence, "timezone_name": record.timezone_name, "enabled": record.enabled, "next_run_at": record.next_run_at.isoformat()})
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("该模型模板已存在监控计划") from exc
        self.session.refresh(record)
        return _monitoring_schedule_to_dict(record)

    def update_schedule(self, schedule_id: str, expected_row_version: int, payload: dict, actor: str) -> dict:
        record = self.session.get(ModelMonitoringScheduleRecord, schedule_id)
        if not record:
            raise LookupError("模型监控计划不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("模型监控计划已被更新，请刷新后重试")
        record.cadence = payload["cadence"]
        record.timezone_name = payload["timezone_name"]
        record.enabled = payload["enabled"]
        record.next_run_at = _as_utc(payload["next_run_at"])
        record.updated_by = actor
        try:
            self.session.flush()
            self.audit.append("model_monitoring_schedule", record.id, "monitoring_schedule_updated", actor, {"cadence": record.cadence, "timezone_name": record.timezone_name, "enabled": record.enabled, "next_run_at": record.next_run_at.isoformat()})
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("模型监控计划已被其他用户更新，请刷新后重试") from exc
        self.session.refresh(record)
        return _monitoring_schedule_to_dict(record)

    def record_schedule_execution(self, schedule_id: str, expected_row_version: int, scheduled_for: datetime, as_of: datetime, run_id: str | None, status: str, error_message: str | None, actor: str) -> dict:
        record = self.session.get(ModelMonitoringScheduleRecord, schedule_id)
        if not record:
            raise LookupError("模型监控计划不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("模型监控计划已被更新，请刷新后重试")
        record.last_scheduled_for = _as_utc(scheduled_for)
        record.last_run_at = datetime.now(timezone.utc)
        record.last_run_id = run_id
        record.last_status = status
        record.last_error = error_message[:2000] if error_message else None
        if status == "completed":
            next_run = _advance_schedule_at(_as_utc(scheduled_for), record.cadence)
            while next_run <= _as_utc(as_of):
                next_run = _advance_schedule_at(next_run, record.cadence)
            record.next_run_at = next_run
        else:
            record.next_run_at = _as_utc(scheduled_for)
        record.updated_by = actor
        try:
            self.session.flush()
            self.audit.append("model_monitoring_schedule", record.id, "monitoring_schedule_executed", actor, {"scheduled_for": record.last_scheduled_for.isoformat(), "run_id": run_id, "status": status, "next_run_at": record.next_run_at.isoformat(), "error": record.last_error})
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("模型监控计划执行状态更新发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _monitoring_schedule_to_dict(record)

    def begin_run(self, payload: dict, actor: str) -> dict:
        existing = self.session.scalars(select(ModelMonitoringRunRecord).where(ModelMonitoringRunRecord.run_key == payload["run_key"])).first()
        if existing:
            expected = (payload["template_key"], payload["as_of_period"], payload["trigger_type"])
            actual = (existing.template_key, existing.as_of_period, existing.trigger_type)
            if expected != actual:
                raise ValueError("监控运行键已被不同批次占用")
            if existing.status == "failed":
                existing.status = "running"
                existing.error_message = None
                existing.monitoring_json = {}
                existing.issue_ids = []
                existing.actor = actor
                existing.started_at = datetime.now(timezone.utc)
                existing.completed_at = None
                self.audit.append("model_monitoring_run", existing.id, "monitoring_run_retried", actor, {"run_key": existing.run_key, "template_key": existing.template_key, "as_of_period": existing.as_of_period})
                self.session.commit()
                self.session.refresh(existing)
                return {**_monitoring_run_to_dict(existing), "idempotent": False}
            return {**_monitoring_run_to_dict(existing), "idempotent": True}
        record = ModelMonitoringRunRecord(
            id=str(uuid4()), run_key=payload["run_key"], template_key=payload["template_key"], model_version=payload["model_version"],
            as_of_period=payload["as_of_period"], trigger_type=payload["trigger_type"], status="running",
            effective_source=payload["effective_source"], evidence_level=payload["evidence_level"], dataset_id=payload["dataset_id"],
            readiness_json=deepcopy(payload["readiness"]), monitoring_json={}, issue_ids=[], actor=actor,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("model_monitoring_run", record.id, "monitoring_run_started", actor, {"run_key": record.run_key, "template_key": record.template_key, "as_of_period": record.as_of_period, "trigger_type": record.trigger_type, "effective_source": record.effective_source})
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            concurrent = self.session.scalars(select(ModelMonitoringRunRecord).where(ModelMonitoringRunRecord.run_key == payload["run_key"])).first()
            if concurrent and (concurrent.template_key, concurrent.as_of_period, concurrent.trigger_type) == (payload["template_key"], payload["as_of_period"], payload["trigger_type"]):
                return {**_monitoring_run_to_dict(concurrent), "idempotent": True}
            raise ConcurrentUpdateError("监控运行批次创建发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return {**_monitoring_run_to_dict(record), "idempotent": False}

    def complete_run(self, run_id: str, monitoring: dict, issues: list[dict], actor: str) -> dict:
        record = self.session.get(ModelMonitoringRunRecord, run_id)
        if not record:
            raise LookupError("监控运行批次不存在")
        if record.status != "running":
            return _monitoring_run_to_dict(record)
        record.status = "completed"
        record.monitoring_json = deepcopy(monitoring)
        record.issue_ids = [issue["id"] for issue in issues]
        record.completed_at = datetime.now(timezone.utc)
        for issue in issues:
            for recipient_role in ("model_admin", "risk_manager"):
                dedup_key = f"{record.id}:{issue['id']}:{recipient_role}"
                self.session.add(
                    ModelGovernanceNotificationRecord(
                        id=str(uuid4()), monitoring_run_id=record.id, monitoring_issue_id=issue["id"], template_key=record.template_key,
                        recipient_role=recipient_role, severity=issue["severity"], title=f"{record.template_key} · {issue['title']}",
                        message=f"监控批次 {record.as_of_period} 检出 {issue['metric_label']}，当前状态：{issue['status']}。",
                        dedup_key=dedup_key,
                    )
                )
        try:
            self.session.flush()
            self.audit.append("model_monitoring_run", record.id, "monitoring_run_completed", actor, {"issue_ids": record.issue_ids, "issue_count": len(issues), "evidence_level": record.evidence_level, "dataset_id": record.dataset_id})
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("监控运行批次完成发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _monitoring_run_to_dict(record)

    def fail_run(self, run_id: str, error_message: str, actor: str) -> dict:
        record = self.session.get(ModelMonitoringRunRecord, run_id)
        if not record:
            raise LookupError("监控运行批次不存在")
        record.status = "failed"
        record.error_message = error_message[:2000]
        record.completed_at = datetime.now(timezone.utc)
        self.audit.append("model_monitoring_run", record.id, "monitoring_run_failed", actor, {"error": record.error_message})
        self.session.commit()
        self.session.refresh(record)
        return _monitoring_run_to_dict(record)

    def list_governance_notifications(self, roles: tuple[str, ...], unread_only: bool = False) -> list[dict]:
        statement = select(ModelGovernanceNotificationRecord).order_by(ModelGovernanceNotificationRecord.created_at.desc(), ModelGovernanceNotificationRecord.id.desc())
        if "admin" not in roles:
            statement = statement.where(ModelGovernanceNotificationRecord.recipient_role.in_(roles))
        if unread_only:
            statement = statement.where(ModelGovernanceNotificationRecord.status == "unread")
        return [_governance_notification_to_dict(record) for record in self.session.scalars(statement).all()]

    def read_governance_notification(self, notification_id: str, roles: tuple[str, ...], actor: str) -> dict:
        record = self.session.get(ModelGovernanceNotificationRecord, notification_id)
        if not record:
            raise LookupError("模型治理通知不存在")
        if "admin" not in roles and record.recipient_role not in roles:
            raise PermissionError("无权读取其他角色的模型治理通知")
        if record.status == "unread":
            record.status = "read"
            record.read_at = datetime.now(timezone.utc)
            record.read_by = actor
            self.audit.append("model_governance_notification", record.id, "governance_notification_read", actor, {"monitoring_run_id": record.monitoring_run_id, "monitoring_issue_id": record.monitoring_issue_id})
            self.session.commit()
            self.session.refresh(record)
        return _governance_notification_to_dict(record)

    def link_issue_change(self, issue_id: str, expected_row_version: int, change_id: str, actor: str) -> dict:
        issue = self._get_versioned_issue(issue_id, expected_row_version)
        change = self.session.get(ModelChangeRecord, change_id)
        if not change:
            raise LookupError("模型变更单不存在")
        if change.template_key != issue.template_key:
            raise ValueError("监控问题与模型变更单模板不一致")
        if change.status != "draft":
            raise ValueError("只能关联草稿状态的模型变更单")
        issue.linked_change_id = change.id
        return self._commit_issue(issue, "monitoring_issue_linked_to_change", actor, {"change_id": change.id, "candidate_version": change.candidate_version})

    def sync_issues(self, template_key: str, model_version: str, monitoring: dict, actor: str) -> list[dict]:
        dataset = monitoring.get("dataset") or {}
        dataset_id = str(dataset.get("dataset_id") or f"missing-{template_key}")
        evidence_level = str(dataset.get("evidence_level") or "none")
        if evidence_level == "observed_outcome":
            readiness_issues = self.session.scalars(
                select(ModelMonitoringIssueRecord).where(
                    ModelMonitoringIssueRecord.template_key == template_key,
                    ModelMonitoringIssueRecord.metric_key == "data_readiness",
                    ModelMonitoringIssueRecord.status != "closed",
                )
            ).all()
            for readiness_issue in readiness_issues:
                readiness_issue.status = "closed"
                readiness_issue.closed_at = datetime.now(timezone.utc)
                readiness_issue.revalidated_by = actor
                readiness_issue.revalidation_conclusion = "真实观察样本已达到正式回溯最低门槛"
                self.audit.append("model_monitoring_issue", readiness_issue.id, "monitoring_data_readiness_satisfied", actor, {"dataset_id": dataset_id, "evidence_level": evidence_level})
        candidates = [metric for metric in monitoring.get("performance_metrics", []) if metric.get("status") in {"warn", "fail"}]
        if evidence_level != "observed_outcome":
            candidates.append({"key": "data_readiness", "label": "真实结果数据完备性", "value": None, "status": "warn", "description": "当前监控仍依赖代理数据或缺少跨期真实观察结果"})
        created_or_open = []
        for metric in candidates:
            dedup_key = f"{template_key}:{dataset_id}:{metric['key']}"
            record = self.session.scalars(select(ModelMonitoringIssueRecord).where(ModelMonitoringIssueRecord.dedup_key == dedup_key)).first()
            if record and record.status == "closed":
                record.status = "open"
                record.closed_at = None
                record.revalidation_conclusion = None
                record.revalidated_by = None
                self.audit.append("model_monitoring_issue", record.id, "monitoring_issue_reopened", actor, {"metric_key": metric["key"], "metric_status": metric["status"], "metric_value": metric.get("value")})
            if not record:
                severity = "critical" if metric["status"] == "fail" else "warning"
                record = ModelMonitoringIssueRecord(
                    id=str(uuid4()), template_key=template_key, model_version=model_version, dataset_id=dataset_id,
                    evidence_level=evidence_level, metric_key=metric["key"], metric_label=metric["label"],
                    metric_value=Decimal(str(metric["value"])) if metric.get("value") is not None else None,
                    metric_status=metric["status"], severity=severity,
                    title=f"{metric['label']}需要治理", description=metric.get("description") or "监控指标未达到治理阈值",
                    dedup_key=dedup_key, created_by=actor,
                )
                self.session.add(record)
                self.session.flush()
                self.audit.append("model_monitoring_issue", record.id, "monitoring_issue_opened", actor, {"template_key": template_key, "dataset_id": dataset_id, "evidence_level": evidence_level, "metric_key": metric["key"], "metric_status": metric["status"], "metric_value": metric.get("value")})
            created_or_open.append(record)
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("监控问题生成发生并发冲突，请刷新后重试") from exc
        return [_monitoring_issue_to_dict(record) for record in created_or_open]

    def start_remediation(self, issue_id: str, expected_row_version: int, owner: str, plan: str, due_days: int, actor: str) -> dict:
        record = self._get_versioned_issue(issue_id, expected_row_version)
        if record.status not in {"open", "in_remediation"}:
            raise ValueError("只有待处理或整改中的问题可以制定整改计划")
        record.owner = owner
        record.remediation_plan = plan
        record.remediated_by = actor
        record.due_at = datetime.now(timezone.utc) + timedelta(days=due_days)
        record.status = "in_remediation"
        return self._commit_issue(record, "monitoring_remediation_started", actor, {"owner": owner, "plan": plan, "due_days": due_days})

    def submit_revalidation(self, issue_id: str, expected_row_version: int, result: str, actor: str) -> dict:
        record = self._get_versioned_issue(issue_id, expected_row_version)
        if record.status != "in_remediation":
            raise ValueError("只有整改中的问题可以提交复验")
        record.remediation_result = result
        record.remediated_by = actor
        record.status = "pending_revalidation"
        return self._commit_issue(record, "monitoring_revalidation_submitted", actor, {"result": result})

    def review_revalidation(self, issue_id: str, expected_row_version: int, decision: str, conclusion: str, actor: str) -> dict:
        record = self._get_versioned_issue(issue_id, expected_row_version)
        if record.status != "pending_revalidation":
            raise ValueError("只有待复验问题可以进行复核")
        if record.remediated_by == actor:
            raise PermissionError("整改执行人与复验审核人必须分离")
        record.revalidation_conclusion = conclusion
        record.revalidated_by = actor
        record.status = "closed" if decision == "pass" else "in_remediation"
        record.closed_at = datetime.now(timezone.utc) if decision == "pass" else None
        return self._commit_issue(record, "monitoring_revalidation_passed" if decision == "pass" else "monitoring_revalidation_failed", actor, {"decision": decision, "conclusion": conclusion})

    def _get_versioned_issue(self, issue_id: str, expected_row_version: int) -> ModelMonitoringIssueRecord:
        record = self.session.get(ModelMonitoringIssueRecord, issue_id)
        if not record:
            raise LookupError("监控问题不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("监控问题已被更新，请刷新后重试")
        return record

    def _commit_issue(self, record: ModelMonitoringIssueRecord, event_type: str, actor: str, payload: dict) -> dict:
        try:
            self.session.flush()
            self.audit.append("model_monitoring_issue", record.id, event_type, actor, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("监控问题更新发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _monitoring_issue_to_dict(record)

class ModelGovernanceRepository(_ModelGovernanceRepositoryBase):
    def update_change(self, change_id: str, expected_row_version: int, payload: dict, actor_subject: str, actor_name: str, allow_admin: bool = False) -> dict:
        record = self.session.get(ModelChangeRecord, change_id)
        if not record:
            raise LookupError("模型变更单不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"模型变更单版本已变化，当前版本为 {record.row_version}")
        if record.status != "draft":
            raise ValueError("只有草稿状态可以修改")
        if record.created_by != actor_subject and not allow_admin:
            raise PermissionError("只有变更单创建人可以修改草稿")
        record.config_json = deepcopy(payload["config"])
        record.validation_json = deepcopy(payload["validation"])
        record.impact_json = deepcopy(payload["impact"])
        record.change_reason = payload["change_reason"]
        return self._commit_change(record, "model_change_updated", actor_name, {"candidate_version": record.candidate_version, "config_hash": record.validation_json["config_hash"]})

    def submit_change(self, change_id: str, expected_row_version: int, actor_subject: str, actor_name: str, allow_admin: bool = False) -> dict:
        record = self.session.get(ModelChangeRecord, change_id)
        if not record:
            raise LookupError("模型变更单不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"模型变更单版本已变化，当前版本为 {record.row_version}")
        if record.status != "draft":
            raise ValueError("只有草稿状态可以提交审核")
        if record.created_by != actor_subject and not allow_admin:
            raise PermissionError("只有变更单创建人可以提交审核")
        if not record.validation_json.get("valid"):
            raise ValueError("配置校验未通过，不能提交审核")
        model_risk = record.validation_json.get("model_risk")
        if not model_risk:
            raise ValueError("缺少模型验证快照，请重新保存治理草稿")
        if not model_risk.get("release_gate", {}).get("passed"):
            raise ValueError(f"模型验证发布门槛未通过：{model_risk['release_gate'].get('summary', '请补充验证样本')}")
        record.status = "pending_review"
        record.submitted_at = datetime.now(timezone.utc)
        return self._commit_change(record, "model_change_submitted", actor_name, {"candidate_version": record.candidate_version})

    def review_change(self, change_id: str, expected_row_version: int, decision: str, comment: str, reviewer_subject: str, reviewer_name: str, demo_repository: DemoRepository) -> dict:
        record = self.session.get(ModelChangeRecord, change_id)
        if not record:
            raise LookupError("模型变更单不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"模型变更单版本已变化，当前版本为 {record.row_version}")
        if record.status != "pending_review":
            raise ValueError("只有待审核状态可以执行评审")
        if record.created_by == reviewer_subject:
            raise PermissionError("模型制作者不能审批自己创建的变更单")
        now = datetime.now(timezone.utc)
        record.reviewed_by = reviewer_subject
        record.reviewed_by_name = reviewer_name
        record.reviewed_at = now
        record.review_comment = comment
        if decision == "reject":
            record.status = "rejected"
            return self._commit_change(record, "model_change_rejected", reviewer_name, {"comment": comment})

        model_risk = record.validation_json.get("model_risk")
        if not model_risk:
            raise ValueError("缺少模型验证快照，请退回并重新保存治理草稿")
        if not model_risk.get("release_gate", {}).get("passed"):
            raise ValueError(f"模型验证发布门槛未通过：{model_risk['release_gate'].get('summary', '请补充验证样本')}")

        current = self.get_config(demo_repository, record.template_key)
        if not current or current.get("version") != record.base_version:
            raise ConcurrentUpdateError("生效模型已变化，请基于最新版本重新创建变更单")
        active = self.session.scalars(select(ModelReleaseRecord).where(ModelReleaseRecord.template_key == record.template_key, ModelReleaseRecord.is_active.is_(True))).first()
        if active:
            active.is_active = False
            try:
                self.session.flush()
            except (IntegrityError, StaleDataError) as exc:
                self.session.rollback()
                raise ConcurrentUpdateError("模型发布发生并发冲突，请刷新后重试") from exc
        else:
            baseline = demo_repository.get_template(record.template_key)
            existing_baseline = self.session.scalars(select(ModelReleaseRecord).where(ModelReleaseRecord.template_key == record.template_key, ModelReleaseRecord.model_version == baseline["version"])).first()
            if not existing_baseline:
                self.session.add(ModelReleaseRecord(id=str(uuid4()), template_key=record.template_key, model_version=baseline["version"], config_json=deepcopy(baseline), config_hash=content_hash(baseline), source_change_id=None, is_active=False, published_by="system-baseline"))
        release = ModelReleaseRecord(
            id=str(uuid4()),
            template_key=record.template_key,
            model_version=record.candidate_version,
            config_json=deepcopy(record.config_json),
            config_hash=record.validation_json["config_hash"],
            source_change_id=record.id,
            is_active=True,
            published_by=reviewer_name,
            published_at=now,
        )
        self.session.add(release)
        record.status = "published"
        record.published_at = now
        try:
            self.audit.append("model_change", record.id, "model_change_published", reviewer_name, {"release_id": release.id, "model_version": release.model_version, "comment": comment, "config_hash": release.config_hash})
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("模型发布发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        result = _model_change_to_dict(record)
        result["release_id"] = release.id
        return result

    def list_releases(self, template_key: str | None = None) -> list[dict]:
        statement = select(ModelReleaseRecord).order_by(ModelReleaseRecord.published_at.desc(), ModelReleaseRecord.id.desc())
        if template_key:
            statement = statement.where(ModelReleaseRecord.template_key == template_key)
        return [_model_release_to_dict(record) for record in self.session.scalars(statement).all()]

    def rollback(self, release_id: str, actor_name: str, comment: str) -> dict:
        target = self.session.get(ModelReleaseRecord, release_id)
        if not target:
            raise LookupError("模型发布版本不存在")
        if target.is_active:
            raise ValueError("目标版本已经是当前生效版本")
        current = self.session.scalars(select(ModelReleaseRecord).where(ModelReleaseRecord.template_key == target.template_key, ModelReleaseRecord.is_active.is_(True))).first()
        if current:
            current.is_active = False
            try:
                self.session.flush()
            except (IntegrityError, StaleDataError) as exc:
                self.session.rollback()
                raise ConcurrentUpdateError("模型回滚发生并发冲突，请刷新后重试") from exc
        try:
            target.is_active = True
            self.audit.append("model_release", target.id, "model_release_rolled_back", actor_name, {"template_key": target.template_key, "model_version": target.model_version, "previous_release_id": current.id if current else None, "comment": comment})
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("模型回滚发生并发冲突，请刷新后重试") from exc
        self.session.refresh(target)
        return _model_release_to_dict(target)

    def _commit_change(self, record: ModelChangeRecord, event_type: str, actor_name: str, payload: dict) -> dict:
        try:
            self.session.flush()
            self.audit.append("model_change", record.id, event_type, actor_name, payload)
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("模型变更单发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _model_change_to_dict(record)


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, aggregate_type: str, aggregate_id: str, event_type: str, actor: str, payload: dict) -> dict:
        existing = self.session.scalars(
            select(AuditEventRecord)
            .where(AuditEventRecord.aggregate_type == aggregate_type, AuditEventRecord.aggregate_id == aggregate_id)
        ).all()
        ordered = _order_hash_chain([_audit_to_dict(row) for row in existing])
        previous_hash = ordered[-1]["event_hash"] if ordered else ""
        event_id = str(uuid4())
        event_hash = content_hash(
            {
                "id": event_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "event_type": event_type,
                "actor": actor,
                "payload": payload,
                "previous_hash": previous_hash,
            }
        )
        record = AuditEventRecord(
            id=event_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            actor=actor,
            payload=deepcopy(payload),
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self.session.add(record)
        self.session.flush()
        return _audit_to_dict(record)

    def list(self, aggregate_id: str | None = None) -> list[dict]:
        statement = select(AuditEventRecord).order_by(AuditEventRecord.created_at, AuditEventRecord.id)
        if aggregate_id:
            statement = statement.where(AuditEventRecord.aggregate_id == aggregate_id)
        rows = [_audit_to_dict(row) for row in self.session.scalars(statement).all()]
        return _order_hash_chain(rows) if aggregate_id else rows


class ApprovalCaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def save(self, case: dict, actor: str = "system", event_type: str = "approval_case_updated", expected_row_version: int | None = None, audit_payload: dict | None = None, commit: bool = True, release_assignment: bool = False) -> dict:
        record = self.session.get(ApprovalCaseRecord, case["case_id"])
        previous_stage = record.current_stage if record else None
        previous_status = record.status if record else None
        if record is None:
            record = ApprovalCaseRecord(case_id=case["case_id"], counterparty_id=case["counterparty_id"], counterparty_name=case["counterparty_name"], current_stage=case["current_stage"], status=case["status"])
            self.session.add(record)
        elif expected_row_version is not None and record.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"审批记录版本已变化，当前版本为 {record.row_version}")
        try:
            record.current_stage = case["current_stage"]
            record.status = case["status"]
            record.completed_stages = deepcopy(case["completed_stages"])
            record.case_data = deepcopy(case["data"])
            record.timeline = deepcopy(case["timeline"])
            if previous_stage != case["current_stage"] or previous_status != case["status"] or release_assignment:
                clear_assignment(record)
            if case["status"] == "待补件":
                record.stage_due_at = None
            elif case["status"] == "处理中" and (
                previous_stage != case["current_stage"]
                or previous_status == "待补件"
                or not record.stage_due_at
            ):
                now = datetime.now(timezone.utc)
                record.stage_started_at = now
                record.stage_due_at = now + timedelta(hours=STAGE_SLA_HOURS.get(case["current_stage"], 24))
            self.session.flush()
            event_payload = {"stage": case["current_stage"], "status": case["status"], "row_version": record.row_version}
            event_payload.update(deepcopy(audit_payload or {}))
            self.audit.append("approval_case", case["case_id"], event_type, actor, event_payload)
            if commit:
                self.session.commit()
        except (StaleDataError, IntegrityError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("审批记录已被其他用户更新，请刷新后重试") from exc
        if commit:
            self.session.refresh(record)
        return _case_to_dict(record)

    def get(self, case_id: str) -> dict | None:
        record = self.session.get(ApprovalCaseRecord, case_id)
        return _case_to_dict(record) if record else None

    def list(self, counterparty_id: str | None = None) -> list[dict]:
        statement = select(ApprovalCaseRecord).order_by(ApprovalCaseRecord.created_at.desc())
        if counterparty_id:
            statement = statement.where(ApprovalCaseRecord.counterparty_id == counterparty_id)
        rows = self.session.scalars(statement).all()
        return [_case_to_dict(row) for row in rows]


class DecisionGovernanceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def record(self, case: dict, variance: dict, actor: str) -> dict:
        existing = self.session.scalars(select(DecisionVarianceRecord).where(DecisionVarianceRecord.case_id == case["case_id"])).first()
        if existing:
            return _decision_variance_to_dict(existing)
        scoring = case.get("data", {}).get("scoring", {})
        record = DecisionVarianceRecord(
            id=str(uuid4()),
            case_id=case["case_id"],
            counterparty_id=case["counterparty_id"],
            counterparty_name=case["counterparty_name"],
            rating_run_id=scoring.get("rating_run_id"),
            model_snapshot_id=scoring.get("model_snapshot_id"),
            direction=variance["direction"],
            materiality=variance["materiality"],
            recommendation_json=deepcopy(variance["recommendation"]),
            decision_json=deepcopy(variance["final_decision"]),
            variance_json={
                "changed_fields": deepcopy(variance["changed_fields"]),
                "deltas": deepcopy(variance["deltas"]),
                "requires_reason": variance["requires_reason"],
                "requires_compensating_controls": variance["requires_compensating_controls"],
            },
            reason_category=variance.get("reason_category"),
            reason_detail=variance.get("reason_detail"),
            compensating_controls=deepcopy(variance.get("compensating_controls", [])),
            decided_by=actor,
        )
        self.session.add(record)
        self.session.flush()
        self.audit.append(
            "approval_case",
            case["case_id"],
            "decision_variance_recorded",
            actor,
            {
                "variance_id": record.id,
                "direction": record.direction,
                "materiality": record.materiality,
                "changed_fields": variance["changed_fields"],
                "reason_category": record.reason_category,
            },
        )
        return _decision_variance_to_dict(record)

    def list(self, case_id: str | None = None, direction: str | None = None, materiality: str | None = None) -> list[dict]:
        statement = select(DecisionVarianceRecord).order_by(DecisionVarianceRecord.decided_at.desc(), DecisionVarianceRecord.id.desc())
        if case_id:
            statement = statement.where(DecisionVarianceRecord.case_id == case_id)
        if direction:
            statement = statement.where(DecisionVarianceRecord.direction == direction)
        if materiality:
            statement = statement.where(DecisionVarianceRecord.materiality == materiality)
        return [_decision_variance_to_dict(record) for record in self.session.scalars(statement).all()]

    def summary(self) -> dict:
        rows = self.list()
        adjusted = [item for item in rows if item["direction"] != "aligned"]
        limit_reductions = [abs(float(item["deltas"]["limit_ratio"])) for item in rows if float(item["deltas"]["limit_amount"]) < 0]
        directions = {key: sum(item["direction"] == key for item in rows) for key in ["aligned", "stricter", "relaxed", "mixed", "rejected"]}
        return {
            "total": len(rows),
            "aligned_count": directions["aligned"],
            "adjusted_count": len(adjusted),
            "material_count": sum(item["materiality"] == "material" for item in rows),
            "relaxation_count": directions["relaxed"] + directions["mixed"],
            "average_limit_reduction_rate": round(sum(limit_reductions) / len(limit_reductions), 4) if limit_reductions else 0,
            "direction_distribution": directions,
            "recent": rows[:8],
        }


class RatingRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def save_run(self, counterparty: dict, template_key: str, config: dict, result: dict, actor: str = "rating-agent", case_id: str | None = None, commit: bool = True) -> dict:
        config = _materialize_model_runtime_defaults(config)
        config_hash = content_hash(config)
        snapshot = self.session.scalars(
            select(ModelSnapshotRecord).where(
                ModelSnapshotRecord.template_key == template_key,
                ModelSnapshotRecord.model_version == config["version"],
                ModelSnapshotRecord.config_hash == config_hash,
            )
        ).first()
        if snapshot is None:
            snapshot = ModelSnapshotRecord(id=str(uuid4()), template_key=template_key, model_name=config["name"], model_version=config["version"], config_json=deepcopy(config), config_hash=config_hash)
            self.session.add(snapshot)
            self.session.flush()
        run = RatingRunRecord(
            id=str(uuid4()),
            counterparty_id=counterparty["id"],
            case_id=case_id,
            template_key=template_key,
            model_snapshot_id=snapshot.id,
            input_json=deepcopy(counterparty),
            input_hash=content_hash(counterparty),
            result_json=deepcopy(result),
            result_hash=content_hash(result),
        )
        self.session.add(run)
        self.audit.append("rating_run", run.id, "rating_completed", actor, {
            "counterparty_id": counterparty["id"], "case_id": case_id, "model_snapshot_id": snapshot.id,
            "input_hash": run.input_hash, "result_hash": run.result_hash,
            "data_snapshot_hash": counterparty.get("_data_governance", {}).get("data_snapshot_hash"),
            "mapping_snapshot_hash": counterparty.get("_data_governance", {}).get("mapping_snapshot_hash"),
        })
        self.session.flush()
        if commit:
            self.session.commit()
            self.session.refresh(run)
        return _rating_run_to_dict(run)

    def get(self, run_id: str) -> dict | None:
        record = self.session.get(RatingRunRecord, run_id)
        return _rating_run_to_dict(record) if record else None

    def list(self, counterparty_id: str | None = None) -> list[dict]:
        statement = select(RatingRunRecord).order_by(RatingRunRecord.created_at.desc())
        if counterparty_id:
            statement = statement.where(RatingRunRecord.counterparty_id == counterparty_id)
        return [_rating_run_to_dict(row) for row in self.session.scalars(statement).all()]


class PortfolioRatingBatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list(self, template_key: str | None = None, limit: int = 20) -> list[dict]:
        statement = select(PortfolioRatingBatchRecord).order_by(PortfolioRatingBatchRecord.created_at.desc())
        if template_key:
            statement = statement.where(PortfolioRatingBatchRecord.template_key == template_key)
        return [_portfolio_rating_batch_to_dict(item) for item in self.session.scalars(statement.limit(limit)).all()]

    def get(self, batch_id: str) -> dict | None:
        record = self.session.get(PortfolioRatingBatchRecord, batch_id)
        return _portfolio_rating_batch_to_dict(record) if record else None

    def get_by_key(self, batch_key: str) -> dict | None:
        record = self.session.scalars(
            select(PortfolioRatingBatchRecord).where(PortfolioRatingBatchRecord.batch_key == batch_key)
        ).first()
        return _portfolio_rating_batch_to_dict(record) if record else None

    def create(self, payload: dict, actor: str, actor_name: str) -> dict:
        existing = self.get_by_key(payload["batch_key"])
        if existing:
            if existing["request_hash"] != payload["request_hash"]:
                raise ValueError("批次编号已存在，但模型、范围或输入快照已变化")
            return {**existing, "idempotent": True}
        record = PortfolioRatingBatchRecord(
            id=str(uuid4()),
            batch_key=payload["batch_key"],
            request_hash=payload["request_hash"],
            template_key=payload["template_key"],
            model_version=payload["model_version"],
            model_snapshot_id=payload.get("model_snapshot_id"),
            scope_type=payload["scope_type"],
            status=payload["status"],
            candidate_count=payload["candidate_count"],
            success_count=payload["success_count"],
            skipped_count=payload["skipped_count"],
            summary_json=deepcopy(payload["summary"]),
            results_json=deepcopy(payload["results"]),
            skipped_json=deepcopy(payload["skipped"]),
            result_hash=payload["result_hash"],
            created_by=actor,
            created_by_name=actor_name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("portfolio_rating_batch", record.id, "portfolio_rating_completed", actor, {
                "batch_key": record.batch_key,
                "template_key": record.template_key,
                "model_version": record.model_version,
                "scope_type": record.scope_type,
                "candidate_count": record.candidate_count,
                "success_count": record.success_count,
                "skipped_count": record.skipped_count,
                "request_hash": record.request_hash,
                "result_hash": record.result_hash,
            })
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("组合评级批次发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return {**_portfolio_rating_batch_to_dict(record), "idempotent": False}

    def rollback(self) -> None:
        self.session.rollback()


class CreditReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list(self, case_id: str | None = None, counterparty_id: str | None = None) -> list[dict]:
        statement = select(CreditReportRecord).order_by(CreditReportRecord.created_at.desc(), CreditReportRecord.report_version.desc())
        if case_id:
            statement = statement.where(CreditReportRecord.case_id == case_id)
        if counterparty_id:
            statement = statement.where(CreditReportRecord.counterparty_id == counterparty_id)
        return [_credit_report_to_dict(record) for record in self.session.scalars(statement).all()]

    def get(self, report_id: str) -> dict | None:
        record = self.session.get(CreditReportRecord, report_id)
        return _credit_report_to_dict(record) if record else None

    def get_by_case_snapshot(self, case_id: str, snapshot_hash: str) -> dict | None:
        record = self.session.scalars(
            select(CreditReportRecord).where(CreditReportRecord.case_id == case_id, CreditReportRecord.snapshot_hash == snapshot_hash)
        ).first()
        return _credit_report_to_dict(record) if record else None

    def next_version(self, case_id: str) -> int:
        rows = self.session.scalars(select(CreditReportRecord.report_version).where(CreditReportRecord.case_id == case_id)).all()
        return max(rows, default=0) + 1

    def create(self, metadata: dict, actor: str) -> tuple[dict, bool]:
        record = CreditReportRecord(**metadata, created_by=actor)
        self.session.add(record)
        try:
            self.session.flush()
            event_payload = {
                "report_no": record.report_no,
                "case_id": record.case_id,
                "counterparty_id": record.counterparty_id,
                "report_version": record.report_version,
                "snapshot_hash": record.snapshot_hash,
                "pdf_sha256": record.pdf_sha256,
                "size_bytes": record.size_bytes,
            }
            self.audit.append("credit_report", record.id, "credit_report_sealed", actor, event_payload)
            self.audit.append("approval_case", record.case_id, "credit_report_generated", actor, event_payload)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.session.scalars(
                select(CreditReportRecord).where(
                    CreditReportRecord.case_id == metadata["case_id"],
                    CreditReportRecord.snapshot_hash == metadata["snapshot_hash"],
                )
            ).first()
            if existing:
                return _credit_report_to_dict(existing), True
            raise ConcurrentUpdateError("信用报告归档发生并发冲突，请刷新后重试") from exc
        self.session.refresh(record)
        return _credit_report_to_dict(record), False


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def create(self, metadata: dict, actor: str, correction_id: str | None = None, assignment_subject: str | None = None) -> dict:
        metadata.setdefault("created_at", datetime.now(timezone.utc))
        record = DocumentRecord(**metadata)
        correction = None
        if correction_id:
            correction = self.session.get(DocumentCorrectionRecord, correction_id)
            if not correction:
                raise LookupError("补件任务不存在")
            if correction.status != "open":
                raise ValueError("补件任务当前不允许上传替换资料")
            if assignment_is_active(correction) and correction.assigned_to != assignment_subject:
                raise TaskOwnershipConflict(f"补件任务已由{correction.assigned_to_name or '其他人员'}认领")
            if correction.counterparty_id != record.counterparty_id or correction.case_id != record.case_id or correction.document_type != record.document_type:
                raise ValueError("替换资料与补件任务的企业、审批单或资料类型不匹配")
        self.session.add(record)
        self.audit.append(
            "document",
            record.id,
            "document_uploaded",
            actor,
            {"counterparty_id": record.counterparty_id, "case_id": record.case_id, "document_type": record.document_type, "sha256": record.sha256, "size_bytes": record.size_bytes},
        )
        if correction:
            self.session.flush()
            version_ids = list(correction.version_document_ids_json or [])
            if record.id not in version_ids:
                version_ids.append(record.id)
            correction.current_document_id = record.id
            correction.version_document_ids_json = version_ids
            correction.status = "resubmitted"
            correction.assigned_role, correction.sla_started_at, correction.sla_due_at = correction_sla_window("resubmitted", datetime.now(timezone.utc))
            clear_assignment(correction)
            correction.attempt_count += 1
            correction.resolved_by = None
            correction.resolved_by_name = None
            correction.resolved_at = None
            self.audit.append(
                "document_correction",
                correction.id,
                "correction_resubmitted",
                actor,
                {
                    "replacement_document_id": record.id,
                    "attempt_count": correction.attempt_count,
                    "version_document_ids": version_ids,
                    "assigned_role": correction.assigned_role,
                    "sla_due_at": correction.sla_due_at.isoformat(),
                },
            )
            self._notify_correction_lifecycle(
                correction,
                event="resubmitted",
                roles={correction.assigned_role},
                level="resubmitted",
                title="补件新版本待复核",
                message=f"{correction.document_type} 已提交第 {correction.attempt_count} 个替换版本，请完成独立复核。",
            )
        try:
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("补件任务已被其他用户更新，请刷新后重试") from exc
        self.session.refresh(record)
        return _document_to_dict(record)

    def get(self, document_id: str) -> dict | None:
        record = self.session.get(DocumentRecord, document_id)
        return _document_to_dict(record) if record else None

    def list(self, counterparty_id: str | None = None, case_id: str | None = None) -> list[dict]:
        statement = select(DocumentRecord).order_by(DocumentRecord.created_at.desc())
        if counterparty_id:
            statement = statement.where(DocumentRecord.counterparty_id == counterparty_id)
        if case_id:
            statement = statement.where(DocumentRecord.case_id == case_id)
        return [_document_to_dict(row) for row in self.session.scalars(statement).all()]

    def get_correction(self, correction_id: str) -> dict | None:
        record = self.session.get(DocumentCorrectionRecord, correction_id)
        return _document_correction_to_dict(record) if record else None

    def list_corrections(self, counterparty_id: str | None = None, case_id: str | None = None) -> list[dict]:
        statement = select(DocumentCorrectionRecord).order_by(DocumentCorrectionRecord.created_at.desc())
        if counterparty_id:
            statement = statement.where(DocumentCorrectionRecord.counterparty_id == counterparty_id)
        if case_id:
            statement = statement.where(DocumentCorrectionRecord.case_id == case_id)
        return [_document_correction_to_dict(row) for row in self.session.scalars(statement).all()]

    def list_correction_workbench(self, active_only: bool = True) -> list[dict]:
        statement = select(DocumentCorrectionRecord).order_by(
            DocumentCorrectionRecord.sla_due_at.asc(),
            DocumentCorrectionRecord.created_at.desc(),
        )
        if active_only:
            statement = statement.where(DocumentCorrectionRecord.status.in_(["open", "resubmitted"]))
        records = self.session.scalars(statement).all()
        if not records:
            return []
        case_ids = {record.case_id for record in records if record.case_id}
        case_names = {
            row.case_id: row.counterparty_name
            for row in self.session.scalars(select(ApprovalCaseRecord).where(ApprovalCaseRecord.case_id.in_(case_ids))).all()
        } if case_ids else {}
        record_ids = [record.id for record in records]
        action_events = self.session.scalars(
            select(AuditEventRecord)
            .where(
                AuditEventRecord.aggregate_type == "document_correction",
                AuditEventRecord.aggregate_id.in_(record_ids),
            )
            .order_by(AuditEventRecord.created_at, AuditEventRecord.id)
        ).all()
        raw_events_by_id: dict[str, list[dict]] = {}
        for event in action_events:
            raw_events_by_id.setdefault(event.aggregate_id, []).append(_audit_to_dict(event))
        action_event_types = {"correction_manually_reminded", "correction_reassigned", "correction_sla_extended"}
        events_by_id = {
            record_id: [
                {
                    "event_type": event["event_type"],
                    "actor": event["actor"],
                    "reason": event["payload"].get("reason", ""),
                    "detail": event["payload"].get("detail", ""),
                    "created_at": event["created_at"],
                }
                for event in reversed(_order_hash_chain(events))
                if event["event_type"] in action_event_types
            ][:5]
            for record_id, events in raw_events_by_id.items()
        }
        result = []
        for record in records:
            item = _document_correction_to_dict(record)
            item["counterparty_name"] = case_names.get(record.case_id, record.counterparty_id)
            item["recent_actions"] = events_by_id.get(record.id, [])
            result.append(item)
        return result

    def _notify_correction_lifecycle(
        self,
        correction: DocumentCorrectionRecord,
        *,
        event: str,
        roles: set[str],
        level: str,
        title: str,
        message: str,
        severity: str = "info",
        action_page: str = "documents",
    ) -> None:
        if not correction.case_id:
            return
        notifications = NotificationRepository(self.session)
        for role in sorted(roles):
            notifications.create_if_absent(
                {
                    "case_id": correction.case_id,
                    "counterparty_id": correction.counterparty_id,
                    "recipient_role": role,
                    "category": "document_correction",
                    "level": level,
                    "severity": severity,
                    "title": title,
                    "message": message,
                    "action_json": {
                        "page": action_page,
                        "counterparty_id": correction.counterparty_id,
                        "case_id": correction.case_id,
                        "correction_id": correction.id,
                    },
                    "dedup_key": f"correction-lifecycle:{correction.id}:{event}:{correction.attempt_count}:{role}",
                    "status": "unread",
                }
            )

    def act_on_correction(
        self,
        correction_id: str,
        expected_row_version: int,
        action: str,
        reason: str,
        actor: str,
        assigned_role: str | None = None,
        extension_hours: int | None = None,
    ) -> dict:
        record = self.session.get(DocumentCorrectionRecord, correction_id)
        if not record:
            raise LookupError("补件任务不存在")
        if record.status not in {"open", "resubmitted"}:
            raise ValueError("已结束的补件任务不能继续处置")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("补件任务已被其他人员更新，请刷新后重试")
        now = datetime.now(timezone.utc)
        event_type: str
        event_payload = {"action": action, "reason": reason}
        notification_roles: set[str] = set()
        notification_level: str
        notification_title: str
        notification_message: str

        if action == "remind":
            if not record.case_id:
                raise ValueError("未关联审批申请的补件任务不能发送站内催办")
            if record.last_reminded_at and (now - correction_as_utc(record.last_reminded_at)).total_seconds() < MIN_MANUAL_REMINDER_INTERVAL_SECONDS:
                raise ValueError("同一补件任务两次人工催办至少间隔 30 分钟")
            record.reminder_count += 1
            record.last_reminded_at = now
            notification_roles = {record.assigned_role}
            if record.status == "open":
                notification_roles.add("client")
            notification_level = "reminder"
            notification_title = "补件任务人工催办"
            notification_message = f"{record.document_type} 补件任务待处理，请在 {record.sla_due_at.isoformat()} 前完成。催办原因：{reason}"
            event_type = "correction_manually_reminded"
            event_payload.update(
                {
                    "reminder_count": record.reminder_count,
                    "recipient_roles": sorted(notification_roles),
                    "detail": f"第 {record.reminder_count} 次人工催办",
                }
            )
        elif action == "reassign":
            allowed_roles = {
                "open": {"client", "relationship_manager"},
                "resubmitted": {"risk_manager", "approver"},
            }[record.status]
            if assigned_role not in allowed_roles:
                raise ValueError("目标角色不具备当前补件节点的实际处理权限")
            if assigned_role == record.assigned_role:
                raise ValueError("目标角色与当前责任角色相同")
            previous_role = record.assigned_role
            previous_assignee = record.assigned_to
            previous_assignee_name = record.assigned_to_name
            record.assigned_role = assigned_role
            clear_assignment(record)
            notification_roles = {assigned_role}
            notification_level = "assignment"
            notification_title = "补件任务已转派"
            notification_message = f"{record.document_type} 补件任务已转派给当前角色，截止时间 {record.sla_due_at.isoformat()}。转派原因：{reason}"
            event_type = "correction_reassigned"
            event_payload.update(
                {
                    "previous_role": previous_role,
                    "previous_assignee": previous_assignee,
                    "previous_assignee_name": previous_assignee_name,
                    "assigned_role": assigned_role,
                    "detail": f"{previous_role} → {assigned_role}",
                }
            )
        elif action == "extend":
            if not extension_hours:
                raise ValueError("延期操作必须指定延期小时数")
            if record.extension_count >= MAX_CORRECTION_EXTENSION_COUNT:
                raise ValueError("单个补件任务最多允许延期 3 次")
            if record.total_extension_hours + extension_hours > MAX_TOTAL_CORRECTION_EXTENSION_HOURS:
                raise ValueError("单个补件任务累计延期不能超过 168 小时")
            previous_due_at = record.sla_due_at
            record.sla_due_at = record.sla_due_at + timedelta(hours=extension_hours)
            record.extension_count += 1
            record.total_extension_hours += extension_hours
            notification_roles = {record.assigned_role}
            if record.status == "open":
                notification_roles.add("client")
            notification_level = "extension"
            notification_title = "补件任务 SLA 已延期"
            notification_message = f"{record.document_type} 补件任务延期 {extension_hours} 小时，新截止时间 {record.sla_due_at.isoformat()}。延期原因：{reason}"
            event_type = "correction_sla_extended"
            event_payload.update(
                {
                    "extension_hours": extension_hours,
                    "previous_due_at": previous_due_at.isoformat(),
                    "sla_due_at": record.sla_due_at.isoformat(),
                    "extension_count": record.extension_count,
                    "total_extension_hours": record.total_extension_hours,
                    "detail": f"延期 {extension_hours} 小时",
                }
            )
        else:
            raise ValueError("不支持的补件处置动作")

        try:
            self.session.flush()
            self.audit.append("document_correction", record.id, event_type, actor, event_payload)
            if record.case_id:
                notifications = NotificationRepository(self.session)
                for role in sorted(notification_roles):
                    notifications.create_if_absent(
                        {
                            "case_id": record.case_id,
                            "counterparty_id": record.counterparty_id,
                            "recipient_role": role,
                            "category": "document_correction",
                            "level": notification_level,
                            "severity": "warning" if action == "remind" else "info",
                            "title": notification_title,
                            "message": notification_message,
                            "action_json": {
                                "page": "documents",
                                "counterparty_id": record.counterparty_id,
                                "case_id": record.case_id,
                                "correction_id": record.id,
                            },
                            "dedup_key": f"correction-action:{record.id}:{record.row_version}:{action}:{role}",
                            "status": "unread",
                        }
                    )
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("补件任务已被其他人员更新，请刷新后重试") from exc
        self.session.refresh(record)
        return _document_correction_to_dict(record)

    def link_case(
        self,
        document_id: str,
        case_id: str,
        expected_row_version: int,
        actor_name: str,
    ) -> dict:
        record = self.session.get(DocumentRecord, document_id)
        if not record:
            raise LookupError("资料不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("资料归属已更新，请刷新后重试")
        if record.case_id and record.case_id != case_id:
            raise ValueError("资料已关联其他审批申请，不能直接改绑")
        if record.case_id == case_id:
            return _document_to_dict(record)
        record.case_id = case_id
        try:
            self.session.flush()
            self.audit.append(
                "document",
                record.id,
                "document_linked_to_case",
                actor_name,
                {"case_id": case_id, "counterparty_id": record.counterparty_id},
            )
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("资料归属已被其他用户更新，请刷新后重试") from exc
        self.session.refresh(record)
        return _document_to_dict(record)

    def review(
        self,
        document_id: str,
        expected_row_version: int,
        decision: str,
        comment: str,
        checks: list[dict],
        actor_subject: str,
        actor_name: str,
    ) -> dict:
        record = self.session.get(DocumentRecord, document_id)
        if not record:
            raise LookupError("资料不存在")
        if record.row_version != expected_row_version:
            raise ConcurrentUpdateError("资料检查状态已更新，请刷新后重试")
        if record.uploaded_by == actor_subject:
            raise PermissionError("资料上传人与检查人必须分离")
        active_correction = self.session.scalars(
            select(DocumentCorrectionRecord).where(
                DocumentCorrectionRecord.current_document_id == document_id,
                DocumentCorrectionRecord.status.in_(["open", "resubmitted"]),
            ).order_by(DocumentCorrectionRecord.created_at.desc())
        ).first()
        if active_correction and assignment_is_active(active_correction) and active_correction.assigned_to != actor_subject:
            raise TaskOwnershipConflict(f"补件任务已由{active_correction.assigned_to_name or '其他人员'}认领")
        if decision == "verify" and any(item.get("status") != "pass" for item in checks):
            raise ValueError("核验通过要求全部检查项均为通过，不能包含不通过或不适用")
        record.checklist_json = deepcopy(checks)
        record.review_status = {
            "verify": "verified",
            "needs_supplement": "needs_supplement",
            "reject": "rejected",
        }[decision]
        record.status = {
            "verify": "已核验",
            "needs_supplement": "待补充",
            "reject": "已驳回",
        }[decision]
        record.review_comment = comment
        record.reviewed_by = actor_subject
        record.reviewed_by_name = actor_name
        record.reviewed_at = datetime.now(timezone.utc)
        try:
            self.session.flush()
            self._update_correction_after_review(record, decision, comment, checks, actor_subject, actor_name)
            self.audit.append(
                "document",
                record.id,
                "document_reviewed",
                actor_name,
                {
                    "decision": decision,
                    "review_status": record.review_status,
                    "checks": checks,
                    "comment": comment,
                },
            )
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("资料检查状态已被其他用户更新，请刷新后重试") from exc
        self.session.refresh(record)
        return _document_to_dict(record)

    def _update_correction_after_review(
        self,
        document: DocumentRecord,
        decision: str,
        comment: str,
        checks: list[dict],
        actor_subject: str,
        actor_name: str,
    ) -> None:
        correction = self.session.scalars(
            select(DocumentCorrectionRecord).where(
                DocumentCorrectionRecord.current_document_id == document.id,
                DocumentCorrectionRecord.status.in_(["open", "resubmitted"]),
            ).order_by(DocumentCorrectionRecord.created_at.desc())
        ).first()
        now = datetime.now(timezone.utc)
        failed_check_keys = [item["key"] for item in checks if item.get("status") != "pass"]
        if decision == "needs_supplement":
            assigned_role, sla_started_at, sla_due_at = correction_sla_window("open", now)
            if not correction:
                correction = DocumentCorrectionRecord(
                    id=str(uuid4()),
                    counterparty_id=document.counterparty_id,
                    case_id=document.case_id,
                    document_type=document.document_type,
                    original_document_id=document.id,
                    current_document_id=document.id,
                    version_document_ids_json=[document.id],
                    status="open",
                    reason=comment,
                    failed_check_keys_json=failed_check_keys,
                    attempt_count=0,
                    requested_by=actor_subject,
                    requested_by_name=actor_name,
                    requested_at=now,
                    assigned_role=assigned_role,
                    sla_started_at=sla_started_at,
                    sla_due_at=sla_due_at,
                )
                self.session.add(correction)
                event_type = "correction_requested"
            else:
                correction.status = "open"
                correction.reason = comment
                correction.failed_check_keys_json = failed_check_keys
                correction.requested_by = actor_subject
                correction.requested_by_name = actor_name
                correction.requested_at = now
                correction.assigned_role = assigned_role
                clear_assignment(correction)
                correction.sla_started_at = sla_started_at
                correction.sla_due_at = sla_due_at
                correction.resolved_by = None
                correction.resolved_by_name = None
                correction.resolved_at = None
                event_type = "correction_reopened"
            self.session.flush()
            self._pause_approval_case_for_correction(correction, actor_name, event_type)
            self.audit.append(
                "document_correction",
                correction.id,
                event_type,
                actor_name,
                {
                    "document_id": document.id,
                    "reason": comment,
                    "failed_check_keys": failed_check_keys,
                    "attempt_count": correction.attempt_count,
                    "assigned_role": correction.assigned_role,
                    "sla_due_at": correction.sla_due_at.isoformat(),
                },
            )
            self._notify_correction_lifecycle(
                correction,
                event=event_type,
                roles={"client", "relationship_manager"},
                level="task_created" if event_type == "correction_requested" else "reopened",
                title="新增补件任务" if event_type == "correction_requested" else "补件任务已重新打开",
                message=f"{correction.document_type} 需补充，请在 {correction.sla_due_at.isoformat()} 前提交替换资料。原因：{comment}",
                severity="warning",
            )
        elif correction and correction.status == "resubmitted":
            if decision == "verify":
                correction.status = "closed"
                clear_assignment(correction)
                correction.resolved_by = actor_subject
                correction.resolved_by_name = actor_name
                correction.resolved_at = now
                self.session.flush()
                resumed_case = self._resume_approval_case_after_corrections(correction, actor_name)
                event_type = "correction_closed"
            else:
                assigned_role, sla_started_at, sla_due_at = correction_sla_window("open", now)
                correction.status = "open"
                correction.reason = comment
                correction.failed_check_keys_json = failed_check_keys
                correction.requested_by = actor_subject
                correction.requested_by_name = actor_name
                correction.requested_at = now
                correction.assigned_role = assigned_role
                clear_assignment(correction)
                correction.sla_started_at = sla_started_at
                correction.sla_due_at = sla_due_at
                correction.resolved_by = None
                correction.resolved_by_name = None
                correction.resolved_at = None
                self.session.flush()
                self._pause_approval_case_for_correction(correction, actor_name, "correction_resubmission_rejected")
                event_type = "correction_resubmission_rejected"
                resumed_case = None
            self.audit.append(
                "document_correction",
                correction.id,
                event_type,
                actor_name,
                {
                    "document_id": document.id,
                    "decision": decision,
                    "comment": comment,
                    "failed_check_keys": failed_check_keys,
                    "attempt_count": correction.attempt_count,
                    "status": correction.status,
                    "assigned_role": correction.assigned_role,
                    "sla_due_at": correction.sla_due_at.isoformat(),
                },
            )
            if decision == "verify":
                self._notify_correction_lifecycle(
                    correction,
                    event=event_type,
                    roles={"client", "relationship_manager"},
                    level="completed",
                    title="补件资料已核验通过",
                    message=f"{correction.document_type} 的替换版本已核验通过，补件任务已完成。",
                    action_page="approvals",
                )
                if resumed_case:
                    self._notify_correction_lifecycle(
                        correction,
                        event="approval_resumed",
                        roles=set(APPROVAL_STAGE_ROLES.get(resumed_case.current_stage, set())),
                        level="resumed",
                        title="审批流程已恢复",
                        message=f"全部补件任务已完成，{stage_label(resumed_case.current_stage)}环节已恢复并重新计算 SLA。",
                        action_page="approvals",
                    )
            else:
                self._notify_correction_lifecycle(
                    correction,
                    event=event_type,
                    roles={"client", "relationship_manager"},
                    level="reopened",
                    title="补件新版本未通过",
                    message=f"{correction.document_type} 的替换版本未通过复核，请重新提交。原因：{comment}",
                    severity="warning",
                )

    def _pause_approval_case_for_correction(
        self,
        correction: DocumentCorrectionRecord,
        actor_name: str,
        source_event: str,
    ) -> None:
        if not correction.case_id:
            return
        case = self.session.get(ApprovalCaseRecord, correction.case_id)
        if not case or case.status in {"已完成", "已拒绝", "已撤回"}:
            return
        case.status = "待补件"
        case.stage_due_at = None
        clear_assignment(case)
        data = deepcopy(case.case_data or {})
        workflow = data.setdefault("_workflow", {})
        correction_ids = self.session.scalars(
            select(DocumentCorrectionRecord.id).where(
                DocumentCorrectionRecord.case_id == correction.case_id,
                DocumentCorrectionRecord.status.in_(["open", "resubmitted"]),
            ).order_by(DocumentCorrectionRecord.created_at, DocumentCorrectionRecord.id)
        ).all()
        workflow["active_document_correction_ids"] = correction_ids
        workflow["document_correction_paused_at"] = datetime.now(timezone.utc).isoformat()
        case.case_data = data
        timeline = list(case.timeline or [])
        timeline.append(
            {
                "类型": "资料退补",
                "环节": stage_label(case.current_stage),
                "处理人": actor_name,
                "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "处理结果": f"{correction.document_type} 需补充，审批 SLA 已暂停",
            }
        )
        case.timeline = timeline
        self.session.flush()
        self.audit.append(
            "approval_case",
            case.case_id,
            "approval_paused_for_document_correction",
            actor_name,
            {
                "correction_id": correction.id,
                "document_type": correction.document_type,
                "source_event": source_event,
                "active_document_correction_ids": correction_ids,
                "stage": case.current_stage,
            },
        )

    def _resume_approval_case_after_corrections(
        self,
        correction: DocumentCorrectionRecord,
        actor_name: str,
    ) -> ApprovalCaseRecord | None:
        if not correction.case_id:
            return None
        case = self.session.get(ApprovalCaseRecord, correction.case_id)
        if not case or case.status != "待补件":
            return None
        remaining = self.session.scalars(
            select(DocumentCorrectionRecord.id).where(
                DocumentCorrectionRecord.case_id == correction.case_id,
                DocumentCorrectionRecord.status.in_(["open", "resubmitted"]),
            ).order_by(DocumentCorrectionRecord.created_at, DocumentCorrectionRecord.id)
        ).all()
        data = deepcopy(case.case_data or {})
        workflow = data.setdefault("_workflow", {})
        workflow["active_document_correction_ids"] = list(remaining)
        case.case_data = data
        if remaining:
            self.session.flush()
            return None
        now = datetime.now(timezone.utc)
        case.status = "处理中"
        case.stage_started_at = now
        case.stage_due_at = now + timedelta(hours=STAGE_SLA_HOURS.get(case.current_stage, 24))
        workflow["document_correction_resumed_at"] = now.isoformat()
        case.case_data = data
        timeline = list(case.timeline or [])
        timeline.append(
            {
                "类型": "补件恢复",
                "环节": stage_label(case.current_stage),
                "处理人": actor_name,
                "处理时间": now.strftime("%Y-%m-%d %H:%M:%S"),
                "处理结果": "全部补件任务已核验通过，审批流程恢复并重新计算环节 SLA",
            }
        )
        case.timeline = timeline
        self.session.flush()
        self.audit.append(
            "approval_case",
            case.case_id,
            "approval_resumed_after_document_corrections",
            actor_name,
            {
                "correction_id": correction.id,
                "stage": case.current_stage,
                "stage_started_at": case.stage_started_at.isoformat(),
                "stage_due_at": case.stage_due_at.isoformat(),
            },
        )
        return case


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def create_if_absent(self, payload: dict) -> tuple[dict, bool]:
        existing = self.session.scalars(select(NotificationRecord).where(NotificationRecord.dedup_key == payload["dedup_key"])).first()
        if existing:
            return _notification_to_dict(existing), False
        record = NotificationRecord(id=str(uuid4()), **payload)
        try:
            with self.session.begin_nested():
                self.session.add(record)
                self.session.flush()
        except IntegrityError:
            existing = self.session.scalars(select(NotificationRecord).where(NotificationRecord.dedup_key == payload["dedup_key"])).first()
            if not existing:
                raise
            return _notification_to_dict(existing), False
        return _notification_to_dict(record), True

    def list(self, recipient_roles: tuple[str, ...] | None = None, recipient_subject: str | None = None, status: str | None = None, counterparty_id: str | None = None, limit: int = 100) -> list[dict]:
        statement = select(NotificationRecord).order_by(NotificationRecord.created_at.desc(), NotificationRecord.id.desc()).limit(limit)
        if recipient_roles is not None:
            broadcast_scope = and_(
                NotificationRecord.recipient_subject.is_(None),
                NotificationRecord.recipient_role.in_(recipient_roles),
            )
            statement = statement.where(
                or_(
                    NotificationRecord.recipient_subject == recipient_subject,
                    broadcast_scope,
                )
                if recipient_subject
                else broadcast_scope
            )
        if status:
            statement = statement.where(NotificationRecord.status == status)
        if counterparty_id:
            statement = statement.where(NotificationRecord.counterparty_id == counterparty_id)
        return [_notification_to_dict(row) for row in self.session.scalars(statement).all()]

    def get(self, notification_id: str) -> dict | None:
        record = self.session.get(NotificationRecord, notification_id)
        return _notification_to_dict(record) if record else None

    def mark_read(self, notification_id: str, actor: str) -> dict | None:
        record = self.session.get(NotificationRecord, notification_id)
        if not record:
            return None
        if record.status == "unread":
            record.status = "read"
            record.read_at = datetime.now(timezone.utc)
            self.audit.append("notification", record.id, "notification_read", actor, {"case_id": record.case_id, "recipient_role": record.recipient_role})
            self.session.commit()
            self.session.refresh(record)
        return _notification_to_dict(record)

    def commit(self) -> None:
        self.session.commit()


class CreditFacilityRepository:
    REVIEW_INTERVAL_DAYS = {"实时监控": 1, "月度": 30, "季度": 90, "半年": 180, "年度": 365}

    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def commit(self) -> None:
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("授信台账落地发生并发冲突，请刷新后重试") from exc

    def rollback(self) -> None:
        self.session.rollback()

    def create_from_completed_case(self, case: dict, actor: str) -> dict | None:
        strategy = case.get("data", {}).get("final_strategy", {})
        if strategy.get("decision") == "拒绝" or strategy.get("access_strategy") in {"禁入", "不建议准入"}:
            return None
        existing = self.session.scalars(select(CreditFacilityRecord).where(CreditFacilityRecord.case_id == case["case_id"])).first()
        if existing:
            return _facility_to_dict(existing)
        proposal = case.get("data", {}).get("credit_proposal", {})
        scoring = case.get("data", {}).get("scoring", {})
        suggested_limit = _money(proposal.get("suggested_limit", 0))
        approved_limit = _money(strategy.get("approved_limit", suggested_limit))
        payment_term_days = int(strategy.get("approved_payment_term_days", proposal.get("suggested_payment_term_days", 0)))
        if approved_limit <= 0 or payment_term_days < 0:
            raise ValueError("审批结果缺少有效的授信额度或账期")
        if approved_limit > suggested_limit:
            raise ValueError("最终批准额度不能高于模型建议额度，请退回额度建议环节重新评估")
        validity_days = int(strategy.get("facility_validity_days", 365))
        if validity_days < 30 or validity_days > 1825:
            raise ValueError("授信有效期必须介于 30 至 1825 天")
        now = datetime.now(timezone.utc)
        monitoring_frequency = str(strategy.get("monitoring_frequency", "月度"))
        record = CreditFacilityRecord(
            id=str(uuid4()),
            case_id=case["case_id"],
            counterparty_id=case["counterparty_id"],
            counterparty_name=case["counterparty_name"],
            approved_limit=approved_limit,
            used_limit=Decimal("0.00"),
            payment_term_days=payment_term_days,
            rating=str(scoring.get("rating", "-")),
            access_strategy=str(strategy.get("access_strategy", proposal.get("access_strategy", "人工复核"))),
            monitoring_frequency=monitoring_frequency,
            status="active",
            effective_at=now,
            expires_at=now + timedelta(days=validity_days),
            next_review_at=now + timedelta(days=self.REVIEW_INTERVAL_DAYS.get(monitoring_frequency, 30)),
        )
        self.session.add(record)
        self.session.flush()
        self.audit.append("credit_facility", record.id, "credit_facility_activated", actor, {"case_id": record.case_id, "approved_limit": float(approved_limit), "payment_term_days": payment_term_days, "expires_at": record.expires_at.isoformat(), "rating": record.rating})
        return _facility_to_dict(record)

    def list(self, counterparty_id: str | None = None) -> list[dict]:
        statement = select(CreditFacilityRecord).order_by(CreditFacilityRecord.created_at.desc(), CreditFacilityRecord.id.desc())
        if counterparty_id:
            statement = statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
        return [_facility_to_dict(record) for record in self.session.scalars(statement).all()]

    def get(self, facility_id: str) -> dict | None:
        record = self.session.get(CreditFacilityRecord, facility_id)
        return _facility_to_dict(record) if record else None

    def list_transactions(self, facility_id: str) -> list[dict]:
        statement = select(CreditUsageRecord).where(CreditUsageRecord.facility_id == facility_id).order_by(CreditUsageRecord.occurred_at.desc(), CreditUsageRecord.id.desc())
        return [_usage_to_dict(record) for record in self.session.scalars(statement).all()]

    def list_risk_events(self, facility_id: str | None = None, counterparty_id: str | None = None) -> list[dict]:
        statement = select(RiskEventRecord, CreditFacilityRecord).join(CreditFacilityRecord, CreditFacilityRecord.id == RiskEventRecord.facility_id).order_by(RiskEventRecord.occurred_at.desc(), RiskEventRecord.id.desc())
        if facility_id:
            statement = statement.where(RiskEventRecord.facility_id == facility_id)
        if counterparty_id:
            statement = statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
        return [{**_risk_event_to_dict(event), "counterparty_id": facility.counterparty_id, "counterparty_name": facility.counterparty_name} for event, facility in self.session.execute(statement).all()]

    def create_risk_event(self, facility_id: str, payload: dict, actor: str) -> dict:
        occurred_at = _as_utc(payload["occurred_at"])
        if occurred_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("风险事件发生时间不能晚于当前时间 5 分钟以上")
        if len(json.dumps(payload.get("payload", {}), ensure_ascii=False, default=str).encode("utf-8")) > 32768:
            raise ValueError("风险事件原始载荷不能超过 32KB")
        existing = self.session.scalars(select(RiskEventRecord).where(RiskEventRecord.source == payload["source"], RiskEventRecord.external_event_id == payload["external_event_id"])).first()
        if existing:
            if not _risk_event_matches(existing, facility_id, payload):
                raise ValueError("外部事件编号已被不同风险事件使用")
            alert = self.session.get(FacilityAlertRecord, existing.linked_alert_id) if existing.linked_alert_id else None
            return {"risk_event": _risk_event_to_dict(existing), "alert": _alert_to_dict(alert) if alert else None, "idempotent": True}
        facility = self.session.get(CreditFacilityRecord, facility_id)
        if not facility:
            raise LookupError("授信台账不存在")
        event = RiskEventRecord(
            id=str(uuid4()),
            facility_id=facility_id,
            external_event_id=payload["external_event_id"],
            event_type=payload["event_type"],
            source=payload["source"],
            severity=payload["severity"],
            occurred_at=occurred_at,
            title=payload["title"],
            description=payload["description"],
            event_payload=deepcopy(payload.get("payload", {})),
            status="active",
            created_by=actor,
        )
        self.session.add(event)
        self.session.flush()
        dedup_key = f"risk_event:{event.source}:{event.external_event_id}"
        self._ensure_alert(facility, f"risk_event:{event.event_type}", event.severity, event.title, event.description, dedup_key)
        self.session.flush()
        alert = self.session.scalars(select(FacilityAlertRecord).where(FacilityAlertRecord.dedup_key == dedup_key)).first()
        event.linked_alert_id = alert.id if alert else None
        self.audit.append("credit_facility", facility.id, "risk_event_ingested", actor, {"risk_event_id": event.id, "external_event_id": event.external_event_id, "event_type": event.event_type, "source": event.source, "severity": event.severity, "alert_id": event.linked_alert_id})
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raced = self.session.scalars(select(RiskEventRecord).where(RiskEventRecord.source == payload["source"], RiskEventRecord.external_event_id == payload["external_event_id"])).first()
            if raced and _risk_event_matches(raced, facility_id, payload):
                raced_alert = self.session.get(FacilityAlertRecord, raced.linked_alert_id) if raced.linked_alert_id else None
                return {"risk_event": _risk_event_to_dict(raced), "alert": _alert_to_dict(raced_alert) if raced_alert else None, "idempotent": True}
            raise ConcurrentUpdateError("风险事件接入发生并发冲突，请刷新后重试") from exc
        self.session.refresh(event)
        if alert:
            self.session.refresh(alert)
        return {"risk_event": _risk_event_to_dict(event), "alert": _alert_to_dict(alert) if alert else None, "idempotent": False}

    def transact(self, facility_id: str, transaction_ref: str, transaction_type: str, amount: float, expected_row_version: int, actor: str, reason: str) -> dict:
        existing = self.session.scalars(select(CreditUsageRecord).where(CreditUsageRecord.transaction_ref == transaction_ref)).first()
        rounded_amount = _money(amount)
        if existing:
            if existing.facility_id != facility_id or existing.transaction_type != transaction_type or _money(existing.amount) != rounded_amount:
                raise ValueError("交易参考号已被其他额度交易使用")
            return {"facility": self.get(facility_id), "transaction": _usage_to_dict(existing), "idempotent": True}
        facility = self.session.get(CreditFacilityRecord, facility_id)
        if not facility:
            raise LookupError("授信台账不存在")
        if facility.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"授信台账版本已变化，当前版本为 {facility.row_version}")
        now = datetime.now(timezone.utc)
        if facility.status != "active" or _as_utc(facility.expires_at) <= now:
            raise ValueError("当前授信已失效或被冻结，不能发生额度交易")
        if rounded_amount <= 0:
            raise ValueError("交易金额必须大于 0")
        if transaction_type == "drawdown":
            if rounded_amount > _money(facility.approved_limit - facility.used_limit):
                raise ValueError("额度占用超过当前可用额度")
            facility.used_limit = _money(facility.used_limit + rounded_amount)
        elif transaction_type == "repayment":
            if rounded_amount > _money(facility.used_limit):
                raise ValueError("归还金额不能超过已用额度")
            facility.used_limit = _money(facility.used_limit - rounded_amount)
        else:
            raise ValueError("不支持的额度交易类型")
        transaction = CreditUsageRecord(id=str(uuid4()), facility_id=facility.id, transaction_ref=transaction_ref, transaction_type=transaction_type, amount=rounded_amount, balance_after=facility.used_limit, occurred_at=now, actor=actor, reason=reason)
        self.session.add(transaction)
        self.audit.append("credit_facility", facility.id, f"credit_{transaction_type}", actor, {"transaction_id": transaction.id, "transaction_ref": transaction_ref, "amount": float(rounded_amount), "balance_after": float(facility.used_limit), "reason": reason})
        utilization = facility.used_limit / facility.approved_limit if facility.approved_limit else 0
        if utilization >= Decimal("0.90"):
            self._ensure_alert(facility, "high_utilization", "critical", "额度使用率过高", f"额度使用率已达到 {utilization:.1%}。", f"utilization:{facility.id}:90")
        else:
            self._resolve_alerts(facility.id, "high_utilization", actor)
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raced = self.session.scalars(select(CreditUsageRecord).where(CreditUsageRecord.transaction_ref == transaction_ref)).first()
            if raced and raced.facility_id == facility_id and raced.transaction_type == transaction_type and _money(raced.amount) == rounded_amount:
                return {"facility": self.get(facility_id), "transaction": _usage_to_dict(raced), "idempotent": True}
            raise ConcurrentUpdateError("额度交易发生并发冲突，请刷新后重试") from exc
        self.session.refresh(facility)
        self.session.refresh(transaction)
        return {"facility": _facility_to_dict(facility), "transaction": _usage_to_dict(transaction), "idempotent": False}

    def review(self, facility_id: str, expected_row_version: int, rating: str, next_review_days: int, actor: str, conclusion: str) -> dict:
        facility = self.session.get(CreditFacilityRecord, facility_id)
        if not facility:
            raise LookupError("授信台账不存在")
        if facility.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"授信台账版本已变化，当前版本为 {facility.row_version}")
        if facility.status != "active":
            raise ValueError("只有生效中的授信可以执行贷后复评")
        now = datetime.now(timezone.utc)
        facility.rating = rating
        facility.last_review_at = now
        facility.next_review_at = now + timedelta(days=next_review_days)
        self._resolve_alerts(facility.id, "review_due", actor)
        self.audit.append("credit_facility", facility.id, "post_credit_review_completed", actor, {"rating": rating, "next_review_at": facility.next_review_at.isoformat(), "conclusion": conclusion})
        try:
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("贷后复评发生并发冲突，请刷新后重试") from exc
        self.session.refresh(facility)
        return _facility_to_dict(facility)

    def control(self, facility_id: str, expected_row_version: int, action: str, target_limit: float | None, actor: str, reason: str) -> dict:
        facility = self.session.get(CreditFacilityRecord, facility_id)
        if not facility:
            raise LookupError("授信台账不存在")
        if facility.row_version != expected_row_version:
            raise ConcurrentUpdateError(f"授信台账版本已变化，当前版本为 {facility.row_version}")
        self._apply_control(facility, action, target_limit, actor, reason)
        try:
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("授信控制发生并发冲突，请刷新后重试") from exc
        self.session.refresh(facility)
        return _facility_to_dict(facility)

    def dispose_alert(self, alert_id: str, expected_alert_version: int, expected_facility_version: int, action: str, target_limit: float | None, actor: str, conclusion: str) -> dict:
        alert = self.session.get(FacilityAlertRecord, alert_id)
        if not alert:
            raise LookupError("贷后预警不存在")
        if alert.row_version != expected_alert_version:
            raise ConcurrentUpdateError(f"预警版本已变化，当前版本为 {alert.row_version}")
        if alert.status == "resolved":
            raise ValueError("贷后预警已经闭环")
        facility = self.session.get(CreditFacilityRecord, alert.facility_id)
        if not facility:
            raise LookupError("授信台账不存在")
        if facility.row_version != expected_facility_version:
            raise ConcurrentUpdateError(f"授信台账版本已变化，当前版本为 {facility.row_version}")
        if action != "monitor":
            self._apply_control(facility, action, target_limit, actor, conclusion)
        now = datetime.now(timezone.utc)
        alert.status = "resolved"
        alert.disposition_action = action
        alert.disposition_note = conclusion
        alert.resolved_at = now
        alert.resolved_by = actor
        linked_events = self.session.scalars(select(RiskEventRecord).where(RiskEventRecord.linked_alert_id == alert.id, RiskEventRecord.status == "active")).all()
        for event in linked_events:
            event.status = "resolved"
            event.resolved_at = now
        self.audit.append("credit_facility", facility.id, "facility_alert_disposed", actor, {"alert_id": alert.id, "action": action, "target_limit": target_limit, "conclusion": conclusion, "risk_event_ids": [event.id for event in linked_events]})
        try:
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise ConcurrentUpdateError("预警处置发生并发冲突，请刷新后重试") from exc
        self.session.refresh(alert)
        self.session.refresh(facility)
        return {"alert": _alert_to_dict(alert), "facility": _facility_to_dict(facility)}

    def scan(self, actor: str, now: datetime | None = None) -> dict:
        scan_time = _as_utc(now or datetime.now(timezone.utc))
        facilities = self.session.scalars(select(CreditFacilityRecord).where(CreditFacilityRecord.status == "active")).all()
        opened = 0
        expired = 0
        for facility in facilities:
            expires_at = _as_utc(facility.expires_at)
            if expires_at <= scan_time:
                facility.status = "expired"
                expired += 1
                opened += int(self._ensure_alert(facility, "expired", "critical", "授信已经到期", f"授信已于 {expires_at.date().isoformat()} 到期，禁止继续用信。", f"expired:{facility.id}:{expires_at.date().isoformat()}"))
                continue
            elif expires_at <= scan_time + timedelta(days=30):
                opened += int(self._ensure_alert(facility, "expiring", "warning", "授信即将到期", f"授信将在 {expires_at.date().isoformat()} 到期，请及时续评。", f"expiring:{facility.id}:{expires_at.date().isoformat()}"))
            if _as_utc(facility.next_review_at) <= scan_time:
                opened += int(self._ensure_alert(facility, "review_due", "warning", "贷后复评已到期", f"计划复评时间为 {_as_utc(facility.next_review_at).date().isoformat()}。", f"review:{facility.id}:{_as_utc(facility.next_review_at).isoformat()}"))
            utilization = facility.used_limit / facility.approved_limit if facility.approved_limit else 0
            if utilization >= Decimal("0.90"):
                opened += int(self._ensure_alert(facility, "high_utilization", "critical", "额度使用率过高", f"额度使用率已达到 {utilization:.1%}。", f"utilization:{facility.id}:90"))
        self.audit.append("post_credit_scan", str(uuid4()), "post_credit_scan_completed", actor, {"run_at": scan_time.isoformat(), "active_facilities_scanned": len(facilities), "facilities_expired": expired, "alerts_opened": opened})
        self.session.commit()
        return {"run_at": scan_time.isoformat(), "active_facilities_scanned": len(facilities), "facilities_expired": expired, "alerts_opened": opened}

    def list_alerts(self, counterparty_id: str | None = None) -> list[dict]:
        statement = select(FacilityAlertRecord, CreditFacilityRecord).join(CreditFacilityRecord, CreditFacilityRecord.id == FacilityAlertRecord.facility_id).order_by(FacilityAlertRecord.created_at.desc(), FacilityAlertRecord.id.desc())
        if counterparty_id:
            statement = statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
        return [{**_alert_to_dict(alert), "counterparty_id": facility.counterparty_id, "counterparty_name": facility.counterparty_name} for alert, facility in self.session.execute(statement).all()]

    def acknowledge_alert(self, alert_id: str, actor: str) -> dict | None:
        alert = self.session.get(FacilityAlertRecord, alert_id)
        if not alert:
            return None
        if alert.status == "open":
            alert.status = "acknowledged"
            alert.acknowledged_at = datetime.now(timezone.utc)
            alert.acknowledged_by = actor
            self.audit.append("credit_facility", alert.facility_id, "facility_alert_acknowledged", actor, {"alert_id": alert.id, "alert_type": alert.alert_type})
            try:
                self.session.commit()
                self.session.refresh(alert)
            except StaleDataError:
                self.session.rollback()
                alert = self.session.get(FacilityAlertRecord, alert_id)
        return _alert_to_dict(alert)

    def summary(self, counterparty_id: str | None = None) -> dict:
        facility_statement = select(CreditFacilityRecord)
        if counterparty_id:
            facility_statement = facility_statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
        facilities = self.session.scalars(facility_statement).all()
        facility_ids = [item.id for item in facilities]
        alert_statement = select(FacilityAlertRecord).where(FacilityAlertRecord.status.in_(["open", "acknowledged"]))
        if counterparty_id:
            alert_statement = alert_statement.where(FacilityAlertRecord.facility_id.in_(facility_ids))
        unresolved = self.session.scalars(alert_statement).all()
        return {
            "total_facilities": len(facilities),
            "active_facilities": sum(item.status == "active" for item in facilities),
            "approved_limit": float(_money(sum((item.approved_limit for item in facilities if item.status == "active"), Decimal("0.00")))),
            "used_limit": float(_money(sum((item.used_limit for item in facilities if item.status == "active"), Decimal("0.00")))),
            "available_limit": float(_money(sum((item.approved_limit - item.used_limit for item in facilities if item.status == "active"), Decimal("0.00")))),
            "high_utilization_facilities": sum(item.status == "active" and item.approved_limit > 0 and item.used_limit / item.approved_limit >= Decimal("0.90") for item in facilities),
            "unresolved_alerts": len(unresolved),
            "critical_alerts": sum(item.severity == "critical" for item in unresolved),
        }

    def _ensure_alert(self, facility: CreditFacilityRecord, alert_type: str, severity: str, title: str, message: str, dedup_key: str) -> bool:
        existing = self.session.scalars(select(FacilityAlertRecord).where(FacilityAlertRecord.dedup_key == dedup_key)).first()
        if existing:
            if existing.status == "resolved":
                existing.status = "open"
                existing.acknowledged_at = None
                existing.acknowledged_by = None
                existing.disposition_action = None
                existing.disposition_note = None
                existing.resolved_at = None
                existing.resolved_by = None
                existing.message = message
                return True
            return False
        self.session.add(FacilityAlertRecord(id=str(uuid4()), facility_id=facility.id, alert_type=alert_type, severity=severity, title=title, message=message, dedup_key=dedup_key, status="open"))
        return True

    def _resolve_alerts(self, facility_id: str, alert_type: str, actor: str) -> None:
        alerts = self.session.scalars(select(FacilityAlertRecord).where(FacilityAlertRecord.facility_id == facility_id, FacilityAlertRecord.alert_type == alert_type, FacilityAlertRecord.status.in_(["open", "acknowledged"]))).all()
        now = datetime.now(timezone.utc)
        for alert in alerts:
            alert.status = "resolved"
            alert.disposition_action = "auto_resolved"
            alert.disposition_note = "触发条件已自动消除"
            alert.resolved_at = now
            alert.resolved_by = actor

    def _apply_control(self, facility: CreditFacilityRecord, action: str, target_limit: float | None, actor: str, reason: str) -> None:
        previous = {"status": facility.status, "approved_limit": float(_money(facility.approved_limit))}
        now = datetime.now(timezone.utc)
        if action == "freeze":
            if facility.status != "active":
                raise ValueError("只有生效中的授信可以冻结")
            facility.status = "frozen"
        elif action == "unfreeze":
            if facility.status != "frozen":
                raise ValueError("只有冻结中的授信可以解冻")
            if _as_utc(facility.expires_at) <= now:
                raise ValueError("授信已经到期，不能解冻")
            facility.status = "active"
        elif action == "reduce_limit":
            if facility.status not in {"active", "frozen"}:
                raise ValueError("当前授信状态不允许压降额度")
            if target_limit is None:
                raise ValueError("压降额度必须填写目标额度")
            target = _money(target_limit)
            if target >= facility.approved_limit:
                raise ValueError("目标额度必须低于当前批准额度")
            if target < facility.used_limit:
                raise ValueError("目标额度不能低于当前已用额度，请先完成额度归还")
            facility.approved_limit = target
        elif action == "close":
            if facility.status not in {"active", "frozen"}:
                raise ValueError("当前授信状态不允许关闭")
            if facility.used_limit > 0:
                raise ValueError("仍有已用额度，不能关闭授信")
            facility.status = "closed"
        else:
            raise ValueError("不支持的授信控制动作")
        self.audit.append("credit_facility", facility.id, f"facility_{action}", actor, {"reason": reason, "previous": previous, "current": {"status": facility.status, "approved_limit": float(_money(facility.approved_limit))}})


def clear_persistent_data(session: Session) -> None:
    session.execute(delete(AuditEventRecord))
    session.execute(delete(ModelGovernanceNotificationRecord))
    session.execute(delete(ModelMonitoringScheduleRecord))
    session.execute(delete(ModelMonitoringRunRecord))
    session.execute(delete(ModelMonitoringIssueRecord))
    session.execute(delete(ModelOutcomeImportRecord))
    session.execute(delete(ModelOutcomeRecord))
    session.execute(delete(NotificationRecord))
    session.execute(delete(RiskEventRecord))
    session.execute(delete(FacilityAlertRecord))
    session.execute(delete(CreditUsageRecord))
    session.execute(delete(CreditFacilityRecord))
    session.execute(delete(EnterpriseIndicatorObservationRecord))
    session.execute(delete(DocumentCorrectionRecord))
    session.execute(delete(DocumentRecord))
    session.execute(delete(CreditReportRecord))
    session.execute(delete(DecisionVarianceRecord))
    session.execute(delete(EnterpriseDataResolutionRecord))
    session.execute(delete(EnterpriseDataFieldRecord))
    session.execute(delete(EnterpriseDataImportRecord))
    session.execute(delete(PortfolioRatingBatchRecord))
    session.execute(delete(RatingRunRecord))
    session.execute(delete(ModelSnapshotRecord))
    session.execute(delete(ModelReleaseRecord))
    session.execute(delete(ModelChangeRecord))
    session.execute(delete(AuthorityPolicyActivationRunRecord))
    session.execute(delete(AuthorityPolicyEvidenceAnchorRecord))
    session.execute(delete(CreditAuthorityPolicyRecord))
    session.execute(delete(ApprovalCaseRecord))
    session.commit()


def _case_to_dict(record: ApprovalCaseRecord) -> dict:
    sla_status, remaining_seconds = _approval_sla(record)
    return {
        "case_id": record.case_id,
        "counterparty_id": record.counterparty_id,
        "counterparty_name": record.counterparty_name,
        "current_stage": record.current_stage,
        "status": record.status,
        "completed_stages": deepcopy(record.completed_stages or []),
        "data": deepcopy(record.case_data or {}),
        "timeline": deepcopy(record.timeline or []),
        "row_version": record.row_version,
        "stage_started_at": record.stage_started_at.isoformat() if record.stage_started_at else None,
        "stage_due_at": record.stage_due_at.isoformat() if record.stage_due_at else None,
        "assigned_to": record.assigned_to,
        "assigned_to_name": record.assigned_to_name,
        "assigned_at": record.assigned_at.isoformat() if record.assigned_at else None,
        "assignment_expires_at": record.assignment_expires_at.isoformat() if record.assignment_expires_at else None,
        "sla_status": sla_status,
        "remaining_seconds": remaining_seconds,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _approval_sla(record: ApprovalCaseRecord) -> tuple[str, int | None]:
    if record.status in {"已完成", "已拒绝", "已撤回"}:
        return "已停止", 0
    if record.status == "待补件":
        return "已暂停", 0
    if not record.stage_due_at:
        return "未设置", None
    due_at = record.stage_due_at if record.stage_due_at.tzinfo else record.stage_due_at.replace(tzinfo=timezone.utc)
    remaining = int((due_at - datetime.now(timezone.utc)).total_seconds())
    if remaining < 0:
        return "已超时", remaining
    warning_seconds = STAGE_SLA_HOURS.get(record.current_stage, 24) * 3600 * 0.25
    return ("即将超时" if remaining <= warning_seconds else "正常"), remaining


def _audit_to_dict(record: AuditEventRecord) -> dict:
    return {"id": record.id, "aggregate_type": record.aggregate_type, "aggregate_id": record.aggregate_id, "event_type": record.event_type, "actor": record.actor, "payload": deepcopy(record.payload), "previous_hash": record.previous_hash, "event_hash": record.event_hash, "created_at": record.created_at.isoformat() if record.created_at else None}


def _rating_run_to_dict(record: RatingRunRecord) -> dict:
    return {"id": record.id, "counterparty_id": record.counterparty_id, "case_id": record.case_id, "template_key": record.template_key, "model_snapshot_id": record.model_snapshot_id, "input": deepcopy(record.input_json), "input_hash": record.input_hash, "result": deepcopy(record.result_json), "result_hash": record.result_hash, "created_at": record.created_at.isoformat() if record.created_at else None}


def _portfolio_rating_batch_to_dict(record: PortfolioRatingBatchRecord) -> dict:
    return {
        "id": record.id,
        "batch_key": record.batch_key,
        "request_hash": record.request_hash,
        "template_key": record.template_key,
        "model_version": record.model_version,
        "model_snapshot_id": record.model_snapshot_id,
        "scope_type": record.scope_type,
        "status": record.status,
        "candidate_count": record.candidate_count,
        "success_count": record.success_count,
        "skipped_count": record.skipped_count,
        "summary": deepcopy(record.summary_json),
        "results": deepcopy(record.results_json),
        "skipped": deepcopy(record.skipped_json),
        "result_hash": record.result_hash,
        "created_by": record.created_by,
        "created_by_name": record.created_by_name,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _credit_report_to_dict(record: CreditReportRecord) -> dict:
    return {
        "id": record.id,
        "report_no": record.report_no,
        "case_id": record.case_id,
        "counterparty_id": record.counterparty_id,
        "report_version": record.report_version,
        "report_type": record.report_type,
        "status": record.status,
        "snapshot": deepcopy(record.snapshot_json),
        "snapshot_hash": record.snapshot_hash,
        "object_key": record.object_key,
        "pdf_sha256": record.pdf_sha256,
        "size_bytes": record.size_bytes,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _decision_variance_to_dict(record: DecisionVarianceRecord) -> dict:
    variance = deepcopy(record.variance_json or {})
    return {
        "id": record.id,
        "case_id": record.case_id,
        "counterparty_id": record.counterparty_id,
        "counterparty_name": record.counterparty_name,
        "rating_run_id": record.rating_run_id,
        "model_snapshot_id": record.model_snapshot_id,
        "direction": record.direction,
        "materiality": record.materiality,
        "recommendation": deepcopy(record.recommendation_json or {}),
        "final_decision": deepcopy(record.decision_json or {}),
        "changed_fields": variance.get("changed_fields", []),
        "deltas": variance.get("deltas", {}),
        "requires_reason": variance.get("requires_reason", False),
        "requires_compensating_controls": variance.get("requires_compensating_controls", False),
        "reason_category": record.reason_category,
        "reason_detail": record.reason_detail,
        "compensating_controls": deepcopy(record.compensating_controls or []),
        "decided_by": record.decided_by,
        "decided_at": record.decided_at.isoformat() if record.decided_at else None,
    }


def _enterprise_import_to_dict(record: EnterpriseDataImportRecord) -> dict:
    return {
        "id": record.id,
        "import_key": record.import_key,
        "counterparty_id": record.counterparty_id,
        "source_type": record.source_type,
        "source_name": record.source_name,
        "source_priority": record.source_priority,
        "schema_version": record.schema_version,
        "as_of_date": record.as_of_date.isoformat() if record.as_of_date else None,
        "evidence_reference": record.evidence_reference,
        "payload_hash": record.payload_hash,
        "status": record.status,
        "field_count": record.field_count,
        "conflict_count": record.conflict_count,
        "stale_count": record.stale_count,
        "invalid_count": record.invalid_count,
        "quality_score": float(record.quality_score),
        "quality": deepcopy(record.quality_json or {}),
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _enterprise_field_to_dict(record: EnterpriseDataFieldRecord) -> dict:
    dynamic_freshness = freshness_status(record.field_path, record.observed_at)
    return {
        "id": record.id,
        "import_id": record.import_id,
        "counterparty_id": record.counterparty_id,
        "field_path": record.field_path,
        "value": deepcopy(record.value_json),
        "value_hash": record.value_hash,
        "value_type": record.value_type,
        "source_type": record.source_type,
        "source_name": record.source_name,
        "source_priority": record.source_priority,
        "evidence_reference": record.evidence_reference,
        "evidence_locator": record.evidence_locator,
        "observed_at": record.observed_at.isoformat() if record.observed_at else None,
        "freshness_days": record.freshness_days,
        "freshness_status": dynamic_freshness,
        "validation_status": record.validation_status,
        "conflict_status": record.conflict_status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _enterprise_resolution_to_dict(record: EnterpriseDataResolutionRecord) -> dict:
    return {
        "id": record.id,
        "counterparty_id": record.counterparty_id,
        "field_path": record.field_path,
        "selected_field_id": record.selected_field_id,
        "selected_value": deepcopy(record.selected_value_json),
        "selected_value_hash": record.selected_value_hash,
        "candidate_snapshot_hash": record.candidate_snapshot_hash,
        "candidate_count": record.candidate_count,
        "reason_category": record.reason_category,
        "rationale": record.rationale,
        "status": record.status,
        "created_by": record.created_by,
        "created_by_name": record.created_by_name,
        "reviewed_by": record.reviewed_by,
        "reviewed_by_name": record.reviewed_by_name,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "review_comment": record.review_comment,
        "row_version": record.row_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _candidate_snapshot_hash(candidates: list[dict]) -> str:
    return content_hash(sorted(
        (item["id"], item["value_hash"], item["source_type"], item["observed_at"])
        for item in candidates
    ))


def _indicator_observation_to_dict(record: EnterpriseIndicatorObservationRecord) -> dict:
    return {
        "id": record.id,
        "counterparty_id": record.counterparty_id,
        "indicator_id": record.indicator_id,
        "indicator_name": record.indicator_name,
        "values": deepcopy(record.values_json),
        "values_hash": record.values_hash,
        "evidence_document_id": record.evidence_document_id,
        "evidence_reference": record.evidence_reference,
        "observed_at": record.observed_at.isoformat() if record.observed_at else None,
        "status": record.status,
        "created_by": record.created_by,
        "created_by_name": record.created_by_name,
        "reviewed_by": record.reviewed_by,
        "reviewed_by_name": record.reviewed_by_name,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "review_comment": record.review_comment,
        "row_version": record.row_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _document_to_dict(record: DocumentRecord) -> dict:
    return {
        "id": record.id,
        "counterparty_id": record.counterparty_id,
        "case_id": record.case_id,
        "document_type": record.document_type,
        "original_name": record.original_name,
        "object_key": record.object_key,
        "content_type": record.content_type,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "uploaded_by": record.uploaded_by,
        "status": record.status,
        "checklist": deepcopy(record.checklist_json or []),
        "review_status": record.review_status,
        "review_comment": record.review_comment,
        "reviewed_by": record.reviewed_by,
        "reviewed_by_name": record.reviewed_by_name,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "row_version": record.row_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _document_correction_to_dict(record: DocumentCorrectionRecord) -> dict:
    sla = correction_sla_snapshot(record.status, record.sla_due_at)
    return {
        "id": record.id,
        "counterparty_id": record.counterparty_id,
        "case_id": record.case_id,
        "document_type": record.document_type,
        "original_document_id": record.original_document_id,
        "current_document_id": record.current_document_id,
        "version_document_ids": deepcopy(record.version_document_ids_json or []),
        "status": record.status,
        "reason": record.reason,
        "failed_check_keys": deepcopy(record.failed_check_keys_json or []),
        "attempt_count": record.attempt_count,
        "requested_by": record.requested_by,
        "requested_by_name": record.requested_by_name,
        "requested_at": record.requested_at.isoformat() if record.requested_at else None,
        "assigned_role": record.assigned_role,
        "assigned_to": record.assigned_to,
        "assigned_to_name": record.assigned_to_name,
        "assigned_at": record.assigned_at.isoformat() if record.assigned_at else None,
        "assignment_expires_at": record.assignment_expires_at.isoformat() if record.assignment_expires_at else None,
        "sla_started_at": record.sla_started_at.isoformat() if record.sla_started_at else None,
        "sla_due_at": record.sla_due_at.isoformat() if record.sla_due_at else None,
        "reminder_count": record.reminder_count,
        "last_reminded_at": record.last_reminded_at.isoformat() if record.last_reminded_at else None,
        "extension_count": record.extension_count,
        "total_extension_hours": record.total_extension_hours,
        **sla,
        "resolved_by": record.resolved_by,
        "resolved_by_name": record.resolved_by_name,
        "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None,
        "row_version": record.row_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _notification_to_dict(record: NotificationRecord) -> dict:
    return {
        "id": record.id,
        "case_id": record.case_id,
        "counterparty_id": record.counterparty_id,
        "recipient_role": record.recipient_role,
        "recipient_subject": record.recipient_subject,
        "category": record.category,
        "level": record.level,
        "severity": record.severity,
        "title": record.title,
        "message": record.message,
        "action": deepcopy(record.action_json or {}),
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "read_at": record.read_at.isoformat() if record.read_at else None,
    }


def _facility_to_dict(record: CreditFacilityRecord) -> dict:
    approved = _money(record.approved_limit)
    used = _money(record.used_limit)
    return {
        "id": record.id,
        "case_id": record.case_id,
        "counterparty_id": record.counterparty_id,
        "counterparty_name": record.counterparty_name,
        "approved_limit": float(approved),
        "used_limit": float(used),
        "available_limit": float(_money(approved - used)),
        "utilization_rate": float(round(used / approved, 4)) if approved else 0,
        "payment_term_days": record.payment_term_days,
        "rating": record.rating,
        "access_strategy": record.access_strategy,
        "monitoring_frequency": record.monitoring_frequency,
        "status": record.status,
        "effective_at": record.effective_at.isoformat() if record.effective_at else None,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "last_review_at": record.last_review_at.isoformat() if record.last_review_at else None,
        "next_review_at": record.next_review_at.isoformat() if record.next_review_at else None,
        "row_version": record.row_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _usage_to_dict(record: CreditUsageRecord) -> dict:
    return {"id": record.id, "facility_id": record.facility_id, "transaction_ref": record.transaction_ref, "transaction_type": record.transaction_type, "amount": float(_money(record.amount)), "balance_after": float(_money(record.balance_after)), "occurred_at": record.occurred_at.isoformat(), "actor": record.actor, "reason": record.reason, "created_at": record.created_at.isoformat() if record.created_at else None}


def _alert_to_dict(record: FacilityAlertRecord) -> dict:
    return {"id": record.id, "facility_id": record.facility_id, "alert_type": record.alert_type, "severity": record.severity, "title": record.title, "message": record.message, "status": record.status, "created_at": record.created_at.isoformat() if record.created_at else None, "acknowledged_at": record.acknowledged_at.isoformat() if record.acknowledged_at else None, "acknowledged_by": record.acknowledged_by, "disposition_action": record.disposition_action, "disposition_note": record.disposition_note, "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None, "resolved_by": record.resolved_by, "row_version": record.row_version}


def _risk_event_to_dict(record: RiskEventRecord) -> dict:
    return {"id": record.id, "facility_id": record.facility_id, "external_event_id": record.external_event_id, "event_type": record.event_type, "source": record.source, "severity": record.severity, "occurred_at": record.occurred_at.isoformat(), "title": record.title, "description": record.description, "payload": deepcopy(record.event_payload or {}), "linked_alert_id": record.linked_alert_id, "status": record.status, "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None, "created_by": record.created_by, "created_at": record.created_at.isoformat() if record.created_at else None}


def _risk_event_matches(record: RiskEventRecord, facility_id: str, payload: dict) -> bool:
    return (
        record.facility_id == facility_id
        and record.event_type == payload["event_type"]
        and record.source == payload["source"]
        and record.severity == payload["severity"]
        and _as_utc(record.occurred_at) == _as_utc(payload["occurred_at"])
        and record.title == payload["title"]
        and record.description == payload["description"]
        and (record.event_payload or {}) == payload.get("payload", {})
    )


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("金额必须是有效数字") from exc


def _model_change_to_dict(record: ModelChangeRecord) -> dict:
    return {
        "id": record.id,
        "template_key": record.template_key,
        "base_version": record.base_version,
        "candidate_version": record.candidate_version,
        "status": record.status,
        "config": deepcopy(record.config_json),
        "validation": deepcopy(record.validation_json),
        "impact": deepcopy(record.impact_json),
        "change_reason": record.change_reason,
        "created_by": record.created_by,
        "created_by_name": record.created_by_name,
        "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
        "reviewed_by": record.reviewed_by,
        "reviewed_by_name": record.reviewed_by_name,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "review_comment": record.review_comment,
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "row_version": record.row_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _model_release_to_dict(record: ModelReleaseRecord) -> dict:
    return {
        "id": record.id,
        "template_key": record.template_key,
        "model_version": record.model_version,
        "config_hash": record.config_hash,
        "source_change_id": record.source_change_id,
        "is_active": record.is_active,
        "published_by": record.published_by,
        "published_at": record.published_at.isoformat() if record.published_at else None,
    }


def _model_outcome_to_dict(record: ModelOutcomeRecord) -> dict:
    return {
        "id": record.id,
        "external_observation_id": record.external_observation_id,
        "source": record.source,
        "template_key": record.template_key,
        "model_version": record.model_version,
        "counterparty_id": record.counterparty_id,
        "population_period": record.population_period,
        "predicted_score": float(record.predicted_score),
        "predicted_pd": float(record.predicted_pd),
        "observed_event": record.observed_event,
        "prediction_at": record.prediction_at.isoformat(),
        "observation_end": record.observation_end.isoformat(),
        "evidence_reference": record.evidence_reference,
        "verification_status": record.verification_status,
        "verified_by": record.verified_by,
        "verified_at": record.verified_at.isoformat() if record.verified_at else None,
        "verification_note": record.verification_note,
        "row_version": record.row_version,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _outcome_import_to_dict(record: ModelOutcomeImportRecord) -> dict:
    return {
        "id": record.id,
        "import_key": record.import_key,
        "source": record.source,
        "template_key": record.template_key,
        "population_period": record.population_period,
        "payload_hash": record.payload_hash,
        "status": record.status,
        "expected_count": record.expected_count,
        "received_count": record.received_count,
        "count_variance": record.received_count - record.expected_count,
        "created_count": record.created_count,
        "idempotent_count": record.idempotent_count,
        "rejected_count": record.rejected_count,
        "results": deepcopy(record.results_json or []),
        "error_message": record.error_message,
        "created_by": record.created_by,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _model_outcome_matches(record: ModelOutcomeRecord, payload: dict) -> bool:
    return (
        record.template_key == payload["template_key"]
        and record.model_version == payload["model_version"]
        and record.counterparty_id == payload["counterparty_id"]
        and record.population_period == payload["population_period"]
        and float(record.predicted_score) == float(payload["predicted_score"])
        and float(record.predicted_pd) == float(payload["predicted_pd"])
        and record.observed_event == payload["observed_event"]
        and _as_utc(record.prediction_at) == _as_utc(payload["prediction_at"])
        and _as_utc(record.observation_end) == _as_utc(payload["observation_end"])
        and record.evidence_reference == payload["evidence_reference"]
    )


def _monitoring_issue_to_dict(record: ModelMonitoringIssueRecord) -> dict:
    return {
        "id": record.id,
        "template_key": record.template_key,
        "model_version": record.model_version,
        "dataset_id": record.dataset_id,
        "evidence_level": record.evidence_level,
        "metric_key": record.metric_key,
        "metric_label": record.metric_label,
        "metric_value": float(record.metric_value) if record.metric_value is not None else None,
        "metric_status": record.metric_status,
        "severity": record.severity,
        "title": record.title,
        "description": record.description,
        "status": record.status,
        "owner": record.owner,
        "remediation_plan": record.remediation_plan,
        "remediation_result": record.remediation_result,
        "remediated_by": record.remediated_by,
        "revalidation_conclusion": record.revalidation_conclusion,
        "revalidated_by": record.revalidated_by,
        "linked_change_id": record.linked_change_id,
        "due_at": record.due_at.isoformat() if record.due_at else None,
        "closed_at": record.closed_at.isoformat() if record.closed_at else None,
        "row_version": record.row_version,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _monitoring_run_to_dict(record: ModelMonitoringRunRecord) -> dict:
    return {
        "id": record.id,
        "run_key": record.run_key,
        "template_key": record.template_key,
        "model_version": record.model_version,
        "as_of_period": record.as_of_period,
        "trigger_type": record.trigger_type,
        "status": record.status,
        "effective_source": record.effective_source,
        "evidence_level": record.evidence_level,
        "dataset_id": record.dataset_id,
        "readiness": deepcopy(record.readiness_json or {}),
        "monitoring": deepcopy(record.monitoring_json or {}),
        "issue_ids": deepcopy(record.issue_ids or []),
        "error_message": record.error_message,
        "actor": record.actor,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _monitoring_schedule_to_dict(record: ModelMonitoringScheduleRecord) -> dict:
    return {
        "id": record.id,
        "template_key": record.template_key,
        "cadence": record.cadence,
        "timezone_name": record.timezone_name,
        "enabled": record.enabled,
        "next_run_at": record.next_run_at.isoformat(),
        "last_scheduled_for": record.last_scheduled_for.isoformat() if record.last_scheduled_for else None,
        "last_run_at": record.last_run_at.isoformat() if record.last_run_at else None,
        "last_run_id": record.last_run_id,
        "last_status": record.last_status,
        "last_error": record.last_error,
        "row_version": record.row_version,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _advance_schedule_at(value: datetime, cadence: str) -> datetime:
    months = 1 if cadence == "monthly" else 3
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    month_days = (31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return value.replace(year=year, month=month, day=min(value.day, month_days[month - 1]))


def _governance_notification_to_dict(record: ModelGovernanceNotificationRecord) -> dict:
    return {
        "id": record.id,
        "monitoring_run_id": record.monitoring_run_id,
        "monitoring_issue_id": record.monitoring_issue_id,
        "template_key": record.template_key,
        "recipient_role": record.recipient_role,
        "severity": record.severity,
        "title": record.title,
        "message": record.message,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "read_at": record.read_at.isoformat() if record.read_at else None,
        "read_by": record.read_by,
    }


def _order_hash_chain(events: list[dict]) -> list[dict]:
    if len(events) < 2:
        return events
    by_previous = {event["previous_hash"]: event for event in events}
    ordered = []
    current_hash = ""
    while current_hash in by_previous:
        event = by_previous[current_hash]
        ordered.append(event)
        current_hash = event["event_hash"]
    return ordered if len(ordered) == len(events) else events
