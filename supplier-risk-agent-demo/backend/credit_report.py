from __future__ import annotations

import html
import hashlib
import json
import os
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from backend.decision_governance import build_decision_variance

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
    _REPORTLAB_AVAILABLE = True
except ModuleNotFoundError:
    _REPORTLAB_AVAILABLE = False


REPORT_SCHEMA_VERSION = "1.1"
FONT_NAME = "STSong-Light"


def build_credit_report_snapshot(
    case: dict,
    counterparty: dict,
    rating_run: dict,
    documents: list[dict],
    raw_profile: dict | None = None,
) -> dict:
    result = rating_run["result"]
    selection = case["data"].get("model_selection", {})
    proposal = case["data"].get("credit_proposal", {})
    final_strategy = case["data"].get("final_strategy", {})
    decision_variance = final_strategy.get("decision_variance") or build_decision_variance(proposal, final_strategy)
    application = case["data"].get("approval_submit", {})
    raw_profile = raw_profile or {}
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": "credit_decision",
        "case": {
            "case_id": case["case_id"],
            "status": case["status"],
            "counterparty_id": case["counterparty_id"],
            "counterparty_name": case["counterparty_name"],
            "created_at": case.get("created_at"),
            "completed_at": case.get("updated_at"),
        },
        "counterparty": {
            "id": counterparty["id"],
            "name": counterparty["name"],
            "credit_code": counterparty.get("credit_code", "-"),
            "counterparty_type": counterparty.get("counterparty_type", "supplier"),
            "industry": counterparty.get("industry", "-"),
            "cooperation_status": counterparty.get("cooperation_status", "-"),
        },
        "application": {
            "business_type": application.get("business_type", "-"),
            "requested_limit": application.get("requested_limit", counterparty.get("requested_limit", 0)),
            "requested_term_days": application.get("requested_term_days", 0),
        },
        "model": {
            "template_key": selection.get("template_key", rating_run.get("template_key")),
            "model_name": selection.get("model_name", "-"),
            "model_version": selection.get("model_version", result.get("model_version", "-")),
            "rating_run_id": rating_run["id"],
            "model_snapshot_id": rating_run["model_snapshot_id"],
            "input_hash": rating_run.get("input_hash") or _content_hash(rating_run["input"]),
            "result_hash": rating_run["result_hash"],
        },
        "rating": {
            "total_score": result.get("total_score"),
            "raw_rating": result.get("raw_rating"),
            "rating": result.get("rating"),
            "risk_segment": result.get("risk_segment"),
            "access_strategy": result.get("access_strategy"),
            "suggested_limit": result.get("suggested_limit"),
            "suggested_payment_term_days": result.get("suggested_payment_term_days"),
            "monitoring_frequency": result.get("monitoring_frequency"),
            "review_required": result.get("review_required", False),
            "data_completeness": result.get("data_completeness"),
            "calculation_formula": result.get("calculation_formula"),
            "dimension_scores": result.get("dimension_scores", {}),
            "indicator_explanations": result.get("indicator_explanations", []),
            "strong_rule_hits": result.get("strong_rule_hits", []),
            "main_positive_factors": result.get("main_positive_factors", []),
            "main_deductions": result.get("main_deductions", []),
        },
        "proposal": {
            "suggested_limit": proposal.get("suggested_limit", result.get("suggested_limit")),
            "suggested_payment_term_days": proposal.get("suggested_payment_term_days", result.get("suggested_payment_term_days")),
            "access_strategy": proposal.get("access_strategy", result.get("access_strategy")),
            "monitoring_frequency": proposal.get("monitoring_frequency", result.get("monitoring_frequency")),
        },
        "decision": {
            "decision": final_strategy.get("decision", "-"),
            "access_strategy": final_strategy.get("access_strategy", proposal.get("access_strategy", "-")),
            "approved_limit": final_strategy.get("approved_limit", 0),
            "approved_payment_term_days": final_strategy.get("approved_payment_term_days", 0),
            "monitoring_frequency": final_strategy.get("monitoring_frequency", proposal.get("monitoring_frequency", "-")),
            "facility_validity_days": final_strategy.get("facility_validity_days", 0),
        },
        "decision_variance": decision_variance,
        "documents": [
            {
                "id": item["id"],
                "document_type": item["document_type"],
                "original_name": item["original_name"],
                "sha256": item["sha256"],
                "status": item["status"],
                "created_at": item.get("created_at"),
            }
            for item in sorted(documents, key=lambda row: (row["document_type"], row["original_name"], row["id"]))
        ],
        "timeline": list(case.get("timeline", [])),
        "source_lineage": [
            {
                "source_id": item.get("source_id", "-"),
                "file": item.get("file", "-"),
                "pages": item.get("pages", "-"),
                "usage": item.get("usage", "-"),
            }
            for item in raw_profile.get("source_lineage", [])
        ],
        "data_limitations": list(raw_profile.get("missing_critical_fields", [])),
    }


def render_credit_report_pdf(snapshot: dict, report_no: str, report_version: int) -> bytes:
    if not _REPORTLAB_AVAILABLE:
        return _render_with_external_python(snapshot, report_no, report_version)
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    buffer = BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title=f"{snapshot['counterparty']['name']}信用评级与授信决策报告",
        author="衡信客商信用风险平台",
        subject=report_no,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="report-frame")
    doc.addPageTemplates(PageTemplate(id="credit-report", frames=[frame], onPage=lambda canvas, current_doc: _draw_page(canvas, current_doc, report_no)))
    styles = _styles()
    story: list[Any] = []

    story.extend([
        Paragraph("客商信用评级与授信决策报告", styles["title"]),
        Paragraph(_safe(snapshot["counterparty"]["name"]), styles["subtitle"]),
        Spacer(1, 5 * mm),
        _info_table([
            ("报告编号", report_no), ("归档版本", f"V{report_version}"),
            ("审批申请", snapshot["case"]["case_id"]), ("决策状态", snapshot["case"]["status"]),
            ("模型版本", snapshot["model"]["model_version"]), ("决策完成时间", _date_time(snapshot["case"].get("completed_at"))),
        ], styles),
        Spacer(1, 6 * mm),
    ])

    _section(story, "一、评级与授信结论", styles)
    rating = snapshot["rating"]
    decision = snapshot["decision"]
    story.append(_metric_table([
        ("综合评分", _score(rating.get("total_score"))),
        ("信用等级", rating.get("rating") or "-"),
        ("风险分层", rating.get("risk_segment") or "-"),
        ("最终决策", decision.get("decision") or "-"),
    ], styles))
    story.append(Spacer(1, 3 * mm))
    story.append(_comparison_table(snapshot, styles))
    story.extend([Spacer(1, 3 * mm), _decision_variance_note(snapshot.get("decision_variance", {}), styles)])

    _section(story, "二、企业与申请信息", styles)
    party = snapshot["counterparty"]
    application = snapshot["application"]
    story.append(_info_table([
        ("统一社会信用代码", party.get("credit_code", "-")), ("客商类型", "客户" if party.get("counterparty_type") == "customer" else "供应商"),
        ("所属行业", party.get("industry", "-")), ("合作状态", party.get("cooperation_status", "-")),
        ("业务类型", application.get("business_type", "-")), ("申请额度", _money(application.get("requested_limit"))),
        ("申请账期", _days(application.get("requested_term_days"))), ("授信有效期", _days(decision.get("facility_validity_days"))),
    ], styles))

    _section(story, "三、模型计算与关键因素", styles)
    model = snapshot["model"]
    story.append(_info_table([
        ("模型名称", model.get("model_name", "-")), ("模板标识", model.get("template_key", "-")),
        ("评级运行编号", model.get("rating_run_id", "-")), ("模型快照编号", model.get("model_snapshot_id", "-")),
        ("输入数据哈希", model.get("input_hash", "-")), ("结果数据哈希", model.get("result_hash", "-")),
    ], styles, compact=True))
    formula = rating.get("calculation_formula")
    if formula:
        story.extend([Spacer(1, 2 * mm), Paragraph(f"计算公式：{_safe(formula)}", styles["note"])])
    story.extend([Spacer(1, 3 * mm), _indicator_table(rating.get("indicator_explanations", []), styles)])

    _section(story, "四、强规则与人工复核边界", styles)
    hits = [item for item in rating.get("strong_rule_hits", []) if item.get("hit", True)]
    if hits:
        story.append(_rule_table(hits, styles))
    else:
        story.append(Paragraph("未命中强制覆盖规则。", styles["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"人工复核要求：{'需要' if rating.get('review_required') else '无需'}。最终策略以授权审批人的归档决策为准，模型仅提供可解释的决策支持。", styles["note"]))

    _section(story, "五、可信资料与数据来源", styles)
    story.append(_document_table(snapshot.get("documents", []), styles))
    if snapshot.get("source_lineage"):
        story.extend([Spacer(1, 3 * mm), Paragraph("材料来源追踪", styles["subhead"]), _source_table(snapshot["source_lineage"], styles)])
    limitations = snapshot.get("data_limitations", [])
    if limitations:
        story.extend([Spacer(1, 3 * mm), Paragraph("数据限制：" + "、".join(_safe(item) for item in limitations) + "。缺失字段不得解释为零风险。", styles["warning"])])

    _section(story, "六、审批轨迹", styles)
    story.append(_timeline_table(snapshot.get("timeline", []), styles))

    _section(story, "七、完整性封印", styles)
    snapshot_hash = _content_hash(snapshot)
    story.append(Paragraph(f"报告业务快照 SHA-256：{snapshot_hash}", styles["hash"]))
    story.append(Paragraph("本报告由审批单、冻结模型版本、可信评级运行、关联材料指纹与最终授信策略共同生成。报告元数据及文件指纹另行写入审计链；下载时系统会重新计算文件指纹，校验失败即拒绝提供文件。", styles["note"]))

    doc.build(story)
    return buffer.getvalue()


def build_report_preview(snapshot: dict) -> dict:
    return {
        "counterparty": snapshot["counterparty"],
        "case": snapshot["case"],
        "model": snapshot["model"],
        "rating": snapshot["rating"],
        "proposal": snapshot["proposal"],
        "decision": snapshot["decision"],
        "decision_variance": snapshot.get("decision_variance", {}),
        "document_count": len(snapshot.get("documents", [])),
        "timeline_count": len(snapshot.get("timeline", [])),
        "source_count": len(snapshot.get("source_lineage", [])),
        "data_limitations": snapshot.get("data_limitations", []),
    }


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName=FONT_NAME, fontSize=22, leading=29, textColor=colors.HexColor("#102a43"), alignment=TA_CENTER, spaceAfter=4),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=base["Normal"], fontName=FONT_NAME, fontSize=12, leading=18, textColor=colors.HexColor("#52667a"), alignment=TA_CENTER, wordWrap="CJK"),
        "section": ParagraphStyle("ReportSection", parent=base["Heading2"], fontName=FONT_NAME, fontSize=13, leading=19, textColor=colors.HexColor("#0f5d73"), spaceBefore=9, spaceAfter=5, wordWrap="CJK"),
        "subhead": ParagraphStyle("ReportSubhead", parent=base["Heading3"], fontName=FONT_NAME, fontSize=10.5, leading=15, textColor=colors.HexColor("#173f5f"), wordWrap="CJK"),
        "body": ParagraphStyle("ReportBody", parent=base["BodyText"], fontName=FONT_NAME, fontSize=9, leading=14, textColor=colors.HexColor("#243b53"), wordWrap="CJK"),
        "small": ParagraphStyle("ReportSmall", parent=base["BodyText"], fontName=FONT_NAME, fontSize=7.2, leading=10, textColor=colors.HexColor("#486581"), wordWrap="CJK"),
        "note": ParagraphStyle("ReportNote", parent=base["BodyText"], fontName=FONT_NAME, fontSize=8.2, leading=13, textColor=colors.HexColor("#486581"), backColor=colors.HexColor("#edf7fa"), borderPadding=6, wordWrap="CJK"),
        "warning": ParagraphStyle("ReportWarning", parent=base["BodyText"], fontName=FONT_NAME, fontSize=8.2, leading=13, textColor=colors.HexColor("#8a4b08"), backColor=colors.HexColor("#fff7e6"), borderPadding=6, wordWrap="CJK"),
        "hash": ParagraphStyle("ReportHash", parent=base["BodyText"], fontName=FONT_NAME, fontSize=7, leading=11, textColor=colors.HexColor("#334e68"), wordWrap="CJK"),
    }


def _draw_page(canvas, doc, report_no: str) -> None:
    canvas.saveState()
    canvas.setFont(FONT_NAME, 7)
    canvas.setFillColor(colors.HexColor("#829ab1"))
    canvas.drawString(18 * mm, 10 * mm, f"衡信客商信用风险平台  |  {report_no}")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
    canvas.setStrokeColor(colors.HexColor("#d9e2ec"))
    canvas.line(18 * mm, A4[1] - 14 * mm, A4[0] - 18 * mm, A4[1] - 14 * mm)
    canvas.restoreState()


def _section(story: list[Any], title: str, styles: dict[str, ParagraphStyle]) -> None:
    story.append(Paragraph(title, styles["section"]))


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_safe(value), style)


def _safe(value: Any) -> str:
    return html.escape(str(value if value not in (None, "") else "-"))


def _info_table(items: list[tuple[str, Any]], styles: dict[str, ParagraphStyle], compact: bool = False) -> Table:
    rows = []
    for index in range(0, len(items), 2):
        pair = items[index:index + 2]
        row: list[Any] = []
        for label, value in pair:
            row.extend([_paragraph(label, styles["small"]), _paragraph(value, styles["small"] if compact else styles["body"])])
        if len(pair) == 1:
            row.extend(["", ""])
        rows.append(row)
    table = Table(rows, colWidths=[29 * mm, 55.5 * mm, 29 * mm, 55.5 * mm], repeatRows=0)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4f8")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f0f4f8")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9e2ec")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _metric_table(items: list[tuple[str, Any]], styles: dict[str, ParagraphStyle]) -> Table:
    row = []
    for label, value in items:
        row.append([_paragraph(label, styles["small"]), Paragraph(_safe(value), ParagraphStyle("Metric", parent=styles["body"], fontSize=15, leading=20, textColor=colors.HexColor("#0f5d73"), alignment=TA_CENTER))])
    table = Table([row], colWidths=[42.25 * mm] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf7fa")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8d8e0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8d8e0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _comparison_table(snapshot: dict, styles: dict[str, ParagraphStyle]) -> Table:
    proposal, decision = snapshot["proposal"], snapshot["decision"]
    data = [[_paragraph(item, styles["small"]) for item in ["策略项目", "模型建议", "最终审批"]]]
    data.extend([
        [_paragraph("准入策略", styles["small"]), _paragraph(proposal.get("access_strategy"), styles["body"]), _paragraph(decision.get("access_strategy"), styles["body"])],
        [_paragraph("授信额度", styles["small"]), _paragraph(_money(proposal.get("suggested_limit")), styles["body"]), _paragraph(_money(decision.get("approved_limit")), styles["body"])],
        [_paragraph("授信账期", styles["small"]), _paragraph(_days(proposal.get("suggested_payment_term_days")), styles["body"]), _paragraph(_days(decision.get("approved_payment_term_days")), styles["body"])],
        [_paragraph("监控频率", styles["small"]), _paragraph(proposal.get("monitoring_frequency"), styles["body"]), _paragraph(decision.get("monitoring_frequency"), styles["body"])],
    ])
    return _styled_table(data, [35 * mm, 67 * mm, 67 * mm])


def _decision_variance_note(variance: dict, styles: dict[str, ParagraphStyle]) -> Paragraph:
    direction_labels = {"aligned": "与模型一致", "stricter": "审慎收紧", "relaxed": "风险放宽", "mixed": "混合调整", "rejected": "最终拒绝"}
    materiality_labels = {"none": "无偏差", "minor": "一般偏差", "material": "重大偏差"}
    direction = direction_labels.get(str(variance.get("direction")), str(variance.get("direction") or "未记录"))
    materiality = materiality_labels.get(str(variance.get("materiality")), str(variance.get("materiality") or "未记录"))
    reason = variance.get("reason_detail") or "模型建议与最终决策一致，无需填写调整原因。"
    category = variance.get("reason_category") or "无需调整"
    controls = "、".join(str(item) for item in variance.get("compensating_controls", [])) or "无"
    text = f"审批偏差治理：{direction} / {materiality}；原因类别：{category}；具体说明：{reason}；补偿性控制：{controls}"
    return Paragraph(_safe(text), styles["warning"] if variance.get("materiality") == "material" else styles["note"])


def _indicator_table(items: list[dict], styles: dict[str, ParagraphStyle]) -> Table:
    if not items:
        return Table([[_paragraph("暂无逐指标解释。", styles["body"])]], colWidths=[169 * mm])
    data = [[_paragraph(item, styles["small"]) for item in ["维度", "指标", "影响", "计算解释与证据"]]]
    for item in items[:30]:
        evidence = item.get("evidence")
        reason = item.get("reason") or "-"
        detail = f"{reason}；证据：{evidence}" if evidence not in (None, "") else reason
        data.append([
            _paragraph(item.get("dimension_label") or item.get("dimension"), styles["small"]),
            _paragraph(item.get("indicator"), styles["small"]),
            _paragraph(item.get("points", "-"), styles["small"]),
            _paragraph(detail, styles["small"]),
        ])
    return _styled_table(data, [30 * mm, 38 * mm, 18 * mm, 83 * mm], repeat_rows=1)


def _rule_table(items: list[dict], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[_paragraph(item, styles["small"]) for item in ["规则编号", "规则名称", "动作/影响", "命中条件"]]]
    for item in items:
        action = item.get("action") or {}
        action_text = "、".join(f"{key}={value}" for key, value in action.items()) or _safe(item.get("action", "-"))
        conditions = item.get("matched_conditions") or []
        condition_text = "；".join(str(row.get("label") or row.get("reason") or row) for row in conditions) or str(item.get("reason") or "-")
        data.append([
            _paragraph(item.get("rule_id", "-"), styles["small"]),
            _paragraph(item.get("rule_name") or item.get("name") or "-", styles["small"]),
            _paragraph(action_text, styles["small"]),
            _paragraph(condition_text, styles["small"]),
        ])
    return _styled_table(data, [24 * mm, 41 * mm, 49 * mm, 55 * mm], repeat_rows=1)


def _document_table(items: list[dict], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[_paragraph(item, styles["small"]) for item in ["资料类型", "文件名称", "SHA-256 指纹", "状态"]]]
    for item in items:
        data.append([
            _paragraph(item["document_type"], styles["small"]),
            _paragraph(item["original_name"], styles["small"]),
            _paragraph(item["sha256"], styles["small"]),
            _paragraph(item["status"], styles["small"]),
        ])
    if len(data) == 1:
        data.append([_paragraph("-", styles["small"]), _paragraph("无关联资料", styles["small"]), _paragraph("-", styles["small"]), _paragraph("-", styles["small"])])
    return _styled_table(data, [27 * mm, 55 * mm, 65 * mm, 22 * mm], repeat_rows=1)


def _source_table(items: list[dict], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[_paragraph(item, styles["small"]) for item in ["来源编号", "材料", "页码", "用途"]]]
    for item in items:
        data.append([_paragraph(item["source_id"], styles["small"]), _paragraph(item["file"], styles["small"]), _paragraph(item["pages"], styles["small"]), _paragraph(item["usage"], styles["small"])])
    return _styled_table(data, [28 * mm, 57 * mm, 20 * mm, 64 * mm], repeat_rows=1)


def _timeline_table(items: list[dict], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[_paragraph(item, styles["small"]) for item in ["时间", "环节", "处理人", "处理结果"]]]
    for item in items:
        data.append([
            _paragraph(item.get("处理时间", "-"), styles["small"]),
            _paragraph(item.get("环节", "-"), styles["small"]),
            _paragraph(item.get("处理人", "-"), styles["small"]),
            _paragraph(item.get("处理结果", "-"), styles["small"]),
        ])
    if len(data) == 1:
        data.append([_paragraph("-", styles["small"]), _paragraph("-", styles["small"]), _paragraph("-", styles["small"]), _paragraph("无审批轨迹", styles["small"])])
    return _styled_table(data, [34 * mm, 36 * mm, 30 * mm, 69 * mm], repeat_rows=1)


def _styled_table(data: list[list[Any]], widths: list[float], repeat_rows: int = 0) -> Table:
    table = Table(data, colWidths=widths, repeatRows=repeat_rows)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9eaf0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#173f5f")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _money(value: Any) -> str:
    try:
        return f"{float(value or 0):,.0f} 元"
    except (TypeError, ValueError):
        return "-"


def _days(value: Any) -> str:
    try:
        return f"{int(value or 0)} 天"
    except (TypeError, ValueError):
        return "-"


def _score(value: Any) -> str:
    try:
        return f"{float(value):.1f} 分"
    except (TypeError, ValueError):
        return "-"


def _date_time(value: Any) -> str:
    return str(value or "-").replace("T", " ").replace("+00:00", " UTC")


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _render_with_external_python(snapshot: dict, report_no: str, report_version: int) -> bytes:
    renderer_python = os.getenv("PDF_RENDERER_PYTHON", "").strip()
    if not renderer_python:
        raise RuntimeError("当前 Python 环境缺少 ReportLab，请安装项目依赖或配置 PDF_RENDERER_PYTHON")
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "tmp" / "pdfs"
    temp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as directory:
        input_path = Path(directory) / "report-input.json"
        output_path = Path(directory) / "report-output.pdf"
        input_path.write_text(json.dumps({"snapshot": snapshot, "report_no": report_no, "report_version": report_version}, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            [renderer_python, "-m", "backend.credit_report", str(input_path), str(output_path)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "PDF 渲染进程失败").strip()
            raise RuntimeError(message[:2000])
        return output_path.read_bytes()


def _main() -> None:
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m backend.credit_report INPUT_JSON OUTPUT_PDF")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not _REPORTLAB_AVAILABLE:
        raise SystemExit("ReportLab is not available in the renderer runtime")
    content = render_credit_report_pdf(payload["snapshot"], payload["report_no"], int(payload["report_version"]))
    Path(sys.argv[2]).write_bytes(content)


if __name__ == "__main__":
    _main()
