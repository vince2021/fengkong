from __future__ import annotations

import pytest

from backend.credit_authority import (
    authority_owner_roles,
    build_credit_authority,
    record_authority_signoff,
)


def _case(limit: float, rating: str = "A", strategy: str = "准入") -> dict:
    return {
        "data": {
            "scoring": {"rating": rating},
            "credit_proposal": {
                "suggested_limit": limit,
                "access_strategy": strategy,
            },
        }
    }


@pytest.mark.parametrize(
    ("case", "tier", "roles"),
    [
        (_case(5_000_000, "A", "准入"), "standard", ["approver"]),
        (_case(5_000_001, "A", "准入"), "enhanced", ["risk_manager", "approver"]),
        (_case(1_000_000, "B", "人工复核"), "enhanced", ["risk_manager", "approver"]),
        (_case(20_000_001, "A", "准入"), "committee", ["risk_manager", "approver", "approver"]),
        (_case(1_000_000, "D", "禁入"), "committee", ["risk_manager", "approver", "approver"]),
    ],
)
def test_authority_matrix_selects_tier_and_signoff_roles(case: dict, tier: str, roles: list[str]) -> None:
    authority = build_credit_authority(case)

    assert authority["tier"] == tier
    assert [slot["role"] for slot in authority["slots"]] == roles
    assert authority_owner_roles(case) == {roles[0]}


@pytest.mark.parametrize(
    ("conclusion", "tier", "roles"),
    [
        ("controls_required", "enhanced", ["risk_manager", "approver"]),
        ("decline_recommended", "committee", ["risk_manager", "approver", "approver"]),
    ],
)
def test_renewal_risk_review_escalates_authority(conclusion: str, tier: str, roles: list[str]) -> None:
    case = _case(1_000_000, "A", "准入")
    case["application_type"] = "renewal"
    case["data"]["_workflow"] = {"renewal_risk_review": {"conclusion": conclusion}}

    authority = build_credit_authority(case)

    assert authority["tier"] == tier
    assert [slot["role"] for slot in authority["slots"]] == roles
    assert authority["basis"]["renewal_risk_conclusion"] == conclusion


def test_committee_signoff_is_sequential_and_enforces_distinct_people() -> None:
    authority = build_credit_authority(_case(30_000_000))

    with pytest.raises(ValueError, match="前序会签"):
        record_authority_signoff(
            authority,
            slot_key="approver_primary",
            decision="approve",
            comment="同意进入下一环节",
            signer_subject="approver-1",
            signer_name="审批人甲",
            signer_roles=("approver",),
        )

    record_authority_signoff(
        authority,
        slot_key="risk_concurrence",
        decision="approve",
        comment="风险条件符合政策",
        signer_subject="risk-1",
        signer_name="风控经理",
        signer_roles=("risk_manager",),
    )
    record_authority_signoff(
        authority,
        slot_key="approver_primary",
        decision="approve",
        comment="第一席位审批同意",
        signer_subject="approver-1",
        signer_name="审批人甲",
        signer_roles=("approver",),
    )
    with pytest.raises(ValueError, match="不能重复"):
        record_authority_signoff(
            authority,
            slot_key="approver_secondary",
            decision="approve",
            comment="尝试重复签署席位",
            signer_subject="approver-1",
            signer_name="审批人甲",
            signer_roles=("approver",),
        )

    record_authority_signoff(
        authority,
        slot_key="approver_secondary",
        decision="approve",
        comment="第二席位独立审批同意",
        signer_subject="approver-2",
        signer_name="审批人乙",
        signer_roles=("approver",),
    )
    assert authority["status"] == "approved"


def test_signoff_rejection_terminates_authority() -> None:
    authority = build_credit_authority(_case(8_000_000))
    record_authority_signoff(
        authority,
        slot_key="risk_concurrence",
        decision="reject",
        comment="风险条件不符合准入政策",
        signer_subject="risk-1",
        signer_name="风控经理",
        signer_roles=("risk_manager",),
    )

    assert authority["status"] == "rejected"
