"""isolate credit facilities and post-credit records by tenant

Revision ID: 20260908_0083
Revises: 20260907_0082
"""
from alembic import op
import sqlalchemy as sa


revision = "20260908_0083"
down_revision = "20260907_0082"
branch_labels = None
depends_on = None


CHILD_TABLES = (
    "credit_usage_transactions",
    "facility_alerts",
    "risk_events",
    "facility_control_conditions",
    "facility_control_extensions",
)


def _backfill_facilities() -> None:
    connection = op.get_bind()
    invalid = connection.execute(
        sa.text(
            "SELECT f.id, f.case_id, f.counterparty_id, a.tenant_id, a.counterparty_id "
            "FROM credit_facilities f LEFT JOIN approval_cases a ON a.case_id = f.case_id "
            "WHERE a.case_id IS NULL OR a.counterparty_id <> f.counterparty_id"
        )
    ).first()
    if invalid:
        raise RuntimeError(
            f"Cannot backfill credit_facilities: facility {invalid[0]!r} has no matching tenant approval/counterparty"
        )
    connection.execute(
        sa.text(
            "UPDATE credit_facilities SET tenant_id = ("
            "SELECT a.tenant_id FROM approval_cases a WHERE a.case_id = credit_facilities.case_id"
            ") WHERE tenant_id IS NULL"
        )
    )


def _backfill_children() -> None:
    connection = op.get_bind()
    for table_name in CHILD_TABLES:
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET tenant_id = ("
                f"SELECT f.tenant_id FROM credit_facilities f WHERE f.id = {table_name}.facility_id"
                f") WHERE tenant_id IS NULL"
            )
        )
        missing = connection.execute(
            sa.text(f"SELECT id FROM {table_name} WHERE tenant_id IS NULL LIMIT 1")
        ).first()
        if missing:
            raise RuntimeError(
                f"Cannot backfill {table_name}: record {missing[0]!r} has no matching credit facility"
            )


def _validate_domain_links() -> None:
    connection = op.get_bind()
    checks = (
        (
            "facility_control_conditions",
            "SELECT c.id FROM facility_control_conditions c "
            "LEFT JOIN approval_cases a ON a.case_id = c.source_case_id AND a.tenant_id = c.tenant_id "
            "WHERE a.case_id IS NULL LIMIT 1",
            "source approval belongs to another tenant",
        ),
        (
            "facility_control_conditions",
            "SELECT c.id FROM facility_control_conditions c "
            "LEFT JOIN facility_alerts a ON a.id = c.linked_alert_id AND a.tenant_id = c.tenant_id "
            "WHERE c.linked_alert_id IS NOT NULL AND a.id IS NULL LIMIT 1",
            "linked alert belongs to another tenant",
        ),
        (
            "facility_control_extensions",
            "SELECT e.id FROM facility_control_extensions e "
            "LEFT JOIN facility_control_conditions c ON c.id = e.condition_id AND c.tenant_id = e.tenant_id "
            "WHERE c.id IS NULL LIMIT 1",
            "control condition belongs to another tenant",
        ),
        (
            "risk_events",
            "SELECT e.id FROM risk_events e "
            "LEFT JOIN facility_alerts a ON a.id = e.linked_alert_id AND a.tenant_id = e.tenant_id "
            "WHERE e.linked_alert_id IS NOT NULL AND a.id IS NULL LIMIT 1",
            "linked alert belongs to another tenant",
        ),
    )
    for table_name, query, reason in checks:
        invalid = connection.execute(sa.text(query)).first()
        if invalid:
            raise RuntimeError(f"Cannot isolate {table_name}: record {invalid[0]!r} {reason}")


def _validate_downgrade_uniqueness() -> None:
    connection = op.get_bind()
    checks = (
        (
            "credit_usage_transactions",
            "transaction_ref",
            "SELECT transaction_ref FROM credit_usage_transactions "
            "GROUP BY transaction_ref HAVING COUNT(*) > 1 LIMIT 1",
        ),
        (
            "facility_alerts",
            "dedup_key",
            "SELECT dedup_key FROM facility_alerts "
            "GROUP BY dedup_key HAVING COUNT(*) > 1 LIMIT 1",
        ),
        (
            "risk_events",
            "source + external_event_id",
            "SELECT source || ':' || external_event_id FROM risk_events "
            "GROUP BY source, external_event_id HAVING COUNT(*) > 1 LIMIT 1",
        ),
    )
    for table_name, key_name, query in checks:
        duplicate = connection.execute(sa.text(query)).first()
        if duplicate:
            raise RuntimeError(
                f"Cannot downgrade {table_name}: tenant-scoped {key_name} {duplicate[0]!r} "
                "is duplicated and cannot be represented by the previous global uniqueness rule"
            )


def upgrade() -> None:
    op.add_column("credit_facilities", sa.Column("tenant_id", sa.String(128), nullable=True))
    for table_name in CHILD_TABLES:
        op.add_column(table_name, sa.Column("tenant_id", sa.String(128), nullable=True))

    _backfill_facilities()
    _backfill_children()
    _validate_domain_links()

    with op.batch_alter_table("approval_cases") as batch:
        batch.create_unique_constraint("uq_approval_case_tenant_id", ["tenant_id", "case_id"])

    with op.batch_alter_table("credit_facilities") as batch:
        batch.drop_index("ix_credit_facilities_status_expiry")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_credit_facility_tenant_id", ["tenant_id", "id"])
        batch.create_foreign_key(
            "fk_credit_facility_tenant_case",
            "approval_cases",
            ["tenant_id", "case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_credit_facility_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_credit_facility_tenant_supersedes",
            "credit_facilities",
            ["tenant_id", "supersedes_facility_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_credit_facilities_tenant_id", ["tenant_id"])
        batch.create_index("ix_credit_facilities_tenant_status_expiry", ["tenant_id", "status", "expires_at"])
        batch.create_index(
            "ix_credit_facilities_tenant_counterparty_created",
            ["tenant_id", "counterparty_id", "created_at"],
        )

    with op.batch_alter_table("facility_alerts") as batch:
        batch.drop_constraint("uq_facility_alert_dedup", type_="unique")
        batch.drop_index("ix_facility_alerts_status_severity_created")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_facility_alert_tenant_id", ["tenant_id", "id"])
        batch.create_unique_constraint("uq_facility_alert_dedup", ["tenant_id", "dedup_key"])
        batch.create_foreign_key(
            "fk_facility_alert_tenant_facility",
            "credit_facilities",
            ["tenant_id", "facility_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_facility_alerts_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_facility_alerts_tenant_status_severity_created",
            ["tenant_id", "status", "severity", "created_at"],
        )

    with op.batch_alter_table("facility_control_conditions") as batch:
        batch.drop_constraint("uq_facility_control_condition_source_sequence", type_="unique")
        batch.drop_index("ix_facility_control_conditions_facility_status_due")
        batch.drop_index("ix_facility_control_conditions_status_due")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_facility_control_condition_tenant_id", ["tenant_id", "id"])
        batch.create_unique_constraint(
            "uq_facility_control_condition_source_sequence",
            ["tenant_id", "source_case_id", "sequence"],
        )
        batch.create_foreign_key(
            "fk_facility_control_condition_tenant_facility",
            "credit_facilities",
            ["tenant_id", "facility_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_facility_control_condition_tenant_case",
            "approval_cases",
            ["tenant_id", "source_case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_facility_control_condition_tenant_alert",
            "facility_alerts",
            ["tenant_id", "linked_alert_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_facility_control_conditions_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_facility_control_conditions_tenant_facility_status_due",
            ["tenant_id", "facility_id", "status", "due_at"],
        )
        batch.create_index(
            "ix_facility_control_conditions_tenant_status_due",
            ["tenant_id", "status", "due_at"],
        )

    with op.batch_alter_table("facility_control_extensions") as batch:
        batch.drop_index("uq_facility_control_extensions_pending")
        batch.drop_index("ix_facility_control_extensions_condition_requested")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key(
            "fk_facility_control_extension_tenant_condition",
            "facility_control_conditions",
            ["tenant_id", "condition_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_facility_control_extension_tenant_facility",
            "credit_facilities",
            ["tenant_id", "facility_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_facility_control_extensions_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_facility_control_extensions_tenant_condition_requested",
            ["tenant_id", "condition_id", "requested_at"],
        )
        batch.create_index(
            "uq_facility_control_extensions_pending",
            ["tenant_id", "condition_id"],
            unique=True,
            sqlite_where=sa.text("status = 'pending'"),
            postgresql_where=sa.text("status = 'pending'"),
        )

    with op.batch_alter_table("credit_usage_transactions") as batch:
        batch.drop_index("ix_credit_usage_transactions_transaction_ref")
        batch.drop_index("ix_credit_usage_facility_occurred")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint(
            "uq_credit_usage_tenant_transaction_ref", ["tenant_id", "transaction_ref"]
        )
        batch.create_foreign_key(
            "fk_credit_usage_tenant_facility",
            "credit_facilities",
            ["tenant_id", "facility_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_credit_usage_transactions_tenant_id", ["tenant_id"])
        batch.create_index("ix_credit_usage_transactions_transaction_ref", ["transaction_ref"])
        batch.create_index(
            "ix_credit_usage_tenant_facility_occurred", ["tenant_id", "facility_id", "occurred_at"]
        )

    with op.batch_alter_table("risk_events") as batch:
        batch.drop_index("uq_risk_events_source_external_id")
        batch.drop_index("ix_risk_events_facility_occurred")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key(
            "fk_risk_event_tenant_facility",
            "credit_facilities",
            ["tenant_id", "facility_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_risk_event_tenant_alert",
            "facility_alerts",
            ["tenant_id", "linked_alert_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_risk_events_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_risk_events_tenant_facility_occurred", ["tenant_id", "facility_id", "occurred_at"]
        )
        batch.create_index(
            "uq_risk_events_source_external_id",
            ["tenant_id", "source", "external_event_id"],
            unique=True,
        )


def downgrade() -> None:
    _validate_downgrade_uniqueness()

    with op.batch_alter_table("risk_events") as batch:
        batch.drop_index("uq_risk_events_source_external_id")
        batch.drop_index("ix_risk_events_tenant_facility_occurred")
        batch.drop_index("ix_risk_events_tenant_id")
        batch.drop_constraint("fk_risk_event_tenant_alert", type_="foreignkey")
        batch.drop_constraint("fk_risk_event_tenant_facility", type_="foreignkey")
        batch.drop_column("tenant_id")
        batch.create_index("ix_risk_events_facility_occurred", ["facility_id", "occurred_at"])
        batch.create_index("uq_risk_events_source_external_id", ["source", "external_event_id"], unique=True)

    with op.batch_alter_table("credit_usage_transactions") as batch:
        batch.drop_index("ix_credit_usage_tenant_facility_occurred")
        batch.drop_index("ix_credit_usage_transactions_transaction_ref")
        batch.drop_index("ix_credit_usage_transactions_tenant_id")
        batch.drop_constraint("fk_credit_usage_tenant_facility", type_="foreignkey")
        batch.drop_constraint("uq_credit_usage_tenant_transaction_ref", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_index("ix_credit_usage_facility_occurred", ["facility_id", "occurred_at"])
        batch.create_index("ix_credit_usage_transactions_transaction_ref", ["transaction_ref"], unique=True)

    with op.batch_alter_table("facility_control_extensions") as batch:
        batch.drop_index("uq_facility_control_extensions_pending")
        batch.drop_index("ix_facility_control_extensions_tenant_condition_requested")
        batch.drop_index("ix_facility_control_extensions_tenant_id")
        batch.drop_constraint("fk_facility_control_extension_tenant_facility", type_="foreignkey")
        batch.drop_constraint("fk_facility_control_extension_tenant_condition", type_="foreignkey")
        batch.drop_column("tenant_id")
        batch.create_index(
            "ix_facility_control_extensions_condition_requested", ["condition_id", "requested_at"]
        )
        batch.create_index(
            "uq_facility_control_extensions_pending",
            ["condition_id"],
            unique=True,
            sqlite_where=sa.text("status = 'pending'"),
            postgresql_where=sa.text("status = 'pending'"),
        )

    with op.batch_alter_table("facility_control_conditions") as batch:
        batch.drop_index("ix_facility_control_conditions_tenant_status_due")
        batch.drop_index("ix_facility_control_conditions_tenant_facility_status_due")
        batch.drop_index("ix_facility_control_conditions_tenant_id")
        batch.drop_constraint("fk_facility_control_condition_tenant_alert", type_="foreignkey")
        batch.drop_constraint("fk_facility_control_condition_tenant_case", type_="foreignkey")
        batch.drop_constraint("fk_facility_control_condition_tenant_facility", type_="foreignkey")
        batch.drop_constraint("uq_facility_control_condition_source_sequence", type_="unique")
        batch.drop_constraint("uq_facility_control_condition_tenant_id", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint(
            "uq_facility_control_condition_source_sequence", ["source_case_id", "sequence"]
        )
        batch.create_index(
            "ix_facility_control_conditions_facility_status_due", ["facility_id", "status", "due_at"]
        )
        batch.create_index("ix_facility_control_conditions_status_due", ["status", "due_at"])

    with op.batch_alter_table("facility_alerts") as batch:
        batch.drop_index("ix_facility_alerts_tenant_status_severity_created")
        batch.drop_index("ix_facility_alerts_tenant_id")
        batch.drop_constraint("fk_facility_alert_tenant_facility", type_="foreignkey")
        batch.drop_constraint("uq_facility_alert_dedup", type_="unique")
        batch.drop_constraint("uq_facility_alert_tenant_id", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint("uq_facility_alert_dedup", ["dedup_key"])
        batch.create_index(
            "ix_facility_alerts_status_severity_created", ["status", "severity", "created_at"]
        )

    with op.batch_alter_table("credit_facilities") as batch:
        batch.drop_index("ix_credit_facilities_tenant_counterparty_created")
        batch.drop_index("ix_credit_facilities_tenant_status_expiry")
        batch.drop_index("ix_credit_facilities_tenant_id")
        batch.drop_constraint("fk_credit_facility_tenant_supersedes", type_="foreignkey")
        batch.drop_constraint("fk_credit_facility_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("fk_credit_facility_tenant_case", type_="foreignkey")
        batch.drop_constraint("uq_credit_facility_tenant_id", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_index("ix_credit_facilities_status_expiry", ["status", "expires_at"])

    with op.batch_alter_table("approval_cases") as batch:
        batch.drop_constraint("uq_approval_case_tenant_id", type_="unique")
