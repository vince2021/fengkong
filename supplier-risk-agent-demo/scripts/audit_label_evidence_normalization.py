#!/usr/bin/env python3
"""Read-only audit for tenant outcome-label evidence normalization.

The command never updates labels. It classifies v4 labels that can be fully
recomputed, legacy v3 labels that are only reconstructable from stored fields,
and labels whose evidence graph or hash is no longer valid.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.db_models import TenantOutcomeLabelRecord
from backend.repository import content_hash
from backend.tenant_outcome_repository import TenantOutcomeRepository, TenantRolloutError


def _legacy_payload(repository: TenantOutcomeRepository, record: TenantOutcomeLabelRecord) -> dict:
    return repository._canonical_label_payload({
        "source": record.source,
        "external_label_id": record.external_label_id,
        "routing_decision_id": record.routing_decision_id,
        "counterparty_id": record.counterparty_id,
        "label_definition": record.label_definition,
        "observed_event": record.observed_event,
        "label_definition_id": record.label_definition_id,
        "label_definition_version": record.label_definition_version,
        "label_definition_hash": record.label_definition_hash,
        "observation_end": record.observation_end,
        "loss_amount": record.loss_amount,
        "exposure_amount": record.exposure_amount,
        "evidence_reference": record.evidence_reference,
    })


def classify_label(repository: TenantOutcomeRepository, record: TenantOutcomeLabelRecord) -> dict:
    status = "legacy_manual_review"
    reason = "历史 v3 载荷缺少不可变规范 JSON，需要副本上人工确认原始小数文本。"
    reconstructed_hash = None
    try:
        repository._verify_label_integrity(record)
        integrity = "valid"
    except TenantRolloutError as exc:
        integrity = "invalid"
        status = "evidence_invalid"
        reason = exc.message

    if record.evidence_schema_version == "tenant-outcome-label-v4":
        if integrity == "valid":
            status = "canonical_valid"
            reason = "v4 规范证据 JSON、记录字段、路由与标签口径均可复算。"
    elif integrity == "valid":
        legacy = _legacy_payload(repository, record)
        reconstructed_hash = content_hash(legacy)
        if reconstructed_hash == record.label_payload_hash:
            status = "legacy_reconstructable"
            reason = "v3 输入载荷可由当前存储字段重建；仍不能证明原始文本小数格式未变化。"

    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "policy_id": record.policy_id,
        "evidence_schema_version": record.evidence_schema_version,
        "evidence_hash": record.evidence_hash,
        "label_payload_hash": record.label_payload_hash,
        "reconstructed_legacy_payload_hash": reconstructed_hash,
        "status": status,
        "reason": reason,
    }


def scan_labels(session, tenant_id: str | None = None, policy_id: str | None = None) -> dict:
    statement = select(TenantOutcomeLabelRecord).order_by(
        TenantOutcomeLabelRecord.tenant_id,
        TenantOutcomeLabelRecord.policy_id,
        TenantOutcomeLabelRecord.created_at,
        TenantOutcomeLabelRecord.id,
    )
    if tenant_id:
        statement = statement.where(TenantOutcomeLabelRecord.tenant_id == tenant_id)
    if policy_id:
        statement = statement.where(TenantOutcomeLabelRecord.policy_id == policy_id)
    repository = TenantOutcomeRepository(session)
    rows = [classify_label(repository, record) for record in session.scalars(statement).all()]
    return {
        "schema_version": "tenant-outcome-label-normalization-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {"tenant_id": tenant_id, "policy_id": policy_id},
        "read_only": True,
        "summary": {key: count for key, count in sorted(Counter(row["status"] for row in rows).items())},
        "total": len(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读扫描租户结果标签的规范化证据状态")
    parser.add_argument("--tenant-id", help="只扫描一个租户")
    parser.add_argument("--policy-id", help="只扫描一个灰度策略")
    parser.add_argument("--output", type=Path, help="将 JSON 报告写入本地文件；不写数据库")
    parser.add_argument("--fail-on-review", action="store_true", help="存在需人工复核或证据失效时返回非零")
    args = parser.parse_args()
    with SessionLocal() as session:
        report = scan_labels(session, args.tenant_id, args.policy_id)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    if args.fail_on_review and any(key in report["summary"] for key in ("legacy_manual_review", "evidence_invalid")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
