from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from typing import Callable

from backend.credit_authority import build_credit_authority
from rating.scorecard import rate_counterparty


TIER_KEYS = ("standard", "enhanced", "committee")
TIER_ORDER = {key: index for index, key in enumerate(TIER_KEYS)}
MIN_IMPACT_SAMPLES = 5
MIN_IMPACT_COVERAGE = 0.60


def build_authority_policy_impact(
    *,
    active_policy: dict,
    candidate_config: dict,
    candidate_policy_version: str,
    counterparties: list[dict],
    model_config_resolver: Callable[[str], dict | None],
    population: dict | None = None,
) -> dict:
    candidate_hash = _content_hash(candidate_config)
    candidate_policy = {
        "id": None,
        "policy_version": candidate_policy_version,
        "config_hash": candidate_hash,
        "config": candidate_config,
        "source": "candidate",
    }
    config_diff = build_authority_policy_config_diff(active_policy["config"], candidate_config)
    population = population or build_authority_impact_population(counterparties, model_config_resolver)
    details: list[dict] = []
    for rated in population["rows"]:
        case = {
            "data": {
                "scoring": {"rating": rated["rating"]},
                "credit_proposal": {
                    "suggested_limit": rated["suggested_limit"],
                    "access_strategy": rated["access_strategy"],
                },
            }
        }
        before = build_credit_authority(case, active_policy)
        after = build_credit_authority(case, candidate_policy)
        before_slots = len(before["slots"])
        after_slots = len(after["slots"])
        tier_delta = TIER_ORDER[after["tier"]] - TIER_ORDER[before["tier"]]
        details.append(
            {
                **rated,
                "before_tier": before["tier"],
                "before_tier_label": before["tier_label"],
                "after_tier": after["tier"],
                "after_tier_label": after["tier_label"],
                "direction": "escalated" if tier_delta > 0 else "deescalated" if tier_delta < 0 else "unchanged",
                "before_signoff_count": before_slots,
                "after_signoff_count": after_slots,
                "signoff_delta": after_slots - before_slots,
                "drivers": _change_drivers(before, after, active_policy["config"], candidate_config),
            }
        )

    migration_matrix = {
        before: {after: 0 for after in TIER_KEYS}
        for before in TIER_KEYS
    }
    for row in details:
        migration_matrix[row["before_tier"]][row["after_tier"]] += 1
    eligible = len(details)
    total = population["portfolio_count"]
    coverage = eligible / total if total else 0.0
    gates = [
        _gate("sample_size", "有效评估样本", eligible >= MIN_IMPACT_SAMPLES, eligible, f">={MIN_IMPACT_SAMPLES}"),
        _gate("coverage", "样本计算覆盖率", coverage >= MIN_IMPACT_COVERAGE, round(coverage, 4), f">={MIN_IMPACT_COVERAGE:.0%}"),
        _gate("calculation_integrity", "计算完整性", not population["calculation_errors"], len(population["calculation_errors"]), "=0 个错误"),
    ]
    passed = all(item["passed"] for item in gates)
    failed_labels = [item["label"] for item in gates if not item["passed"]]
    before_distribution = Counter(item["before_tier"] for item in details)
    after_distribution = Counter(item["after_tier"] for item in details)
    return {
        "version": "authority-impact-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_policy_version": active_policy["policy_version"],
        "base_config_hash": active_policy["config_hash"],
        "candidate_policy_version": candidate_policy_version,
        "candidate_config_hash": candidate_hash,
        "config_diff": config_diff,
        "input_snapshot_hash": population["input_snapshot_hash"],
        "release_gate": {
            "passed": passed,
            "status": "pass" if passed else "blocked",
            "summary": "组合影响评估通过" if passed else f"需补齐：{'、'.join(failed_labels)}",
            "gates": gates,
        },
        "sample_profile": {
            "portfolio_count": total,
            "eligible_count": eligible,
            "skipped_count": len(population["skipped_samples"]),
            "calculation_error_count": len(population["calculation_errors"]),
            "coverage_rate": round(coverage, 4),
        },
        "summary": {
            "changed_count": sum(item["direction"] != "unchanged" for item in details),
            "escalated_count": sum(item["direction"] == "escalated" for item in details),
            "deescalated_count": sum(item["direction"] == "deescalated" for item in details),
            "slot_changed_count": sum(item["signoff_delta"] != 0 for item in details),
            "additional_signoffs": sum(max(item["signoff_delta"], 0) for item in details),
            "removed_signoffs": sum(max(-item["signoff_delta"], 0) for item in details),
            "escalated_limit": sum(item["suggested_limit"] for item in details if item["direction"] == "escalated"),
            "deescalated_limit": sum(item["suggested_limit"] for item in details if item["direction"] == "deescalated"),
        },
        "before_distribution": {key: before_distribution.get(key, 0) for key in TIER_KEYS},
        "after_distribution": {key: after_distribution.get(key, 0) for key in TIER_KEYS},
        "migration_matrix": migration_matrix,
        "details": details,
        "skipped_samples": population["skipped_samples"][:20],
        "calculation_errors": population["calculation_errors"][:20],
    }


def build_authority_policy_config_diff(base_config: dict, candidate_config: dict) -> dict:
    changes: list[dict] = []
    _append_threshold_change(
        changes,
        key="standard_limit",
        label="标准授权上限",
        before=base_config["standard_limit"],
        after=candidate_config["standard_limit"],
    )
    _append_threshold_change(
        changes,
        key="enhanced_limit",
        label="加强授权上限",
        before=base_config["enhanced_limit"],
        after=candidate_config["enhanced_limit"],
    )
    for key, label, add_direction, remove_direction in (
        ("low_risk_ratings", "低风险评级集合", "relaxed", "tightened"),
        ("high_risk_ratings", "高风险评级集合", "tightened", "relaxed"),
        ("restricted_strategies", "加强复核策略集合", "tightened", "relaxed"),
        ("prohibited_strategies", "委员会/禁止准入策略集合", "tightened", "relaxed"),
    ):
        _append_set_change(
            changes,
            key=key,
            label=label,
            before=base_config[key],
            after=candidate_config[key],
            add_direction=add_direction,
            remove_direction=remove_direction,
        )
    for tier_key in TIER_KEYS:
        base_tier = base_config["tiers"][tier_key]
        candidate_tier = candidate_config["tiers"][tier_key]
        _append_tier_slot_change(changes, tier_key, base_tier["label"], base_tier["slots"], candidate_tier["slots"])
        if base_tier["label"] != candidate_tier["label"]:
            changes.append(_change(
                f"tiers.{tier_key}.label",
                f"{base_tier['label']}名称",
                "tier_metadata",
                base_tier["label"],
                candidate_tier["label"],
                "neutral",
                "层级名称调整，不改变系统触发逻辑",
            ))
        if base_tier["reason"] != candidate_tier["reason"]:
            changes.append(_change(
                f"tiers.{tier_key}.reason",
                f"{base_tier['label']}触发说明",
                "tier_metadata",
                base_tier["reason"],
                candidate_tier["reason"],
                "neutral",
                "触发说明文案调整，不改变系统触发逻辑",
            ))

    direction_counts = Counter(item["direction"] for item in changes)
    material_directions = {item["direction"] for item in changes if item["direction"] in {"tightened", "relaxed", "mixed"}}
    if not changes:
        overall_direction = "unchanged"
    elif "mixed" in material_directions or {"tightened", "relaxed"}.issubset(material_directions):
        overall_direction = "mixed"
    elif "tightened" in material_directions:
        overall_direction = "tightened"
    elif "relaxed" in material_directions:
        overall_direction = "relaxed"
    else:
        overall_direction = "neutral"
    return {
        "version": "authority-config-diff-v1",
        "overall_direction": overall_direction,
        "summary": {
            "changed_field_count": len(changes),
            "tightened_count": direction_counts["tightened"],
            "relaxed_count": direction_counts["relaxed"],
            "mixed_count": direction_counts["mixed"],
            "neutral_count": direction_counts["neutral"],
        },
        "changes": changes,
        "method_note": "趋严/放宽依据额度边界、风险集合和会签席位的预设治理方向判定，仅用于辅助审阅，不构成风险偏好建议。",
    }


def build_authority_impact_population(
    counterparties: list[dict],
    model_config_resolver: Callable[[str], dict | None],
) -> dict:
    rows: list[dict] = []
    skipped: list[dict] = []
    calculation_errors: list[dict] = []
    for counterparty in counterparties:
        template_key = _template_key(counterparty)
        config = model_config_resolver(template_key)
        if not config:
            skipped.append(_skip(counterparty, template_key, "模型配置不存在"))
            continue
        try:
            rating = rate_counterparty(counterparty, config)
        except (KeyError, TypeError, ValueError) as exc:
            calculation_errors.append(_skip(counterparty, template_key, str(exc) or "评级计算失败"))
            continue
        if not rating.get("ok"):
            skipped.append(_skip(counterparty, template_key, rating.get("error") or "模型不适用"))
            continue
        rows.append(
            {
                "counterparty_id": counterparty["id"],
                "counterparty_name": counterparty["name"],
                "counterparty_type": counterparty["counterparty_type"],
                "template_key": template_key,
                "model_version": config.get("version", "-"),
                "model_config_hash": _content_hash(config),
                "rating": rating["rating"],
                "access_strategy": rating["access_strategy"],
                "suggested_limit": rating["suggested_limit"],
            }
        )
    rated_snapshot_rows = [
        {
            "status": "rated",
            **{
                key: row[key]
                for key in (
                    "counterparty_id",
                    "template_key",
                    "model_version",
                    "model_config_hash",
                    "rating",
                    "access_strategy",
                    "suggested_limit",
                )
            },
        }
        for row in rows
    ]
    unresolved_snapshot_rows = [
        {
            "status": status,
            "counterparty_id": item["counterparty_id"],
            "counterparty_name": item["counterparty_name"],
            "template_key": item["template_key"],
            "reason": item["reason"],
        }
        for status, items in (("skipped", skipped), ("calculation_error", calculation_errors))
        for item in items
    ]
    snapshot_rows = sorted(
        [*rated_snapshot_rows, *unresolved_snapshot_rows],
        key=lambda item: (str(item["counterparty_id"]), str(item["status"])),
    )
    return {
        "portfolio_count": len(counterparties),
        "rows": rows,
        "skipped_samples": skipped,
        "calculation_errors": calculation_errors,
        "input_snapshot_hash": _content_hash(snapshot_rows),
    }


def compare_authority_policy_scenarios(
    *,
    active_policy: dict,
    scenarios: list[dict],
    counterparties: list[dict],
    model_config_resolver: Callable[[str], dict | None],
) -> dict:
    if not 2 <= len(scenarios) <= 5:
        raise ValueError("多情景比较必须包含 2—5 个策略")
    keys = [str(item["key"]) for item in scenarios]
    if len(keys) != len(set(keys)):
        raise ValueError("情景标识不能重复")
    population = build_authority_impact_population(counterparties, model_config_resolver)
    results: list[dict] = []
    for scenario in scenarios:
        impact = build_authority_policy_impact(
            active_policy=active_policy,
            candidate_config=scenario["config"],
            candidate_policy_version=f"SCENARIO-{scenario['key']}",
            counterparties=counterparties,
            model_config_resolver=model_config_resolver,
            population=population,
        )
        total_signoffs = sum(item["after_signoff_count"] for item in impact["details"])
        enhanced_review_count = (
            impact["after_distribution"]["enhanced"]
            + impact["after_distribution"]["committee"]
        )
        results.append(
            {
                "key": scenario["key"],
                "name": scenario["name"],
                "description": scenario["description"],
                "config": scenario["config"],
                "config_hash": impact["candidate_config_hash"],
                "impact": impact,
                "metrics": {
                    "total_signoffs": total_signoffs,
                    "average_signoffs": round(total_signoffs / len(impact["details"]), 2) if impact["details"] else 0,
                    "standard_count": impact["after_distribution"]["standard"],
                    "enhanced_count": impact["after_distribution"]["enhanced"],
                    "committee_count": impact["after_distribution"]["committee"],
                    "enhanced_review_count": enhanced_review_count,
                    "control_intensity_index": impact["after_distribution"]["enhanced"] + impact["after_distribution"]["committee"] * 2,
                },
            }
        )
    snapshot_hashes = {item["impact"]["input_snapshot_hash"] for item in results}
    if len(snapshot_hashes) != 1:
        raise ValueError("多情景比较未使用同一输入快照，已停止输出")
    eligible = len(population["rows"])
    lowest_workload_value = min(item["metrics"]["total_signoffs"] for item in results)
    highest_control_value = max(item["metrics"]["control_intensity_index"] for item in results)
    lowest_workload_keys = [
        item["key"] for item in results
        if item["metrics"]["total_signoffs"] == lowest_workload_value
    ]
    highest_control_keys = [
        item["key"] for item in results
        if item["metrics"]["control_intensity_index"] == highest_control_value
    ]
    return {
        "version": "authority-scenario-comparison-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_policy_version": active_policy["policy_version"],
        "base_config_hash": active_policy["config_hash"],
        "input_snapshot_hash": population["input_snapshot_hash"],
        "sample_profile": {
            "portfolio_count": len(counterparties),
            "eligible_count": eligible,
            "coverage_rate": round(eligible / len(counterparties), 4) if counterparties else 0,
            "skipped_count": len(population["skipped_samples"]),
            "calculation_error_count": len(population["calculation_errors"]),
        },
        "lowest_workload_key": lowest_workload_keys[0],
        "highest_control_key": highest_control_keys[0],
        "lowest_workload_keys": lowest_workload_keys,
        "highest_control_keys": highest_control_keys,
        "scenarios": results,
    }


def _append_threshold_change(changes: list[dict], *, key: str, label: str, before: float, after: float) -> None:
    if before == after:
        return
    direction = "tightened" if after < before else "relaxed"
    changes.append(_change(
        key,
        label,
        "limit_threshold",
        before,
        after,
        direction,
        f"额度边界{'下调' if direction == 'tightened' else '上调'} {abs(after - before) / 10_000:g} 万元",
    ))


def _append_set_change(
    changes: list[dict],
    *,
    key: str,
    label: str,
    before: list[str],
    after: list[str],
    add_direction: str,
    remove_direction: str,
) -> None:
    before_set = set(before)
    after_set = set(after)
    added = [item for item in after if item not in before_set]
    removed = [item for item in before if item not in after_set]
    if not added and not removed:
        if before != after:
            changes.append({
                **_change(key, label, "risk_set", before, after, "neutral", "集合成员未变，仅调整展示顺序"),
                "added": [],
                "removed": [],
            })
        return
    directions = {
        direction
        for values, direction in ((added, add_direction), (removed, remove_direction))
        if values
    }
    direction = next(iter(directions)) if len(directions) == 1 else "mixed"
    descriptions = []
    if added:
        descriptions.append(f"新增：{'、'.join(added)}")
    if removed:
        descriptions.append(f"移除：{'、'.join(removed)}")
    changes.append({
        **_change(key, label, "risk_set", before, after, direction, "；".join(descriptions)),
        "added": added,
        "removed": removed,
    })


def _append_tier_slot_change(
    changes: list[dict],
    tier_key: str,
    tier_label: str,
    before: list[dict],
    after: list[dict],
) -> None:
    if before == after:
        return
    before_counts = Counter(slot["role"] for slot in before)
    after_counts = Counter(slot["role"] for slot in after)
    if len(after) > len(before):
        direction = "tightened"
    elif len(after) < len(before):
        direction = "relaxed"
    elif after_counts != before_counts:
        direction = "mixed"
    else:
        direction = "neutral"
    before_labels = [slot["label"] for slot in before]
    after_labels = [slot["label"] for slot in after]
    changes.append(_change(
        f"tiers.{tier_key}.slots",
        f"{tier_label}会签席位",
        "signoff_slots",
        before_labels,
        after_labels,
        direction,
        f"会签席位 {len(before)}→{len(after)}；风控 {before_counts['risk_manager']}→{after_counts['risk_manager']}，审批 {before_counts['approver']}→{after_counts['approver']}",
    ))


def _change(
    key: str,
    label: str,
    category: str,
    before: object,
    after: object,
    direction: str,
    rationale: str,
) -> dict:
    return {
        "key": key,
        "label": label,
        "category": category,
        "before": before,
        "after": after,
        "direction": direction,
        "rationale": rationale,
    }


def _template_key(counterparty: dict) -> str:
    recommended = counterparty.get("data_quality", {}).get("recommended_model")
    if recommended:
        return str(recommended)
    industry = str(counterparty.get("industry") or "general")
    if industry == "tech_enterprise":
        return "tech_enterprise_basic"
    if industry in {"pharma", "manufacturing", "construction", "logistics"}:
        return industry
    return "general"


def _change_drivers(before: dict, after: dict, base_config: dict, candidate_config: dict) -> list[str]:
    drivers: list[str] = []
    basis = after["basis"]
    if base_config["standard_limit"] != candidate_config["standard_limit"]:
        drivers.append(
            f"标准额度边界 {base_config['standard_limit'] / 10_000:g}万→{candidate_config['standard_limit'] / 10_000:g}万"
        )
    if base_config["enhanced_limit"] != candidate_config["enhanced_limit"]:
        drivers.append(
            f"加强额度边界 {base_config['enhanced_limit'] / 10_000:g}万→{candidate_config['enhanced_limit'] / 10_000:g}万"
        )
    rating = basis["rating"]
    if (
        (rating in base_config["low_risk_ratings"]) != (rating in candidate_config["low_risk_ratings"])
        or (rating in base_config["high_risk_ratings"]) != (rating in candidate_config["high_risk_ratings"])
    ):
        drivers.append(f"评级 {rating} 的风险集合归属变化")
    strategy = basis["access_strategy"]
    if (
        (strategy in base_config["restricted_strategies"]) != (strategy in candidate_config["restricted_strategies"])
        or (strategy in base_config["prohibited_strategies"]) != (strategy in candidate_config["prohibited_strategies"])
    ):
        drivers.append(f"准入策略“{strategy}”的触发集合变化")
    if before["tier"] == after["tier"] and len(before["slots"]) != len(after["slots"]):
        drivers.append(f"{after['tier_label']}会签席位 {len(before['slots'])}→{len(after['slots'])}")
    if before["tier"] != after["tier"]:
        drivers.append(f"授权层级 {before['tier_label']}→{after['tier_label']}")
    return drivers or ["当前样本授权结果不变"]


def _skip(counterparty: dict, template_key: str, reason: str) -> dict:
    return {
        "counterparty_id": counterparty.get("id", "-"),
        "counterparty_name": counterparty.get("name", "-"),
        "template_key": template_key,
        "reason": reason,
    }


def _gate(key: str, label: str, passed: bool, actual: int | float, threshold: str) -> dict:
    return {"key": key, "label": label, "passed": passed, "actual": actual, "threshold": threshold}


def _content_hash(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
