"""Allow a pending in-service renewal beside its still-effective acceptance.

Revision ID: 20260923_0107
Revises: 20260923_0106
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260923_0107"
down_revision = "20260923_0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_model_risk_reacceptance_active_release", table_name="model_risk_reacceptances")
    for status in ("pending", "accepted"):
        op.create_index(f"uq_model_risk_reacceptance_{status}_release", "model_risk_reacceptances",
                        ["tenant_id", "model_release_id"], unique=True,
                        sqlite_where=sa.text(f"status = '{status}'"),
                        postgresql_where=sa.text(f"status = '{status}'"))


def downgrade() -> None:
    coexist = op.get_bind().execute(sa.text(
        "SELECT 1 FROM model_risk_reacceptances AS pending JOIN model_risk_reacceptances AS accepted "
        "ON pending.tenant_id = accepted.tenant_id AND pending.model_release_id = accepted.model_release_id "
        "WHERE pending.status = 'pending' AND accepted.status = 'accepted' LIMIT 1"
    )).first()
    if coexist:
        raise RuntimeError("存在待签续期与有效结论并行的记录，不能无损回退到旧唯一索引")
    for status in ("pending", "accepted"):
        op.drop_index(f"uq_model_risk_reacceptance_{status}_release", table_name="model_risk_reacceptances")
    op.create_index("uq_model_risk_reacceptance_active_release", "model_risk_reacceptances",
                    ["tenant_id", "model_release_id"], unique=True,
                    sqlite_where=sa.text("status IN ('pending', 'accepted')"),
                    postgresql_where=sa.text("status IN ('pending', 'accepted')"))
