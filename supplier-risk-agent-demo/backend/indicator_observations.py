from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, time, timezone
from typing import Any

from rating.enterprise_indicator_pool import apply_verified_indicator_observations, get_enterprise_risk_indicator


def validate_indicator_observation(indicator_id: str, values: dict[str, Any]) -> tuple[dict, dict[str, Any]]:
    indicator = get_enterprise_risk_indicator(indicator_id)
    if not indicator:
        raise ValueError("企业风险指标不存在")
    scoring = indicator["scoring"]
    expected_paths = scoring.get("input_fields") or [indicator["field_path"]]
    if set(values) != set(expected_paths):
        raise ValueError(f"指标值字段必须完整匹配：{', '.join(expected_paths)}")

    normalized: dict[str, Any] = {}
    for path in expected_paths:
        value = values[path]
        if scoring["type"] == "boolean_hit":
            if not isinstance(value, bool):
                raise ValueError(f"{indicator['name']} 必须提交布尔值")
            normalized[path] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{indicator['name']} 必须提交数值")
        if not float("-inf") < float(value) < float("inf"):
            raise ValueError("指标值必须是有限数值")
        if float(value) < 0:
            raise ValueError("指标值不能小于 0")
        normalized[path] = int(value) if float(value).is_integer() else float(value)
    return indicator, normalized


def observed_datetime(value: date) -> datetime:
    if value > datetime.now(timezone.utc).date():
        raise ValueError("指标数据截止日期不能晚于当前日期")
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def apply_effective_observations(rating_input: dict, readiness: dict, observations: list[dict]) -> tuple[dict, dict]:
    prepared = apply_verified_indicator_observations(rating_input, observations)
    effective = [
        {
            "id": item["id"],
            "indicator_id": item["indicator_id"],
            "values_hash": item["values_hash"],
            "observed_at": item["observed_at"],
            "reviewed_by": item.get("reviewed_by"),
        }
        for item in observations
        if item.get("status") == "verified"
    ]
    updated = deepcopy(readiness)
    updated["indicator_observation_count"] = len(effective)
    updated["indicator_observation_hash"] = _hash(effective)
    updated["data_snapshot_hash"] = _hash({
        "governed_data_snapshot_hash": readiness.get("data_snapshot_hash"),
        "indicator_observations": effective,
    })
    prepared["_data_governance"] = deepcopy(updated)
    return prepared, updated


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
