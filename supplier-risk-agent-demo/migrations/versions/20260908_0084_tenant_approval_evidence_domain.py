"""isolate approval evidence records by tenant

Revision ID: 20260908_0084
Revises: 20260908_0083
"""
from alembic import op
import sqlalchemy as sa


revision = "20260908_0084"
down_revision = "20260908_0083"
branch_labels = None
depends_on = None


LEGACY_TENANT_ID = "tenant-demo-hengxin"
CASE_OR_COUNTERPARTY_TABLES = ("documents", "rating_runs")


def _backfill_case_or_counterparty_table(table_name: str) -> None:
    connection = op.get_bind()
    invalid_case = connection.execute(
        sa.text(
            f"SELECT r.id FROM {table_name} r "
            "LEFT JOIN approval_cases a ON a.case_id = r.case_id "
            "WHERE r.case_id IS NOT NULL "
            "AND (a.case_id IS NULL OR a.counterparty_id <> r.counterparty_id) LIMIT 1"
        )
    ).first()
    if invalid_case:
        raise RuntimeError(
            f"Cannot backfill {table_name}: record {invalid_case[0]!r} has no matching approval/counterparty"
        )
    connection.execute(
        sa.text(
            f"UPDATE {table_name} SET tenant_id = ("
            f"SELECT a.tenant_id FROM approval_cases a WHERE a.case_id = {table_name}.case_id"
            ") WHERE case_id IS NOT NULL AND tenant_id IS NULL"
        )
    )
    connection.execute(
        sa.text(
            f"UPDATE {table_name} SET tenant_id = :legacy_tenant "
            "WHERE case_id IS NULL AND tenant_id IS NULL AND EXISTS ("
            f"SELECT 1 FROM counterparties c WHERE c.counterparty_id = {table_name}.counterparty_id "
            "AND c.tenant_id = :legacy_tenant)"
        ),
        {"legacy_tenant": LEGACY_TENANT_ID},
    )
    connection.execute(
        sa.text(
            f"UPDATE {table_name} SET tenant_id = ("
            f"SELECT MIN(c.tenant_id) FROM counterparties c WHERE c.counterparty_id = {table_name}.counterparty_id"
            ") WHERE case_id IS NULL AND tenant_id IS NULL AND 1 = ("
            f"SELECT COUNT(*) FROM counterparties c WHERE c.counterparty_id = {table_name}.counterparty_id)"
        )
    )
    unresolved = connection.execute(
        sa.text(f"SELECT id FROM {table_name} WHERE tenant_id IS NULL LIMIT 1")
    ).first()
    if unresolved:
        raise RuntimeError(
            f"Cannot backfill {table_name}: record {unresolved[0]!r} has missing or ambiguous counterparty ownership"
        )


def _backfill_reports() -> None:
    connection = op.get_bind()
    invalid = connection.execute(
        sa.text(
            "SELECT r.id FROM credit_reports r "
            "LEFT JOIN approval_cases a ON a.case_id = r.case_id "
            "WHERE a.case_id IS NULL OR a.counterparty_id <> r.counterparty_id LIMIT 1"
        )
    ).first()
    if invalid:
        raise RuntimeError(
            f"Cannot backfill credit_reports: report {invalid[0]!r} has no matching approval/counterparty"
        )
    connection.execute(
        sa.text(
            "UPDATE credit_reports SET tenant_id = ("
            "SELECT a.tenant_id FROM approval_cases a WHERE a.case_id = credit_reports.case_id"
            ") WHERE tenant_id IS NULL"
        )
    )


def _backfill_corrections() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE document_corrections SET tenant_id = ("
            "SELECT d.tenant_id FROM documents d WHERE d.id = document_corrections.original_document_id"
            ") WHERE tenant_id IS NULL"
        )
    )
    invalid = connection.execute(
        sa.text(
            "SELECT c.id FROM document_corrections c "
            "LEFT JOIN documents original ON original.id = c.original_document_id "
            "LEFT JOIN documents current ON current.id = c.current_document_id "
            "LEFT JOIN approval_cases a ON a.case_id = c.case_id "
            "WHERE original.id IS NULL OR current.id IS NULL OR c.tenant_id IS NULL "
            "OR original.tenant_id <> c.tenant_id OR current.tenant_id <> c.tenant_id "
            "OR original.counterparty_id <> c.counterparty_id "
            "OR current.counterparty_id <> c.counterparty_id "
            "OR (c.case_id IS NOT NULL AND (a.case_id IS NULL OR a.tenant_id <> c.tenant_id "
            "OR a.counterparty_id <> c.counterparty_id)) LIMIT 1"
        )
    ).first()
    if invalid:
        raise RuntimeError(
            f"Cannot backfill document_corrections: correction {invalid[0]!r} has inconsistent document or approval ownership"
        )


def upgrade() -> None:
    for table_name in (*CASE_OR_COUNTERPARTY_TABLES, "credit_reports", "document_corrections"):
        op.add_column(table_name, sa.Column("tenant_id", sa.String(128), nullable=True))

    for table_name in CASE_OR_COUNTERPARTY_TABLES:
        _backfill_case_or_counterparty_table(table_name)
    _backfill_reports()
    _backfill_corrections()

    with op.batch_alter_table("rating_runs") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_rating_run_tenant_id", ["tenant_id", "id"])
        batch.create_foreign_key(
            "fk_rating_run_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_rating_run_tenant_case",
            "approval_cases",
            ["tenant_id", "case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_rating_runs_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_rating_runs_tenant_counterparty_created",
            ["tenant_id", "counterparty_id", "created_at"],
        )
        batch.create_index(
            "ix_rating_runs_tenant_case_created",
            ["tenant_id", "case_id", "created_at"],
        )

    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_counterparty_case")
        batch.drop_constraint("uq_documents_case_source_document", type_="unique")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_document_tenant_id", ["tenant_id", "id"])
        batch.create_unique_constraint(
            "uq_documents_case_source_document",
            ["tenant_id", "case_id", "source_document_id"],
        )
        batch.create_foreign_key(
            "fk_document_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_tenant_case",
            "approval_cases",
            ["tenant_id", "case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_tenant_source",
            "documents",
            ["tenant_id", "source_document_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_documents_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_documents_tenant_counterparty_case",
            ["tenant_id", "counterparty_id", "case_id", "created_at"],
        )

    with op.batch_alter_table("document_corrections") as batch:
        batch.drop_index("ix_document_corrections_scope_status")
        batch.drop_index("ix_document_corrections_sla_status")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key(
            "fk_document_correction_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_correction_tenant_case",
            "approval_cases",
            ["tenant_id", "case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_correction_tenant_original",
            "documents",
            ["tenant_id", "original_document_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_correction_tenant_current",
            "documents",
            ["tenant_id", "current_document_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_document_corrections_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_document_corrections_tenant_scope_status",
            ["tenant_id", "counterparty_id", "case_id", "status", "created_at"],
        )
        batch.create_index(
            "ix_document_corrections_tenant_sla_status",
            ["tenant_id", "status", "sla_due_at"],
        )

    with op.batch_alter_table("credit_reports") as batch:
        batch.drop_index("ix_credit_reports_case_version")
        batch.drop_constraint("uq_credit_report_case_snapshot", type_="unique")
        batch.drop_constraint("uq_credit_report_case_version", type_="unique")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint(
            "uq_credit_report_case_snapshot",
            ["tenant_id", "case_id", "snapshot_hash"],
        )
        batch.create_unique_constraint(
            "uq_credit_report_case_version",
            ["tenant_id", "case_id", "report_version"],
        )
        batch.create_foreign_key(
            "fk_credit_report_tenant_case",
            "approval_cases",
            ["tenant_id", "case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_credit_report_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_credit_reports_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_credit_reports_tenant_case_version",
            ["tenant_id", "case_id", "report_version"],
        )
        batch.create_index(
            "ix_credit_reports_tenant_counterparty_created",
            ["tenant_id", "counterparty_id", "created_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("credit_reports") as batch:
        batch.drop_index("ix_credit_reports_tenant_counterparty_created")
        batch.drop_index("ix_credit_reports_tenant_case_version")
        batch.drop_index("ix_credit_reports_tenant_id")
        batch.drop_constraint("fk_credit_report_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("fk_credit_report_tenant_case", type_="foreignkey")
        batch.drop_constraint("uq_credit_report_case_version", type_="unique")
        batch.drop_constraint("uq_credit_report_case_snapshot", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint(
            "uq_credit_report_case_snapshot", ["case_id", "snapshot_hash"]
        )
        batch.create_unique_constraint(
            "uq_credit_report_case_version", ["case_id", "report_version"]
        )
        batch.create_index("ix_credit_reports_case_version", ["case_id", "report_version"])

    with op.batch_alter_table("document_corrections") as batch:
        batch.drop_index("ix_document_corrections_tenant_sla_status")
        batch.drop_index("ix_document_corrections_tenant_scope_status")
        batch.drop_index("ix_document_corrections_tenant_id")
        batch.drop_constraint("fk_document_correction_tenant_current", type_="foreignkey")
        batch.drop_constraint("fk_document_correction_tenant_original", type_="foreignkey")
        batch.drop_constraint("fk_document_correction_tenant_case", type_="foreignkey")
        batch.drop_constraint("fk_document_correction_tenant_counterparty", type_="foreignkey")
        batch.drop_column("tenant_id")
        batch.create_index(
            "ix_document_corrections_scope_status",
            ["counterparty_id", "case_id", "status", "created_at"],
        )
        batch.create_index("ix_document_corrections_sla_status", ["status", "sla_due_at"])

    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_tenant_counterparty_case")
        batch.drop_index("ix_documents_tenant_id")
        batch.drop_constraint("fk_document_tenant_source", type_="foreignkey")
        batch.drop_constraint("fk_document_tenant_case", type_="foreignkey")
        batch.drop_constraint("fk_document_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("uq_documents_case_source_document", type_="unique")
        batch.drop_constraint("uq_document_tenant_id", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint(
            "uq_documents_case_source_document", ["case_id", "source_document_id"]
        )
        batch.create_index(
            "ix_documents_counterparty_case", ["counterparty_id", "case_id", "created_at"]
        )

    with op.batch_alter_table("rating_runs") as batch:
        batch.drop_index("ix_rating_runs_tenant_case_created")
        batch.drop_index("ix_rating_runs_tenant_counterparty_created")
        batch.drop_index("ix_rating_runs_tenant_id")
        batch.drop_constraint("fk_rating_run_tenant_case", type_="foreignkey")
        batch.drop_constraint("fk_rating_run_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("uq_rating_run_tenant_id", type_="unique")
        batch.drop_column("tenant_id")
