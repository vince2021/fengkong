"""Add observed model outcomes and monitoring issue workflow.

Revision ID: 20260715_0015
Revises: 20260714_0014
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0015"
down_revision = "20260714_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_observation_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("population_period", sa.String(length=16), nullable=False),
        sa.Column("predicted_score", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("predicted_pd", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("observed_event", sa.Boolean(), nullable=False),
        sa.Column("prediction_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_observation_id", name="uq_model_outcome_source_external_id"),
    )
    for column in ["external_observation_id", "source", "template_key", "model_version", "counterparty_id", "population_period", "observed_event", "prediction_at", "observation_end", "created_at"]:
        op.create_index(f"ix_model_outcomes_{column}", "model_outcomes", [column])
    op.create_index("ix_model_outcomes_template_period", "model_outcomes", ["template_key", "population_period", "created_at"])

    op.create_table(
        "model_monitoring_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("metric_label", sa.String(length=128), nullable=False),
        sa.Column("metric_value", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("metric_status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("owner", sa.String(length=128), nullable=True),
        sa.Column("remediation_plan", sa.Text(), nullable=True),
        sa.Column("remediation_result", sa.Text(), nullable=True),
        sa.Column("remediated_by", sa.String(length=128), nullable=True),
        sa.Column("revalidation_conclusion", sa.Text(), nullable=True),
        sa.Column("revalidated_by", sa.String(length=128), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="uq_monitoring_issue_dedup"),
    )
    for column in ["template_key", "evidence_level", "metric_key", "severity", "status", "due_at", "created_at"]:
        op.create_index(f"ix_model_monitoring_issues_{column}", "model_monitoring_issues", [column])
    op.create_index("ix_monitoring_issues_template_status_due", "model_monitoring_issues", ["template_key", "status", "due_at"])


def downgrade() -> None:
    op.drop_table("model_monitoring_issues")
    op.drop_table("model_outcomes")
