from __future__ import annotations

from copy import deepcopy


STATUS_SEVERITY = {
    "pass": 0,
    "manual_review": 1,
    "warning": 2,
    "block": 3,
}


def build_document_version_comparison(
    correction: dict,
    previous_document: dict,
    current_document: dict,
    previous_precheck: dict,
    current_precheck: dict,
) -> dict:
    previous_checks = {item["key"]: item for item in previous_precheck.get("checks", [])}
    current_checks = {item["key"]: item for item in current_precheck.get("checks", [])}
    check_changes = []
    for key in dict.fromkeys([*previous_checks, *current_checks]):
        previous = previous_checks.get(key)
        current = current_checks.get(key)
        previous_status = (previous or {}).get("status", "manual_review")
        current_status = (current or {}).get("status", "manual_review")
        check_changes.append(
            {
                "key": key,
                "label": (current or previous or {}).get("label", key),
                "previous_status": previous_status,
                "current_status": current_status,
                "trend": _status_trend(previous_status, current_status),
                "previous_detail": (previous or {}).get("detail"),
                "current_detail": (current or {}).get("detail"),
            }
        )

    previous_fields = {item["key"]: item for item in previous_precheck.get("extracted_fields", [])}
    current_fields = {item["key"]: item for item in current_precheck.get("extracted_fields", [])}
    field_changes = []
    for key in dict.fromkeys([*previous_fields, *current_fields]):
        previous = previous_fields.get(key)
        current = current_fields.get(key)
        change_type = _field_change_type(previous, current)
        field_changes.append(
            {
                "key": key,
                "label": (current or previous or {}).get("label", key),
                "previous_value": (previous or {}).get("value"),
                "current_value": (current or {}).get("value"),
                "previous_matches_expected": (previous or {}).get("matches_expected"),
                "current_matches_expected": (current or {}).get("matches_expected"),
                "previous_confidence": (previous or {}).get("confidence"),
                "current_confidence": (current or {}).get("confidence"),
                "change_type": change_type,
            }
        )

    resolved_checks = [item for item in check_changes if item["trend"] == "improved" and item["current_status"] == "pass"]
    new_check_issues = [item for item in check_changes if item["trend"] == "regressed" and item["current_status"] != "pass"]
    remaining_checks = [item for item in check_changes if item["current_status"] != "pass"]
    resolved_fields = [item for item in field_changes if item["change_type"] == "resolved"]
    new_field_issues = [item for item in field_changes if item["change_type"] == "introduced"]
    remaining_fields = [
        item
        for item in field_changes
        if item["current_matches_expected"] is False or item["change_type"] == "unresolved"
    ]
    previous_severity = sum(STATUS_SEVERITY.get(item["previous_status"], 1) for item in check_changes)
    previous_severity += sum(item["previous_matches_expected"] is False for item in field_changes) * 2
    current_severity = sum(STATUS_SEVERITY.get(item["current_status"], 1) for item in check_changes)
    current_severity += len(remaining_fields) * 2
    if current_severity < previous_severity:
        overall_trend = "improved"
    elif current_severity > previous_severity:
        overall_trend = "regressed"
    else:
        overall_trend = "unchanged"

    remaining_count = len(remaining_checks) + len(remaining_fields)
    blocked = any(item["current_status"] == "block" for item in check_changes)
    if blocked:
        readiness = "blocked"
        recommendation = "新版本存在文件完整性阻断项，不得进入人工核验通过。"
    elif remaining_count:
        readiness = "attention_required"
        recommendation = "新版本仍有自动预检异常，复核人应逐项核对原件后决定继续退补或核验。"
    else:
        readiness = "ready_for_manual_review"
        recommendation = "新版本自动预检未发现遗留异常，可进入人工五项核验；自动结果不能替代复核结论。"

    return {
        "correction_id": correction["id"],
        "document_type": correction["document_type"],
        "from_document": _document_summary(previous_document),
        "to_document": _document_summary(current_document),
        "overall_trend": overall_trend,
        "readiness": readiness,
        "summary": {
            "resolved_count": len(resolved_checks) + len(resolved_fields),
            "remaining_count": remaining_count,
            "new_issue_count": len(new_check_issues) + len(new_field_issues),
            "changed_field_count": sum(item["change_type"] != "unchanged" for item in field_changes),
        },
        "requested_check_keys": deepcopy(correction.get("failed_check_keys") or []),
        "check_changes": check_changes,
        "field_changes": field_changes,
        "recommendation": recommendation,
        "disclaimer": "版本差异仅用于辅助定位变化，最终核验必须由独立风控人员查看原件并逐项判断。",
    }


def _status_trend(previous_status: str, current_status: str) -> str:
    previous = STATUS_SEVERITY.get(previous_status, 1)
    current = STATUS_SEVERITY.get(current_status, 1)
    if current < previous:
        return "improved"
    if current > previous:
        return "regressed"
    return "unchanged"


def _field_change_type(previous: dict | None, current: dict | None) -> str:
    if previous and previous.get("matches_expected") is False and current and current.get("matches_expected") is True:
        return "resolved"
    if previous and previous.get("matches_expected") is False and not current:
        return "unresolved"
    if (not previous or previous.get("matches_expected") is not False) and current and current.get("matches_expected") is False:
        return "introduced"
    if not previous or not current:
        return "changed"
    if previous.get("value") != current.get("value") or previous.get("matches_expected") != current.get("matches_expected"):
        return "changed"
    return "unchanged"


def _document_summary(document: dict) -> dict:
    return {
        "id": document["id"],
        "original_name": document["original_name"],
        "sha256": document["sha256"],
        "size_bytes": document["size_bytes"],
        "created_at": document.get("created_at"),
    }
