"""Idempotently seed demo counterparties into each development tenant."""
from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.counterparty_repository import CounterpartyRepository
from backend.database import SessionLocal, initialize_database
from backend.db_models import CounterpartyRecord


BASE_DIR = Path(__file__).resolve().parents[1]
DEVELOPMENT_TENANTS = ("tenant-demo-hengxin", "tenant-demo-alt", "tenant-platform-internal")
CORE_FIELDS = {
    "id", "name", "credit_code", "counterparty_type", "industry", "cooperation_status",
    "is_key_counterparty", "requested_limit", "current_limit", "current_payment_term_days",
    "current_rating", "current_segment", "external", "internal", "financial",
}


def seed_development_counterparties(session: Session) -> int:
    samples = json.loads((BASE_DIR / "data" / "counterparties.json").read_text(encoding="utf-8"))
    created = 0
    for tenant_id in DEVELOPMENT_TENANTS:
        for sample in samples:
            existing = session.scalars(
                select(CounterpartyRecord).where(
                    CounterpartyRecord.tenant_id == tenant_id,
                    CounterpartyRecord.counterparty_id == sample["id"],
                )
            ).first()
            if existing is not None:
                continue
            extensions = {key: deepcopy(value) for key, value in sample.items() if key not in CORE_FIELDS}
            record = CounterpartyRecord(
                id=str(uuid4()), tenant_id=tenant_id, counterparty_id=sample["id"],
                credit_code=str(sample["credit_code"]).upper(), name=sample["name"],
                counterparty_type=sample["counterparty_type"], industry=sample.get("industry", "general"),
                cooperation_status=sample.get("cooperation_status", "pending"),
                is_key_counterparty=bool(sample.get("is_key_counterparty", False)),
                requested_limit=Decimal(str(sample.get("requested_limit", 0))),
                current_limit=Decimal(str(sample.get("current_limit", 0))),
                current_payment_term_days=int(sample.get("current_payment_term_days", 0)),
                current_rating=sample.get("current_rating"), current_segment=sample.get("current_segment"),
                external_json=deepcopy(sample.get("external", {})), internal_json=deepcopy(sample.get("internal", {})),
                financial_json=deepcopy(sample.get("financial", {})), extensions_json=extensions,
                profile_hash="", status="active", source_type="demo_seed", created_by="system-demo-seed",
                updated_by="system-demo-seed",
            )
            record.profile_hash = CounterpartyRepository._profile_hash(record)
            session.add(record)
            created += 1
    session.commit()
    return created


def main() -> None:
    initialize_database()
    with SessionLocal() as session:
        created = seed_development_counterparties(session)
    print(f"Seeded {created} development counterparty records.")


if __name__ == "__main__":
    main()
