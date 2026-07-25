from __future__ import annotations

import hashlib
import io
import zipfile

import backend.document_precheck as document_precheck
from backend.document_precheck import precheck_document


def test_excel_precheck_extracts_shared_strings_and_matches_financial_document() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook><sheet name='资产负债表'/></workbook>")
        archive.writestr("xl/sharedStrings.xml", "<sst><si><t>深圳测试公司</t></si><si><t>利润表</t></si><si><t>现金流量表</t></si></sst>")
    content = buffer.getvalue()
    result = precheck_document(
        {
            "id": "doc-1",
            "document_type": "最近一期财务报表",
            "original_name": "2026年一季度.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        content,
        {"name": "深圳测试公司", "credit_code": "91440300TEST000001"},
    )
    assert result["overall_status"] == "pass"
    assert all(item["status"] == "pass" for item in result["checks"])


def test_precheck_blocks_tampered_object() -> None:
    content = "营业执照 统一社会信用代码 91440300TEST000001 深圳测试公司".encode()
    result = precheck_document(
        {
            "id": "doc-2",
            "document_type": "营业执照",
            "original_name": "营业执照.txt",
            "content_type": "text/plain",
            "sha256": "0" * 64,
        },
        content,
        {"name": "深圳测试公司", "credit_code": "91440300TEST000001"},
    )
    assert result["overall_status"] == "block"
    assert result["checks"][0]["status"] == "block"


def test_image_ocr_extracts_reviewable_fields_without_auto_verification(monkeypatch) -> None:
    content = b"\x89PNG\r\n\x1a\nmock-image"

    def fake_ocr(*_args, **_kwargs) -> dict:
        lines = [
            "营业执照",
            "深圳测试有限公司",
            "统一社会信用代码 91440300TEST000001",
            "法定代表人：张三",
            "营业期限：2020年01月01日至长期",
        ]
        return {
            "status": "success",
            "provider": "macos_vision",
            "pages_processed": 1,
            "average_confidence": 0.92,
            "lines": [{"text": line, "confidence": 0.92, "page": 1} for line in lines],
            "warning": None,
        }

    monkeypatch.setattr(document_precheck, "run_document_ocr", fake_ocr)
    result = precheck_document(
        {
            "id": "doc-ocr-1",
            "document_type": "营业执照",
            "original_name": "scan.png",
            "content_type": "image/png",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        content,
        {"name": "深圳测试有限公司", "credit_code": "91440300TEST000001", "legal_representative": "张三"},
    )
    assert result["overall_status"] == "pass"
    assert result["ocr"]["status"] == "success"
    assert {item["key"] for item in result["extracted_fields"]} == {"company_name", "credit_code", "legal_representative", "validity_period"}
    assert all(item["matches_expected"] is not False for item in result["extracted_fields"])
    assert "不替代独立风控人员" in result["disclaimer"]


def test_low_confidence_ocr_stays_in_warning_state(monkeypatch) -> None:
    content = b"\xff\xd8\xffmock-image"
    monkeypatch.setattr(
        document_precheck,
        "run_document_ocr",
        lambda *_args, **_kwargs: {
            "status": "success",
            "provider": "macos_vision",
            "pages_processed": 1,
            "average_confidence": 0.51,
            "lines": [{"text": "营业执照", "confidence": 0.51, "page": 1}],
            "warning": None,
        },
    )
    result = precheck_document(
        {
            "id": "doc-ocr-2",
            "document_type": "营业执照",
            "original_name": "scan.jpg",
            "content_type": "image/jpeg",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        content,
        {"name": "深圳测试有限公司", "credit_code": "91440300TEST000001"},
    )
    assert result["overall_status"] == "warning"
    assert any(item["key"] == "ocr_recognition" and item["status"] == "warning" for item in result["checks"])
    assert any("不得直接据此确认" in item for item in result["recommendations"])


def test_legal_representative_field_labels_are_not_extracted_as_person_names() -> None:
    content = "法定代表人名称\n法定代表人或者负责人\n深圳测试有限公司".encode()
    result = precheck_document(
        {
            "id": "doc-label-only",
            "document_type": "法定代表人身份证明",
            "original_name": "字段说明.txt",
            "content_type": "text/plain",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        content,
        {"name": "深圳测试有限公司", "credit_code": "91440300TEST000001"},
    )
    assert "legal_representative" not in {item["key"] for item in result["extracted_fields"]}
