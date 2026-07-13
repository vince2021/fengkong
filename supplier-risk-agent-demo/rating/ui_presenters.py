from __future__ import annotations

from html import escape
from typing import Any


SUCCESS_KEYWORDS = ("AAA", "AA", "A", "自动准入", "准入", "优质", "核心", "无需", "否", "通过")
WARNING_KEYWORDS = ("B", "审慎", "人工复核", "限制", "关注", "重点监控", "需要", "是", "观察")
DANGER_KEYWORDS = ("C", "D", "禁入", "拒绝", "不予", "不建议", "高风险", "强拒", "失信")

BADGE_FIELDS = {"评级", "原始等级", "风险分层", "准入策略", "需复核", "动作", "是否满足", "模型策略", "复核后策略", "状态"}


def risk_tone(value: Any) -> str:
    text = _display_value(value)
    if text in {"-", "", "None"}:
        return "neutral"
    if any(keyword in text for keyword in DANGER_KEYWORDS):
        return "danger"
    if any(keyword in text for keyword in WARNING_KEYWORDS):
        return "warning"
    if any(keyword in text for keyword in SUCCESS_KEYWORDS):
        return "success"
    return "neutral"


def badge_html(label: Any, tone: str | None = None) -> str:
    display = _display_value(label)
    resolved_tone = tone or risk_tone(display)
    return f'<span class="risk-badge risk-badge-{resolved_tone}">{escape(display)}</span>'


def key_value_panel_html(data: dict[str, Any]) -> str:
    rows = []
    for key, value in data.items():
        rows.append(
            '<div class="kv-row">'
            f'<div class="kv-key">{escape(str(key))}</div>'
            f'<div class="kv-value">{_format_cell(key, value)}</div>'
            "</div>"
        )
    return f'<div class="kv-panel">{"".join(rows)}</div>'


def rows_table_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty-state">暂无数据</div>'

    headers = list(rows[0].keys())
    header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(
            f'<td data-label="{escape(str(header))}">{_format_cell(str(header), row.get(header, ""))}</td>'
            for header in headers
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="risk-table-wrap">'
        '<table class="risk-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</div>"
    )


def status_strip_html(items: list[tuple[str, Any]]) -> str:
    cells = []
    for label, value in items:
        cells.append(
            '<div class="status-cell">'
            f'<div class="status-label">{escape(label)}</div>'
            f'<div class="status-value">{badge_html(value)}</div>'
            "</div>"
        )
    return f'<div class="status-strip">{"".join(cells)}</div>'


def _format_cell(field: str, value: Any) -> str:
    display = _display_value(value)
    if isinstance(value, bool):
        return badge_html("需要" if value else "无需", "warning" if value else "success")
    if field in BADGE_FIELDS:
        return badge_html(display)
    return escape(display).replace("\n", "<br>")


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "-"
    return str(value)
