from __future__ import annotations

from copy import deepcopy

from backend.authority_policy_impact import build_authority_policy_config_diff
from backend.authority_policy_repository import DEFAULT_AUTHORITY_POLICY_CONFIG


def test_authority_policy_config_diff_identifies_unchanged_baseline() -> None:
    diff = build_authority_policy_config_diff(
        deepcopy(DEFAULT_AUTHORITY_POLICY_CONFIG),
        deepcopy(DEFAULT_AUTHORITY_POLICY_CONFIG),
    )

    assert diff["overall_direction"] == "unchanged"
    assert diff["summary"]["changed_field_count"] == 0
    assert diff["changes"] == []


def test_authority_policy_config_diff_classifies_tightening_controls() -> None:
    candidate = deepcopy(DEFAULT_AUTHORITY_POLICY_CONFIG)
    candidate["standard_limit"] = 3_000_000
    candidate["enhanced_limit"] = 12_000_000
    candidate["low_risk_ratings"].remove("A")
    candidate["high_risk_ratings"].append("B")
    candidate["tiers"]["enhanced"]["slots"].append(
        {"key": "approver_peer", "role": "approver", "label": "第二有权审批人"}
    )

    diff = build_authority_policy_config_diff(DEFAULT_AUTHORITY_POLICY_CONFIG, candidate)

    assert diff["overall_direction"] == "tightened"
    assert diff["summary"]["tightened_count"] == 5
    assert {item["key"] for item in diff["changes"]} == {
        "standard_limit",
        "enhanced_limit",
        "low_risk_ratings",
        "high_risk_ratings",
        "tiers.enhanced.slots",
    }


def test_authority_policy_config_diff_marks_bidirectional_set_change_as_mixed() -> None:
    candidate = deepcopy(DEFAULT_AUTHORITY_POLICY_CONFIG)
    candidate["low_risk_ratings"] = ["AAA", "BBB", "A"]

    diff = build_authority_policy_config_diff(DEFAULT_AUTHORITY_POLICY_CONFIG, candidate)

    assert diff["overall_direction"] == "mixed"
    change = diff["changes"][0]
    assert change["direction"] == "mixed"
    assert change["added"] == ["BBB"]
    assert change["removed"] == ["AA"]


def test_authority_policy_config_diff_records_semantic_neutral_reordering() -> None:
    candidate = deepcopy(DEFAULT_AUTHORITY_POLICY_CONFIG)
    candidate["restricted_strategies"] = list(reversed(candidate["restricted_strategies"]))

    diff = build_authority_policy_config_diff(DEFAULT_AUTHORITY_POLICY_CONFIG, candidate)

    assert diff["overall_direction"] == "neutral"
    assert diff["summary"]["neutral_count"] == 1
    assert diff["changes"][0]["rationale"] == "集合成员未变，仅调整展示顺序"
