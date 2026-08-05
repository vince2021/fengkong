from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from backend.authority_policy_repository import builtin_policy_snapshot


def build_credit_authority(case: dict, policy_snapshot: dict | None = None) -> dict:
    proposal = case.get("data", {}).get("credit_proposal", {})
    scoring = case.get("data", {}).get("scoring", {})
    suggested_limit = _number(proposal.get("suggested_limit"))
    rating = str(scoring.get("rating") or proposal.get("rating") or "").upper()
    strategy = str(proposal.get("access_strategy") or "")
    renewal_review = case.get("data", {}).get("_workflow", {}).get("renewal_risk_review", {})
    renewal_conclusion = str(renewal_review.get("conclusion") or "") if case.get("application_type") == "renewal" else ""
    policy = deepcopy(policy_snapshot or builtin_policy_snapshot())
    config = policy["config"]
    if (
        suggested_limit > config["enhanced_limit"]
        or rating in set(config["high_risk_ratings"])
        or strategy in set(config["prohibited_strategies"])
    ):
        tier = "committee"
    elif (
        suggested_limit > config["standard_limit"]
        or rating not in set(config["low_risk_ratings"])
        or strategy in set(config["restricted_strategies"])
    ):
        tier = "enhanced"
    else:
        tier = "standard"
    risk_reason = ""
    if renewal_conclusion == "decline_recommended":
        tier = "committee"
        risk_reason = "风控复核建议拒绝，强制升级委员会授权"
    elif renewal_conclusion == "controls_required" and tier == "standard":
        tier = "enhanced"
        risk_reason = "风控复核要求落实控制措施，至少升级加强授权"
    tier_config = config["tiers"][tier]
    slots = [_slot(item["key"], item["role"], item["label"]) for item in tier_config["slots"]]

    return {
        "version": "2026.07",
        "tier": tier,
        "tier_label": tier_config["label"],
        "reason": f"{tier_config['reason']}；{risk_reason}" if risk_reason else tier_config["reason"],
        "policy": {
            "id": policy.get("id"),
            "version": policy["policy_version"],
            "config_hash": policy["config_hash"],
            "source": policy.get("source", "published"),
        },
        "basis": {
            "suggested_limit": suggested_limit,
            "rating": rating or "-",
            "access_strategy": strategy or "-",
            "renewal_risk_conclusion": renewal_conclusion or None,
        },
        "slots": slots,
        "status": "pending",
    }


def ensure_credit_authority(case: dict) -> dict:
    workflow = case.setdefault("data", {}).setdefault("_workflow", {})
    authority = workflow.get("credit_authority")
    if not isinstance(authority, dict) or not isinstance(authority.get("slots"), list):
        authority = build_credit_authority(case)
        workflow["credit_authority"] = authority
    refresh_authority_status(authority)
    return authority


def current_authority_slot(case_or_data: Any) -> dict | None:
    if hasattr(case_or_data, "case_data"):
        data = case_or_data.case_data or {}
    elif isinstance(case_or_data, dict) and "data" in case_or_data:
        data = case_or_data.get("data", {})
    else:
        data = case_or_data if isinstance(case_or_data, dict) else {}
    authority = data.get("_workflow", {}).get("credit_authority")
    if not isinstance(authority, dict):
        return None
    return next((slot for slot in authority.get("slots", []) if slot.get("status") == "pending"), None)


def authority_owner_roles(case_or_data: Any, fallback: set[str] | None = None) -> set[str]:
    slot = current_authority_slot(case_or_data)
    if slot is None:
        data = _case_data(case_or_data)
        authority = data.get("_workflow", {}).get("credit_authority")
        if not isinstance(authority, dict):
            slot = next(
                (item for item in build_credit_authority({"data": data})["slots"] if item["status"] == "pending"),
                None,
            )
    return {str(slot["role"])} if slot else set(fallback or {"approver"})


def authority_has_signer(case_or_data: Any, signer_subject: str | None) -> bool:
    if not signer_subject:
        return False
    authority = _case_data(case_or_data).get("_workflow", {}).get("credit_authority")
    return isinstance(authority, dict) and any(
        slot.get("status") == "approved" and slot.get("signed_by") == signer_subject
        for slot in authority.get("slots", [])
    )


def record_authority_signoff(
    authority: dict,
    *,
    slot_key: str,
    decision: str,
    comment: str,
    signer_subject: str,
    signer_name: str,
    signer_roles: tuple[str, ...],
    occurred_at: str | None = None,
) -> dict:
    slots = authority.get("slots", [])
    slot = next((item for item in slots if item.get("key") == slot_key), None)
    if not slot:
        raise ValueError("授权会签节点不存在")
    current = next((item for item in slots if item.get("status") == "pending"), None)
    if current is None:
        raise ValueError("授权会签已全部完成")
    if current.get("key") != slot_key:
        raise ValueError(f"请先完成前序会签：{current.get('label', current.get('key'))}")
    if slot.get("role") not in signer_roles and "admin" not in signer_roles:
        raise PermissionError(f"当前角色无权处理会签节点：{slot.get('label')}")
    prior_signers = {
        item.get("signed_by")
        for item in slots
        if item.get("status") == "approved" and item.get("signed_by")
    }
    if signer_subject in prior_signers:
        raise ValueError("同一人员不能重复占用多个会签席位")

    slot.update(
        {
            "status": "approved" if decision == "approve" else "rejected",
            "decision": decision,
            "comment": comment,
            "signed_by": signer_subject,
            "signed_by_name": signer_name,
            "signed_at": occurred_at or datetime.now().astimezone().isoformat(),
        }
    )
    refresh_authority_status(authority)
    return deepcopy(slot)


def refresh_authority_status(authority: dict) -> str:
    statuses = [slot.get("status") for slot in authority.get("slots", [])]
    if "rejected" in statuses:
        authority["status"] = "rejected"
    elif statuses and all(status == "approved" for status in statuses):
        authority["status"] = "approved"
    else:
        authority["status"] = "pending"
    return authority["status"]


def _slot(key: str, role: str, label: str) -> dict:
    return {
        "key": key,
        "role": role,
        "label": label,
        "status": "pending",
        "decision": None,
        "comment": None,
        "signed_by": None,
        "signed_by_name": None,
        "signed_at": None,
    }


def _number(value: Any) -> float:
    try:
        return max(float(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _case_data(case_or_data: Any) -> dict:
    if hasattr(case_or_data, "case_data"):
        return case_or_data.case_data or {}
    if isinstance(case_or_data, dict) and "data" in case_or_data:
        return case_or_data.get("data", {})
    return case_or_data if isinstance(case_or_data, dict) else {}
