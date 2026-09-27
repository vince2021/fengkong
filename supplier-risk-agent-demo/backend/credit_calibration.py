from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from statistics import median

from backend.repository import content_hash
from rating.corporate_credit_scorecard import rate_corporate_credit
from rating.enterprise_indicator_pool import get_model_indicator_selection
from rating.risk_screening_policy import apply_risk_screening_policy
from rating.risk_screening_policy import get_risk_screening_policy


RATING_ORDER = ["AAA", "AA", "A", "BBB", "BB", "B", "D"]
AUTO_ADMISSIONS = {"自动准入", "准入", "优先准入", "正常准入", "approve"}
REJECT_ADMISSIONS = {"禁入", "不建议准入", "reject"}
LIMIT_BANDS = (
    ("zero", "0", 0, 0),
    ("under_1m", "0-100万", 0, 1_000_000),
    ("1m_3m", "100-300万", 1_000_000, 3_000_000),
    ("3m_5m", "300-500万", 3_000_000, 5_000_000),
    ("5m_10m", "500-1000万", 5_000_000, 10_000_000),
    ("over_10m", "1000万以上", 10_000_000, None),
)


def calibration_configuration(config: dict) -> dict:
    if config.get("scorecard_type") != "corporate_credit_v2":
        raise ValueError("当前校准工作台只支持材料增强型工商企业信用模型")
    thresholds = config["thresholds"]
    return {
        "template_key": "corporate_credit_v2",
        "model_name": config["name"],
        "model_version": config["version"],
        "model_config_hash": content_hash(config),
        "policy_status": config["credit_policy"].get("policy_status"),
        "rating_bands": [
            {
                "rating": row["rating"],
                "score_min": float(row["score_min"]),
                "score_max": float(row["score_max"]),
                "limit_multiplier": float(row["limit_multiplier"]),
                "payment_term_days": int(row["payment_term_days"]),
                "access_strategy": row["access_strategy"],
            }
            for row in config["strategy_mapping"]
        ],
        "default_candidate": {
            "score_threshold_shift": 0,
            "limit_multiplier_scale": 1,
            "revenue_limit_scale": 1,
            "order_amount_scale": 1,
            "payment_term_scale": 1,
            "overdue_rate_high": float(thresholds["overdue_rate_high"]),
            "limit_utilization_high": float(thresholds["limit_utilization_high"]),
            "invoice_match_rate_low": float(thresholds["invoice_match_rate_low"]),
            "delivery_fulfillment_rate_low": float(thresholds["delivery_fulfillment_rate_low"]),
        },
        "parameter_notes": {
            "score_threshold_shift": "统一平移 AAA 至 B 的最低分门槛；正值更严格，负值更宽松。",
            "limit_multiplier_scale": "按比例调整各评级的申请额度系数，不改变申请额度、收入和交易规模上限。",
            "revenue_limit_scale": "按比例调整收入承载额度；最终额度仍取全部候选上限中的最小值。",
            "order_amount_scale": "按比例调整近 12 个月交易规模承载额度，仅在内部交易资料完整时参与。",
            "payment_term_scale": "按比例调整各评级账期；强规则账期上限仍可进一步收紧。",
            "rule_thresholds": "四项交易规则阈值只在内部交易资料完整时生效。",
        },
    }


def analyze_credit_calibration(config: dict, snapshot: dict, request: dict) -> dict:
    if config.get("scorecard_type") != "corporate_credit_v2":
        raise ValueError("当前校准工作台只支持材料增强型工商企业信用模型")
    samples = deepcopy((snapshot.get("samples") or [])[: int(request["sample_limit"])])
    if not samples:
        raise ValueError("所选不可变快照没有可用于校准的样本")
    positive_labels = {str(value).strip().lower() for value in request["positive_labels"]}
    candidate_parameters = deepcopy(request["candidate"])
    candidate_config = build_credit_calibration_candidate(config, candidate_parameters)

    paired, failures = _run_pairs(samples, config, candidate_config, positive_labels)
    if not paired:
        raise ValueError("所选样本无法完成企业信用模型计算")
    baseline = _portfolio_metrics(paired, "baseline")
    candidate = _portfolio_metrics(paired, "candidate")
    migration = _migration(paired)
    sensitivity = []
    shifts = sorted({-5.0, -2.0, 0.0, 2.0, 5.0, float(candidate_parameters["score_threshold_shift"])})
    for shift in shifts:
        if shift == float(candidate_parameters["score_threshold_shift"]):
            metrics = candidate
        else:
            scenario_parameters = {**candidate_parameters, "score_threshold_shift": shift}
            scenario_config = build_credit_calibration_candidate(config, scenario_parameters)
            scenario_pairs = _run_single_side(samples, scenario_config, positive_labels)
            metrics = _portfolio_metrics(scenario_pairs, "candidate")
        sensitivity.append({
            "score_threshold_shift": shift,
            "automatic_approval_rate": metrics["automatic_approval_rate"],
            "manual_review_rate": metrics["manual_review_rate"],
            "reject_rate": metrics["reject_rate"],
            "average_limit": metrics["average_limit"],
            "total_limit": metrics["total_limit"],
            "event_exposure_ratio": metrics["event_exposure_ratio"],
        })

    warnings = []
    if len(paired) < 100:
        warnings.append("有效样本少于 100 条，仅作为开发敏感性证据，不可替代正式校准。")
    labeled = sum(1 for row in paired if row["is_event"] is not None)
    events = sum(1 for row in paired if row["is_event"] is True)
    non_events = sum(1 for row in paired if row["is_event"] is False)
    if not labeled:
        warnings.append("快照没有有效标签，收益/风险指标降级为非监督额度与准入分布证据。")
    elif not events or not non_events:
        warnings.append("标签仅包含单一类别，事件敞口和捕获率不能代表完整的监督校准证据。")
    coverage = float((snapshot.get("coverage") or {}).get("overall_field_coverage_rate") or 0)
    if coverage < 0.8:
        warnings.append("快照整体字段覆盖率低于 80%，缺失中性分和人工复核可能主导校准结果。")
    if failures:
        warnings.append(f"有 {len(failures)} 条样本在基线或候选方案计算失败，已从成对比较中排除。")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "template_key": request["template_key"], "name": config["name"],
            "version": config["version"], "baseline_config_hash": content_hash(config),
            "candidate_config_hash": content_hash(candidate_config),
        },
        "snapshot": {
            key: snapshot.get(key)
            for key in ("id", "tenant_id", "dataset_id", "dataset_code", "dataset_name", "version", "as_of_date", "content_hash", "sample_count")
        },
        "baseline_parameters": calibration_configuration(config)["default_candidate"],
        "sample": {
            "selected_count": len(samples), "paired_success_count": len(paired),
            "failure_count": len(failures), "labeled_count": labeled,
            "event_count": events, "non_event_count": non_events,
            "label_coverage_rate": round(labeled / len(paired), 6),
            "evidence_level": "supervised" if events and non_events else "degraded",
        },
        "candidate_parameters": candidate_parameters,
        "baseline": baseline,
        "candidate": candidate,
        "deltas": _metric_deltas(baseline, candidate),
        "migration": migration,
        "sensitivity": sensitivity,
        "failures": failures[:20],
        "warnings": warnings,
        "governance_note": "本结果只用于候选参数分析，不修改当前模型；采纳参数后仍需创建模型变更、固定比较证据并独立复核发布。",
    }
    result["evidence_hash"] = content_hash({key: value for key, value in result.items() if key not in {"generated_at", "evidence_hash"}})
    return result


def build_credit_calibration_candidate(
    config: dict,
    parameters: dict,
    candidate_version: str | None = None,
    change_reason: str | None = None,
) -> dict:
    candidate = deepcopy(config)
    candidate["indicator_selection"] = deepcopy(get_model_indicator_selection(config))
    candidate["risk_screening_policy"] = deepcopy(get_risk_screening_policy(config))
    shift = float(parameters["score_threshold_shift"])
    rows = deepcopy(candidate["strategy_mapping"])
    for row in rows:
        if row["rating"] != "D":
            row["score_min"] = round(max(1.0, min(100.0, float(row["score_min"]) + shift)), 2)
        row["limit_multiplier"] = round(float(row["limit_multiplier"]) * float(parameters["limit_multiplier_scale"]), 6)
        row["payment_term_days"] = min(180, max(0, round(float(row["payment_term_days"]) * float(parameters["payment_term_scale"]))))
    ordered = sorted(rows, key=lambda row: float(row["score_min"]), reverse=True)
    for index, row in enumerate(ordered):
        row["score_max"] = 100 if index == 0 else round(float(ordered[index - 1]["score_min"]) - 0.01, 2)
    candidate["strategy_mapping"] = rows
    policy = candidate["credit_policy"]
    policy["revenue_limit_pct_by_rating"] = {
        rating: round(float(value) * float(parameters["revenue_limit_scale"]), 8)
        for rating, value in policy["revenue_limit_pct_by_rating"].items()
    }
    policy["order_amount_multiplier"] = round(float(policy["order_amount_multiplier"]) * float(parameters["order_amount_scale"]), 8)
    policy["payment_term_days_by_rating"] = {
        row["rating"]: row["payment_term_days"] for row in rows
    }
    for key in ("overdue_rate_high", "limit_utilization_high", "invoice_match_rate_low", "delivery_fulfillment_rate_low"):
        candidate["thresholds"][key] = float(parameters[key])
    candidate["version"] = candidate_version or f"{config['version']}-CALIBRATION"
    if change_reason is not None:
        candidate["change_reason"] = change_reason.strip()
        candidate["status"] = "active"
        candidate["credit_policy"]["policy_status"] = "候选校准草稿，待比较验证与独立复核发布"
    return candidate


def _run_pairs(samples: list[dict], baseline_config: dict, candidate_config: dict, positive_labels: set[str]) -> tuple[list[dict], list[dict]]:
    pairs = []
    failures = []
    baseline_runtime = deepcopy(baseline_config)
    baseline_runtime.pop("decision_pipeline_code", None)
    for index, entry in enumerate(samples):
        sample = deepcopy(entry.get("sample") or {})
        label = entry.get("label")
        is_event = None if label in (None, "") else str(label).strip().lower() in positive_labels
        try:
            baseline = apply_risk_screening_policy(sample, baseline_runtime, rate_corporate_credit(sample, baseline_runtime))
            candidate = apply_risk_screening_policy(sample, candidate_config, rate_corporate_credit(sample, candidate_config))
            if not baseline.get("ok") or not candidate.get("ok"):
                raise ValueError("模型返回失败状态")
            pairs.append({"id": str(sample.get("id") or index), "label": label, "is_event": is_event, "baseline": baseline, "candidate": candidate})
        except (KeyError, TypeError, ValueError) as exc:
            failures.append({"sample_id": str(sample.get("id") or index), "reason": str(exc) or "模型计算失败"})
    return pairs, failures


def _run_single_side(samples: list[dict], config: dict, positive_labels: set[str]) -> list[dict]:
    pairs = []
    for index, entry in enumerate(samples):
        sample = deepcopy(entry.get("sample") or {})
        label = entry.get("label")
        is_event = None if label in (None, "") else str(label).strip().lower() in positive_labels
        try:
            result = apply_risk_screening_policy(sample, config, rate_corporate_credit(sample, config))
            if result.get("ok"):
                pairs.append({"id": str(sample.get("id") or index), "label": label, "is_event": is_event, "candidate": result})
        except (KeyError, TypeError, ValueError):
            continue
    return pairs


def _portfolio_metrics(pairs: list[dict], side: str) -> dict:
    results = [row[side] for row in pairs]
    count = len(results)
    ratings = _distribution((result.get("rating") or "未知" for result in results), RATING_ORDER)
    admissions = _distribution((result.get("access_strategy") or "未知" for result in results))
    limits = [max(float(result.get("suggested_limit") or 0), 0) for result in results]
    terms = [max(int(result.get("suggested_payment_term_days") or 0), 0) for result in results]
    auto_count = sum(1 for result in results if result.get("access_strategy") in AUTO_ADMISSIONS)
    reject_count = sum(1 for result in results if result.get("access_strategy") in REJECT_ADMISSIONS)
    manual_count = count - auto_count - reject_count
    labeled_rows = [row for row in pairs if row["is_event"] is not None]
    event_rows = [row for row in labeled_rows if row["is_event"]]
    non_event_rows = [row for row in labeled_rows if row["is_event"] is False]
    labeled_limit = sum(max(float(row[side].get("suggested_limit") or 0), 0) for row in labeled_rows)
    event_limit = sum(max(float(row[side].get("suggested_limit") or 0), 0) for row in event_rows)
    non_event_limit = sum(max(float(row[side].get("suggested_limit") or 0), 0) for row in non_event_rows)
    restricted_events = sum(1 for row in event_rows if row[side].get("access_strategy") not in AUTO_ADMISSIONS)
    return {
        "sample_count": count,
        "average_score": round(sum(float(result.get("total_score") or 0) for result in results) / count, 4) if count else 0,
        "automatic_approval_rate": round(auto_count / count, 6) if count else 0,
        "manual_review_rate": round(manual_count / count, 6) if count else 0,
        "reject_rate": round(reject_count / count, 6) if count else 0,
        "average_limit": round(sum(limits) / count, 2) if count else 0,
        "median_limit": round(median(limits), 2) if limits else 0,
        "total_limit": round(sum(limits), 2),
        "average_payment_term_days": round(sum(terms) / count, 2) if count else 0,
        "event_exposure_ratio": round(event_limit / labeled_limit, 6) if labeled_limit else None,
        "restricted_event_capture_rate": round(restricted_events / len(event_rows), 6) if event_rows else None,
        "event_limit": round(event_limit, 2) if event_rows else None,
        "non_event_limit": round(non_event_limit, 2) if non_event_rows else None,
        "rating_distribution": ratings,
        "admission_distribution": admissions,
        "limit_distribution": _limit_distribution(limits),
        "payment_term_distribution": _distribution((str(value) for value in terms), ["0", "15", "30", "45", "60"]),
    }


def _distribution(values, preferred: list[str] | None = None) -> list[dict]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    keys = [key for key in (preferred or []) if key in counts]
    keys.extend(sorted(key for key in counts if key not in keys))
    return [{"key": key, "count": counts[key], "rate": round(counts[key] / total, 6) if total else 0} for key in keys]


def _limit_distribution(limits: list[float]) -> list[dict]:
    rows = []
    total = len(limits)
    for key, label, lower, upper in LIMIT_BANDS:
        if key == "zero":
            count = sum(1 for value in limits if value == 0)
        else:
            count = sum(1 for value in limits if value > lower and (upper is None or value <= upper))
        rows.append({"key": key, "label": label, "count": count, "rate": round(count / total, 6) if total else 0})
    return rows


def _migration(pairs: list[dict]) -> dict:
    rating_cells: dict[tuple[str, str], int] = {}
    admission_cells: dict[tuple[str, str], int] = {}
    improved = worsened = rating_changed = admission_changed = 0
    for row in pairs:
        before_rating = str(row["baseline"].get("rating") or "未知")
        after_rating = str(row["candidate"].get("rating") or "未知")
        rating_cells[(before_rating, after_rating)] = rating_cells.get((before_rating, after_rating), 0) + 1
        if before_rating != after_rating:
            rating_changed += 1
            before_rank = RATING_ORDER.index(before_rating) if before_rating in RATING_ORDER else len(RATING_ORDER)
            after_rank = RATING_ORDER.index(after_rating) if after_rating in RATING_ORDER else len(RATING_ORDER)
            improved += int(after_rank < before_rank)
            worsened += int(after_rank > before_rank)
        before_access = str(row["baseline"].get("access_strategy") or "未知")
        after_access = str(row["candidate"].get("access_strategy") or "未知")
        admission_cells[(before_access, after_access)] = admission_cells.get((before_access, after_access), 0) + 1
        admission_changed += int(before_access != after_access)
    total = len(pairs)
    return {
        "rating_changed_count": rating_changed,
        "rating_change_rate": round(rating_changed / total, 6) if total else 0,
        "rating_improved_count": improved,
        "rating_worsened_count": worsened,
        "admission_changed_count": admission_changed,
        "admission_change_rate": round(admission_changed / total, 6) if total else 0,
        "rating_cells": [{"from": key[0], "to": key[1], "count": count} for key, count in sorted(rating_cells.items())],
        "admission_cells": [{"from": key[0], "to": key[1], "count": count} for key, count in sorted(admission_cells.items())],
    }


def _metric_deltas(baseline: dict, candidate: dict) -> dict:
    keys = (
        "average_score", "automatic_approval_rate", "manual_review_rate", "reject_rate",
        "average_limit", "median_limit", "total_limit", "average_payment_term_days",
        "event_exposure_ratio", "restricted_event_capture_rate", "event_limit", "non_event_limit",
    )
    return {
        key: None if baseline[key] is None or candidate[key] is None else round(float(candidate[key]) - float(baseline[key]), 6)
        for key in keys
    }
