"""Generate tenant-native monitoring snapshots from sealed routes and labels."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from backend.database import SessionLocal
from backend.db_models import TenantOutcomeLabelDefinitionRecord, TenantRolloutPolicyRecord
from backend.security import Principal
from backend.tenant_outcome_repository import TenantOutcomeRepository


SCHEDULER_PRINCIPAL = Principal(
    subject="system:tenant-monitoring-scheduler", name="租户监控快照调度器",
    roles=("admin",), permissions=frozenset({"*"}),
    tenant_id="tenant-platform-internal", client_id="system-scheduler",
)


def run_tenant_monitoring_snapshot(session, now: datetime | None = None, tenant_id: str | None = None) -> dict:
    as_of = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    statement = select(TenantRolloutPolicyRecord).where(
        TenantRolloutPolicyRecord.status == "active",
        TenantRolloutPolicyRecord.starts_at <= as_of,
        TenantRolloutPolicyRecord.ends_at > as_of,
    )
    if tenant_id:
        statement = statement.where(TenantRolloutPolicyRecord.tenant_id == tenant_id)
    policies = session.scalars(statement.order_by(TenantRolloutPolicyRecord.tenant_id, TenantRolloutPolicyRecord.id)).all()
    generated, skipped, failed = [], [], []
    for policy in policies:
        definitions = session.scalars(select(TenantOutcomeLabelDefinitionRecord).where(
            TenantOutcomeLabelDefinitionRecord.tenant_id == policy.tenant_id,
            TenantOutcomeLabelDefinitionRecord.status == "published",
            TenantOutcomeLabelDefinitionRecord.is_active.is_(True),
        ).order_by(TenantOutcomeLabelDefinitionRecord.version.desc(), TenantOutcomeLabelDefinitionRecord.created_at.desc())).all()
        definition = next((candidate for candidate in definitions if {
            policy.champion_model_key, policy.challenger_model_key,
        }.issubset(set(candidate.applicable_model_keys_json or []))), None)
        if definition is None:
            skipped.append({
                "tenant_id": policy.tenant_id, "policy_id": policy.id,
                "reason": "published_label_definition_missing" if not definitions else "published_label_definition_not_applicable",
            })
            continue
        repository = TenantOutcomeRepository(session)
        principal = Principal(
            subject=SCHEDULER_PRINCIPAL.subject, name=SCHEDULER_PRINCIPAL.name,
            roles=SCHEDULER_PRINCIPAL.roles, permissions=SCHEDULER_PRINCIPAL.permissions,
            tenant_id=policy.tenant_id, client_id=SCHEDULER_PRINCIPAL.client_id,
        )
        try:
            result = repository.generate_monitoring_runs(policy.tenant_id, policy.id, {
                "label_definition_id": definition.id, "as_of": as_of,
            }, principal)
            generated.append({"tenant_id": policy.tenant_id, "policy_id": policy.id, "result": result})
        except Exception as exc:
            session.rollback()
            failed.append({
                "tenant_id": policy.tenant_id, "policy_id": policy.id,
                "error_type": type(exc).__name__,
                "error_code": getattr(exc, "code", None),
                "error_message": getattr(exc, "message", str(exc)),
            })
    return {"as_of": as_of.isoformat(), "policy_count": len(policies), "generated": generated, "skipped": skipped, "failed": failed,
            "generated_count": len(generated), "skipped_count": len(skipped), "failed_count": len(failed)}


def main() -> int:
    with SessionLocal() as session:
        result = run_tenant_monitoring_snapshot(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
