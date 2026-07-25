"""Add monitoring runs, governance notifications, and recalibration links.

Revision ID: 20260716_0017
Revises: 20260716_0016
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0017"
down_revision = "20260716_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_monitoring_issues", sa.Column("linked_change_id", sa.String(length=36), nullable=True))
    with op.batch_alter_table("model_monitoring_issues") as batch_op:
        batch_op.create_foreign_key("fk_monitoring_issue_change", "model_changes", ["linked_change_id"], ["id"])
    op.create_index("ix_model_monitoring_issues_linked_change_id", "model_monitoring_issues", ["linked_change_id"])

    op.create_table(
        "model_monitoring_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_key", sa.String(length=256), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("as_of_period", sa.String(length=6), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("effective_source", sa.String(length=32), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("readiness_json", sa.JSON(), nullable=False),
        sa.Column("monitoring_json", sa.JSON(), nullable=False),
        sa.Column("issue_ids", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["run_key", "template_key", "model_version", "as_of_period", "trigger_type", "status", "evidence_level", "created_at"]:
        op.create_index(f"ix_model_monitoring_runs_{column}", "model_monitoring_runs", [column], unique=column == "run_key")
    op.create_index("ix_monitoring_runs_template_period", "model_monitoring_runs", ["template_key", "as_of_period", "created_at"])

    op.create_table(
        "model_governance_notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("monitoring_run_id", sa.String(length=36), nullable=False),
        sa.Column("monitoring_issue_id", sa.String(length=36), nullable=True),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("recipient_role", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unread"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_by", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["monitoring_run_id"], ["model_monitoring_runs.id"]),
        sa.ForeignKeyConstraint(["monitoring_issue_id"], ["model_monitoring_issues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="uq_model_governance_notification_dedup"),
    )
    for column in ["monitoring_run_id", "monitoring_issue_id", "template_key", "recipient_role", "severity", "status", "created_at"]:
        op.create_index(f"ix_model_governance_notifications_{column}", "model_governance_notifications", [column])
    op.create_index("ix_governance_notifications_role_status_created", "model_governance_notifications", ["recipient_role", "status", "created_at"])


def downgrade() -> None:
    op.drop_table("model_governance_notifications")
    op.drop_table("model_monitoring_runs")
    op.drop_index("ix_model_monitoring_issues_linked_change_id", table_name="model_monitoring_issues")
    with op.batch_alter_table("model_monitoring_issues") as batch_op:
        batch_op.drop_constraint("fk_monitoring_issue_change", type_="foreignkey")
        batch_op.drop_column("linked_change_id")
