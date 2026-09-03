from __future__ import annotations

from math import isfinite
from typing import Any


def validate_scorecard(definition: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    indicators = definition.get("indicators") or []
    if not indicators:
        errors.append("评分卡至少需要绑定一个指标")

    total_weight = 0.0
    seen: set[tuple[str, str]] = set()
    for item in indicators:
        code = str(item.get("indicator_code") or "").strip()
        version = str(item.get("indicator_version") or "").strip()
        key = (code, version)
        if not code or not version:
            errors.append("每个指标必须固定指标编码和版本")
        elif key in seen:
            errors.append(f"指标 {code}@{version} 重复绑定")
        seen.add(key)
        if not str(item.get("field_path") or "").strip():
            errors.append(f"指标 {code or '未命名'} 必须固定取值字段路径")
        try:
            weight = float(item.get("weight"))
            if not isfinite(weight) or weight <= 0:
                raise ValueError
            total_weight += weight
        except (TypeError, ValueError):
            errors.append(f"指标 {code or '未命名'} 的权重必须大于 0")
        errors.extend(_validate_bins(code, item.get("data_type"), item.get("bins") or []))
        warnings.extend(_monotonic_warnings(code, item.get("bins") or []))

    if total_weight > 0 and abs(total_weight - 100) > 0.01:
        warnings.append(f"当前指标权重合计 {total_weight:.2f}%，发布时将按比例归一化")

    scale = definition.get("score_scale") or {}
    try:
        minimum, maximum = float(scale.get("min")), float(scale.get("max"))
        if not (isfinite(minimum) and isfinite(maximum) and maximum > minimum):
            raise ValueError
    except (TypeError, ValueError):
        errors.append("总分刻度必须包含有效且递增的最小值和最大值")
        minimum, maximum = 0.0, 100.0

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "indicator_count": len(indicators),
            "total_weight": round(total_weight, 4),
            "score_min": minimum,
            "score_max": maximum,
            "bin_count": sum(len(item.get("bins") or []) for item in indicators),
        },
    }


def _validate_bins(code: str, data_type: str | None, bins: list[dict]) -> list[str]:
    errors: list[str] = []
    missing_count = sum(item.get("kind") == "missing" for item in bins)
    if missing_count != 1:
        errors.append(f"指标 {code} 必须且只能配置一个缺失箱")
    regular = [item for item in bins if item.get("kind") != "missing"]
    if not regular:
        errors.append(f"指标 {code} 至少需要一个非缺失分箱")
    for item in bins:
        try:
            score = float(item.get("score"))
            if not isfinite(score):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"指标 {code} 的每个分箱必须配置有效分数")
    if data_type == "numeric":
        ranges = []
        for item in regular:
            if item.get("kind") != "range":
                errors.append(f"数值指标 {code} 只能使用连续区间分箱")
                continue
            lower, upper = item.get("lower"), item.get("upper")
            try:
                low = float("-inf") if lower is None else float(lower)
                high = float("inf") if upper is None else float(upper)
                if low >= high:
                    raise ValueError
                ranges.append((low, high, bool(item.get("lower_inclusive", True)), bool(item.get("upper_inclusive", False))))
            except (TypeError, ValueError):
                errors.append(f"指标 {code} 存在无效区间边界")
        ranges.sort(key=lambda value: value[0])
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1] or current[0] == previous[1] and previous[3] and current[2]:
                errors.append(f"指标 {code} 的连续分箱存在重叠")
                break
    else:
        values: set[str] = set()
        for item in regular:
            if item.get("kind") != "category" or not item.get("values"):
                errors.append(f"离散指标 {code} 的分箱必须配置枚举值")
                continue
            normalized = {str(value) for value in item["values"]}
            if values & normalized:
                errors.append(f"指标 {code} 的离散分箱存在重复枚举值")
            values |= normalized
    return errors


def _monotonic_warnings(code: str, bins: list[dict]) -> list[str]:
    ordered = [item for item in bins if item.get("kind") == "range"]
    ordered.sort(key=lambda item: float("-inf") if item.get("lower") is None else float(item["lower"]))
    scores = [float(item["score"]) for item in ordered if item.get("score") is not None]
    if len(scores) > 2 and not (scores == sorted(scores) or scores == sorted(scores, reverse=True)):
        return [f"指标 {code} 的区间分数非单调，请确认业务依据"]
    return []
