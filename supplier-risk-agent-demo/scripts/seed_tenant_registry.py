"""Seed local development tenants, memberships, and API clients."""
from __future__ import annotations

from backend.database import SessionLocal
from backend.tenant_registry import seed_development_tenant_registry


def main() -> None:
    with SessionLocal() as session:
        seed_development_tenant_registry(session)
    print("Development tenant registry seeded.")


if __name__ == "__main__":
    main()
