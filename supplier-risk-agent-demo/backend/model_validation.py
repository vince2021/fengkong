from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import sqrt

from backend.model_monitoring import build_monitoring_metrics
from rating.industry_context import preferred_industry_for_template
from rating.scorecard import rate_counterparty


RATING_ORDER = {"AAA": 1, "AA": 2, "A": 3, "BBB": 4, "BB": 5, "B": 6, "CCC": 7, "CC": 8, "C": 9, "D": 10}
MIN_RELEASE_SAMPLES = 5
MIN_RELEASE_COVERAGE = 0.60
MIN_LABELED_SAMPLES = 5


def build_model_validation_report(config: dict, counterparties: list[dict], template_key: str | None = None, monitoring_dataset: dict | None = None) -> dict:
    rows: list[dict] = []
    calculation_errors: list[dict] = []
    excluded: list[dict] = []
    completeness_values: list[float] = []
    template_key = str(template_key or config.get("key") or config.get("industry_template") or "general")
    validation_population = [counterparty for counterparty in counterparties if _is_in_validation_population(counterparty, template_key)]

    for counterparty in validation_population:
        try:
            result = rate_counterparty(counterparty, config)
        except (KeyError, TypeError, ValueError) as exc:
            calculation_errors.append({"counterparty_id": counterparty.get("id", "-"), "reason": str(exc)})
            continue
        if not result.get("ok"):
            excluded.append({"counterparty_id": counterparty.get("id", "-"), "reason": result.get("error", "模型不适用")})
            continue

        predicted_rating = _normalise_rating(result.get("rating"))
        observed_rating = _normalise_rating(counterparty.get("current_rating"))
        completeness = result.get("data_completeness")
        if isinstance(completeness, (int, float)):
            completeness_values.append(float(completeness))
        else:
            completeness_values.append(1.0)
        rows.append(
            {
                "counterparty_id": counterparty["id"],
                "counterparty_name": counterparty["name"],
                "score": float(result["total_score"]),
                "predicted_rating": predicted_rating,
                "observed_rating": observed_rating,
                "data_completeness": completeness_values[-1],
            }
        )

    total = len(validation_population)
    eligible = len(rows)
    labeled = [row for row in rows if row["predicted_rating"] and row["observed_rating"]]
    coverage_rate = eligible / total if total else 0.0
    labeled_rate = len(labeled) / eligible if eligible else 0.0
    average_completeness = sum(completeness_values) / len(completeness_values) if completeness_values else 0.0
    average_grade_gap = (
        sum(abs(RATING_ORDER[row["predicted_rating"]] - RATING_ORDER[row["observed_rating"]]) for row in labeled) / len(labeled)
        if labeled else None
    )
    high_risk_observed = [row for row in labeled if RATING_ORDER[row["observed_rating"]] >= RATING_ORDER["B"]]
    high_risk_recall = (
        sum(RATING_ORDER[row["predicted_rating"]] >= RATING_ORDER["B"] for row in high_risk_observed) / len(high_risk_observed)
        if high_risk_observed else None
    )
    concordance = _pairwise_concordance(labeled)
    scores = [row["score"] for row in rows]
    score_mean = sum(scores) / len(scores) if scores else 0.0
    score_std = sqrt(sum((score - score_mean) ** 2 for score in scores) / len(scores)) if scores else 0.0

    hard_gates = [
        _gate("sample_size", "适用验证样本", eligible >= MIN_RELEASE_SAMPLES, eligible, f">={MIN_RELEASE_SAMPLES}"),
        _gate("coverage", "样本计算覆盖率", coverage_rate >= MIN_RELEASE_COVERAGE, round(coverage_rate, 4), f">={MIN_RELEASE_COVERAGE:.0%}"),
        _gate("labeled_samples", "可回测标签样本", len(labeled) >= MIN_LABELED_SAMPLES, len(labeled), f">={MIN_LABELED_SAMPLES}"),
        _gate("calculation_integrity", "计算完整性", not calculation_errors, len(calculation_errors), "=0 个错误"),
    ]
    release_passed = all(item["passed"] for item in hard_gates)
    failed_labels = [item["label"] for item in hard_gates if not item["passed"]]

    metrics = [
        _metric("sample_coverage", "样本覆盖率", coverage_rate, "percent", "pass" if coverage_rate >= MIN_RELEASE_COVERAGE else "fail", "适用样本 / 全部验证样本"),
        _metric("labeled_coverage", "标签覆盖率", labeled_rate, "percent", "pass" if len(labeled) >= MIN_LABELED_SAMPLES else "fail", "具备可比信用等级的适用样本"),
        _metric("grade_gap", "平均等级偏差", average_grade_gap, "grade", _threshold_status(average_grade_gap, 1.5, lower_is_better=True), "预测等级与当前基准等级的平均档位差"),
        _metric("high_risk_recall", "高风险召回率", high_risk_recall, "percent", _threshold_status(high_risk_recall, 0.75), "基准为 B 级及以下样本的识别比例"),
        _metric("rank_concordance", "风险排序一致率", concordance, "percent", _threshold_status(concordance, 0.70), "有序样本对的预测风险方向一致率"),
        _metric("data_completeness", "平均数据完整度", average_completeness, "percent", "pass" if average_completeness >= 0.80 else "warn", "模型实际使用字段的平均可用程度"),
    ]

    rating_distribution = Counter(row["predicted_rating"] or "未映射" for row in rows)
    monitoring = build_monitoring_metrics(monitoring_dataset)
    findings: list[str] = []
    if not release_passed:
        findings.append(f"发布硬门槛未通过：{'、'.join(failed_labels)}")
    if average_grade_gap is not None and average_grade_gap > 1.5:
        findings.append("预测等级与基准等级偏差较大，需要补充样本并重新校准等级映射")
    if average_completeness < 0.80:
        findings.append("输入数据完整度不足，验证结果需附带人工复核和保守策略")
    failed_monitoring = [item["label"] for item in monitoring.get("performance_metrics", []) if item.get("status") == "fail"]
    if failed_monitoring:
        findings.append(f"回溯监控存在未达标指标：{'、'.join(failed_monitoring)}")
    if (monitoring.get("dataset") or {}).get("evidence_level") == "simulation_proxy":
        findings.append("当前跨期与事件标签为演示代理数据，只能验证计算链，正式发布前必须替换为真实观察样本")
    if len(labeled) < 30:
        findings.append("当前仍属于小样本验证，区分度与校准指标仅用于预验证，不替代正式回溯检验")
    if not findings:
        findings.append("当前预验证未发现阻断项，发布后仍需按月监控漂移并按季回溯")

    return {
        "snapshot_id": f"{template_key}:{config.get('version', 'unknown')}:{eligible}:{len(labeled)}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "template_key": template_key,
        "model_name": config.get("name"),
        "model_version": config.get("version"),
        "release_gate": {
            "passed": release_passed,
            "status": "pass" if release_passed else "blocked",
            "summary": "满足预发布验证硬门槛" if release_passed else f"需补齐：{'、'.join(failed_labels)}",
            "gates": hard_gates,
        },
        "sample_profile": {
            "portfolio_count": len(counterparties),
            "total_count": total,
            "out_of_scope_count": len(counterparties) - total,
            "eligible_count": eligible,
            "excluded_count": len(excluded),
            "calculation_error_count": len(calculation_errors),
            "labeled_count": len(labeled),
            "coverage_rate": round(coverage_rate, 4),
            "labeled_rate": round(labeled_rate, 4),
        },
        "metrics": metrics,
        "score_distribution": {
            "mean": round(score_mean, 2),
            "std": round(score_std, 2),
            "min": round(min(scores), 2) if scores else None,
            "max": round(max(scores), 2) if scores else None,
            "rating_counts": dict(sorted(rating_distribution.items(), key=lambda item: RATING_ORDER.get(item[0], 99))),
        },
        "monitoring": monitoring,
        "findings": findings,
        "excluded_samples": excluded[:20],
        "calculation_errors": calculation_errors[:20],
    }


def _normalise_rating(value: object) -> str | None:
    text = str(value or "").strip().upper()
    if not text or "未评级" in text:
        return None
    for rating in sorted(RATING_ORDER, key=len, reverse=True):
        if text.startswith(rating):
            return rating
    return None


def _is_in_validation_population(counterparty: dict, template_key: str) -> bool:
    recommended_model = counterparty.get("data_quality", {}).get("recommended_model")
    if recommended_model:
        return recommended_model == template_key
    if template_key == "corporate_credit_v2":
        return False
    return counterparty.get("industry") == preferred_industry_for_template(template_key)


def _pairwise_concordance(rows: list[dict]) -> float | None:
    comparable = 0
    concordant = 0
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            observed_delta = RATING_ORDER[left["observed_rating"]] - RATING_ORDER[right["observed_rating"]]
            predicted_delta = RATING_ORDER[left["predicted_rating"]] - RATING_ORDER[right["predicted_rating"]]
            if observed_delta == 0:
                continue
            comparable += 1
            if observed_delta * predicted_delta > 0:
                concordant += 1
            elif predicted_delta == 0:
                concordant += 0.5
    return concordant / comparable if comparable else None


def _gate(key: str, label: str, passed: bool, actual: int | float, threshold: str) -> dict:
    return {"key": key, "label": label, "passed": passed, "actual": actual, "threshold": threshold}


def _metric(key: str, label: str, value: float | None, unit: str, status: str, description: str) -> dict:
    return {"key": key, "label": label, "value": round(value, 4) if value is not None else None, "unit": unit, "status": status, "description": description}


def _threshold_status(value: float | None, threshold: float, *, lower_is_better: bool = False) -> str:
    if value is None:
        return "not_testable"
    passed = value <= threshold if lower_is_better else value >= threshold
    return "pass" if passed else "warn"
