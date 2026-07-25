from __future__ import annotations

from collections import defaultdict


SCORE_BANDS = (
    ("0-50", 0, 50),
    ("50-60", 50, 60),
    ("60-70", 60, 70),
    ("70-80", 70, 80),
    ("80-90", 80, 90),
    ("90-100", 90, 101),
)


def build_observed_monitoring_dataset(template_key: str, outcomes: list[dict]) -> tuple[dict | None, dict]:
    periods = sorted({str(item["population_period"]) for item in outcomes})
    event_count = sum(bool(item["observed_event"]) for item in outcomes)
    non_event_count = len(outcomes) - event_count
    readiness = {
        "observation_count": len(outcomes),
        "period_count": len(periods),
        "periods": periods,
        "event_count": event_count,
        "non_event_count": non_event_count,
        "minimums": {"observations": 30, "periods": 2, "events": 5, "non_events": 5},
    }
    readiness["formal_backtest_ready"] = (
        len(outcomes) >= 30 and len(periods) >= 2 and event_count >= 5 and non_event_count >= 5
    )
    if not outcomes:
        readiness["summary"] = "尚未接入真实结果观察记录"
        return None, readiness

    missing = []
    if len(outcomes) < 30:
        missing.append(f"观察记录还差 {30 - len(outcomes)} 条")
    if len(periods) < 2:
        missing.append("还需至少 1 个独立跨期样本期间")
    if event_count < 5:
        missing.append(f"事件样本还差 {5 - event_count} 条")
    if non_event_count < 5:
        missing.append(f"非事件样本还差 {5 - non_event_count} 条")
    readiness["summary"] = "已达到正式回溯最低门槛" if readiness["formal_backtest_ready"] else "；".join(missing)

    baseline_period = periods[0]
    current_period = periods[-1]
    period_distributions: dict[str, dict[str, int]] = {
        period: {label: 0 for label, _, _ in SCORE_BANDS} for period in periods
    }
    grouped: dict[str, dict[str, float | int]] = defaultdict(lambda: {"pd_sum": 0.0, "event_count": 0, "non_event_count": 0})
    for item in outcomes:
        band = _score_band(float(item["predicted_score"]))
        period_distributions[str(item["population_period"])][band] += 1
        group = grouped[band]
        group["pd_sum"] = float(group["pd_sum"]) + float(item["predicted_pd"])
        key = "event_count" if item["observed_event"] else "non_event_count"
        group[key] = int(group[key]) + 1

    bins = []
    for label, _, _ in SCORE_BANDS:
        group = grouped[label]
        count = int(group["event_count"]) + int(group["non_event_count"])
        if count:
            bins.append(
                {
                    "score_band": label,
                    "average_pd": float(group["pd_sum"]) / count,
                    "event_count": int(group["event_count"]),
                    "non_event_count": int(group["non_event_count"]),
                }
            )

    dataset = {
        "dataset_id": f"observed-{template_key}-{baseline_period}-{current_period}",
        "name": f"{template_key} 真实结果观察数据集",
        "evidence_level": "observed_outcome",
        "label_definition": "来自业务系统的到期观察结果；达到最低样本门槛后可用于正式模型回溯，仍需核对标签口径与数据血缘。",
        "source": "模型结果观察台账",
        "baseline": {"period": baseline_period, "score_band_counts": period_distributions[baseline_period]},
        "current": {"period": current_period, "score_band_counts": period_distributions[current_period]},
        "backtest_bins": bins,
    }
    return dataset, readiness


def select_effective_monitoring_dataset(observed_dataset: dict | None, readiness: dict, proxy_dataset: dict | None) -> tuple[dict | None, str]:
    if observed_dataset and readiness.get("formal_backtest_ready"):
        return observed_dataset, "observed_outcome"
    if proxy_dataset:
        return proxy_dataset, "simulation_proxy"
    return observed_dataset, "observed_outcome_pending" if observed_dataset else "none"


def _score_band(score: float) -> str:
    for label, minimum, maximum in SCORE_BANDS:
        if minimum <= score < maximum:
            return label
    raise ValueError("预测评分必须介于 0 与 100 之间")
