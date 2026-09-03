"""add versioned scorecard monitoring SLA policies

Revision ID: 20260902_0071
Revises: 20260902_0070
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260902_0071"
down_revision = "20260902_0070"
branch_labels = None
depends_on = None

LEGACY_POLICY_ID = "00000000-0000-0000-0000-000000007001"
LEGACY_CONFIG = {
    "code": "MONITORING_SLA_STANDARD",
    "name": "持续验证标准 SLA",
    "description": "由既有 24/72 小时处置时限迁移形成的机构默认策略",
    "applicable_scorecard_codes": [],
    "applicable_event_types": [],
    "is_default": True,
    "severity_rules": {
        "critical": {"response_hours": 24, "due_soon_ratio": 0.25, "escalation_after_hours": 4},
        "warning": {"response_hours": 72, "due_soon_ratio": 0.25, "escalation_after_hours": 4},
    },
}


def _hash(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def upgrade() -> None:
    op.create_table(
        "scorecard_monitoring_sla_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applicable_scorecard_codes", sa.JSON(), nullable=False),
        sa.Column("applicable_event_types", sa.JSON(), nullable=False),
        sa.Column("severity_rules_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(128), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", "version", name="uq_scorecard_monitoring_sla_policy_code_version"),
    )
    for column in ("code", "status", "is_active", "is_default", "config_hash", "created_by", "reviewed_by", "created_at"):
        op.create_index(f"ix_scorecard_monitoring_sla_policies_{column}", "scorecard_monitoring_sla_policies", [column])
    op.create_index(
        "uq_scorecard_monitoring_sla_policy_single_active",
        "scorecard_monitoring_sla_policies", ["code", "is_active"], unique=True,
        sqlite_where=sa.text("is_active = 1"), postgresql_where=sa.text("is_active = true"),
    )

    now = datetime.now(timezone.utc)
    policies = sa.table(
        "scorecard_monitoring_sla_policies",
        sa.column("id", sa.String), sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("version", sa.Integer), sa.column("status", sa.String),
        sa.column("is_active", sa.Boolean), sa.column("is_default", sa.Boolean),
        sa.column("applicable_scorecard_codes", sa.JSON), sa.column("applicable_event_types", sa.JSON),
        sa.column("severity_rules_json", sa.JSON), sa.column("config_hash", sa.String),
        sa.column("change_reason", sa.Text), sa.column("created_by", sa.String),
        sa.column("created_by_name", sa.String), sa.column("reviewed_by", sa.String),
        sa.column("reviewed_by_name", sa.String), sa.column("review_comment", sa.Text),
        sa.column("reviewed_at", sa.DateTime(timezone=True)), sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("row_version", sa.Integer), sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.get_bind().execute(policies.insert().values(
        id=LEGACY_POLICY_ID, code=LEGACY_CONFIG["code"], name=LEGACY_CONFIG["name"],
        description=LEGACY_CONFIG["description"], version=1, status="published", is_active=True,
        is_default=True, applicable_scorecard_codes=[], applicable_event_types=[],
        severity_rules_json=LEGACY_CONFIG["severity_rules"], config_hash=_hash(LEGACY_CONFIG),
        change_reason="迁移既有持续验证预警 SLA", created_by="system-migration",
        created_by_name="系统迁移", reviewed_by="system-migration", reviewed_by_name="系统迁移",
        review_comment="保持既有 24/72 小时与逾期 4 小时升级口径", reviewed_at=now,
        published_at=now, row_version=1, created_at=now,
    ))

    with op.batch_alter_table("scorecard_validation_monitoring_events") as batch:
        batch.add_column(sa.Column("sla_policy_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("sla_policy_snapshot_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("sla_policy_snapshot_hash", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_scorecard_monitoring_event_sla_policy", "scorecard_monitoring_sla_policies",
            ["sla_policy_id"], ["id"], ondelete="RESTRICT",
        )
    events = sa.table(
        "scorecard_validation_monitoring_events",
        sa.column("sla_policy_id", sa.String), sa.column("sla_policy_snapshot_json", sa.JSON),
        sa.column("sla_policy_snapshot_hash", sa.String),
    )
    snapshot = {
        "id": LEGACY_POLICY_ID, "code": LEGACY_CONFIG["code"], "name": LEGACY_CONFIG["name"],
        "version": 1, "config_hash": _hash(LEGACY_CONFIG),
        "applicable_scorecard_codes": [], "applicable_event_types": [],
        "severity_rules": LEGACY_CONFIG["severity_rules"],
    }
    op.get_bind().execute(events.update().values(
        sla_policy_id=LEGACY_POLICY_ID,
        sla_policy_snapshot_json=snapshot,
        sla_policy_snapshot_hash=_hash(snapshot),
    ))
    op.create_index("ix_scorecard_validation_monitoring_events_sla_policy_id", "scorecard_validation_monitoring_events", ["sla_policy_id"])
    op.create_index("ix_scorecard_validation_monitoring_events_sla_policy_snapshot_hash", "scorecard_validation_monitoring_events", ["sla_policy_snapshot_hash"])


def downgrade() -> None:
    op.drop_index("ix_scorecard_validation_monitoring_events_sla_policy_snapshot_hash", table_name="scorecard_validation_monitoring_events")
    op.drop_index("ix_scorecard_validation_monitoring_events_sla_policy_id", table_name="scorecard_validation_monitoring_events")
    with op.batch_alter_table("scorecard_validation_monitoring_events") as batch:
        batch.drop_constraint("fk_scorecard_monitoring_event_sla_policy", type_="foreignkey")
        batch.drop_column("sla_policy_snapshot_hash")
        batch.drop_column("sla_policy_snapshot_json")
        batch.drop_column("sla_policy_id")
    op.drop_index("uq_scorecard_monitoring_sla_policy_single_active", table_name="scorecard_monitoring_sla_policies")
    for column in reversed(("code", "status", "is_active", "is_default", "config_hash", "created_by", "reviewed_by", "created_at")):
        op.drop_index(f"ix_scorecard_monitoring_sla_policies_{column}", table_name="scorecard_monitoring_sla_policies")
    op.drop_table("scorecard_monitoring_sla_policies")
