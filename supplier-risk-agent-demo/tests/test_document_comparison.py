from backend.document_comparison import build_document_version_comparison


def test_document_version_comparison_identifies_resolved_and_remaining_issues() -> None:
    correction = {
        "id": "correction-1",
        "document_type": "营业执照",
        "failed_check_keys": ["entity_match", "completeness"],
    }
    previous_document = _document("old", "错误资料.txt")
    current_document = _document("new", "营业执照.txt")
    previous_precheck = {
        "checks": [
            _check("file_integrity", "文件指纹与格式", "pass"),
            _check("type_consistency", "资料分类一致性", "warning"),
            _check("entity_consistency", "企业主体一致性", "warning"),
            _check("text_extractability", "内容可提取性", "pass"),
        ],
        "extracted_fields": [
            _field("company_name", "企业名称", "其他公司有限公司", False),
            _field("credit_code", "统一社会信用代码", "000000000000000000", False),
        ],
    }
    current_precheck = {
        "checks": [
            _check("file_integrity", "文件指纹与格式", "pass"),
            _check("type_consistency", "资料分类一致性", "pass"),
            _check("entity_consistency", "企业主体一致性", "pass"),
            _check("text_extractability", "内容可提取性", "manual_review"),
        ],
        "extracted_fields": [
            _field("company_name", "企业名称", "测试公司有限公司", True),
            _field("credit_code", "统一社会信用代码", "91440300TEST000001", True),
        ],
    }

    comparison = build_document_version_comparison(
        correction,
        previous_document,
        current_document,
        previous_precheck,
        current_precheck,
    )

    assert comparison["overall_trend"] == "improved"
    assert comparison["readiness"] == "attention_required"
    assert comparison["summary"] == {
        "resolved_count": 4,
        "remaining_count": 1,
        "new_issue_count": 1,
        "changed_field_count": 2,
    }
    assert {item["change_type"] for item in comparison["field_changes"]} == {"resolved"}
    assert comparison["requested_check_keys"] == ["entity_match", "completeness"]


def test_document_version_comparison_blocks_tampered_replacement() -> None:
    comparison = build_document_version_comparison(
        {"id": "correction-2", "document_type": "营业执照", "failed_check_keys": []},
        _document("old", "营业执照-v1.txt"),
        _document("new", "营业执照-v2.txt"),
        {"checks": [_check("file_integrity", "文件指纹与格式", "pass")], "extracted_fields": []},
        {"checks": [_check("file_integrity", "文件指纹与格式", "block")], "extracted_fields": []},
    )

    assert comparison["overall_trend"] == "regressed"
    assert comparison["readiness"] == "blocked"
    assert comparison["summary"]["new_issue_count"] == 1
    assert "不得进入人工核验通过" in comparison["recommendation"]


def test_document_version_comparison_keeps_missing_previous_mismatch_open() -> None:
    comparison = build_document_version_comparison(
        {"id": "correction-3", "document_type": "营业执照", "failed_check_keys": ["entity_match"]},
        _document("old", "营业执照-v1.txt"),
        _document("new", "营业执照-v2.txt"),
        {
            "checks": [_check("file_integrity", "文件指纹与格式", "pass")],
            "extracted_fields": [_field("company_name", "企业名称", "其他公司有限公司", False)],
        },
        {
            "checks": [_check("file_integrity", "文件指纹与格式", "pass")],
            "extracted_fields": [],
        },
    )

    assert comparison["readiness"] == "attention_required"
    assert comparison["summary"]["remaining_count"] == 1
    assert comparison["field_changes"][0]["change_type"] == "unresolved"
    assert comparison["overall_trend"] == "unchanged"


def _document(document_id: str, name: str) -> dict:
    return {
        "id": document_id,
        "original_name": name,
        "sha256": document_id * 16,
        "size_bytes": 100,
        "created_at": "2026-07-25T10:00:00+00:00",
    }


def _check(key: str, label: str, status: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": f"{label}-{status}", "signals": []}


def _field(key: str, label: str, value: str, matches_expected: bool) -> dict:
    return {
        "key": key,
        "label": label,
        "value": value,
        "source": "text_layer",
        "confidence": 1.0,
        "matches_expected": matches_expected,
    }
