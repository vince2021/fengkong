"""isolate enterprise data governance and remaining decision evidence by tenant

Revision ID: 20260908_0085
Revises: 20260908_0084
"""
from alembic import op
import sqlalchemy as sa


revision = "20260908_0085"
down_revision = "20260908_0084"
branch_labels = None
depends_on = None


LEGACY_TENANT_ID = "tenant-demo-hengxin"


def _backfill_by_counterparty(table_name: str) -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"UPDATE {table_name} SET tenant_id = :legacy_tenant "
            "WHERE tenant_id IS NULL AND EXISTS ("
            f"SELECT 1 FROM counterparties c WHERE c.counterparty_id = {table_name}.counterparty_id "
            "AND c.tenant_id = :legacy_tenant)"
        ),
        {"legacy_tenant": LEGACY_TENANT_ID},
    )
    connection.execute(
        sa.text(
            f"UPDATE {table_name} SET tenant_id = ("
            f"SELECT MIN(c.tenant_id) FROM counterparties c WHERE c.counterparty_id = {table_name}.counterparty_id"
            ") WHERE tenant_id IS NULL AND 1 = ("
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


def _backfill_fields() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE enterprise_data_fields SET tenant_id = ("
            "SELECT i.tenant_id FROM enterprise_data_imports i "
            "WHERE i.id = enterprise_data_fields.import_id) WHERE tenant_id IS NULL"
        )
    )
    invalid = connection.execute(
        sa.text(
            "SELECT f.id FROM enterprise_data_fields f "
            "LEFT JOIN enterprise_data_imports i ON i.id = f.import_id "
            "WHERE i.id IS NULL OR f.tenant_id IS NULL "
            "OR i.tenant_id <> f.tenant_id OR i.counterparty_id <> f.counterparty_id LIMIT 1"
        )
    ).first()
    if invalid:
        raise RuntimeError(
            f"Cannot backfill enterprise_data_fields: field {invalid[0]!r} has inconsistent import ownership"
        )


def _backfill_resolutions() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE enterprise_data_resolutions SET tenant_id = ("
            "SELECT f.tenant_id FROM enterprise_data_fields f "
            "WHERE f.id = enterprise_data_resolutions.selected_field_id) WHERE tenant_id IS NULL"
        )
    )
    invalid = connection.execute(
        sa.text(
            "SELECT r.id FROM enterprise_data_resolutions r "
            "LEFT JOIN enterprise_data_fields f ON f.id = r.selected_field_id "
            "WHERE f.id IS NULL OR r.tenant_id IS NULL "
            "OR f.tenant_id <> r.tenant_id OR f.counterparty_id <> r.counterparty_id "
            "OR f.field_path <> r.field_path LIMIT 1"
        )
    ).first()
    if invalid:
        raise RuntimeError(
            f"Cannot backfill enterprise_data_resolutions: resolution {invalid[0]!r} has inconsistent selected field ownership"
        )


def _backfill_variances() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE decision_variances SET tenant_id = ("
            "SELECT a.tenant_id FROM approval_cases a WHERE a.case_id = decision_variances.case_id"
            ") WHERE tenant_id IS NULL"
        )
    )
    invalid = connection.execute(
        sa.text(
            "SELECT v.id FROM decision_variances v "
            "LEFT JOIN approval_cases a ON a.case_id = v.case_id "
            "LEFT JOIN rating_runs r ON r.id = v.rating_run_id "
            "WHERE a.case_id IS NULL OR v.tenant_id IS NULL "
            "OR a.tenant_id <> v.tenant_id OR a.counterparty_id <> v.counterparty_id "
            "OR (v.rating_run_id IS NOT NULL AND (r.id IS NULL OR r.tenant_id <> v.tenant_id "
            "OR r.counterparty_id <> v.counterparty_id)) LIMIT 1"
        )
    ).first()
    if invalid:
        raise RuntimeError(
            f"Cannot backfill decision_variances: variance {invalid[0]!r} has inconsistent approval or rating ownership"
        )


def _reject_unrepresentable_downgrade() -> None:
    connection = op.get_bind()
    for table_name, key_name in (
        ("enterprise_data_imports", "import_key"),
        ("portfolio_rating_batches", "batch_key"),
    ):
        duplicate = connection.execute(
            sa.text(
                f"SELECT {key_name} FROM {table_name} GROUP BY {key_name} "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicate:
            raise RuntimeError(
                f"Cannot downgrade {table_name}: tenant-scoped {key_name} {duplicate[0]!r} cannot be represented by the legacy global unique key"
            )


def upgrade() -> None:
    for table_name in (
        "enterprise_data_imports",
        "enterprise_data_fields",
        "enterprise_data_resolutions",
        "portfolio_rating_batches",
        "decision_variances",
    ):
        op.add_column(table_name, sa.Column("tenant_id", sa.String(128), nullable=True))

    _backfill_by_counterparty("enterprise_data_imports")
    _backfill_fields()
    _backfill_resolutions()
    op.get_bind().execute(
        sa.text("UPDATE portfolio_rating_batches SET tenant_id = :tenant_id WHERE tenant_id IS NULL"),
        {"tenant_id": LEGACY_TENANT_ID},
    )
    _backfill_variances()

    with op.batch_alter_table("enterprise_data_imports") as batch:
        batch.drop_index("ix_enterprise_data_imports_import_key")
        batch.drop_index("ix_enterprise_data_imports_counterparty_created")
        batch.drop_constraint("uq_enterprise_data_import_key", type_="unique")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_enterprise_data_import_tenant_id", ["tenant_id", "id"])
        batch.create_unique_constraint("uq_enterprise_data_import_tenant_key", ["tenant_id", "import_key"])
        batch.create_foreign_key(
            "fk_enterprise_data_import_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_enterprise_data_imports_tenant_id", ["tenant_id"])
        batch.create_index("ix_enterprise_data_imports_import_key", ["import_key"])
        batch.create_index(
            "ix_enterprise_data_imports_tenant_counterparty_created",
            ["tenant_id", "counterparty_id", "created_at"],
        )

    with op.batch_alter_table("enterprise_data_fields") as batch:
        batch.drop_index("ix_enterprise_data_fields_counterparty_path")
        batch.drop_constraint("uq_enterprise_data_field_import_path", type_="unique")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_enterprise_data_field_tenant_id", ["tenant_id", "id"])
        batch.create_unique_constraint(
            "uq_enterprise_data_field_tenant_import_path",
            ["tenant_id", "import_id", "field_path"],
        )
        batch.create_foreign_key(
            "fk_enterprise_data_field_tenant_import",
            "enterprise_data_imports",
            ["tenant_id", "import_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_enterprise_data_field_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_enterprise_data_fields_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_enterprise_data_fields_tenant_counterparty_path",
            ["tenant_id", "counterparty_id", "field_path", "observed_at"],
        )

    with op.batch_alter_table("enterprise_data_resolutions") as batch:
        batch.drop_index("uq_enterprise_data_pending_resolution")
        batch.drop_index("ix_enterprise_data_resolutions_counterparty_path")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key(
            "fk_enterprise_data_resolution_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_enterprise_data_resolution_tenant_field",
            "enterprise_data_fields",
            ["tenant_id", "selected_field_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_enterprise_data_resolutions_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_enterprise_data_resolutions_tenant_counterparty_path",
            ["tenant_id", "counterparty_id", "field_path", "created_at"],
        )
        batch.create_index(
            "uq_enterprise_data_pending_resolution",
            ["tenant_id", "counterparty_id", "field_path"],
            unique=True,
            sqlite_where=sa.text("status = 'pending_review'"),
            postgresql_where=sa.text("status = 'pending_review'"),
        )

    with op.batch_alter_table("portfolio_rating_batches") as batch:
        batch.drop_index("ix_portfolio_rating_batches_batch_key")
        batch.drop_index("ix_portfolio_batches_template_created")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint(
            "uq_portfolio_rating_batch_tenant_key", ["tenant_id", "batch_key"]
        )
        batch.create_index("ix_portfolio_rating_batches_tenant_id", ["tenant_id"])
        batch.create_index("ix_portfolio_rating_batches_batch_key", ["batch_key"])
        batch.create_index(
            "ix_portfolio_batches_tenant_template_created",
            ["tenant_id", "template_key", "created_at"],
        )

    with op.batch_alter_table("decision_variances") as batch:
        batch.drop_index("ix_decision_variances_case_id")
        batch.drop_index("ix_decision_variances_direction_materiality")
        batch.drop_constraint("uq_decision_variance_case", type_="unique")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_unique_constraint("uq_decision_variance_tenant_case", ["tenant_id", "case_id"])
        batch.create_foreign_key(
            "fk_decision_variance_tenant_case",
            "approval_cases",
            ["tenant_id", "case_id"],
            ["tenant_id", "case_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_decision_variance_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_decision_variance_tenant_rating_run",
            "rating_runs",
            ["tenant_id", "rating_run_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_decision_variances_tenant_id", ["tenant_id"])
        batch.create_index("ix_decision_variances_case_id", ["case_id"])
        batch.create_index(
            "ix_decision_variances_tenant_direction_materiality",
            ["tenant_id", "direction", "materiality", "decided_at"],
        )


def downgrade() -> None:
    _reject_unrepresentable_downgrade()

    with op.batch_alter_table("decision_variances") as batch:
        batch.drop_index("ix_decision_variances_tenant_direction_materiality")
        batch.drop_index("ix_decision_variances_case_id")
        batch.drop_index("ix_decision_variances_tenant_id")
        batch.drop_constraint("fk_decision_variance_tenant_rating_run", type_="foreignkey")
        batch.drop_constraint("fk_decision_variance_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("fk_decision_variance_tenant_case", type_="foreignkey")
        batch.drop_constraint("uq_decision_variance_tenant_case", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint("uq_decision_variance_case", ["case_id"])
        batch.create_index("ix_decision_variances_case_id", ["case_id"], unique=True)
        batch.create_index(
            "ix_decision_variances_direction_materiality",
            ["direction", "materiality", "decided_at"],
        )

    with op.batch_alter_table("portfolio_rating_batches") as batch:
        batch.drop_index("ix_portfolio_batches_tenant_template_created")
        batch.drop_index("ix_portfolio_rating_batches_batch_key")
        batch.drop_index("ix_portfolio_rating_batches_tenant_id")
        batch.drop_constraint("uq_portfolio_rating_batch_tenant_key", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_index("ix_portfolio_rating_batches_batch_key", ["batch_key"], unique=True)
        batch.create_index("ix_portfolio_batches_template_created", ["template_key", "created_at"])

    with op.batch_alter_table("enterprise_data_resolutions") as batch:
        batch.drop_index("uq_enterprise_data_pending_resolution")
        batch.drop_index("ix_enterprise_data_resolutions_tenant_counterparty_path")
        batch.drop_index("ix_enterprise_data_resolutions_tenant_id")
        batch.drop_constraint("fk_enterprise_data_resolution_tenant_field", type_="foreignkey")
        batch.drop_constraint("fk_enterprise_data_resolution_tenant_counterparty", type_="foreignkey")
        batch.drop_column("tenant_id")
        batch.create_index(
            "ix_enterprise_data_resolutions_counterparty_path",
            ["counterparty_id", "field_path", "created_at"],
        )
        batch.create_index(
            "uq_enterprise_data_pending_resolution",
            ["counterparty_id", "field_path"],
            unique=True,
            sqlite_where=sa.text("status = 'pending_review'"),
            postgresql_where=sa.text("status = 'pending_review'"),
        )

    with op.batch_alter_table("enterprise_data_fields") as batch:
        batch.drop_index("ix_enterprise_data_fields_tenant_counterparty_path")
        batch.drop_index("ix_enterprise_data_fields_tenant_id")
        batch.drop_constraint("fk_enterprise_data_field_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("fk_enterprise_data_field_tenant_import", type_="foreignkey")
        batch.drop_constraint("uq_enterprise_data_field_tenant_import_path", type_="unique")
        batch.drop_constraint("uq_enterprise_data_field_tenant_id", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint(
            "uq_enterprise_data_field_import_path", ["import_id", "field_path"]
        )
        batch.create_index(
            "ix_enterprise_data_fields_counterparty_path",
            ["counterparty_id", "field_path", "observed_at"],
        )

    with op.batch_alter_table("enterprise_data_imports") as batch:
        batch.drop_index("ix_enterprise_data_imports_tenant_counterparty_created")
        batch.drop_index("ix_enterprise_data_imports_import_key")
        batch.drop_index("ix_enterprise_data_imports_tenant_id")
        batch.drop_constraint("fk_enterprise_data_import_tenant_counterparty", type_="foreignkey")
        batch.drop_constraint("uq_enterprise_data_import_tenant_key", type_="unique")
        batch.drop_constraint("uq_enterprise_data_import_tenant_id", type_="unique")
        batch.drop_column("tenant_id")
        batch.create_unique_constraint("uq_enterprise_data_import_key", ["import_key"])
        batch.create_index("ix_enterprise_data_imports_import_key", ["import_key"], unique=True)
        batch.create_index(
            "ix_enterprise_data_imports_counterparty_created",
            ["counterparty_id", "created_at"],
        )
