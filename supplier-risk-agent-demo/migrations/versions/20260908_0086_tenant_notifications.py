"""isolate notification records by tenant

Revision ID: 20260908_0086
Revises: 20260908_0085
"""
from alembic import op
import sqlalchemy as sa


revision = "20260908_0086"
down_revision = "20260908_0085"
branch_labels = None
depends_on = None


LEGACY_TENANT_ID = "tenant-demo-hengxin"
PLATFORM_INTERNAL_TENANT_ID = "tenant-platform-internal"


def _backfill_notifications() -> None:
    connection = op.get_bind()
    invalid_case = connection.execute(
        sa.text(
            "SELECT n.id FROM notifications n "
            "LEFT JOIN approval_cases a ON a.case_id = n.case_id "
            "WHERE n.case_id IS NOT NULL AND (a.case_id IS NULL "
            "OR (n.counterparty_id IS NOT NULL AND a.counterparty_id <> n.counterparty_id)) LIMIT 1"
        )
    ).first()
    if invalid_case:
        raise RuntimeError(
            f"Cannot backfill notifications: record {invalid_case[0]!r} has no matching approval/counterparty"
        )

    connection.execute(
        sa.text(
            "UPDATE notifications SET tenant_id = ("
            "SELECT a.tenant_id FROM approval_cases a WHERE a.case_id = notifications.case_id"
            ") WHERE case_id IS NOT NULL AND tenant_id IS NULL"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE notifications SET tenant_id = ("
            "SELECT MIN(c.tenant_id) FROM counterparties c "
            "WHERE c.counterparty_id = notifications.counterparty_id"
            ") WHERE case_id IS NULL AND counterparty_id IS NOT NULL AND tenant_id IS NULL "
            "AND 1 = (SELECT COUNT(*) FROM counterparties c "
            "WHERE c.counterparty_id = notifications.counterparty_id)"
        )
    )
    ambiguous_counterparty = connection.execute(
        sa.text(
            "SELECT n.id FROM notifications n WHERE n.tenant_id IS NULL "
            "AND n.case_id IS NULL AND n.counterparty_id IS NOT NULL LIMIT 1"
        )
    ).first()
    if ambiguous_counterparty:
        raise RuntimeError(
            "Cannot backfill notifications: record "
            f"{ambiguous_counterparty[0]!r} has missing or ambiguous counterparty ownership"
        )

    connection.execute(
        sa.text(
            "UPDATE notifications SET tenant_id = :platform_tenant "
            "WHERE tenant_id IS NULL AND case_id IS NULL AND counterparty_id IS NULL "
            "AND category = 'sla_scan'"
        ),
        {"platform_tenant": PLATFORM_INTERNAL_TENANT_ID},
    )
    connection.execute(
        sa.text(
            "UPDATE notifications SET tenant_id = :legacy_tenant "
            "WHERE tenant_id IS NULL AND case_id IS NULL AND counterparty_id IS NULL"
        ),
        {"legacy_tenant": LEGACY_TENANT_ID},
    )

    unresolved = connection.execute(
        sa.text("SELECT id FROM notifications WHERE tenant_id IS NULL LIMIT 1")
    ).first()
    if unresolved:
        raise RuntimeError(
            f"Cannot backfill notifications: record {unresolved[0]!r} has no deterministic tenant ownership"
        )


def upgrade() -> None:
    op.add_column("notifications", sa.Column("tenant_id", sa.String(128), nullable=True))
    _backfill_notifications()

    with op.batch_alter_table("notifications") as batch:
        batch.drop_index("ix_notifications_role_status_created")
        batch.drop_index("ix_notifications_subject_status_created")
        batch.drop_constraint("uq_notifications_dedup_key", type_="unique")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key(
            "fk_notification_tenant",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_notification_tenant_case",
            "approval_cases",
            ["tenant_id", "case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_notification_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_notifications_tenant_dedup_key", ["tenant_id", "dedup_key"]
        )
        batch.create_index("ix_notifications_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_notifications_tenant_role_status_created",
            ["tenant_id", "recipient_role", "status", "created_at"],
        )
        batch.create_index(
            "ix_notifications_tenant_subject_status_created",
            ["tenant_id", "recipient_subject", "status", "created_at"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    reused = connection.execute(
        sa.text(
            "SELECT dedup_key FROM notifications GROUP BY dedup_key "
            "HAVING COUNT(DISTINCT tenant_id) > 1 LIMIT 1"
        )
    ).first()
    if reused:
        raise RuntimeError(
            "Cannot downgrade notifications: tenant-scoped dedup keys cannot be represented by the legacy global key"
        )

    with op.batch_alter_table("notifications") as batch:
        batch.drop_index("ix_notifications_tenant_subject_status_created")
        batch.drop_index("ix_notifications_tenant_role_status_created")
        batch.drop_index("ix_notifications_tenant_id")
        batch.drop_constraint("uq_notifications_tenant_dedup_key", type_="unique")
        batch.drop_constraint("fk_notification_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("fk_notification_tenant_case", type_="foreignkey")
        batch.drop_constraint("fk_notification_tenant", type_="foreignkey")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint("uq_notifications_dedup_key", ["dedup_key"])
        batch.create_index(
            "ix_notifications_role_status_created",
            ["recipient_role", "status", "created_at"],
        )
        batch.create_index(
            "ix_notifications_subject_status_created",
            ["recipient_subject", "status", "created_at"],
        )
