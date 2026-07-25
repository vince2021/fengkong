from __future__ import annotations

import json

from backend.database import SessionLocal
from backend.sla_monitor import run_sla_scan


def main() -> None:
    with SessionLocal() as session:
        result = run_sla_scan(session, actor="scheduled-sla-monitor")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
