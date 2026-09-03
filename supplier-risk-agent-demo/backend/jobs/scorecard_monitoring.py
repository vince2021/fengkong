from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.scorecard_repository import ScorecardRepository


SCHEDULER_ACTOR = "持续验证自动调度器"


def run_scheduled_scorecard_monitoring(
    session: Session,
    *,
    now: datetime | None = None,
    run_key: str | None = None,
    max_plans: int = 50,
    actor: str = SCHEDULER_ACTOR,
) -> dict:
    point = now or datetime.now(timezone.utc)
    return ScorecardRepository(session).run_monitoring_scheduler(
        point,
        max_plans,
        actor,
        actor,
        run_key=run_key,
        trigger_type="scheduler",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="执行评分卡持续验证周期调度")
    parser.add_argument("--run-key", default=None, help="可选幂等运行键；默认按 UTC 五分钟窗口生成")
    parser.add_argument("--max-plans", type=int, default=50, choices=range(1, 201), metavar="1-200")
    args = parser.parse_args()
    with SessionLocal() as session:
        result = run_scheduled_scorecard_monitoring(session, run_key=args.run_key, max_plans=args.max_plans)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    run = result.get("run") or {}
    return 1 if run.get("status") in {"failed", "partial_failed", "dead_letter"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
