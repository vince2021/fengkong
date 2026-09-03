from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from math import isfinite
from typing import Any

from rating.explanations import split_explanations
from rating.rules import apply_rule_actions, evaluate_strong_rules, get_field_value
from rating.strategies import apply_strategy_mapping, get_mapping_for_score


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_scorecard_binding(binding: Any) -> list[str]:
    if binding is None:
        return []
    if not isinstance(binding, dict):
        return ["评分卡绑定格式无效"]
    required = {"scorecard_asset_id", "code", "version", "config_hash", "config"}
    missing = sorted(required - set(binding))
    if missing:
        return [f"评分卡绑定缺少字段：{','.join(missing)}"]
    if stable_hash(binding["config"]) != binding["config_hash"]:
        return ["评分卡绑定配置哈希不一致"]
    config = binding["config"]
    if binding["code"] != config.get("code"):
        return ["评分卡绑定编码与配置不一致"]
    indicators = config.get("indicators")
    if not isinstance(indicators, list) or not indicators:
        return ["评分卡绑定没有可执行指标"]
    for item in indicators:
        if not str(item.get("field_path") or "").strip():
            return [f"评分卡指标 {item.get('indicator_code', '未知')} 缺少字段路径"]
    return []


def rate_governed_scorecard(counterparty: dict, config: dict) -> dict:
    binding = config.get("scorecard_binding")
    errors = validate_scorecard_binding(binding)
    if errors:
        return {"ok": False, "error": "；".join(errors), "counterparty_id": counterparty.get("id")}
    definition = binding["config"]
    try:
        details = [_evaluate_indicator(counterparty, item) for item in definition["indicators"]]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "counterparty_id": counterparty.get("id")}
    total_weight = sum(float(item["weight"]) for item in definition["indicators"])
    if not isfinite(total_weight) or total_weight <= 0:
        return {"ok": False, "error": "评分卡指标权重合计必须大于 0", "counterparty_id": counterparty.get("id")}

    raw_score = sum(item["score"] * item["weight"] for item in details) / total_weight
    theoretical_min = sum(min(float(row["score"]) for row in item["bins"]) * float(item["weight"]) for item in definition["indicators"]) / total_weight
    theoretical_max = sum(max(float(row["score"]) for row in item["bins"]) * float(item["weight"]) for item in definition["indicators"]) / total_weight
    if theoretical_max <= theoretical_min:
        return {"ok": False, "error": "评分卡理论分数范围无效", "counterparty_id": counterparty.get("id")}
    normalized = max(0.0, min(100.0, (raw_score - theoretical_min) / (theoretical_max - theoretical_min) * 100))
    scale = definition["score_scale"]
    if not bool(scale.get("higher_is_better", True)):
        normalized = 100 - normalized
    scaled = float(scale["min"]) + normalized / 100 * (float(scale["max"]) - float(scale["min"]))
    total_score = round(normalized, 1)
    rating = get_mapping_for_score(total_score, config["strategy_mapping"])["rating"]
    strategy = apply_strategy_mapping(counterparty, rating, config)
    strong_rule_hits = evaluate_strong_rules(counterparty, config)
    final_strategy = apply_rule_actions(strategy, strong_rule_hits, counterparty)
    explanations = [_explanation(item) for item in details]
    summary = split_explanations(explanations)
    return {
        "ok": True,
        "counterparty_id": counterparty.get("id"),
        "counterparty_name": counterparty.get("name", ""),
        "counterparty_type": counterparty.get("counterparty_type", ""),
        "model_version": config.get("version"),
        "total_score": total_score,
        "scorecard_score": round(scaled, 2),
        "scorecard_raw_score": round(raw_score, 4),
        "rating": final_strategy["rating"],
        "raw_rating": rating,
        "risk_segment": final_strategy["risk_segment"],
        "access_strategy": final_strategy["access_strategy"],
        "suggested_limit": final_strategy["suggested_limit"],
        "suggested_payment_term_days": final_strategy["payment_term_days"],
        "monitoring_frequency": final_strategy["monitoring_frequency"],
        "dimension_scores": {"governed_scorecard": total_score},
        "indicator_explanations": explanations,
        "strong_rule_hits": strong_rule_hits,
        "review_required": final_strategy["review_required"] or bool(strong_rule_hits),
        "main_deductions": summary["main_deductions"],
        "main_positive_factors": summary["main_positive_factors"],
        "scorecard_execution": {
            "scorecard_asset_id": binding["scorecard_asset_id"],
            "code": binding["code"], "version": binding["version"],
            "config_hash": binding["config_hash"], "binding_hash": stable_hash(binding),
            "score_scale": deepcopy(scale), "raw_range": {"min": theoretical_min, "max": theoretical_max},
            "raw_score": round(raw_score, 4), "normalized_score": total_score,
            "scaled_score": round(scaled, 2), "missing_count": sum(item["missing"] for item in details),
            "details": details,
        },
    }


def _evaluate_indicator(counterparty: dict, item: dict) -> dict:
    value = get_field_value(counterparty, item["field_path"])
    selected = None
    if value is None:
        selected = next((row for row in item["bins"] if row["kind"] == "missing"), None)
    else:
        for row in item["bins"]:
            if row["kind"] == "range" and _in_range(value, row):
                selected = row; break
            if row["kind"] == "category" and _in_category(value, row.get("values") or []):
                selected = row; break
    if selected is None:
        raise ValueError(f"指标 {item['indicator_code']} 的值未命中任何分箱")
    weight = float(item["weight"])
    return {
        "indicator_code": item["indicator_code"], "indicator_version": item["indicator_version"],
        "indicator_name": item["indicator_name"], "field_path": item["field_path"],
        "actual_value": value, "bin_kind": selected["kind"], "bin_label": selected["label"],
        "score": float(selected["score"]), "woe": selected.get("woe"), "weight": weight,
        "max_score": max(float(row["score"]) for row in item["bins"]),
        "weighted_score": round(float(selected["score"]) * weight, 4), "missing": value is None,
    }


def _in_range(value: Any, row: dict) -> bool:
    try:
        actual = float(value)
    except (TypeError, ValueError):
        return False
    lower, upper = row.get("lower"), row.get("upper")
    lower_ok = lower is None or actual > float(lower) or bool(row.get("lower_inclusive", True)) and actual == float(lower)
    upper_ok = upper is None or actual < float(upper) or bool(row.get("upper_inclusive", False)) and actual == float(upper)
    return lower_ok and upper_ok


def _in_category(value: Any, expected: list) -> bool:
    actual = str(value).strip().lower()
    return actual in {str(item).strip().lower() for item in expected}


def _explanation(item: dict) -> dict:
    return {
        "dimension": "governed_scorecard", "dimension_label": "治理评分卡", "indicator_group": "评分卡指标", "indicator": item["indicator_name"],
        "value": item["actual_value"], "threshold": item["bin_label"],
        "points": round(max(0, item["max_score"] - item["score"]) * item["weight"] / 100, 2),
        "reason": f"命中分箱：{item['bin_label']}",
        "evidence": f"{item['field_path']} @ {item['indicator_version']}",
        "calculation": f"分箱 {item['bin_label']} × 权重 {item['weight']:g}%",
        "contribution": item["weighted_score"], "data_status": "missing" if item["missing"] else "available",
    }
