from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


SOURCE_PRIORITIES = {
    "internal_erp": 60,
    "official_registry": 90,
    "audited_financial": 80,
    "external_risk": 75,
    "credit_report": 70,
    "management_submission": 50,
}

DOMAIN_SOURCE_PRIORITIES = {
    "entity": {"official_registry": 100, "credit_report": 80, "management_submission": 50, "internal_erp": 40},
    "ownership": {"official_registry": 100, "credit_report": 80, "management_submission": 50, "internal_erp": 40},
    "financial_statements": {"audited_financial": 100, "internal_erp": 85, "credit_report": 70, "management_submission": 50},
    "external_risk": {"external_risk": 100, "credit_report": 80, "management_submission": 50},
    "internal_transaction_data": {"internal_erp": 100, "management_submission": 50, "credit_report": 40},
}

CRITICAL_FIELDS = {
    "entity.name_cn",
    "entity.unified_social_credit_code",
    "entity.registration_status",
    "entity.industry.name",
}

_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def flatten_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}

    def walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict) and value:
            for key, child in value.items():
                if not isinstance(key, str) or not _SEGMENT_PATTERN.fullmatch(key):
                    raise ValueError(f"字段名不合法：{key}")
                walk(child, f"{prefix}.{key}" if prefix else key)
            return
        _validate_value(value, prefix)
        rows[prefix] = value

    walk(payload, "")
    rows.pop("", None)
    if not rows:
        raise ValueError("导入载荷至少需要包含一个数据字段")
    if len(rows) > 500:
        raise ValueError("单批导入最多包含 500 个叶子字段")
    return rows


def freshness_days(field_path: str) -> int:
    if field_path.startswith("internal_transaction_data."):
        return 30
    if field_path.startswith("external_risk."):
        return 90
    if field_path.startswith("financial_statements."):
        return 540
    if field_path.startswith(("entity.", "ownership.", "operations.")):
        return 365
    return 180


def freshness_status(field_path: str, observed_at: datetime, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
    return "current" if (current - observed).days <= freshness_days(field_path) else "stale"


def source_priority(source_type: str, field_path: str) -> int:
    domain = field_path.split(".", 1)[0]
    return DOMAIN_SOURCE_PRIORITIES.get(domain, {}).get(source_type, SOURCE_PRIORITIES[source_type])


def choose_effective_field(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.get("freshness_status") == "current",
            int(item.get("source_priority", 0)),
            item.get("observed_at") or "",
            item.get("created_at") or "",
            item.get("id") or "",
        ),
    )


def build_quality_summary(
    fields: list[dict],
    all_effective_paths: set[str] | None = None,
    conflict_count: int | None = None,
) -> dict:
    count = len(fields)
    stale = sum(item.get("freshness_status") == "stale" for item in fields)
    conflicts = conflict_count if conflict_count is not None else sum(item.get("conflict_status") != "none" for item in fields)
    invalid = sum(item.get("validation_status") != "valid" for item in fields)
    evidence = sum(bool(item.get("evidence_reference")) for item in fields)
    valid_ratio = (count - invalid) / count if count else 0
    fresh_ratio = (count - stale) / count if count else 0
    evidence_ratio = evidence / count if count else 0
    conflict_ratio = max(0, count - conflicts) / count if count else 0
    quality_score = max(0.0, min(1.0, 0.45 * valid_ratio + 0.25 * fresh_ratio + 0.15 * evidence_ratio + 0.15 * conflict_ratio))
    effective_paths = all_effective_paths if all_effective_paths is not None else {item["field_path"] for item in fields}
    missing = sorted(CRITICAL_FIELDS - effective_paths)
    return {
        "field_count": count,
        "stale_count": stale,
        "conflict_count": conflicts,
        "invalid_count": invalid,
        "evidence_coverage": round(evidence_ratio, 4),
        "quality_score": round(quality_score, 4),
        "missing_critical_fields": missing,
    }


def unflatten_fields(fields: list[dict]) -> dict:
    root: dict[str, Any] = {}
    for item in fields:
        parts = item["field_path"].split(".")
        cursor = root
        for part in parts[:-1]:
            next_value = cursor.get(part)
            if not isinstance(next_value, dict):
                next_value = {}
                cursor[part] = next_value
            cursor = next_value
        cursor[parts[-1]] = item.get("value")
    return root


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _validate_value(value: Any, field_path: str) -> None:
    if len(field_path) > 512:
        raise ValueError("字段路径长度不能超过 512 个字符")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"字段 {field_path} 不能包含 NaN 或无穷值")
    if isinstance(value, str) and len(value) > 10000:
        raise ValueError(f"字段 {field_path} 的文本长度不能超过 10000 个字符")
    if isinstance(value, list) and len(value) > 1000:
        raise ValueError(f"字段 {field_path} 的数组最多包含 1000 项")
