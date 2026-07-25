from __future__ import annotations

import pytest

from backend.decision_governance import build_decision_variance, validate_decision_variance


PROPOSAL = {
    "suggested_limit": 1_000_000,
    "suggested_payment_term_days": 60,
    "access_strategy": "准入",
    "monitoring_frequency": "月度",
}


def test_aligned_decision_requires_no_reason() -> None:
    variance = build_decision_variance(PROPOSAL, {
        "decision": "通过", "approved_limit": 1_000_000, "approved_payment_term_days": 60,
        "access_strategy": "准入", "monitoring_frequency": "月度",
    })
    validate_decision_variance(variance)
    assert variance["direction"] == "aligned"
    assert variance["materiality"] == "none"
    assert variance["changed_fields"] == []


def test_material_reduction_requires_structured_reason() -> None:
    variance = build_decision_variance(PROPOSAL, {
        "decision": "有条件通过", "approved_limit": 700_000, "approved_payment_term_days": 30,
        "access_strategy": "审慎准入", "monitoring_frequency": "实时监控",
    })
    assert variance["direction"] == "stricter"
    assert variance["materiality"] == "material"
    with pytest.raises(ValueError, match="原因类别"):
        validate_decision_variance(variance)

    governed = build_decision_variance(PROPOSAL, {
        "decision": "有条件通过", "approved_limit": 700_000, "approved_payment_term_days": 30,
        "access_strategy": "审慎准入", "monitoring_frequency": "实时监控",
        "adjustment_reason_category": "数据不确定性",
        "adjustment_reason": "内部交易与逾期数据尚未完整接入，采取审慎下调",
    })
    validate_decision_variance(governed)


def test_decision_only_change_uses_decision_risk_order() -> None:
    conditional_proposal = {**PROPOSAL, "access_strategy": "限制准入"}
    relaxed = build_decision_variance(conditional_proposal, {
        "decision": "通过", "approved_limit": 1_000_000, "approved_payment_term_days": 60,
        "access_strategy": "限制准入", "monitoring_frequency": "月度",
        "adjustment_reason_category": "业务例外",
        "adjustment_reason": "客户提供新增付款保障，审批结论调整为直接通过",
        "compensating_controls": ["首期付款到账后发货"],
    })
    assert relaxed["direction"] == "relaxed"
    assert relaxed["deltas"]["decision_steps"] == -1
    validate_decision_variance(relaxed)

    stricter = build_decision_variance(PROPOSAL, {
        "decision": "有条件通过", "approved_limit": 1_000_000, "approved_payment_term_days": 60,
        "access_strategy": "准入", "monitoring_frequency": "月度",
        "adjustment_reason_category": "数据不确定性",
        "adjustment_reason": "关键内部交易字段尚未完整接入，增加条件审批要求",
    })
    assert stricter["direction"] == "stricter"
    assert stricter["deltas"]["decision_steps"] == 1
    validate_decision_variance(stricter)


def test_relaxation_requires_controls_and_limit_increase_is_blocked() -> None:
    term_relaxation = build_decision_variance(PROPOSAL, {
        "decision": "通过", "approved_limit": 1_000_000, "approved_payment_term_days": 90,
        "access_strategy": "准入", "monitoring_frequency": "月度",
        "adjustment_reason_category": "业务例外",
        "adjustment_reason": "战略客户结算周期与项目交付周期存在客观错配",
    })
    assert term_relaxation["direction"] == "relaxed"
    with pytest.raises(ValueError, match="补偿性控制"):
        validate_decision_variance(term_relaxation)

    controlled = build_decision_variance(PROPOSAL, {
        "decision": "通过", "approved_limit": 1_000_000, "approved_payment_term_days": 90,
        "access_strategy": "准入", "monitoring_frequency": "实时监控",
        "adjustment_reason_category": "业务例外",
        "adjustment_reason": "战略客户结算周期与项目交付周期存在客观错配",
        "compensating_controls": ["应收账款每周核验", "出现逾期立即冻结"],
    })
    assert controlled["direction"] == "mixed"
    validate_decision_variance(controlled)

    above_limit = build_decision_variance(PROPOSAL, {
        "decision": "通过", "approved_limit": 1_100_000, "approved_payment_term_days": 60,
        "access_strategy": "准入", "monitoring_frequency": "月度",
        "adjustment_reason_category": "业务例外",
        "adjustment_reason": "业务部门申请提高额度并承诺追加付款保障措施",
        "compensating_controls": ["追加担保"],
    })
    with pytest.raises(ValueError, match="不能高于模型建议额度"):
        validate_decision_variance(above_limit)
