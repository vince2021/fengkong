from __future__ import annotations

from datetime import date, datetime
from math import isfinite, log
from typing import Any

from rating.rules import get_field_value


DEFAULT_VALIDATION_THRESHOLDS = {
    "require_validation_snapshot": True,
    "require_oot_snapshot": True,
    "require_probability_evidence": False,
    "require_sensitive_attribute_evidence": False,
    "min_auc": 0.6,
    "min_ks": 0.2,
    "max_brier": 0.25,
    "max_score_psi": 0.25,
    "min_segment_coverage": 0.8,
    "max_event_rate_gap": 0.2,
    "max_average_score_gap": 15.0,
    "max_auc_gap": 0.15,
    "max_ks_gap": 0.15,
    "max_false_positive_rate_gap": 0.15,
    "max_false_negative_rate_gap": 0.15,
}


def analyze_scorecard_development(config: dict, snapshot: dict, policy: dict) -> dict:
    positive = {str(value).strip().lower() for value in policy["positive_labels"]}
    start = _as_date(policy.get("observation_start"))
    end = _as_date(policy.get("observation_end"))
    as_of = _as_date(snapshot["as_of_date"])
    eligible: list[dict] = []
    exclusions: dict[str, int] = {}
    unlabeled = immature = outside_window = 0

    for row in snapshot["samples"]:
        sample = row["sample"]
        reason = _exclusion_reason(sample, policy.get("exclusion_rules") or [])
        if reason:
            exclusions[reason] = exclusions.get(reason, 0) + 1
            continue
        observed = _as_date(row.get("observed_at"))
        if observed and ((start and observed < start) or (end and observed > end)):
            outside_window += 1
            continue
        if observed and as_of and (as_of - observed).days < int(policy["maturity_days"]):
            immature += 1
            continue
        label = row.get("label")
        if label in (None, ""):
            unlabeled += 1
            continue
        eligible.append({"sample": sample, "event": str(label).strip().lower() in positive})

    event_count = sum(1 for row in eligible if row["event"])
    non_event_count = len(eligible) - event_count
    gates = {
        "sample_count": {"actual": len(eligible), "required": int(policy["min_sample_count"]), "passed": len(eligible) >= int(policy["min_sample_count"])},
        "event_count": {"actual": event_count, "required": int(policy["min_event_count"]), "passed": event_count >= int(policy["min_event_count"])},
        "non_event_count": {"actual": non_event_count, "required": int(policy["min_non_event_count"]), "passed": non_event_count >= int(policy["min_non_event_count"])},
    }

    sufficient = all(item["passed"] for item in gates.values())
    if not eligible:
        evidence_level = "unlabeled"
    elif sufficient:
        evidence_level = "labeled"
    else:
        evidence_level = "degraded"

    indicators = [_analyze_indicator(item, eligible, event_count, non_event_count) for item in config["indicators"]]
    total_iv = round(sum(item["information_value"] for item in indicators), 6)
    return {
        "schema_version": "scorecard-development-report-v1",
        "evidence_level": evidence_level,
        "summary": {
            "snapshot_sample_count": snapshot["sample_count"], "eligible_sample_count": len(eligible),
            "event_count": event_count, "non_event_count": non_event_count,
            "unlabeled_count": unlabeled, "immature_count": immature, "outside_window_count": outside_window,
            "excluded_count": sum(exclusions.values()), "exclusion_reasons": exclusions,
            "total_information_value": total_iv,
        },
        "gates": gates,
        "label_definition": {
            "positive_labels": policy["positive_labels"], "observation_start": policy.get("observation_start"),
            "observation_end": policy.get("observation_end"), "performance_window_days": policy["performance_window_days"],
            "maturity_days": policy["maturity_days"],
        },
        "indicators": indicators,
        "warnings": _warnings(evidence_level, gates, snapshot, policy),
    }


def analyze_scorecard_validation(config: dict, snapshots: dict[str, dict | None], policy: dict) -> dict:
    training = snapshots["training"]
    report = analyze_scorecard_development(config, training, policy)
    report["schema_version"] = "scorecard-development-report-v2"
    subject_field = policy.get("subject_id_field") or "id"
    subject_sets = {
        key: _subject_ids(snapshot, subject_field)
        for key, snapshot in snapshots.items() if snapshot is not None
    }
    overlaps = []
    keys = list(subject_sets)
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            duplicates = sorted(subject_sets[left] & subject_sets[right])
            if duplicates:
                overlaps.append({"left": left, "right": right, "count": len(duplicates), "sample_ids": duplicates[:20]})
    if overlaps:
        pairs = "、".join(f"{item['left']}/{item['right']} {item['count']} 户" for item in overlaps)
        raise ValueError(f"训练、验证和时间外集合存在主体泄漏：{pairs}")

    performance: dict[str, dict | None] = {}
    for key, snapshot in snapshots.items():
        if snapshot is None:
            performance[key] = None
            continue
        eligible = _eligible_samples(snapshot, policy)
        performance[key] = _performance_metrics(config, eligible, policy)
    baseline = performance["training"]
    for key in ("validation", "oot"):
        if performance[key] is not None:
            performance[key]["score_psi"] = _psi(baseline["score_distribution"], performance[key]["score_distribution"])
    baseline["score_psi"] = 0.0
    report["performance"] = performance
    report["split_evidence"] = {
        "subject_id_field": subject_field, "leakage_passed": True, "overlaps": [],
        "snapshots": {key: ({"id": value["id"], "content_hash": value["content_hash"], "as_of_date": value["as_of_date"]} if value else None) for key, value in snapshots.items()},
    }
    if performance["validation"] is None:
        report["warnings"].append("未固定验证集快照，无法提供独立验证性能")
    if performance["oot"] is None:
        report["warnings"].append("未固定时间外快照，无法提供跨期稳定性证据")
    if not policy.get("predicted_probability_field"):
        report["warnings"].append("未配置预测概率字段，Brier 与校准曲线不可测试")
    segment_fields = policy.get("segment_fields") or []
    if segment_fields:
        report["schema_version"] = "scorecard-development-report-v3"
        report["fairness"] = _fairness_analysis(config, snapshots, policy)
        report["warnings"].extend(report["fairness"]["warnings"])
    if policy.get("validation_thresholds"):
        report["schema_version"] = "scorecard-development-report-v4"
        report["validation_gate"] = _validation_gate(report, policy)
    return report


def _validation_gate(report: dict, policy: dict) -> dict:
    thresholds = {**DEFAULT_VALIDATION_THRESHOLDS, **(policy.get("validation_thresholds") or {})}
    checks: list[dict] = []
    warnings: list[str] = []

    def check(key: str, label: str, scope: str, actual: float | None, threshold: float, operator: str, required: bool = True) -> None:
        testable = actual is not None
        passed = (actual >= threshold if operator == ">=" else actual <= threshold) if testable else not required
        detail = f"{scope} {label} {'达到' if passed else '未达到'}门槛"
        if not testable:
            detail = f"{scope} {label}不可测试" + ("，形成阻断" if required else "，保留警告")
        checks.append({
            "key": key, "label": label, "scope": scope, "actual": actual,
            "threshold": threshold, "operator": operator, "testable": testable,
            "passed": passed, "detail": detail,
        })
        if not testable and not required:
            warnings.append(detail)

    performance = report.get("performance") or {}
    for split, required_key, split_label in (
        ("validation", "require_validation_snapshot", "验证集"),
        ("oot", "require_oot_snapshot", "时间外集"),
    ):
        metrics = performance.get(split)
        if metrics is None:
            if thresholds[required_key]:
                checks.append({
                    "key": f"{split}.snapshot", "label": f"{split_label}快照", "scope": split_label,
                    "actual": None, "threshold": 1, "operator": "present", "testable": False,
                    "passed": False, "detail": f"未固定{split_label}快照，形成阻断",
                })
            else:
                warnings.append(f"未固定{split_label}快照，该集合门槛不可测试")
            continue
        check(f"{split}.auc", "AUC", split_label, metrics.get("auc"), thresholds["min_auc"], ">=")
        check(f"{split}.ks", "KS", split_label, metrics.get("ks"), thresholds["min_ks"], ">=")
        check(f"{split}.brier", "Brier", split_label, metrics.get("brier"), thresholds["max_brier"], "<=", thresholds["require_probability_evidence"])
        check(f"{split}.score_psi", "分数 PSI", split_label, metrics.get("score_psi"), thresholds["max_score_psi"], "<=")

    fairness = report.get("fairness")
    sensitive_fields = set((fairness or {}).get("sensitive_attribute_fields") or [])
    if thresholds["require_sensitive_attribute_evidence"] and not sensitive_fields:
        checks.append({
            "key": "fairness.sensitive_attributes", "label": "敏感属性证据", "scope": "分群公平性",
            "actual": None, "threshold": 1, "operator": "present", "testable": False,
            "passed": False, "detail": "机构要求敏感属性证据，但未配置敏感属性字段",
        })
    if fairness:
        gap_thresholds = {
            "event_rate_gap": ("事件率差", "max_event_rate_gap"),
            "average_score_gap": ("平均分差", "max_average_score_gap"),
            "auc_gap": ("AUC 差", "max_auc_gap"),
            "ks_gap": ("KS 差", "max_ks_gap"),
            "false_positive_rate_gap": ("FPR 差", "max_false_positive_rate_gap"),
            "false_negative_rate_gap": ("FNR 差", "max_false_negative_rate_gap"),
        }
        for split in ("validation", "oot"):
            split_report = fairness["splits"].get(split) or {}
            for field, field_report in split_report.items():
                scope = f"{'验证集' if split == 'validation' else '时间外集'} / {field}"
                sensitive_required = field in sensitive_fields and thresholds["require_sensitive_attribute_evidence"]
                check(f"{split}.{field}.coverage", "属性覆盖率", scope, field_report.get("coverage_rate"), thresholds["min_segment_coverage"], ">=", sensitive_required or field_report.get("status") == "tested")
                for gap_key, (label, threshold_key) in gap_thresholds.items():
                    check(f"{split}.{field}.{gap_key}", label, scope, field_report["disparities"].get(gap_key), thresholds[threshold_key], "<=", sensitive_required)
                for group in field_report.get("groups") or []:
                    check(f"{split}.{field}.{group['group']}.score_psi", f"群体 {group['group']} 分数 PSI", scope, group.get("score_psi"), thresholds["max_score_psi"], "<=", False)

    violations = [item for item in checks if not item["passed"]]
    return {
        "passed": not violations,
        "summary": "全部验证门槛通过" if not violations else f"{len(violations)} 项验证门槛未通过",
        "thresholds": thresholds, "checks": checks, "violations": violations, "warnings": warnings,
    }


def _analyze_indicator(indicator: dict, eligible: list[dict], total_events: int, total_non_events: int) -> dict:
    rows = [{"bin_index": index, "bin_kind": item["kind"], "bin_label": item["label"], "configured_woe": item.get("woe"), "sample_count": 0, "event_count": 0} for index, item in enumerate(indicator["bins"])]
    unmatched = 0
    for item in eligible:
        index = _matching_bin(get_field_value(item["sample"], indicator["field_path"]), indicator["bins"])
        if index is None:
            unmatched += 1
            continue
        rows[index]["sample_count"] += 1
        rows[index]["event_count"] += int(item["event"])
    smoothing = 0.5
    bin_count = len(rows)
    iv = 0.0
    supervised = total_events > 0 and total_non_events > 0
    for row in rows:
        row["non_event_count"] = row["sample_count"] - row["event_count"]
        row["event_rate"] = round(row["event_count"] / row["sample_count"], 6) if row["sample_count"] else None
        event_distribution = (row["event_count"] + smoothing) / (total_events + smoothing * bin_count) if supervised else 0
        non_event_distribution = (row["non_event_count"] + smoothing) / (total_non_events + smoothing * bin_count) if supervised else 0
        calculated_woe = log(non_event_distribution / event_distribution) if supervised else None
        contribution = (non_event_distribution - event_distribution) * calculated_woe if calculated_woe is not None else None
        row["calculated_woe"] = round(calculated_woe, 6) if calculated_woe is not None else None
        row["iv_contribution"] = round(contribution, 6) if contribution is not None else None
        row["woe_source"] = "sample_calculated"
        iv += contribution or 0
    ordered_rates = [row["event_rate"] for row in rows if row["bin_kind"] == "range" and row["event_rate"] is not None]
    monotonic = None if len(ordered_rates) < 2 else ordered_rates == sorted(ordered_rates) or ordered_rates == sorted(ordered_rates, reverse=True)
    return {
        "indicator_code": indicator["indicator_code"], "indicator_version": indicator["indicator_version"],
        "indicator_name": indicator["indicator_name"], "field_path": indicator["field_path"],
        "sample_count": sum(row["sample_count"] for row in rows), "unmatched_count": unmatched,
        "missing_count": next((row["sample_count"] for row in rows if row["bin_kind"] == "missing"), 0),
        "information_value": round(iv, 6), "event_rate_monotonic": monotonic, "bins": rows,
    }


def _matching_bin(value: Any, bins: list[dict]) -> int | None:
    for index, row in enumerate(bins):
        if value is None and row["kind"] == "missing":
            return index
        if value is None:
            continue
        if row["kind"] == "range" and _in_range(value, row):
            return index
        if row["kind"] == "category" and str(value).strip().lower() in {str(item).strip().lower() for item in row.get("values") or []}:
            return index
    return None


def _eligible_samples(snapshot: dict, policy: dict) -> list[dict]:
    positive = {str(value).strip().lower() for value in policy["positive_labels"]}
    start, end = _as_date(policy.get("observation_start")), _as_date(policy.get("observation_end"))
    as_of = _as_date(snapshot["as_of_date"])
    rows = []
    for entry in snapshot["samples"]:
        sample = entry["sample"]
        if _exclusion_reason(sample, policy.get("exclusion_rules") or []):
            continue
        observed = _as_date(entry.get("observed_at"))
        if observed and ((start and observed < start) or (end and observed > end)):
            continue
        if observed and as_of and (as_of - observed).days < int(policy["maturity_days"]):
            continue
        label = entry.get("label")
        if label in (None, ""):
            continue
        rows.append({"sample": sample, "event": str(label).strip().lower() in positive})
    return rows


def _subject_ids(snapshot: dict, field: str) -> set[str]:
    values = []
    for index, entry in enumerate(snapshot["samples"], start=1):
        value = get_field_value(entry["sample"], field)
        if value in (None, ""):
            raise ValueError(f"快照 {snapshot['id']} 第 {index} 条样本缺少主体标识字段 {field}")
        values.append(str(value))
    if len(set(values)) != len(values):
        raise ValueError(f"快照 {snapshot['id']} 的主体标识字段 {field} 存在重复")
    return set(values)


def _performance_metrics(config: dict, eligible: list[dict], policy: dict) -> dict:
    rows = _scored_rows(config, eligible, policy)
    events = sum(row["event"] for row in rows)
    non_events = len(rows) - events
    probabilities = [row for row in rows if row["probability"] is not None]
    return {
        "sample_count": len(rows), "event_count": events, "non_event_count": non_events,
        "auc": _auc(rows), "ks": _ks(rows),
        "brier": round(sum((row["probability"] - int(row["event"])) ** 2 for row in probabilities) / len(probabilities), 6) if probabilities else None,
        "probability_coverage_rate": round(len(probabilities) / len(rows), 6) if rows else 0,
        "calibration": _calibration(probabilities), "score_distribution": _score_distribution(rows),
    }


def _scored_rows(config: dict, eligible: list[dict], policy: dict) -> list[dict]:
    rows = []
    probability_field = policy.get("predicted_probability_field")
    for entry in eligible:
        score = _score_sample(config, entry["sample"])
        if score is None:
            continue
        probability = get_field_value(entry["sample"], probability_field) if probability_field else None
        try:
            probability = float(probability) if probability is not None else None
        except (TypeError, ValueError):
            probability = None
        if probability is not None and not 0 <= probability <= 1:
            probability = None
        rows.append({"sample": entry["sample"], "score": score, "risk_score": 100 - score, "event": bool(entry["event"]), "probability": probability})
    return rows


def _fairness_analysis(config: dict, snapshots: dict[str, dict | None], policy: dict) -> dict:
    fields = policy.get("segment_fields") or []
    sensitive = set(policy.get("sensitive_attribute_fields") or [])
    minimum = int(policy.get("min_segment_sample_count", 30))
    threshold = float(policy.get("classification_threshold", 0.5))
    split_rows = {
        key: (_scored_rows(config, _eligible_samples(snapshot, policy), policy) if snapshot else None)
        for key, snapshot in snapshots.items()
    }
    reports: dict[str, dict | None] = {}
    warnings: list[str] = []
    for split, rows in split_rows.items():
        if rows is None:
            reports[split] = None
            continue
        reports[split] = {}
        for field in fields:
            field_report = _segment_field_report(rows, field, field in sensitive, minimum, threshold)
            reports[split][field] = field_report
            if field_report["status"] == "untestable":
                kind = "敏感属性" if field in sensitive else "分群字段"
                warnings.append(f"{split} 集合的{kind} {field} 无有效值，分群差异不可测试")
            elif field_report["status"] == "too_many_groups":
                warnings.append(f"{split} 集合的分群字段 {field} 超过 50 个取值，不生成高基数分群结论")
    training = reports.get("training") or {}
    for split in ("validation", "oot"):
        current = reports.get(split) or {}
        for field in fields:
            if field not in current or field not in training:
                continue
            if training[field]["status"] != "tested" or current[field]["status"] != "tested":
                current[field]["population_psi"] = None
                continue
            current[field]["population_psi"] = _category_psi(training[field]["distribution"], current[field]["distribution"])
            training_groups = {row["group"]: row for row in training[field]["groups"]}
            for group in current[field]["groups"]:
                baseline = training_groups.get(group["group"])
                group["score_psi"] = _psi(baseline["score_distribution"], group["score_distribution"]) if baseline else None
    for field in fields:
        if field in training:
            training[field]["population_psi"] = 0.0 if training[field]["status"] == "tested" else None
            for group in training[field]["groups"]:
                group["score_psi"] = 0.0
    tested = any(
        field_report["status"] == "tested"
        for split_report in reports.values() if split_report
        for field_report in split_report.values()
    )
    return {
        "status": "tested" if tested else "untestable",
        "segment_fields": fields, "sensitive_attribute_fields": sorted(sensitive),
        "min_segment_sample_count": minimum, "classification_threshold": threshold,
        "splits": reports, "warnings": warnings,
    }


def _segment_field_report(rows: list[dict], field: str, sensitive: bool, minimum: int, threshold: float) -> dict:
    grouped: dict[str, list[dict]] = {}
    missing = 0
    for row in rows:
        value = get_field_value(row["sample"], field)
        if value in (None, ""):
            missing += 1
            continue
        grouped.setdefault(str(value), []).append(row)
    distribution = {key: len(value) for key, value in grouped.items()}
    distribution["__MISSING__"] = missing
    if not grouped:
        status = "untestable"
    elif len(grouped) > 50:
        status = "too_many_groups"
    else:
        status = "tested"
    groups = []
    if status == "tested":
        for key, selected in sorted(grouped.items()):
            probabilities = [row for row in selected if row["probability"] is not None]
            confusion = _classification_errors(probabilities, threshold) if len(probabilities) == len(selected) else {"false_positive_rate": None, "false_negative_rate": None}
            groups.append({
                "group": key, "sample_count": len(selected),
                "population_share": round(len(selected) / len(rows), 6) if rows else 0,
                "sample_sufficient": len(selected) >= minimum,
                "event_rate": round(sum(row["event"] for row in selected) / len(selected), 6),
                "average_score": round(sum(row["score"] for row in selected) / len(selected), 6),
                "auc": _auc(selected), "ks": _ks(selected),
                "false_positive_rate": confusion["false_positive_rate"],
                "false_negative_rate": confusion["false_negative_rate"],
                "probability_coverage_rate": round(len(probabilities) / len(selected), 6),
                "score_distribution": _score_distribution(selected),
            })
    sufficient = [row for row in groups if row["sample_sufficient"]]
    return {
        "field_path": field, "sensitive_attribute": sensitive, "status": status,
        "sample_count": len(rows), "covered_count": len(rows) - missing, "missing_count": missing,
        "coverage_rate": round((len(rows) - missing) / len(rows), 6) if rows else 0,
        "distribution": distribution, "group_count": len(grouped), "groups": groups,
        "disparities": _group_disparities(sufficient),
    }


def _classification_errors(rows: list[dict], threshold: float) -> dict:
    if not rows:
        return {"false_positive_rate": None, "false_negative_rate": None}
    non_events = [row for row in rows if not row["event"]]
    events = [row for row in rows if row["event"]]
    false_positives = sum(row["probability"] >= threshold for row in non_events)
    false_negatives = sum(row["probability"] < threshold for row in events)
    return {
        "false_positive_rate": round(false_positives / len(non_events), 6) if non_events else None,
        "false_negative_rate": round(false_negatives / len(events), 6) if events else None,
    }


def _group_disparities(groups: list[dict]) -> dict[str, float | None]:
    result = {}
    for key in ("event_rate", "average_score", "auc", "ks", "false_positive_rate", "false_negative_rate"):
        values = [row[key] for row in groups if row[key] is not None]
        result[f"{key}_gap"] = round(max(values) - min(values), 6) if len(values) >= 2 else None
    return result


def _category_psi(baseline: dict[str, int], comparison: dict[str, int]) -> float | None:
    keys = set(baseline) | set(comparison)
    return _psi({key: baseline.get(key, 0) for key in keys}, {key: comparison.get(key, 0) for key in keys})


def _score_sample(config: dict, sample: dict) -> float | None:
    total_weight = sum(float(item["weight"]) for item in config["indicators"])
    weighted = 0.0
    minimum = maximum = 0.0
    for indicator in config["indicators"]:
        index = _matching_bin(get_field_value(sample, indicator["field_path"]), indicator["bins"])
        if index is None:
            return None
        weight = float(indicator["weight"])
        scores = [float(row["score"]) for row in indicator["bins"]]
        weighted += float(indicator["bins"][index]["score"]) * weight
        minimum += min(scores) * weight
        maximum += max(scores) * weight
    raw, low, high = weighted / total_weight, minimum / total_weight, maximum / total_weight
    if high <= low:
        return None
    normalized = (raw - low) / (high - low) * 100
    if not bool(config["score_scale"].get("higher_is_better", True)):
        normalized = 100 - normalized
    return round(max(0.0, min(100.0, normalized)), 6)


def _auc(rows: list[dict]) -> float | None:
    if not rows or not any(row["event"] for row in rows) or all(row["event"] for row in rows):
        return None
    ordered = sorted(rows, key=lambda row: row["risk_score"])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end]["risk_score"] == ordered[index]["risk_score"]:
            end += 1
        average_rank = (index + 1 + end) / 2
        rank_sum += average_rank * sum(row["event"] for row in ordered[index:end])
        index = end
    events = sum(row["event"] for row in rows)
    non_events = len(rows) - events
    return round((rank_sum - events * (events + 1) / 2) / (events * non_events), 6)


def _ks(rows: list[dict]) -> float | None:
    events = sum(row["event"] for row in rows)
    non_events = len(rows) - events
    if not events or not non_events:
        return None
    cumulative_event = cumulative_non_event = 0
    maximum = 0.0
    for row in sorted(rows, key=lambda item: item["risk_score"], reverse=True):
        cumulative_event += int(row["event"])
        cumulative_non_event += int(not row["event"])
        maximum = max(maximum, abs(cumulative_event / events - cumulative_non_event / non_events))
    return round(maximum, 6)


def _score_distribution(rows: list[dict]) -> dict[str, int]:
    bins = {f"{start:02d}-{start + 9:02d}": 0 for start in range(0, 100, 10)}
    for row in rows:
        start = min(90, int(row["score"] // 10) * 10)
        bins[f"{start:02d}-{start + 9:02d}"] += 1
    return bins


def _psi(baseline: dict[str, int], comparison: dict[str, int]) -> float | None:
    baseline_total, comparison_total = sum(baseline.values()), sum(comparison.values())
    if not baseline_total or not comparison_total:
        return None
    value = 0.0
    for key in baseline:
        base_rate = max(baseline[key] / baseline_total, 1e-6)
        compare_rate = max(comparison.get(key, 0) / comparison_total, 1e-6)
        value += (compare_rate - base_rate) * log(compare_rate / base_rate)
    return round(value, 6)


def _calibration(rows: list[dict]) -> list[dict]:
    bins = []
    for start in (0, 0.2, 0.4, 0.6, 0.8):
        selected = [row for row in rows if start <= row["probability"] < start + 0.2 or start == 0.8 and row["probability"] == 1]
        bins.append({
            "range": f"{start:.1f}-{start + 0.2:.1f}", "sample_count": len(selected),
            "predicted_rate": round(sum(row["probability"] for row in selected) / len(selected), 6) if selected else None,
            "actual_rate": round(sum(row["event"] for row in selected) / len(selected), 6) if selected else None,
        })
    return bins


def _in_range(value: Any, row: dict) -> bool:
    try:
        actual = float(value)
        if not isfinite(actual):
            return False
    except (TypeError, ValueError):
        return False
    lower, upper = row.get("lower"), row.get("upper")
    lower_ok = lower is None or actual > float(lower) or bool(row.get("lower_inclusive", True)) and actual == float(lower)
    upper_ok = upper is None or actual < float(upper) or bool(row.get("upper_inclusive", False)) and actual == float(upper)
    return lower_ok and upper_ok


def _exclusion_reason(sample: dict, rules: list[dict]) -> str | None:
    for rule in rules:
        actual = get_field_value(sample, rule["field_path"])
        expected = rule.get("value")
        operator = rule["operator"]
        matched = operator == "is_missing" and actual is None or operator == "not_missing" and actual is not None
        matched = matched or operator == "equals" and actual == expected or operator == "not_equals" and actual != expected
        matched = matched or operator == "in" and actual in (expected if isinstance(expected, list) else [expected])
        if matched:
            return rule["reason"]
    return None


def _warnings(level: str, gates: dict, snapshot: dict, policy: dict) -> list[str]:
    warnings: list[str] = []
    if level == "unlabeled":
        warnings.append("快照没有可用标签，本报告仅保留样本覆盖证据，不提供监督 WOE/IV 结论")
    elif level == "degraded":
        failed = [key for key, value in gates.items() if not value["passed"]]
        warnings.append("监督样本未达到门槛：" + "、".join(failed))
    if not snapshot.get("observed_at_field"):
        warnings.append("快照未配置观察时间字段，无法验证观察窗口和成熟期")
    if int(policy["performance_window_days"]) < int(policy["maturity_days"]):
        warnings.append("表现窗口短于成熟期，请确认标签口径")
    return warnings


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
