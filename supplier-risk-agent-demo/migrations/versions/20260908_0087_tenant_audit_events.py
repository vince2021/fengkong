"""isolate audit event hash chains by tenant

Revision ID: 20260908_0087
Revises: 20260908_0086
"""
from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260908_0087"
down_revision = "20260908_0086"
branch_labels = None
depends_on = None


PLATFORM_INTERNAL_TENANT_ID = "tenant-platform-internal"
PLATFORM_AGGREGATE_TYPES = frozenset({
    "api_client",
    "credit_calibration_plan",
    "indicator_definition",
    "pipeline_definition",
    "rule_definition",
    "rule_set_definition",
    "sla_scan_execution",
    "sla_scan_failure",
    "sla_scan_skip",
    "tenant",
    "tenant_membership",
})
PLATFORM_AGGREGATE_PREFIXES = (
    "authority_policy",
    "model_",
    "rule_center_",
    "scorecard_",
)
COMPOSITE_TENANT_AGGREGATE_TYPES = frozenset({
    "counterparty",
    "counterparty_import",
    "counterparty_import_mapping",
    "decision_execution",
})
DYNAMIC_TENANT_AGGREGATE_TYPES = frozenset({"post_credit_scan", "sla_scan"})
TENANT_MODEL_LOOKUPS = {
    "approval_case": ("approval_cases", "case_id"),
    "credit_facility": ("credit_facilities", "id"),
    "credit_report": ("credit_reports", "id"),
    "decision_job": ("decision_jobs", "id"),
    "document": ("documents", "id"),
    "document_correction": ("document_corrections", "id"),
    "enterprise_data_import": ("enterprise_data_imports", "id"),
    "enterprise_data_resolution": ("enterprise_data_resolutions", "id"),
    "enterprise_indicator_observation": ("enterprise_indicator_observations", "id"),
    "facility_control_condition": ("facility_control_conditions", "id"),
    "notification": ("notifications", "id"),
    "portfolio_rating_batch": ("portfolio_rating_batches", "id"),
    "rating_run": ("rating_runs", "id"),
}


def _content_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _event_hash(event: dict, *, include_scope: bool, previous_hash: str) -> str:
    body = {
        "id": event["id"],
        "aggregate_type": event["aggregate_type"],
        "aggregate_id": event["aggregate_id"],
        "event_type": event["event_type"],
        "actor": event["actor"],
        "payload": event["payload"],
        "previous_hash": previous_hash,
    }
    if include_scope:
        body["tenant_id"] = event["tenant_id"]
        body["scope_type"] = event["scope_type"]
    return _content_hash(body)


def _payload(value: object, event_id: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Cannot migrate audit event {event_id!r}: payload is not valid JSON"
            ) from exc
    if not isinstance(value, dict):
        raise RuntimeError(
            f"Cannot migrate audit event {event_id!r}: payload must be a JSON object"
        )
    return value


def _load_events(connection) -> list[dict]:
    rows = connection.execute(sa.text(
        "SELECT id, tenant_id, scope_type, aggregate_type, aggregate_id, event_type, "
        "actor, payload, previous_hash, event_hash, created_at FROM audit_events"
    )).mappings().all()
    return [
        {**dict(row), "payload": _payload(row["payload"], row["id"])}
        for row in rows
    ]


def _legacy_events(connection) -> list[dict]:
    rows = connection.execute(sa.text(
        "SELECT id, aggregate_type, aggregate_id, event_type, actor, payload, "
        "previous_hash, event_hash, created_at FROM audit_events"
    )).mappings().all()
    return [
        {
            **dict(row),
            "tenant_id": None,
            "scope_type": None,
            "payload": _payload(row["payload"], row["id"]),
        }
        for row in rows
    ]


def _is_platform_type(aggregate_type: str) -> bool:
    return (
        aggregate_type in PLATFORM_AGGREGATE_TYPES
        or aggregate_type.startswith(PLATFORM_AGGREGATE_PREFIXES)
    )


def _stored_tenants(connection, table: str, identity_field: str, aggregate_id: str) -> set[str]:
    rows = connection.execute(
        sa.text(
            f"SELECT DISTINCT tenant_id FROM {table} "
            f"WHERE {identity_field} = :aggregate_id"
        ),
        {"aggregate_id": aggregate_id},
    ).fetchall()
    return {row[0] for row in rows if isinstance(row[0], str) and row[0]}


def _resolve_owner(connection, event: dict) -> tuple[str, str]:
    aggregate_type = event["aggregate_type"]
    aggregate_id = event["aggregate_id"]
    if _is_platform_type(aggregate_type):
        return PLATFORM_INTERNAL_TENANT_ID, "platform"

    payload_tenant = event["payload"].get("tenant_id")
    candidates = {
        payload_tenant.strip()
        for payload_tenant in [payload_tenant]
        if isinstance(payload_tenant, str) and payload_tenant.strip()
    }
    if aggregate_type in COMPOSITE_TENANT_AGGREGATE_TYPES:
        prefix, separator, _ = aggregate_id.partition(":")
        if separator and prefix:
            candidates.add(prefix)
    elif aggregate_type == "decision_webhook":
        rows = connection.execute(
            sa.text(
                "SELECT DISTINCT j.tenant_id FROM decision_webhook_deliveries d "
                "JOIN decision_jobs j ON j.id = d.job_id WHERE d.id = :aggregate_id"
            ),
            {"aggregate_id": aggregate_id},
        ).fetchall()
        candidates.update(row[0] for row in rows if isinstance(row[0], str) and row[0])
    elif aggregate_type in TENANT_MODEL_LOOKUPS:
        table, identity_field = TENANT_MODEL_LOOKUPS[aggregate_type]
        candidates.update(_stored_tenants(connection, table, identity_field, aggregate_id))
    elif aggregate_type not in DYNAMIC_TENANT_AGGREGATE_TYPES:
        raise RuntimeError(
            f"Cannot migrate audit event {event['id']!r}: aggregate type "
            f"{aggregate_type!r} has no tenant ownership policy"
        )

    if not candidates:
        if aggregate_type in DYNAMIC_TENANT_AGGREGATE_TYPES:
            if aggregate_type == "sla_scan" and event["payload"].get("trigger_type") == "manual":
                raise RuntimeError(
                    f"Cannot migrate audit event {event['id']!r}: manual SLA scan has no tenant ownership"
                )
            return PLATFORM_INTERNAL_TENANT_ID, "platform"
        raise RuntimeError(
            f"Cannot migrate audit event {event['id']!r}: tenant ownership is missing or ambiguous"
        )
    if len(candidates) != 1:
        raise RuntimeError(
            f"Cannot migrate audit event {event['id']!r}: conflicting tenant ownership "
            f"{sorted(candidates)!r}"
        )
    tenant_id = candidates.pop()
    scope_type = "platform" if tenant_id == PLATFORM_INTERNAL_TENANT_ID else "tenant"
    return tenant_id, scope_type


def _ordered_chains(events: list[dict], *, include_scope: bool) -> list[list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for event in events:
        key = (
            (event["tenant_id"], event["scope_type"])
            if include_scope
            else ()
        ) + (event["aggregate_type"], event["aggregate_id"])
        groups.setdefault(key, []).append(event)

    chains: list[list[dict]] = []
    for key, group in groups.items():
        by_previous: dict[str, list[dict]] = {}
        for event in group:
            by_previous.setdefault(event["previous_hash"], []).append(event)
            expected = _event_hash(
                event,
                include_scope=include_scope,
                previous_hash=event["previous_hash"],
            )
            if event["event_hash"] != expected:
                raise RuntimeError(
                    f"Cannot migrate audit chain {key!r}: event {event['id']!r} has an invalid content hash"
                )
        if len(by_previous.get("", [])) != 1:
            raise RuntimeError(
                f"Cannot migrate audit chain {key!r}: expected exactly one root event"
            )
        ordered: list[dict] = []
        current_hash = ""
        visited: set[str] = set()
        while len(by_previous.get(current_hash, [])) == 1:
            event = by_previous[current_hash][0]
            if event["id"] in visited:
                break
            ordered.append(event)
            visited.add(event["id"])
            current_hash = event["event_hash"]
        if len(ordered) != len(group):
            raise RuntimeError(
                f"Cannot migrate audit chain {key!r}: chain is broken, forked, or cyclic"
            )
        chains.append(ordered)
    return chains


def _ensure_tenants_exist(connection, events: list[dict]) -> None:
    required = {event["tenant_id"] for event in events}
    if not required:
        return
    existing = {
        row[0]
        for row in connection.execute(
            sa.text("SELECT id FROM tenants WHERE id IN :tenant_ids").bindparams(
                sa.bindparam("tenant_ids", expanding=True)
            ),
            {"tenant_ids": sorted(required)},
        ).fetchall()
    }
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(
            f"Cannot migrate audit events: tenant registry is missing {missing!r}"
        )


def _rewrite_hashes(connection, chains: list[list[dict]], *, include_scope: bool) -> None:
    for chain in chains:
        previous_hash = ""
        for event in chain:
            new_hash = _event_hash(
                event,
                include_scope=include_scope,
                previous_hash=previous_hash,
            )
            connection.execute(
                sa.text(
                    "UPDATE audit_events SET previous_hash = :previous_hash, "
                    "event_hash = :event_hash WHERE id = :event_id"
                ),
                {
                    "previous_hash": previous_hash,
                    "event_hash": new_hash,
                    "event_id": event["id"],
                },
            )
            previous_hash = new_hash


def upgrade() -> None:
    connection = op.get_bind()
    events = _legacy_events(connection)
    legacy_chains = _ordered_chains(events, include_scope=False)
    for chain in legacy_chains:
        owners = {_resolve_owner(connection, event) for event in chain}
        if len(owners) != 1:
            identity = (chain[0]["aggregate_type"], chain[0]["aggregate_id"])
            raise RuntimeError(
                f"Cannot migrate audit chain {identity!r}: one legacy chain spans multiple tenant scopes"
            )
        tenant_id, scope_type = owners.pop()
        for event in chain:
            event["tenant_id"] = tenant_id
            event["scope_type"] = scope_type
    _ensure_tenants_exist(connection, events)

    op.add_column("audit_events", sa.Column("tenant_id", sa.String(128), nullable=True))
    op.add_column("audit_events", sa.Column("scope_type", sa.String(16), nullable=True))
    for event in events:
        connection.execute(
            sa.text(
                "UPDATE audit_events SET tenant_id = :tenant_id, scope_type = :scope_type "
                "WHERE id = :event_id"
            ),
            {
                "tenant_id": event["tenant_id"],
                "scope_type": event["scope_type"],
                "event_id": event["id"],
            },
        )

    with op.batch_alter_table("audit_events") as batch:
        batch.drop_index("ix_audit_aggregate")
        batch.drop_constraint("uq_audit_chain_parent", type_="unique")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.alter_column("scope_type", existing_type=sa.String(16), nullable=False)
        batch.create_foreign_key(
            "fk_audit_event_tenant",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_audit_scope_tenant",
            "(scope_type = 'platform' AND tenant_id = 'tenant-platform-internal') "
            "OR (scope_type = 'tenant' AND tenant_id <> 'tenant-platform-internal')",
        )
        batch.create_unique_constraint(
            "uq_audit_tenant_chain_parent",
            ["tenant_id", "aggregate_type", "aggregate_id", "previous_hash"],
        )
        batch.create_index("ix_audit_events_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_audit_tenant_aggregate",
            ["tenant_id", "aggregate_type", "aggregate_id", "created_at"],
        )

    _rewrite_hashes(connection, legacy_chains, include_scope=True)


def downgrade() -> None:
    connection = op.get_bind()
    events = _load_events(connection)
    current_chains = _ordered_chains(events, include_scope=True)
    reused = connection.execute(sa.text(
        "SELECT aggregate_type, aggregate_id FROM audit_events "
        "GROUP BY aggregate_type, aggregate_id "
        "HAVING COUNT(DISTINCT tenant_id) > 1 LIMIT 1"
    )).first()
    if reused:
        raise RuntimeError(
            "Cannot downgrade audit events: tenant-scoped chains cannot be represented "
            "by the legacy global aggregate chain"
        )

    _rewrite_hashes(connection, current_chains, include_scope=False)
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_index("ix_audit_tenant_aggregate")
        batch.drop_index("ix_audit_events_tenant_id")
        batch.drop_constraint("uq_audit_tenant_chain_parent", type_="unique")
        batch.drop_constraint("ck_audit_scope_tenant", type_="check")
        batch.drop_constraint("fk_audit_event_tenant", type_="foreignkey")
        batch.drop_column("scope_type")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint(
            "uq_audit_chain_parent",
            ["aggregate_type", "aggregate_id", "previous_hash"],
        )
        batch.create_index(
            "ix_audit_aggregate",
            ["aggregate_type", "aggregate_id", "created_at"],
        )
