"""Add governed outcome label definitions and supervised upgrade decisions.

Revision ID: 20260919_0098
Revises: 20260917_0097
"""
from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "20260919_0098"
down_revision = "20260917_0097"
branch_labels = None
depends_on = None


def _hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.create_table(
        "tenant_outcome_label_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("event_threshold_json", sa.JSON(), nullable=False),
        sa.Column("observation_window_days", sa.Integer(), nullable=False),
        sa.Column("maturity_grace_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_priorities_json", sa.JSON(), nullable=False),
        sa.Column("applicable_model_keys_json", sa.JSON(), nullable=False),
        sa.Column("require_loss_amount", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_exposure_amount", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("submitted_by", sa.String(128), nullable=True),
        sa.Column("submitted_by_name", sa.String(128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("event_type IN ('default', 'delinquency', 'loss', 'recovery')", name="ck_tenant_outcome_label_definition_event_type"),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')", name="ck_tenant_outcome_label_definition_status"),
        sa.CheckConstraint("observation_window_days > 0", name="ck_tenant_outcome_label_definition_window"),
        sa.CheckConstraint("maturity_grace_days >= 0", name="ck_tenant_outcome_label_definition_grace"),
        sa.UniqueConstraint("tenant_id", "code", "version", name="uq_tenant_outcome_label_definition_version"),
    )
    for column in ("tenant_id", "code", "status", "is_active", "config_hash", "created_at"):
        op.create_index(f"ix_tenant_outcome_label_definitions_{column}", "tenant_outcome_label_definitions", [column])
    op.create_index(
        "ix_tenant_outcome_label_definition_tenant_status",
        "tenant_outcome_label_definitions",
        ["tenant_id", "status", "code"],
    )
    op.create_index(
        "uq_tenant_outcome_label_definition_active",
        "tenant_outcome_label_definitions",
        ["tenant_id", "code"],
        unique=True,
        sqlite_where=sa.text("status = 'published' AND is_active = 1"),
        postgresql_where=sa.text("status = 'published' AND is_active = true"),
    )

    default_config = {
        "code": "90_days_default",
        "version": 1,
        "name": "90 天企业违约口径",
        "description": "用于企业评级与授信模型延迟监督的标准违约定义；观察窗口届满后确认逾期或违约事实。",
        "event_type": "default",
        "event_threshold": {"days_past_due": 90},
        "observation_window_days": 90,
        "maturity_grace_days": 0,
        "source_priorities": [
            {"source": "贷后核心系统", "priority": 1},
            {"source": "贷后结果系统", "priority": 2},
            {"source": "贷后结果仓", "priority": 3},
        ],
        "applicable_model_keys": ["general", "general-next", "corporate_credit_v2"],
        "require_loss_amount": False,
        "require_exposure_amount": False,
    }
    connection = op.get_bind()
    tenants = connection.execute(sa.text("SELECT id FROM tenants")).fetchall()
    table = sa.table(
        "tenant_outcome_label_definitions",
        sa.column("id"), sa.column("tenant_id"), sa.column("code"), sa.column("version"),
        sa.column("name"), sa.column("description"), sa.column("event_type"),
        sa.column("event_threshold_json", sa.JSON()), sa.column("observation_window_days"),
        sa.column("maturity_grace_days"), sa.column("source_priorities_json", sa.JSON()),
        sa.column("applicable_model_keys_json", sa.JSON()), sa.column("require_loss_amount", sa.Boolean()),
        sa.column("require_exposure_amount", sa.Boolean()), sa.column("status"), sa.column("is_active", sa.Boolean()),
        sa.column("config_hash"), sa.column("reviewed_by"), sa.column("reviewed_by_name"),
        sa.column("review_comment"), sa.column("created_by"), sa.column("created_by_name"),
    )
    for (tenant_id,) in tenants:
        op.bulk_insert(table, [{
            "id": str(uuid5(NAMESPACE_URL, f"fengkong:{tenant_id}:90_days_default:1")),
            "tenant_id": tenant_id,
            "code": default_config["code"],
            "version": 1,
            "name": default_config["name"],
            "description": default_config["description"],
            "event_type": default_config["event_type"],
            "event_threshold_json": default_config["event_threshold"],
            "observation_window_days": default_config["observation_window_days"],
            "maturity_grace_days": default_config["maturity_grace_days"],
            "source_priorities_json": default_config["source_priorities"],
            "applicable_model_keys_json": default_config["applicable_model_keys"],
            "require_loss_amount": default_config["require_loss_amount"],
            "require_exposure_amount": default_config["require_exposure_amount"],
            "status": "published",
            "is_active": True,
            "config_hash": _hash(default_config),
            "reviewed_by": "system-migration",
            "reviewed_by_name": "系统预置",
            "review_comment": "平台标准口径初始化；不回填或改写历史标签绑定。",
            "created_by": "system-migration",
            "created_by_name": "系统预置",
        }])

    for table_name in ("tenant_outcome_import_batches", "tenant_outcome_labels"):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("label_definition_id", sa.String(36), nullable=True))
            batch.add_column(sa.Column("label_definition_version", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("label_definition_hash", sa.String(64), nullable=True))
            batch.create_foreign_key(
                f"fk_{table_name}_label_definition",
                "tenant_outcome_label_definitions",
                ["label_definition_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        op.create_index(f"ix_{table_name}_label_definition_id", table_name, ["label_definition_id"])
        op.create_index(f"ix_{table_name}_label_definition_hash", table_name, ["label_definition_hash"])

    with op.batch_alter_table("tenant_supervised_evaluations") as batch:
        batch.add_column(sa.Column("label_definition_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("label_definition_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("label_definition_hash", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_tenant_supervised_evaluation_label_definition",
            "tenant_outcome_label_definitions",
            ["label_definition_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_tenant_supervised_evaluations_label_definition_id", "tenant_supervised_evaluations", ["label_definition_id"])
    op.create_index("ix_tenant_supervised_evaluations_label_definition_hash", "tenant_supervised_evaluations", ["label_definition_hash"])

    op.create_table(
        "tenant_supervised_upgrade_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("evaluation_id", sa.String(36), sa.ForeignKey("tenant_supervised_evaluations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False, server_default="promote_candidate"),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("model_change_id", sa.String(36), sa.ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("candidate_version", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('ready', 'draft_created')", name="ck_tenant_supervised_upgrade_status"),
        sa.CheckConstraint("decision = 'promote_candidate'", name="ck_tenant_supervised_upgrade_decision"),
        sa.ForeignKeyConstraint(["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"], name="fk_tenant_supervised_upgrade_tenant_policy", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "evaluation_id", name="uq_tenant_supervised_upgrade_evaluation"),
        sa.UniqueConstraint("model_change_id", name="uq_tenant_supervised_upgrade_model_change"),
    )
    for column in ("tenant_id", "policy_id", "evaluation_id", "status", "evidence_hash", "model_change_id", "created_at"):
        op.create_index(f"ix_tenant_supervised_upgrade_decisions_{column}", "tenant_supervised_upgrade_decisions", [column])
    op.create_index("ix_tenant_supervised_upgrade_policy_created", "tenant_supervised_upgrade_decisions", ["tenant_id", "policy_id", "created_at"])


def downgrade() -> None:
    op.drop_table("tenant_supervised_upgrade_decisions")

    op.drop_index("ix_tenant_supervised_evaluations_label_definition_hash", table_name="tenant_supervised_evaluations")
    op.drop_index("ix_tenant_supervised_evaluations_label_definition_id", table_name="tenant_supervised_evaluations")
    with op.batch_alter_table("tenant_supervised_evaluations") as batch:
        batch.drop_constraint("fk_tenant_supervised_evaluation_label_definition", type_="foreignkey")
        batch.drop_column("label_definition_hash")
        batch.drop_column("label_definition_version")
        batch.drop_column("label_definition_id")

    for table_name in ("tenant_outcome_labels", "tenant_outcome_import_batches"):
        op.drop_index(f"ix_{table_name}_label_definition_hash", table_name=table_name)
        op.drop_index(f"ix_{table_name}_label_definition_id", table_name=table_name)
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(f"fk_{table_name}_label_definition", type_="foreignkey")
            batch.drop_column("label_definition_hash")
            batch.drop_column("label_definition_version")
            batch.drop_column("label_definition_id")

    op.drop_table("tenant_outcome_label_definitions")
