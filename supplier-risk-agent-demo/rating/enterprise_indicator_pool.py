from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from rating.rules import get_field_value


BASE_DIR = Path(__file__).resolve().parents[1]
POOL_PATH = BASE_DIR / "data" / "enterprise_risk_indicator_pool.json"


DEFAULT_MODEL_INDICATORS = {
    "tech_enterprise_basic": [
        "注册年限",
        "被列入失信被执行人",
        "被列入经营异常名录",
        "股东变更",
        "近一年法人及主要人员联合变更",
        "环保处罚",
        "重大纠纷",
        "近3年负面新闻",
    ],
    "corporate_credit_v2": [
        "注册年限",
        "被列入失信被执行人",
        "被列入限制高消费名单",
        "被列入经营异常名录",
        "重大纠纷",
        "股东变更",
        "近一年法人及主要人员联合变更",
        "行政处罚",
        "债券违约",
        "票据违约",
        "近3年负面新闻",
    ],
    "default": [
        "注册年限",
        "被列入失信被执行人",
        "被列入经营异常名录",
        "重大纠纷",
        "股东变更",
        "近一年法人及主要人员联合变更",
        "行政处罚",
        "近3年负面新闻",
    ],
}


@lru_cache(maxsize=1)
def _load_pool() -> dict:
    return json.loads(POOL_PATH.read_text(encoding="utf-8"))


def get_indicator_pool() -> dict:
    return deepcopy(_load_pool())


def get_enterprise_risk_indicator(indicator_id: str) -> dict | None:
    row = next((item for item in _load_pool()["indicators"] if item["id"] == indicator_id), None)
    return deepcopy(row) if row else None


def apply_verified_indicator_observations(counterparty: dict, observations: list[dict]) -> dict:
    prepared = deepcopy(counterparty)
    sources: dict[str, dict] = {}
    for observation in observations:
        if observation.get("status") != "verified":
            continue
        for field_path, value in observation.get("values", {}).items():
            _set_field_value(prepared, field_path, value)
            sources[field_path] = {
                "observation_id": observation["id"],
                "indicator_id": observation["indicator_id"],
                "evidence_document_id": observation.get("evidence_document_id"),
                "evidence_reference": observation.get("evidence_reference"),
                "observed_at": observation.get("observed_at"),
                "reviewed_by_name": observation.get("reviewed_by_name"),
            }
    prepared["_indicator_observation_sources"] = sources
    return prepared


def list_enterprise_risk_indicators(
    *,
    query: str | None = None,
    category: str | None = None,
    use_case: str | None = None,
) -> list[dict]:
    rows = _load_pool()["indicators"]
    query_text = str(query or "").strip().lower()
    category_text = str(category or "").strip()
    use_case_text = str(use_case or "").strip()
    result = []
    for row in rows:
        if category_text and row["category"] != category_text:
            continue
        if use_case_text and use_case_text not in row["use_cases"]:
            continue
        searchable = " ".join(
            [row["name"], row["description"], row["category"], row["data_source"], row["scoring"]["formula"]]
        ).lower()
        if query_text and query_text not in searchable:
            continue
        result.append(deepcopy(row))
    return result


def get_model_indicator_selection(config: dict) -> list[dict]:
    configured = config.get("indicator_selection")
    if isinstance(configured, list) and configured:
        return [
            {
                "indicator_id": str(item["indicator_id"] if isinstance(item, dict) else item),
                "weight": float(item.get("weight", 1)) if isinstance(item, dict) else 1.0,
                "enabled": bool(item.get("enabled", True)) if isinstance(item, dict) else True,
            }
            for item in configured
        ]

    names = DEFAULT_MODEL_INDICATORS.get(config.get("scorecard_type"), DEFAULT_MODEL_INDICATORS["default"])
    by_name = {item["name"]: item for item in _load_pool()["indicators"]}
    return [
        {"indicator_id": by_name[name]["id"], "weight": 1.0, "enabled": True}
        for name in names
        if name in by_name
    ]


def build_model_indicator_details(config: dict) -> list[dict]:
    by_id = {item["id"]: item for item in _load_pool()["indicators"]}
    rows = []
    for selection in get_model_indicator_selection(config):
        indicator = by_id.get(selection["indicator_id"])
        if not indicator:
            continue
        rows.append({**deepcopy(indicator), "model_weight": selection["weight"], "enabled": selection["enabled"]})
    return rows


def validate_indicator_selection(selection: object) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(selection, list) or not selection:
        return ["企业风险指标组合不能为空"], warnings
    valid_ids = {item["id"] for item in _load_pool()["indicators"]}
    ids: list[str] = []
    enabled_count = 0
    for item in selection:
        if not isinstance(item, dict):
            errors.append("指标组合项必须是对象")
            continue
        indicator_id = str(item.get("indicator_id", ""))
        ids.append(indicator_id)
        if indicator_id not in valid_ids:
            errors.append(f"指标池不存在：{indicator_id or '空指标编号'}")
        try:
            weight = float(item.get("weight", 1))
            if weight <= 0 or weight > 100:
                errors.append(f"指标 {indicator_id} 的相对权重必须大于 0 且不超过 100")
        except (TypeError, ValueError):
            errors.append(f"指标 {indicator_id} 的相对权重必须是数值")
        if item.get("enabled", True):
            enabled_count += 1
    if len(ids) != len(set(ids)):
        errors.append("同一模型不能重复选择同一企业风险指标")
    if enabled_count < 3:
        warnings.append("启用指标少于 3 项，企业风险筛查覆盖可能不足")
    return errors, warnings


def evaluate_indicator_pool(counterparty: dict, config: dict) -> dict:
    indicators = build_model_indicator_details(config)
    enabled = [item for item in indicators if item["enabled"]]
    details = [_evaluate_indicator(counterparty, item) for item in enabled]
    total_weight = sum(float(item["model_weight"]) for item in details)
    weighted_score = (
        sum(float(item["score"]) * float(item["model_weight"]) for item in details) / total_weight
        if total_weight
        else 0.0
    )
    available_count = sum(item["data_status"] == "已取得" for item in details)
    return {
        "pool_version": _load_pool()["version"],
        "selected_count": len(enabled),
        "available_count": available_count,
        "missing_count": len(enabled) - available_count,
        "completeness": round(available_count / len(enabled), 4) if enabled else 0.0,
        "weighted_score": round(weighted_score, 2),
        "normalized_score": round(max(min((weighted_score - 1) / 2 * 100, 100), 0), 1) if enabled else 0.0,
        "formula": "企业风险筛查分 = Σ（单指标 1~3 分 × 相对权重）÷ Σ相对权重；缺失指标按 2 分并标记待补充",
        "details": details,
    }


def _evaluate_indicator(counterparty: dict, indicator: dict) -> dict:
    scoring = indicator["scoring"]
    actual = get_field_value(counterparty, indicator["field_path"])
    data_status = "已取得"
    if scoring["type"] == "composite_boolean":
        values = [get_field_value(counterparty, field) for field in scoring["input_fields"]]
        if any(value is None for value in values):
            score = float(scoring["missing_score"])
            actual_display = "待补充联合变更字段"
            data_status = "待补充"
        else:
            flags = [bool(value) for value in values]
            score = 1.0 if all(flags) else 2.0 if any(flags) else 3.0
            actual_display = f"法人变更 {int(flags[0])} 次；主要人员变更 {int(flags[1])} 次"
    elif actual is None:
        score = float(scoring["missing_score"])
        actual_display = "待补充"
        data_status = "待补充"
    elif scoring["type"] == "boolean_hit":
        score = float(scoring["bands"][1]["score"] if bool(actual) else scoring["bands"][0]["score"])
        actual_display = "已触发" if bool(actual) else "未触发"
    else:
        numeric = float(actual)
        score = float(scoring["missing_score"])
        for band in scoring["bands"]:
            if _matches_numeric_band(numeric, band["operator"], float(band["value"])):
                score = float(band["score"])
                break
        actual_display = f"{numeric:g}"

    source_paths = scoring.get("input_fields", [indicator["field_path"]])
    observation_sources = counterparty.get("_indicator_observation_sources", {})
    observation = next((observation_sources[path] for path in source_paths if path in observation_sources), None)
    return {
        "indicator_id": indicator["id"],
        "name": indicator["name"],
        "category": indicator["category"],
        "risk_level": indicator["risk_level"],
        "field_path": indicator["field_path"],
        "actual_value": actual,
        "actual_display": actual_display,
        "score": score,
        "max_score": indicator["max_score"],
        "model_weight": indicator["model_weight"],
        "formula": scoring["formula"],
        "data_status": data_status,
        "data_source": indicator["data_source"],
        "observation_id": observation.get("observation_id") if observation else None,
        "evidence_reference": observation.get("evidence_reference") if observation else None,
        "observed_at": observation.get("observed_at") if observation else None,
        "reviewed_by_name": observation.get("reviewed_by_name") if observation else None,
    }


def _matches_numeric_band(actual: float, operator: str, expected: float) -> bool:
    if operator == "==":
        return actual == expected
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    if operator == ">":
        return actual > expected
    if operator == ">=":
        return actual >= expected
    return False


def _set_field_value(data: dict, path: str, value: object) -> None:
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value
