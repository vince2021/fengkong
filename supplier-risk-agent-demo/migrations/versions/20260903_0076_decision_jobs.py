"""add batch decision jobs and webhook delivery evidence

Revision ID: 20260903_0076
Revises: 20260903_0075
"""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0076"
down_revision = "20260903_0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("failures_json", sa.JSON(), nullable=False),
        sa.Column("callback_json", sa.JSON(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=True),
        sa.Column("evidence_hash", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "job_key", name="uq_decision_job_tenant_key"),
    )
    op.create_index("ix_decision_jobs_job_key", "decision_jobs", ["job_key"])
    op.create_index("ix_decision_jobs_request_hash", "decision_jobs", ["request_hash"])
    op.create_index("ix_decision_jobs_tenant_id", "decision_jobs", ["tenant_id"])
    op.create_index("ix_decision_jobs_client_id", "decision_jobs", ["client_id"])
    op.create_index("ix_decision_jobs_status", "decision_jobs", ["status"])
    op.create_index("ix_decision_jobs_result_hash", "decision_jobs", ["result_hash"])
    op.create_index("ix_decision_jobs_evidence_hash", "decision_jobs", ["evidence_hash"])
    op.create_index("ix_decision_jobs_created_by", "decision_jobs", ["created_by"])
    op.create_index("ix_decision_jobs_created_at", "decision_jobs", ["created_at"])
    op.create_index("ix_decision_jobs_tenant_status_created", "decision_jobs", ["tenant_id", "status", "created_at"])

    op.create_table(
        "decision_webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("decision_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("endpoint_url", sa.String(2000), nullable=False),
        sa.Column("secret_reference", sa.String(256), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("signature_timestamp", sa.String(32), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_history_json", sa.JSON(), nullable=False),
        sa.Column("manual_redelivery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_decision_webhook_deliveries_job_id", "decision_webhook_deliveries", ["job_id"])
    op.create_index("ix_decision_webhook_deliveries_event_type", "decision_webhook_deliveries", ["event_type"])
    op.create_index("ix_decision_webhook_deliveries_payload_hash", "decision_webhook_deliveries", ["payload_hash"])
    op.create_index("ix_decision_webhook_deliveries_status", "decision_webhook_deliveries", ["status"])
    op.create_index("ix_decision_webhook_deliveries_next_attempt_at", "decision_webhook_deliveries", ["next_attempt_at"])
    op.create_index("ix_decision_webhook_deliveries_created_at", "decision_webhook_deliveries", ["created_at"])
    op.create_index("ix_decision_webhooks_job_created", "decision_webhook_deliveries", ["job_id", "created_at"])
    op.create_index("ix_decision_webhooks_status_next", "decision_webhook_deliveries", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("decision_webhook_deliveries")
    op.drop_table("decision_jobs")
