"""Seed governed indicator definitions from the legacy JSON pool."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db_models import IndicatorDefinition
from backend.repository import IndicatorDefinitionRepository


POOL_JSON_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "enterprise_risk_indicator_pool.json"
)
TECH_HEALTH_CATEGORIES = (
    "tech_quality",
    "stability",
    "capability",
    "scale",
    "development",
    "operation",
)
TECH_HEALTH_PLACEHOLDER_COUNT = 32


def _load_pool_json() -> dict:
    return json.loads(POOL_JSON_PATH.read_text(encoding="utf-8"))


def pool_indicator_to_definition(indicator: dict) -> dict:
    """Map one legacy pool row without treating display formulas as code."""
    field_path = str(indicator.get("field_path") or "").strip()
    if not field_path:
        raise ValueError(f"指标 {indicator.get('id', '未知')} 缺少 field_path")
    scoring = indicator.get("scoring")
    if not isinstance(scoring, dict):
        raise ValueError(f"指标 {indicator.get('id', '未知')} 缺少评分配置")

    return {
        "code": str(indicator["id"]),
        "name": str(indicator["name"]),
        "category": str(indicator.get("category_key") or "external_risk"),
        "layer": "atomic",
        "data_type": str(indicator.get("data_type") or "numeric"),
        "field_path": field_path,
        "expression": None,
        "dependencies": None,
        "scoring_json": deepcopy(scoring),
        "max_score": float(indicator.get("max_score", 3)),
        "default_weight": float(indicator.get("default_weight", 1)),
        "source_references": deepcopy(indicator.get("source_references") or []),
        "seed_source": "pool_json",
    }


def dry_run_pool_json() -> dict:
    """Validate and map the source pool without writing to the database."""
    source = _load_pool_json()
    definitions = [
        pool_indicator_to_definition(indicator)
        for indicator in source.get("indicators", [])
    ]
    codes = [definition["code"] for definition in definitions]
    if len(codes) != len(set(codes)):
        raise ValueError("指标种子包含重复编码")
    return {
        "pool_version": source.get("version"),
        "count": len(definitions),
        "samples": definitions[:3],
    }


def seed_from_pool_json(
    session: Session,
    actor: str = "seeder",
    actor_name: str = "灌入脚本",
) -> int:
    """Idempotently publish all absent JSON-pool definitions."""
    source = _load_pool_json()
    repository = IndicatorDefinitionRepository(session)

    existing_codes = set(
        session.scalars(select(IndicatorDefinition.code)).all()
    )
    for source_indicator in source.get("indicators", []):
        definition = pool_indicator_to_definition(source_indicator)
        if definition["code"] in existing_codes:
            continue
        repository.publish_indicator(
            definition,
            actor=actor,
            actor_name=actor_name,
        )
        existing_codes.add(definition["code"])

    return int(
        session.scalar(
            select(func.count(IndicatorDefinition.id)).where(
                IndicatorDefinition.seed_source == "pool_json",
                IndicatorDefinition.status == "published",
                IndicatorDefinition.is_active.is_(True),
            )
        )
        or 0
    )


def seed_tech_health_placeholders(
    session: Session,
    actor: str = "seeder",
) -> int:
    """Idempotently create inactive drafts awaiting formula governance."""
    existing_codes = set(
        session.scalars(select(IndicatorDefinition.code)).all()
    )
    now = datetime.now(timezone.utc)
    for index in range(TECH_HEALTH_PLACEHOLDER_COUNT):
        code = f"TECH_HEALTH_{index:03d}"
        if code in existing_codes:
            continue
        session.add(
            IndicatorDefinition(
                id=str(uuid4()),
                code=code,
                name=f"科创健康分占位-{index + 1:02d}",
                category=TECH_HEALTH_CATEGORIES[
                    index % len(TECH_HEALTH_CATEGORIES)
                ],
                layer="derived",
                data_type="numeric",
                field_path=None,
                expression=None,
                dependencies=[],
                scoring_json={
                    "type": "numeric_bands",
                    "bands": [],
                    "missing_score": 0,
                    "formula": "待治理标定",
                },
                max_score=3.0,
                default_weight=1.0,
                source_references=[],
                seed_source="tech_health",
                version=1,
                status="draft",
                is_active=False,
                row_version=1,
                created_at=now,
                created_by=actor,
            )
        )
        existing_codes.add(code)
    session.commit()

    return int(
        session.scalar(
            select(func.count(IndicatorDefinition.id)).where(
                IndicatorDefinition.seed_source == "tech_health",
                IndicatorDefinition.status == "draft",
                IndicatorDefinition.is_active.is_(False),
            )
        )
        or 0
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="灌入企业风险指标池")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验并展示映射摘要，不写数据库",
    )
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps(dry_run_pool_json(), ensure_ascii=False, indent=2))
        return

    from backend.database import SessionLocal

    with SessionLocal() as session:
        pool_count = seed_from_pool_json(session)
        tech_count = seed_tech_health_placeholders(session)
    print(f"pool_json: {pool_count} active indicators")
    print(f"tech_health: {tech_count} draft placeholders")


if __name__ == "__main__":
    main()
