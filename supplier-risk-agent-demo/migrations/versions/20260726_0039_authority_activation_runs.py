"""persist authority policy activation runs and generic alerts

Revision ID: 20260726_0039
Revises: 20260726_0038
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0039"
down_revision = "20260726_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "authority_policy_activation_runs" not in inspector.get_table_names():
        op.create_table(
            "authority_policy_activation_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("run_key", sa.String(length=128), nullable=False),
            sa.Column("trigger_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("scheduled_policy_id", sa.String(length=36), nullable=True),
            sa.Column("scheduled_policy_version", sa.String(length=128), nullable=True),
            sa.Column("scheduled_effective_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("active_policy_before", sa.String(length=128), nullable=False),
            sa.Column("active_policy_after", sa.String(length=128), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("actor_subject", sa.String(length=128), nullable=False),
            sa.Column("actor_name", sa.String(length=128), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scheduled_policy_id"], ["credit_authority_policies.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_key", name="uq_authority_activation_run_key"),
        )
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("authority_policy_activation_runs")}
    index_specs = {
        "ix_authority_activation_runs_status_created": ["status", "created_at"],
        "ix_authority_policy_activation_runs_run_key": ["run_key"],
        "ix_authority_policy_activation_runs_trigger_type": ["trigger_type"],
        "ix_authority_policy_activation_runs_status": ["status"],
        "ix_authority_policy_activation_runs_scheduled_policy_id": ["scheduled_policy_id"],
        "ix_authority_policy_activation_runs_created_at": ["created_at"],
    }
    for name, columns in index_specs.items():
        if name not in indexes:
            op.create_index(name, "authority_policy_activation_runs", columns)
    notification_columns = {
        column["name"]: column for column in inspector.get_columns("notifications")
    }
    if not notification_columns["case_id"]["nullable"] or not notification_columns["counterparty_id"]["nullable"]:
        with op.batch_alter_table("notifications") as batch:
            if not notification_columns["case_id"]["nullable"]:
                batch.alter_column("case_id", existing_type=sa.String(length=128), nullable=True)
            if not notification_columns["counterparty_id"]["nullable"]:
                batch.alter_column("counterparty_id", existing_type=sa.String(length=128), nullable=True)


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM notifications "
            "WHERE category = 'authority_policy' AND (case_id IS NULL OR counterparty_id IS NULL)"
        )
    )
    with op.batch_alter_table("notifications") as batch:
        batch.alter_column("counterparty_id", existing_type=sa.String(length=128), nullable=False)
        batch.alter_column("case_id", existing_type=sa.String(length=128), nullable=False)
    op.drop_table("authority_policy_activation_runs")
