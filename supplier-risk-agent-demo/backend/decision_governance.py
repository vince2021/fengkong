from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


REASON_CATEGORIES = {
    "审慎下调",
    "客户需求",
    "数据不确定性",
    "新增风险信号",
    "行业政策",
    "业务例外",
    "其他",
}

STRATEGY_RANK = {
    "自动准入": 0,
    "准入": 1,
    "限制准入": 2,
    "审慎准入": 3,
    "人工复核": 4,
    "禁入": 5,
    "不建议准入": 5,
}

MONITORING_RANK = {"年度": 0, "半年": 1, "季度": 2, "月度": 3, "实时监控": 4}
DECISION_RANK = {"通过": 0, "有条件通过": 1, "拒绝": 2}


def build_decision_variance(proposal: dict, decision: dict) -> dict:
    suggested_limit = _money(proposal.get("suggested_limit", 0))
    suggested_term = _integer(proposal.get("suggested_payment_term_days", 0))
    suggested_strategy = str(proposal.get("access_strategy") or "人工复核")
    suggested_monitoring = str(proposal.get("monitoring_frequency") or "月度")
    suggested_decision = _decision_for_strategy(suggested_strategy)

    rejected = decision.get("decision") == "拒绝"
    approved_limit = Decimal("0.00") if rejected else _money(decision.get("approved_limit", suggested_limit))
    approved_term = 0 if rejected else _integer(decision.get("approved_payment_term_days", suggested_term))
    final_strategy = str(decision.get("access_strategy") or suggested_strategy)
    final_monitoring = str(decision.get("monitoring_frequency") or suggested_monitoring)
    final_decision = str(decision.get("decision") or _decision_for_strategy(final_strategy))

    limit_delta = _money(approved_limit - suggested_limit)
    term_delta = approved_term - suggested_term
    strategy_delta = _rank(STRATEGY_RANK, final_strategy, 4) - _rank(STRATEGY_RANK, suggested_strategy, 4)
    monitoring_delta = _rank(MONITORING_RANK, final_monitoring, 3) - _rank(MONITORING_RANK, suggested_monitoring, 3)
    decision_changed = final_decision != suggested_decision
    decision_delta = _rank(DECISION_RANK, final_decision, 1) - _rank(DECISION_RANK, suggested_decision, 1)

    changed_fields: list[str] = []
    if decision_changed:
        changed_fields.append("decision")
    if limit_delta:
        changed_fields.append("approved_limit")
    if term_delta:
        changed_fields.append("approved_payment_term_days")
    if strategy_delta:
        changed_fields.append("access_strategy")
    if monitoring_delta:
        changed_fields.append("monitoring_frequency")

    stricter_signals = [decision_delta > 0, limit_delta < 0, term_delta < 0, strategy_delta > 0, monitoring_delta > 0, rejected]
    relaxed_signals = [decision_delta < 0, limit_delta > 0, term_delta > 0, strategy_delta < 0, monitoring_delta < 0]
    has_stricter = any(stricter_signals)
    has_relaxed = any(relaxed_signals)
    if not changed_fields:
        direction = "aligned"
    elif rejected:
        direction = "rejected"
    elif has_stricter and has_relaxed:
        direction = "mixed"
    elif has_relaxed:
        direction = "relaxed"
    else:
        direction = "stricter"

    limit_ratio = _ratio(limit_delta, suggested_limit)
    material = (
        direction in {"rejected", "relaxed", "mixed"}
        or abs(limit_ratio) >= Decimal("0.20")
        or abs(term_delta) >= 30
        or abs(strategy_delta) >= 2
    )
    materiality = "none" if direction == "aligned" else "material" if material else "minor"
    reason_category = str(decision.get("adjustment_reason_category") or "").strip() or None
    reason_detail = str(decision.get("adjustment_reason") or "").strip() or None
    controls = _controls(decision.get("compensating_controls"))

    return {
        "direction": direction,
        "materiality": materiality,
        "changed_fields": changed_fields,
        "requires_reason": direction != "aligned",
        "requires_compensating_controls": direction in {"relaxed", "mixed"},
        "recommendation": {
            "decision": suggested_decision,
            "access_strategy": suggested_strategy,
            "suggested_limit": float(suggested_limit),
            "suggested_payment_term_days": suggested_term,
            "monitoring_frequency": suggested_monitoring,
        },
        "final_decision": {
            "decision": final_decision,
            "access_strategy": final_strategy,
            "approved_limit": float(approved_limit),
            "approved_payment_term_days": approved_term,
            "monitoring_frequency": final_monitoring,
        },
        "deltas": {
            "limit_amount": float(limit_delta),
            "limit_ratio": float(limit_ratio),
            "payment_term_days": term_delta,
            "strategy_steps": strategy_delta,
            "monitoring_steps": monitoring_delta,
            "decision_steps": decision_delta,
        },
        "reason_category": reason_category,
        "reason_detail": reason_detail,
        "compensating_controls": controls,
    }


def validate_decision_variance(variance: dict) -> None:
    if variance["deltas"]["limit_amount"] > 0:
        raise ValueError("最终批准额度不能高于模型建议额度，请退回额度建议环节重新评估")
    if variance["requires_reason"]:
        category = variance.get("reason_category")
        detail = variance.get("reason_detail") or ""
        if category not in REASON_CATEGORIES:
            raise ValueError("调整模型建议时必须选择有效的偏差原因类别")
        if len(detail) < 10:
            raise ValueError("调整模型建议时必须填写不少于 10 个字的具体原因")
    if variance["requires_compensating_controls"] and not variance.get("compensating_controls"):
        raise ValueError("存在风险放宽项时必须至少填写一项补偿性控制措施")


def _decision_for_strategy(strategy: str) -> str:
    if strategy in {"禁入", "不建议准入"}:
        return "拒绝"
    if strategy in {"自动准入", "准入"}:
        return "通过"
    return "有条件通过"


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("额度必须是有效数字") from exc


def _integer(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("账期必须是整数天数") from exc


def _ratio(delta: Decimal, base: Decimal) -> Decimal:
    if not base:
        return Decimal("0.0000") if not delta else Decimal("1.0000")
    return (delta / base).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _rank(mapping: dict[str, int], value: str, fallback: int) -> int:
    return mapping.get(value, fallback)


def _controls(value) -> list[str]:
    if isinstance(value, str):
        rows = value.replace("，", ",").split(",")
    elif isinstance(value, list):
        rows = value
    else:
        rows = []
    return [str(item).strip() for item in rows if str(item).strip()]
