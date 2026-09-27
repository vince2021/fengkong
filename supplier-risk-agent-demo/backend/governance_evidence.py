"""Tenant-scoped counterparty governance evidence packages and offline verification."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.inspection import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from backend.db_models import (
    ApprovalCaseRecord,
    AuditEventRecord,
    CounterpartyRecord,
    CreditFacilityRecord,
    CreditReportRecord,
    CreditUsageRecord,
    DecisionExecutionRecord,
    DecisionVarianceRecord,
    DocumentCorrectionRecord,
    DocumentRecord,
    EnterpriseDataFieldRecord,
    EnterpriseDataImportRecord,
    EnterpriseDataResolutionRecord,
    EnterpriseIndicatorObservationRecord,
    FacilityAlertRecord,
    FacilityControlConditionRecord,
    FacilityControlExtensionRecord,
    ModelSnapshotRecord,
    NotificationRecord,
    RatingRunRecord,
    RiskEventRecord,
)
from backend.repository import PLATFORM_INTERNAL_TENANT_ID, audit_event_hash, content_hash


SCHEMA_VERSION = "counterparty-governance-evidence-v1"
PACKAGE_HASH_EXCLUDED_FIELDS = frozenset({"generated_at", "package_hash", "package_hash_algorithm"})
FORBIDDEN_KEYS = frozenset({"object_key", "secret_reference", "key_fingerprint", "source_content"})


class GovernanceEvidenceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CounterpartyGovernanceEvidenceRepository:
    """Build an exportable evidence package for one counterparty in one tenant."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def build(
        self,
        tenant_id: str,
        counterparty_id: str,
        *,
        generated_at: datetime | None = None,
    ) -> dict:
        counterparty_record = self.session.scalars(
            select(CounterpartyRecord).where(
                CounterpartyRecord.tenant_id == tenant_id,
                CounterpartyRecord.counterparty_id == counterparty_id,
            )
        ).first()
        if counterparty_record is None:
            raise GovernanceEvidenceError("COUNTERPARTY_NOT_FOUND", "当前租户下不存在该客商", 404)

        imports = self._tenant_rows(EnterpriseDataImportRecord, tenant_id, counterparty_id=counterparty_id)
        fields = self._tenant_rows(EnterpriseDataFieldRecord, tenant_id, counterparty_id=counterparty_id)
        resolutions = self._tenant_rows(EnterpriseDataResolutionRecord, tenant_id, counterparty_id=counterparty_id)
        observations = self._tenant_rows(EnterpriseIndicatorObservationRecord, tenant_id, counterparty_id=counterparty_id)
        cases = self._tenant_rows(ApprovalCaseRecord, tenant_id, counterparty_id=counterparty_id)
        ratings = self._tenant_rows(RatingRunRecord, tenant_id, counterparty_id=counterparty_id)
        variances = self._tenant_rows(DecisionVarianceRecord, tenant_id, counterparty_id=counterparty_id)
        documents = self._tenant_rows(DocumentRecord, tenant_id, counterparty_id=counterparty_id)
        corrections = self._tenant_rows(DocumentCorrectionRecord, tenant_id, counterparty_id=counterparty_id)
        reports = self._tenant_rows(CreditReportRecord, tenant_id, counterparty_id=counterparty_id)
        facilities = self._tenant_rows(CreditFacilityRecord, tenant_id, counterparty_id=counterparty_id)
        notifications = self._tenant_rows(NotificationRecord, tenant_id, counterparty_id=counterparty_id)
        decisions = self._tenant_rows(DecisionExecutionRecord, tenant_id, counterparty_id=counterparty_id)

        facility_ids = [record.id for record in facilities]
        conditions = self._tenant_rows(FacilityControlConditionRecord, tenant_id, facility_id=facility_ids)
        condition_ids = [record.id for record in conditions]
        usages = self._tenant_rows(CreditUsageRecord, tenant_id, facility_id=facility_ids)
        alerts = self._tenant_rows(FacilityAlertRecord, tenant_id, facility_id=facility_ids)
        risk_events = self._tenant_rows(RiskEventRecord, tenant_id, facility_id=facility_ids)
        extensions = self._tenant_rows(FacilityControlExtensionRecord, tenant_id, condition_id=condition_ids)

        records = {
            "enterprise_data_imports": self._serialize_many(imports),
            "enterprise_data_fields": self._serialize_many(fields, exclude={"evidence_locator"}),
            "enterprise_data_resolutions": self._serialize_many(resolutions),
            "indicator_observations": self._serialize_many(observations),
            "rating_runs": self._serialize_many(ratings),
            "approval_cases": self._serialize_many(cases),
            "decision_variances": self._serialize_many(variances),
            "documents": self._serialize_many(documents, exclude={"object_key"}),
            "document_corrections": self._serialize_many(corrections),
            "credit_reports": self._serialize_many(reports, exclude={"object_key", "snapshot"}),
            "credit_facilities": self._serialize_many(facilities),
            "credit_usage_transactions": self._serialize_many(usages),
            "facility_alerts": self._serialize_many(alerts),
            "risk_events": self._serialize_many(risk_events),
            "facility_control_conditions": self._serialize_many(conditions),
            "facility_control_extensions": self._serialize_many(extensions),
            "notifications": self._serialize_many(notifications),
            "decision_executions": self._serialize_many(decisions, exclude={"asset_snapshot"}),
        }
        for document in records["documents"]:
            document["binary_included"] = False
        for report in records["credit_reports"]:
            report["report_binary_included"] = False
            report["snapshot_included"] = False

        aggregate_keys = self._aggregate_keys(
            tenant_id=tenant_id,
            counterparty_id=counterparty_id,
            records={
                "imports": imports,
                "resolutions": resolutions,
                "observations": observations,
                "cases": cases,
                "ratings": ratings,
                "documents": documents,
                "corrections": corrections,
                "reports": reports,
                "facilities": facilities,
                "conditions": conditions,
                "notifications": notifications,
                "decisions": decisions,
            },
        )
        audit_chains = self._tenant_audit_chains(tenant_id, aggregate_keys)
        platform_references = self._platform_asset_references(ratings, decisions)
        platform_checkpoints = self._platform_audit_checkpoints(platform_references)
        assessment = _evidence_assessment(records, audit_chains, platform_references, platform_checkpoints)
        counterparty = _counterparty_evidence(counterparty_record)
        record_hash_checks = _record_hash_checks(counterparty, records)
        integrity_checks = [
            _check("tenant_scope", "租户范围", True, tenant_id),
            _check(
                "audit_chains",
                "业务审计链",
                all(chain["valid"] for chain in audit_chains),
                f"{len(audit_chains)} 条已收录链；{sum(chain['valid'] for chain in audit_chains)} 条通过",
                applicable=bool(audit_chains),
            ),
            _check(
                "record_hashes",
                "业务记录摘要",
                all(item["passed"] for item in record_hash_checks),
                f"{sum(item['passed'] for item in record_hash_checks)} / {len(record_hash_checks)} 项通过",
                applicable=bool(record_hash_checks),
            ),
            _check(
                "sensitive_material_excluded",
                "敏感材料排除",
                not _find_forbidden_keys({"counterparty": counterparty, "records": records}),
                "未包含文档二进制、对象存储路径或密钥字段",
            ),
        ]
        body = {
            "schema_version": SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "counterparty_id": counterparty_id,
            "scope": {
                "type": "single_counterparty",
                "tenant_boundary": "authenticated_tenant",
                "platform_assets": "references_only",
                "documents": "metadata_and_sha256_only",
            },
            "counterparty": counterparty,
            "records": records,
            "audit": {
                "tenant_business_chains": audit_chains,
                "platform_asset_checkpoints": platform_checkpoints,
            },
            "platform_asset_references": platform_references,
            "record_hash_checks": record_hash_checks,
            "evidence_assessment": assessment,
            "integrity": {
                "passed": all(item["passed"] for item in integrity_checks),
                "checks": integrity_checks,
            },
        }
        package = {
            **body,
            "generated_at": _iso(generated_at or datetime.now(timezone.utc)),
            "package_hash_algorithm": "SHA-256",
            "package_hash": content_hash(body),
        }
        # Treat generation as read-only: do not append an audit event that would
        # immediately make this just-built package stale.
        return package

    def _tenant_rows(self, model: type, tenant_id: str, **filters: Any) -> list[Any]:
        statement = select(model).where(model.tenant_id == tenant_id)
        for field, value in filters.items():
            column = getattr(model, field)
            if isinstance(value, list):
                if not value:
                    return []
                statement = statement.where(column.in_(value))
            else:
                statement = statement.where(column == value)
        created_at = getattr(model, "created_at", None)
        if created_at is not None:
            statement = statement.order_by(created_at, getattr(model, "id", created_at))
        return list(self.session.scalars(statement).all())

    @staticmethod
    def _serialize_many(records: list[Any], *, exclude: set[str] | None = None) -> list[dict]:
        return [_serialize_record(record, exclude=exclude) for record in records]

    @staticmethod
    def _aggregate_keys(*, tenant_id: str, counterparty_id: str, records: dict[str, list[Any]]) -> set[tuple[str, str]]:
        mapping = {
            "imports": "enterprise_data_import",
            "resolutions": "enterprise_data_resolution",
            "observations": "enterprise_indicator_observation",
            "cases": "approval_case",
            "ratings": "rating_run",
            "documents": "document",
            "corrections": "document_correction",
            "reports": "credit_report",
            "facilities": "credit_facility",
            "conditions": "facility_control_condition",
            "notifications": "notification",
        }
        keys = {("counterparty", f"{tenant_id}:{counterparty_id}")}
        for domain, aggregate_type in mapping.items():
            for record in records[domain]:
                keys.add((aggregate_type, str(record.case_id if domain == "cases" else record.id)))
        for record in records["decisions"]:
            keys.add(("decision_execution", f"{tenant_id}:{record.request_id}"))
        return keys

    def _tenant_audit_chains(self, tenant_id: str, keys: set[tuple[str, str]]) -> list[dict]:
        if not keys:
            return []
        aggregate_types = sorted({key[0] for key in keys})
        rows = self.session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == tenant_id,
                AuditEventRecord.scope_type == "tenant",
                AuditEventRecord.aggregate_type.in_(aggregate_types),
            )
        ).all()
        grouped: dict[tuple[str, str], list[AuditEventRecord]] = {}
        for row in rows:
            key = (row.aggregate_type, row.aggregate_id)
            if key in keys:
                grouped.setdefault(key, []).append(row)
        return [_serialize_audit_chain(tenant_id, key[0], key[1], grouped[key]) for key in sorted(grouped)]

    def _platform_asset_references(
        self,
        ratings: list[RatingRunRecord],
        decisions: list[DecisionExecutionRecord],
    ) -> list[dict]:
        references: list[dict] = []
        snapshot_ids = sorted({record.model_snapshot_id for record in ratings})
        if snapshot_ids:
            snapshots = self.session.scalars(
                select(ModelSnapshotRecord).where(ModelSnapshotRecord.id.in_(snapshot_ids))
            ).all()
            for snapshot in snapshots:
                references.append({
                    "asset_type": "model_snapshot",
                    "evidence_scope": "platform_shared",
                    "id": snapshot.id,
                    "code": snapshot.template_key,
                    "version": snapshot.model_version,
                    "config_hash": snapshot.config_hash,
                })
        for record in decisions:
            references.extend([
                {
                    "asset_type": "decision_model",
                    "evidence_scope": "platform_shared",
                    "code": record.model_key,
                    "version": record.model_version,
                    "config_hash": record.model_config_hash,
                    "source_execution_id": record.id,
                },
                {
                    "asset_type": "decision_pipeline",
                    "evidence_scope": "platform_shared",
                    "code": record.pipeline_code,
                    "version": record.pipeline_version,
                    "config_hash": record.pipeline_hash,
                    "assets_hash": record.assets_hash,
                    "source_execution_id": record.id,
                },
            ])
        unique = {content_hash(reference): reference for reference in references}
        return [unique[key] for key in sorted(unique)]

    def _platform_audit_checkpoints(self, references: list[dict]) -> list[dict]:
        tokens = {
            str(value)
            for reference in references
            for key, value in reference.items()
            if key in {"id", "code", "version", "config_hash", "assets_hash"} and value not in {None, ""}
        }
        if not tokens:
            return []
        rows = self.session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
                AuditEventRecord.scope_type == "platform",
            )
        ).all()
        all_chains: dict[tuple[str, str], list[AuditEventRecord]] = {}
        matched_keys: set[tuple[str, str]] = set()
        for row in rows:
            key = (row.aggregate_type, row.aggregate_id)
            all_chains.setdefault(key, []).append(row)
            searchable = json.dumps(row.payload or {}, ensure_ascii=False, sort_keys=True, default=str)
            if row.aggregate_id in tokens or any(len(token) >= 4 and token in searchable for token in tokens):
                matched_keys.add(key)
        checkpoints = []
        for key in sorted(matched_keys):
            chain = _serialize_audit_chain(PLATFORM_INTERNAL_TENANT_ID, key[0], key[1], all_chains[key])
            checkpoints.append({
                "evidence_scope": "platform_shared",
                "tenant_id": PLATFORM_INTERNAL_TENANT_ID,
                "aggregate_type": key[0],
                "aggregate_id": key[1],
                "event_count": chain["event_count"],
                "terminal_hash": chain["terminal_hash"],
                "valid": chain["valid"],
            })
        return checkpoints


def verify_counterparty_governance_evidence_package(
    package: object,
    expected_package_hash: str | None = None,
) -> dict:
    """Verify a downloaded package without requiring database access."""
    checks: list[dict] = []
    if not isinstance(package, dict):
        return _verification_result(
            [_check("package_shape", "证据包结构", False, "证据包必须是 JSON 对象")],
            "",
            expected_package_hash,
        )
    body = {key: deepcopy(value) for key, value in package.items() if key not in PACKAGE_HASH_EXCLUDED_FIELDS}
    computed_hash = content_hash(body)
    declared_hash = str(package.get("package_hash") or "")
    tenant_id = package.get("tenant_id")
    counterparty_id = package.get("counterparty_id")
    records = package.get("records")
    audit = package.get("audit") if isinstance(package.get("audit"), dict) else {}
    chains = audit.get("tenant_business_chains")
    normalized_expected = expected_package_hash.strip().lower() if isinstance(expected_package_hash, str) else None

    checks.extend([
        _check("schema_version", "证据包协议", package.get("schema_version") == SCHEMA_VERSION, str(package.get("schema_version") or "缺失")),
        _check("hash_algorithm", "封印算法", package.get("package_hash_algorithm") == "SHA-256", str(package.get("package_hash_algorithm") or "缺失")),
        _check("package_hash", "包级内容封印", bool(declared_hash) and declared_hash == computed_hash, f"声明 {declared_hash or '缺失'} · 复算 {computed_hash}"),
        _check(
            "external_hash_anchor",
            "外部哈希锚点",
            normalized_expected is None or normalized_expected == computed_hash,
            "未提供外部哈希" if normalized_expected is None else f"期望 {normalized_expected} · 复算 {computed_hash}",
            applicable=normalized_expected is not None,
        ),
        _check(
            "scope_identity",
            "单户范围标识",
            isinstance(tenant_id, str) and bool(tenant_id) and isinstance(counterparty_id, str) and bool(counterparty_id)
            and isinstance(package.get("counterparty"), dict)
            and package["counterparty"].get("tenant_id") == tenant_id
            and package["counterparty"].get("id") == counterparty_id,
            f"{tenant_id or '缺失'} / {counterparty_id or '缺失'}",
        ),
        _check(
            "tenant_record_isolation",
            "业务记录租户隔离",
            isinstance(records, dict) and _records_match_tenant(records, tenant_id),
            "所有带租户字段的业务记录均归属包声明租户",
        ),
        _check(
            "audit_chain_integrity",
            "业务审计链完整性",
            isinstance(chains, list) and all(_verify_serialized_audit_chain(chain, tenant_id) for chain in chains),
            f"{len(chains) if isinstance(chains, list) else 0} 条业务链",
            applicable=isinstance(chains, list) and bool(chains),
        ),
        _check(
            "platform_reference_scope",
            "平台资产引用边界",
            isinstance(package.get("platform_asset_references"), list)
            and all(isinstance(item, dict) and item.get("evidence_scope") == "platform_shared" for item in package["platform_asset_references"]),
            f"{len(package.get('platform_asset_references', [])) if isinstance(package.get('platform_asset_references'), list) else 0} 项平台引用",
            applicable=bool(package.get("platform_asset_references")),
        ),
        _check(
            "sensitive_material_excluded",
            "敏感材料排除",
            not _find_forbidden_keys(package),
            "未发现禁止打包的密钥、内部对象路径或文件内容字段",
        ),
    ])
    generated_record_checks = package.get("record_hash_checks")
    recomputed_record_checks = _record_hash_checks(package.get("counterparty", {}), records if isinstance(records, dict) else {})
    checks.append(_check(
        "record_hashes",
        "业务记录摘要复算",
        isinstance(generated_record_checks, list)
        and generated_record_checks == recomputed_record_checks
        and all(item["passed"] for item in recomputed_record_checks),
        f"{sum(item['passed'] for item in recomputed_record_checks)} / {len(recomputed_record_checks)} 项通过",
        applicable=bool(recomputed_record_checks),
    ))
    return _verification_result(checks, computed_hash, normalized_expected)


def _serialize_record(record: Any, *, exclude: set[str] | None = None) -> dict:
    excluded = exclude or set()
    result: dict[str, Any] = {}
    for attribute in sqlalchemy_inspect(record).mapper.column_attrs:
        key = attribute.key
        public_key = key[:-5] if key.endswith("_json") else key
        if key in excluded or public_key in excluded or key in FORBIDDEN_KEYS or public_key in FORBIDDEN_KEYS:
            continue
        result[public_key] = _json_value(getattr(record, key))
    return result


def _counterparty_evidence(record: CounterpartyRecord) -> dict:
    return {
        "id": record.counterparty_id,
        "tenant_id": record.tenant_id,
        "credit_code": record.credit_code,
        "name": record.name,
        "counterparty_type": record.counterparty_type,
        "industry": record.industry,
        "cooperation_status": record.cooperation_status,
        "is_key_counterparty": record.is_key_counterparty,
        "requested_limit": float(record.requested_limit),
        "current_limit": float(record.current_limit),
        "current_payment_term_days": record.current_payment_term_days,
        "current_rating": record.current_rating,
        "current_segment": record.current_segment,
        "external": deepcopy(record.external_json or {}),
        "internal": deepcopy(record.internal_json or {}),
        "financial": deepcopy(record.financial_json or {}),
        "extensions": deepcopy(record.extensions_json or {}),
        "profile_hash": record.profile_hash,
        "status": record.status,
        "source_type": record.source_type,
        "row_version": record.row_version,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "archived_at": _iso(record.archived_at),
        "archived_by": record.archived_by,
        "archive_reason": record.archive_reason,
    }


def _serialize_audit_chain(tenant_id: str, aggregate_type: str, aggregate_id: str, records: list[AuditEventRecord]) -> dict:
    by_previous: dict[str, list[AuditEventRecord]] = {}
    for record in records:
        by_previous.setdefault(record.previous_hash, []).append(record)
    ordered: list[AuditEventRecord] = []
    previous_hash = ""
    seen: set[str] = set()
    while len(by_previous.get(previous_hash, [])) == 1:
        record = by_previous[previous_hash][0]
        if record.id in seen:
            break
        ordered.append(record)
        seen.add(record.id)
        previous_hash = record.event_hash
    leftovers = sorted((record for record in records if record.id not in seen), key=lambda item: (_iso(item.created_at) or "", item.id))
    serialized = [_serialize_audit_event(record) for record in [*ordered, *leftovers]]
    complete = len(ordered) == len(records)
    return {
        "tenant_id": tenant_id,
        "scope_type": "platform" if tenant_id == PLATFORM_INTERNAL_TENANT_ID else "tenant",
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "valid": bool(records) and complete and all(item["hash_valid"] for item in serialized),
        "event_count": len(records),
        "terminal_hash": previous_hash if complete else "",
        "events": serialized,
    }


def _serialize_audit_event(record: AuditEventRecord) -> dict:
    expected_hash = audit_event_hash(
        event_id=record.id,
        tenant_id=record.tenant_id,
        scope_type=record.scope_type,
        aggregate_type=record.aggregate_type,
        aggregate_id=record.aggregate_id,
        event_type=record.event_type,
        actor=record.actor,
        payload=record.payload or {},
        previous_hash=record.previous_hash,
    )
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "scope_type": record.scope_type,
        "event_type": record.event_type,
        "actor": record.actor,
        "payload": deepcopy(record.payload or {}),
        "previous_hash": record.previous_hash,
        "event_hash": record.event_hash,
        "expected_hash": expected_hash,
        "hash_valid": record.event_hash == expected_hash,
        "created_at": _iso(record.created_at),
    }


def _verify_serialized_audit_chain(chain: object, tenant_id: object) -> bool:
    if not isinstance(chain, dict) or chain.get("tenant_id") != tenant_id or chain.get("scope_type") != "tenant":
        return False
    events = chain.get("events")
    if not isinstance(events, list) or not events:
        return False
    previous_hash = ""
    for event in events:
        if not isinstance(event, dict) or event.get("previous_hash") != previous_hash:
            return False
        expected = audit_event_hash(
            event_id=event.get("id"),
            tenant_id=event.get("tenant_id"),
            scope_type=event.get("scope_type"),
            aggregate_type=chain.get("aggregate_type"),
            aggregate_id=chain.get("aggregate_id"),
            event_type=event.get("event_type"),
            actor=event.get("actor"),
            payload=event.get("payload"),
            previous_hash=previous_hash,
        )
        if event.get("tenant_id") != tenant_id or event.get("scope_type") != "tenant" or event.get("event_hash") != expected or event.get("expected_hash") != expected or event.get("hash_valid") is not True:
            return False
        previous_hash = expected
    return chain.get("valid") is True and chain.get("event_count") == len(events) and chain.get("terminal_hash") == previous_hash


def _record_hash_checks(counterparty: dict, records: dict) -> list[dict]:
    checks: list[dict] = []
    if isinstance(counterparty, dict) and counterparty:
        profile_body = {
            key: counterparty.get(key)
            for key in (
                "id", "name", "credit_code", "counterparty_type", "industry", "cooperation_status",
                "is_key_counterparty", "requested_limit", "current_limit", "current_payment_term_days",
                "current_rating", "current_segment", "external", "internal", "financial", "extensions",
            )
        }
        checks.append(_check("counterparty_profile_hash", "客商画像摘要", content_hash(profile_body) == counterparty.get("profile_hash"), str(counterparty.get("profile_hash") or "缺失")))
    pairs = {
        "enterprise_data_fields": ("value", "value_hash"),
        "indicator_observations": ("values", "values_hash"),
        "rating_runs": ("input", "input_hash"),
        "decision_executions": ("request", "request_hash"),
    }
    for domain, (source_key, hash_key) in pairs.items():
        for index, record in enumerate(records.get(domain, []) if isinstance(records, dict) else []):
            if isinstance(record, dict):
                checks.append(_check(f"{domain}:{index}:{hash_key}", f"{domain} 记录摘要", content_hash(record.get(source_key)) == record.get(hash_key), str(record.get(hash_key) or "缺失")))
    for index, record in enumerate(records.get("rating_runs", []) if isinstance(records, dict) else []):
        if isinstance(record, dict):
            checks.append(_check(f"rating_runs:{index}:result_hash", "rating_runs 结果摘要", content_hash(record.get("result")) == record.get("result_hash"), str(record.get("result_hash") or "缺失")))
    for index, record in enumerate(records.get("decision_executions", []) if isinstance(records, dict) else []):
        if isinstance(record, dict):
            for source_key, hash_key in (("normalized_input", "input_hash"), ("result", "result_hash"), ("trace", "trace_hash")):
                checks.append(_check(f"decision_executions:{index}:{hash_key}", f"decision_executions {source_key} 摘要", content_hash(record.get(source_key)) == record.get(hash_key), str(record.get(hash_key) or "缺失")))
    return checks


def _evidence_assessment(records: dict, chains: list[dict], platform_references: list[dict], platform_checkpoints: list[dict]) -> dict:
    present = {
        "data_lineage": bool(records["enterprise_data_imports"] and records["enterprise_data_fields"]),
        "indicator_observations": bool(records["indicator_observations"]),
        "rating_runs": bool(records["rating_runs"]),
        "approval_cases": bool(records["approval_cases"]),
        "documents": bool(records["documents"]),
        "credit_reports": bool(records["credit_reports"]),
        "credit_facilities": bool(records["credit_facilities"]),
        "post_credit_activity": bool(records["credit_usage_transactions"] or records["facility_alerts"] or records["risk_events"] or records["facility_control_conditions"]),
        "business_audit_chains": bool(chains),
        "platform_asset_references": bool(platform_references),
        "platform_audit_checkpoints": bool(platform_checkpoints),
    }
    missing = [key for key, available in present.items() if not available]
    core_keys = ("data_lineage", "rating_runs", "approval_cases", "documents", "credit_reports", "credit_facilities", "business_audit_chains")
    core_count = sum(present[key] for key in core_keys)
    level = "complete" if core_count == len(core_keys) and all(chain["valid"] for chain in chains) else "partial" if core_count >= 3 else "limited"
    return {
        "level": level,
        "domain_count": len(present),
        "present_domain_count": sum(present.values()),
        "completeness_ratio": round(sum(present.values()) / len(present), 4),
        "domains": present,
        "missing_domains": missing,
        "note": "证据等级仅反映当前已归档材料范围；缺失域不会被推断或补造。",
    }


def _records_match_tenant(records: dict, tenant_id: object) -> bool:
    for values in records.values():
        if not isinstance(values, list):
            return False
        for record in values:
            if not isinstance(record, dict):
                return False
            if "tenant_id" in record and record["tenant_id"] != tenant_id:
                return False
    return True


def _find_forbidden_keys(value: object, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            if key in FORBIDDEN_KEYS:
                found.append(next_path)
            found.extend(_find_forbidden_keys(item, next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_forbidden_keys(item, f"{path}[{index}]"))
    return found


def _verification_result(checks: list[dict], computed_hash: str, expected_hash: str | None) -> dict:
    verified = all(item["passed"] for item in checks)
    return {
        "verified": verified,
        "trust_level": "externally_anchored" if verified and expected_hash else "self_sealed" if verified else "invalid",
        "computed_package_hash": computed_hash,
        "expected_package_hash": expected_hash,
        "checks": checks,
        "note": "包级封印、租户边界、记录摘要与审计链均通过离线复验。" if verified else "证据包复验失败，不应作为完整审计证据使用。",
    }


def _check(key: str, label: str, passed: bool, detail: str, *, applicable: bool = True) -> dict:
    return {"key": key, "label": label, "passed": bool(passed), "applicable": applicable, "detail": detail}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return deepcopy(value)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
