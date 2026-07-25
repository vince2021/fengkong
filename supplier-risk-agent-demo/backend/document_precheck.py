from __future__ import annotations

import hashlib
import html
import io
import re
import zipfile
from pathlib import Path

from backend.document_ocr import run_document_ocr


DOCUMENT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "营业执照": ("营业执照", "统一社会信用代码", "法定代表人", "登记机关"),
    "公司章程": ("公司章程", "股东会", "董事会", "章程修正案"),
    "法定代表人身份证明": ("法定代表人", "身份证明", "身份证号码", "授权委托"),
    "股权结构及股东名册": ("股权结构", "股东名册", "持股比例", "出资比例"),
    "实控人及受益所有人说明": ("实际控制人", "受益所有人", "最终受益人", "控制关系"),
    "近三年审计报告": ("审计报告", "审计意见", "资产负债表", "利润表"),
    "最近一期财务报表": ("财务报表", "资产负债表", "利润表", "现金流量表"),
    "财务报表": ("财务报表", "资产负债表", "利润表", "现金流量表"),
    "征信授权书": ("征信授权", "信用报告查询", "授权书", "征信查询"),
    "纳税及完税证明": ("完税证明", "纳税", "税款", "税务局"),
    "主要业务合同": ("合同", "甲方", "乙方", "签署"),
    "业务合同": ("合同", "甲方", "乙方", "签署"),
    "订单履约台账": ("订单", "履约", "交付", "验收"),
    "应收账款账龄表": ("应收账款", "账龄", "逾期", "客户余额"),
    "行业资质证书": ("资质证书", "许可", "认证", "有效期"),
    "高新技术企业证书": ("高新技术企业", "证书编号", "有效期"),
    "知识产权清单": ("专利", "软件著作权", "商标", "知识产权"),
    "研发人员名单": ("研发人员", "研发岗位", "劳动关系", "人员名单"),
    "研发投入专项说明": ("研发投入", "研发费用", "研究开发", "收入"),
    "合作授信银行及余额清单": ("授信银行", "授信额度", "用信余额", "贷款余额"),
    "环保合规及处罚说明": ("环保", "环境保护", "行政处罚", "整改"),
    "科创准入财务指标表": ("营业收入", "净资产", "研发投入", "资产负债率"),
}

MAX_EXTRACTED_CHARACTERS = 30_000
MAX_ZIP_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 6 * 1024 * 1024


def precheck_document(document: dict, content: bytes, counterparty: dict | None) -> dict:
    extracted_text, extraction = _extract_text(content, document["content_type"], document["original_name"])
    ocr = {"status": "not_needed", "provider": None, "pages_processed": 0, "average_confidence": 0.0, "lines": [], "warning": None}
    if extraction["status"] == "unavailable":
        ocr = run_document_ocr(content, document["original_name"], document["sha256"])
        if ocr["status"] == "success":
            extracted_text = "\n".join(item["text"] for item in ocr["lines"])
            extraction = {
                "status": "extracted",
                "characters": len(_normalize(extracted_text)),
                "detail": f"已通过离线 OCR 识别 {ocr['pages_processed']} 页，平均置信度 {ocr['average_confidence']:.0%}",
            }
    normalized_text = _normalize(extracted_text)
    normalized_filename = _normalize(Path(document["original_name"]).stem)
    expected_keywords = DOCUMENT_TYPE_KEYWORDS.get(document["document_type"], (document["document_type"],))
    matched_type_terms = [term for term in expected_keywords if _normalize(term) in normalized_text or _normalize(term) in normalized_filename]
    exact_type_match = _normalize(document["document_type"]) in normalized_text or _normalize(document["document_type"]) in normalized_filename
    type_supported = exact_type_match or len(matched_type_terms) >= 2
    integrity_valid = hashlib.sha256(content).hexdigest() == document["sha256"]

    checks = [
        {
            "key": "file_integrity",
            "label": "文件指纹与格式",
            "status": "pass" if integrity_valid else "block",
            "detail": "文件指纹与归档记录一致" if integrity_valid else "文件指纹与归档记录不一致，禁止核验通过",
            "signals": [document["content_type"], Path(document["original_name"]).suffix.lower() or "无扩展名"],
        }
    ]

    if type_supported:
        type_status = "pass"
        type_detail = f"找到与“{document['document_type']}”一致的内容或文件名线索"
    elif extraction["status"] == "unavailable":
        type_status = "manual_review"
        type_detail = "当前文件无法提取文本，需人工核对资料分类"
    else:
        type_status = "warning"
        type_detail = f"未找到与“{document['document_type']}”一致的关键词，可能存在错分"
    checks.append({"key": "type_consistency", "label": "资料分类一致性", "status": type_status, "detail": type_detail, "signals": matched_type_terms})

    entity_terms = [value for value in ((counterparty or {}).get("name"), (counterparty or {}).get("credit_code")) if value]
    matched_entity_terms = [term for term in entity_terms if _normalize(term) in normalized_text or _normalize(term) in normalized_filename]
    if matched_entity_terms:
        entity_status = "pass"
        entity_detail = "找到企业名称或统一社会信用代码线索"
    elif extraction["status"] == "unavailable":
        entity_status = "manual_review"
        entity_detail = "当前文件无法提取主体文本，需人工核对企业归属"
    else:
        entity_status = "warning"
        entity_detail = "未找到当前企业名称或统一社会信用代码，需重点核对主体归属"
    checks.append({"key": "entity_consistency", "label": "企业主体一致性", "status": entity_status, "detail": entity_detail, "signals": matched_entity_terms})

    checks.append(
        {
            "key": "text_extractability",
            "label": "内容可提取性",
            "status": "pass" if extraction["status"] == "extracted" else "manual_review",
            "detail": extraction["detail"],
            "signals": [f"提取 {extraction['characters']} 个字符"],
        }
    )
    if ocr["status"] != "not_needed":
        if ocr["status"] == "success" and ocr["average_confidence"] >= 0.75:
            ocr_status = "pass"
            ocr_detail = f"离线 OCR 已完成，平均置信度 {ocr['average_confidence']:.0%}"
        elif ocr["status"] == "success":
            ocr_status = "warning"
            ocr_detail = f"OCR 平均置信度仅 {ocr['average_confidence']:.0%}，识别字段需逐项核对"
        else:
            ocr_status = "manual_review"
            ocr_detail = ocr.get("warning") or "OCR 未取得可用结果，需人工打开原件"
        checks.append({"key": "ocr_recognition", "label": "扫描件 OCR", "status": ocr_status, "detail": ocr_detail, "signals": [ocr.get("provider") or "未配置提供程序"]})
    statuses = {item["status"] for item in checks}
    overall_status = "block" if "block" in statuses else "warning" if "warning" in statuses else "manual_review" if "manual_review" in statuses else "pass"
    recommendations = []
    if type_status == "warning":
        recommendations.append("核对文件内容与资料类型；分类错误时要求重新上传或更正资料类型")
    if entity_status == "warning":
        recommendations.append("核对企业名称、统一社会信用代码及签章主体")
    if extraction["status"] == "unavailable":
        recommendations.append("打开原文件进行人工检查，自动预检不能替代人工核验")
    if ocr["status"] == "success" and ocr["average_confidence"] < 0.75:
        recommendations.append("OCR 置信度较低，不得直接据此确认主体、证照编号或有效期")
    if not recommendations:
        recommendations.append("自动预检未发现明显异常，仍须完成全部人工核验项")
    return {
        "document_id": document["id"],
        "document_type": document["document_type"],
        "overall_status": overall_status,
        "summary": {
            "pass": "自动预检通过",
            "warning": "发现需重点核对的线索",
            "manual_review": "需要人工读取原件",
            "block": "文件完整性异常",
        }[overall_status],
        "checks": checks,
        "recommendations": recommendations,
        "ocr": {
            "status": ocr["status"],
            "provider": ocr["provider"],
            "pages_processed": ocr["pages_processed"],
            "average_confidence": ocr["average_confidence"],
            "warning": ocr["warning"],
        },
        "extracted_fields": _extract_structured_fields(extracted_text, counterparty, ocr),
        "generated_from_sha256": document["sha256"],
        "disclaimer": "自动预检仅提供核验辅助，不替代独立风控人员的人工判断。",
    }


def _extract_text(content: bytes, content_type: str, filename: str) -> tuple[str, dict]:
    suffix = Path(filename).suffix.lower()
    if content_type == "text/plain" or suffix == ".txt":
        text = content.decode("utf-8", errors="ignore")[:MAX_EXTRACTED_CHARACTERS]
        return text, _extraction_result(text, "已读取文本文件")
    if suffix in {".docx", ".xlsx"}:
        text = _extract_office_xml(content, suffix)
        label = "Word" if suffix == ".docx" else "Excel"
        return text, _extraction_result(text, f"已从 {label} 文档提取可检索文本")
    if content_type == "application/pdf" or suffix == ".pdf":
        text = _extract_basic_pdf_text(content)
        return text, _extraction_result(text, "已从 PDF 文本层提取可检索字符")
    return "", {"status": "unavailable", "characters": 0, "detail": "图片或当前格式未配置 OCR，需人工打开原件"}


def _extract_office_xml(content: bytes, suffix: str) -> str:
    patterns = ("word/document.xml",) if suffix == ".docx" else ("xl/sharedStrings.xml", "xl/workbook.xml", "xl/worksheets/")
    fragments: list[str] = []
    total_bytes = 0
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist():
                if not any(info.filename == pattern or info.filename.startswith(pattern) for pattern in patterns):
                    continue
                if info.file_size > MAX_ZIP_MEMBER_BYTES or total_bytes + info.file_size > MAX_ZIP_TOTAL_BYTES:
                    continue
                raw = archive.read(info)
                total_bytes += len(raw)
                xml = raw.decode("utf-8", errors="ignore")
                fragments.append(html.unescape(re.sub(r"<[^>]+>", " ", xml)))
                if sum(len(item) for item in fragments) >= MAX_EXTRACTED_CHARACTERS:
                    break
    except (OSError, zipfile.BadZipFile):
        return ""
    return " ".join(fragments)[:MAX_EXTRACTED_CHARACTERS]


def _extract_basic_pdf_text(content: bytes) -> str:
    decoded = content[:2_000_000].decode("latin-1", errors="ignore")
    fragments = re.findall(r"\(([^()]*)\)\s*Tj|\[([^\]]*)\]\s*TJ", decoded)
    return " ".join(left or right for left, right in fragments)[:MAX_EXTRACTED_CHARACTERS]


def _extraction_result(text: str, success_detail: str) -> dict:
    characters = len(_normalize(text))
    if characters:
        return {"status": "extracted", "characters": characters, "detail": success_detail}
    return {"status": "unavailable", "characters": 0, "detail": "未提取到可检索文本，可能是扫描件或空文档，需人工打开原件"}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _extract_structured_fields(text: str, counterparty: dict | None, ocr: dict) -> list[dict]:
    if not text.strip():
        return []
    source = "ocr" if ocr["status"] == "success" else "text_layer"
    confidence = ocr["average_confidence"] if source == "ocr" else 1.0
    fields: list[dict] = []

    credit_codes = re.findall(r"(?<![A-Z0-9])[0-9A-Z]{18}(?![A-Z0-9])", text.upper())
    if credit_codes:
        fields.append(_field("credit_code", "统一社会信用代码", credit_codes[0], source, confidence, (counterparty or {}).get("credit_code")))

    known_name = (counterparty or {}).get("name")
    if known_name and _normalize(known_name) in _normalize(text):
        fields.append(_field("company_name", "企业名称", known_name, source, confidence, known_name))
    else:
        company_match = re.search(r"([\u4e00-\u9fffA-Za-z0-9（）()·]{4,50}(?:股份有限公司|有限责任公司|有限公司))", text)
        if company_match:
            fields.append(_field("company_name", "企业名称", company_match.group(1), source, confidence, known_name))

    legal_rep_match = re.search(r"法定代表人(?:\s*[:：]\s*|\s+)([\u4e00-\u9fff·]{2,20})", text)
    if legal_rep_match:
        fields.append(_field("legal_representative", "法定代表人", legal_rep_match.group(1), source, confidence, (counterparty or {}).get("legal_representative")))

    validity_match = re.search(r"(?:营业期限|有效期)\s*[:：]?\s*([0-9]{4}[^\n]{0,35}(?:长期|[0-9日]))", text)
    if validity_match:
        fields.append(_field("validity_period", "营业期限/有效期", validity_match.group(1).strip(), source, confidence, None))
    return fields[:8]


def _field(key: str, label: str, value: str, source: str, confidence: float, expected: str | None) -> dict:
    normalized_expected = _normalize(expected or "")
    matches_expected = None if not normalized_expected else normalized_expected == _normalize(value)
    return {
        "key": key,
        "label": label,
        "value": value[:128],
        "source": source,
        "confidence": round(confidence, 4),
        "matches_expected": matches_expected,
    }
