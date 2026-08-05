from __future__ import annotations

import pytest

from backend.routers.approvals import _renewal_final_disposition


def _renewal_case(conclusion: str, controls: list[str] | None = None) -> dict:
    return {
        "application_type": "renewal",
        "data": {
            "_workflow": {
                "renewal_risk_review": {
                    "status": "completed",
                    "conclusion": conclusion,
                    "review_note": "已基于最新风险证据完成独立复核",
                    "control_measures": controls or [],
                    "reviewed_by_name": "风控经理",
                    "reviewed_at": "2026-08-05 10:00:00",
                }
            }
        },
    }


def test_controlled_renewal_carries_review_measures_into_final_strategy() -> None:
    payload = _renewal_final_disposition(
        _renewal_case("controls_required", ["月度核查诉讼", "额度不得超模型建议"]),
        {"decision": "有条件通过", "access_strategy": "限制准入"},
    )

    assert payload["renewal_risk_disposition"]["alignment"] == "controls_adopted"
    assert payload["renewal_risk_disposition"]["adopted_controls"] == ["月度核查诉讼", "额度不得超模型建议"]


def test_controlled_renewal_rejects_missing_measures_and_deduplicates_tasks() -> None:
    with pytest.raises(ValueError, match="未形成可执行措施"):
        _renewal_final_disposition(
            _renewal_case("controls_required"),
            {"decision": "有条件通过", "access_strategy": "限制准入"},
        )

    payload = _renewal_final_disposition(
        _renewal_case("controls_required", ["月度核查诉讼", "月度核查诉讼"]),
        {"decision": "有条件通过", "access_strategy": "限制准入"},
    )
    assert payload["renewal_risk_disposition"]["adopted_controls"] == ["月度核查诉讼"]


def test_unknown_renewal_risk_conclusion_fails_closed() -> None:
    with pytest.raises(ValueError, match="复核结论无效"):
        _renewal_final_disposition(
            _renewal_case("legacy_unknown"),
            {"decision": "通过", "access_strategy": "准入"},
        )


def test_decline_recommendation_requires_reason_and_controls_when_overridden() -> None:
    with pytest.raises(ValueError, match="特别审批理由"):
        _renewal_final_disposition(
            _renewal_case("decline_recommended"),
            {"decision": "通过", "access_strategy": "准入", "compensating_controls": ["实时监控"]},
        )

    with pytest.raises(ValueError, match="补偿性控制措施"):
        _renewal_final_disposition(
            _renewal_case("decline_recommended"),
            {"decision": "通过", "access_strategy": "准入", "renewal_risk_override_reason": "基于集团担保和回款安排特别批准"},
        )

    payload = _renewal_final_disposition(
        _renewal_case("decline_recommended"),
        {
            "decision": "有条件通过",
            "access_strategy": "限制准入",
            "renewal_risk_override_reason": "基于足额保证金和集团担保审慎特别批准",
            "compensating_controls": ["落实足额保证金", "实时监控风险"],
        },
    )
    assert payload["renewal_risk_disposition"]["alignment"] == "decline_overridden"
    assert payload["renewal_risk_disposition"]["adopted_controls"] == ["落实足额保证金", "实时监控风险"]


def test_decline_recommendation_can_be_adopted_without_post_credit_tasks() -> None:
    payload = _renewal_final_disposition(
        _renewal_case("decline_recommended"),
        {"decision": "拒绝", "access_strategy": "禁入"},
    )

    assert payload["renewal_risk_disposition"]["alignment"] == "decline_adopted"
    assert payload["renewal_risk_disposition"]["adopted_controls"] == []
