from __future__ import annotations

from math import log


def build_monitoring_metrics(dataset: dict | None) -> dict:
    if not dataset:
        return {
            "dataset": None,
            "population_stability": {"status": "not_testable", "value": None, "reason": "尚未接入跨期样本快照，无法计算 PSI"},
            "backtesting": {"status": "blocked", "sample_count": 0, "event_count": 0, "non_event_count": 0},
            "performance_metrics": [],
            "recommended_frequency": "月度数据漂移监控、季度回溯验证、年度全面重检",
        }

    baseline = dataset.get("baseline", {}).get("score_band_counts", {})
    current = dataset.get("current", {}).get("score_band_counts", {})
    bins = dataset.get("backtest_bins", [])
    psi = _population_stability_index(baseline, current)
    auc = _auc_from_bins(bins)
    ks = _ks_from_bins(bins)
    brier = _brier_from_bins(bins)
    event_count = sum(int(item.get("event_count", 0)) for item in bins)
    non_event_count = sum(int(item.get("non_event_count", 0)) for item in bins)
    sample_count = event_count + non_event_count
    actual_event_rate = event_count / sample_count if sample_count else None
    expected_event_rate = (
        sum(float(item.get("average_pd", 0)) * (int(item.get("event_count", 0)) + int(item.get("non_event_count", 0))) for item in bins) / sample_count
        if sample_count else None
    )
    calibration_gap = abs(actual_event_rate - expected_event_rate) if actual_event_rate is not None and expected_event_rate is not None else None

    return {
        "dataset": {
            "dataset_id": dataset.get("dataset_id"),
            "name": dataset.get("name"),
            "evidence_level": dataset.get("evidence_level", "unknown"),
            "label_definition": dataset.get("label_definition"),
            "source": dataset.get("source"),
            "baseline_period": dataset.get("baseline", {}).get("period"),
            "current_period": dataset.get("current", {}).get("period"),
        },
        "population_stability": {
            "status": _psi_status(psi),
            "value": round(psi, 4) if psi is not None else None,
            "reason": "PSI < 0.10 稳定，0.10-0.25 关注，>= 0.25 触发重检" if psi is not None else "跨期分布数据不足",
            "baseline_distribution": baseline,
            "current_distribution": current,
        },
        "backtesting": {
            "status": "ready" if sample_count >= 30 and event_count >= 5 and non_event_count >= 5 else "blocked",
            "sample_count": sample_count,
            "event_count": event_count,
            "non_event_count": non_event_count,
            "actual_event_rate": round(actual_event_rate, 4) if actual_event_rate is not None else None,
            "expected_event_rate": round(expected_event_rate, 4) if expected_event_rate is not None else None,
            "calibration_gap": round(calibration_gap, 4) if calibration_gap is not None else None,
        },
        "performance_metrics": [
            _metric("psi", "PSI", psi, _psi_status(psi), "跨期评分分布稳定性"),
            _metric("auc", "AUC", auc, _higher_status(auc, 0.70, 0.60), "模型区分事件与非事件样本的能力"),
            _metric("ks", "KS", ks, _higher_status(ks, 0.30, 0.20), "事件与非事件累计分布最大差异"),
            _metric("brier", "Brier Score", brier, _lower_status(brier, 0.20, 0.25), "预测概率与事件结果的均方误差"),
            _metric("calibration_gap", "事件率偏差", calibration_gap, _lower_status(calibration_gap, 0.05, 0.10), "实际事件率与平均预测概率的绝对差"),
        ],
        "recommended_frequency": "月度 PSI、季度 AUC/KS/Brier 回溯、年度等级与 PD 映射重检",
    }


def _population_stability_index(baseline: dict, current: dict) -> float | None:
    keys = list(dict.fromkeys([*baseline.keys(), *current.keys()]))
    baseline_total = sum(float(baseline.get(key, 0)) for key in keys)
    current_total = sum(float(current.get(key, 0)) for key in keys)
    if not keys or baseline_total <= 0 or current_total <= 0:
        return None
    epsilon = 0.0001
    value = 0.0
    for key in keys:
        baseline_share = max(float(baseline.get(key, 0)) / baseline_total, epsilon)
        current_share = max(float(current.get(key, 0)) / current_total, epsilon)
        value += (current_share - baseline_share) * log(current_share / baseline_share)
    return value


def _auc_from_bins(bins: list[dict]) -> float | None:
    ordered = sorted(bins, key=lambda item: float(item.get("average_pd", 0)), reverse=True)
    events = sum(int(item.get("event_count", 0)) for item in ordered)
    non_events = sum(int(item.get("non_event_count", 0)) for item in ordered)
    if not events or not non_events:
        return None
    concordant = 0.0
    lower_non_events = non_events
    for item in ordered:
        event_count = int(item.get("event_count", 0))
        non_event_count = int(item.get("non_event_count", 0))
        lower_non_events -= non_event_count
        concordant += event_count * lower_non_events + 0.5 * event_count * non_event_count
    return concordant / (events * non_events)


def _ks_from_bins(bins: list[dict]) -> float | None:
    ordered = sorted(bins, key=lambda item: float(item.get("average_pd", 0)), reverse=True)
    events = sum(int(item.get("event_count", 0)) for item in ordered)
    non_events = sum(int(item.get("non_event_count", 0)) for item in ordered)
    if not events or not non_events:
        return None
    cumulative_events = 0
    cumulative_non_events = 0
    maximum = 0.0
    for item in ordered:
        cumulative_events += int(item.get("event_count", 0))
        cumulative_non_events += int(item.get("non_event_count", 0))
        maximum = max(maximum, abs(cumulative_events / events - cumulative_non_events / non_events))
    return maximum


def _brier_from_bins(bins: list[dict]) -> float | None:
    weighted_error = 0.0
    count = 0
    for item in bins:
        probability = float(item.get("average_pd", 0))
        events = int(item.get("event_count", 0))
        non_events = int(item.get("non_event_count", 0))
        weighted_error += events * (1 - probability) ** 2 + non_events * probability**2
        count += events + non_events
    return weighted_error / count if count else None


def _metric(key: str, label: str, value: float | None, status: str, description: str) -> dict:
    return {"key": key, "label": label, "value": round(value, 4) if value is not None else None, "status": status, "description": description}


def _psi_status(value: float | None) -> str:
    if value is None:
        return "not_testable"
    return "pass" if value < 0.10 else "warn" if value < 0.25 else "fail"


def _higher_status(value: float | None, pass_threshold: float, warn_threshold: float) -> str:
    if value is None:
        return "not_testable"
    return "pass" if value >= pass_threshold else "warn" if value >= warn_threshold else "fail"


def _lower_status(value: float | None, pass_threshold: float, warn_threshold: float) -> str:
    if value is None:
        return "not_testable"
    return "pass" if value <= pass_threshold else "warn" if value <= warn_threshold else "fail"
