from __future__ import annotations


def build_delivery_package(flow: dict, guidance: dict, script: dict, assets: dict, pilot: dict) -> dict:
    company_name = flow["scenario_title"].split("｜", 1)[0]
    role_label = guidance["role_label"]
    summary = flow["summary"]
    rating_result = f"{summary['最终评级']} / {summary['准入策略']} / {summary['风险分层']}"

    return {
        "package_title": f"{company_name}｜{role_label}完整交付包",
        "cover_summary": {
            "演示企业": company_name,
            "目标角色": role_label,
            "评级结论": rating_result,
            "人工复核": summary["人工复核"],
            "客户核心问题": guidance["core_question"],
            "推荐下一步": guidance["next_action"],
        },
        "sections": {
            "演示脚本": _script_rows(script),
            "客户异议回应": script["objection_responses"],
            "演示准备清单": script["pre_demo_checklist"],
            "获客资产": _assets_rows(assets),
            "试点工作台": _pilot_rows(pilot),
        },
    }


def build_delivery_package_markdown(package: dict) -> str:
    sections = [f"# {package['package_title']}"]
    sections.append("## 封面摘要")
    sections.append(_dict_to_markdown(package["cover_summary"]))

    for section_name, rows in package["sections"].items():
        sections.append(f"## {section_name}")
        sections.append(_rows_to_markdown(rows))
    return "\n\n".join(sections)


def _script_rows(script: dict) -> list[dict]:
    rows = []
    for version_name, sections in script["versions"].items():
        for item in sections:
            rows.append(
                {
                    "版本": version_name,
                    "环节": item["section"],
                    "话术": item["talk_track"],
                    "看屏幕": item["screen_focus"],
                }
            )
    rows.append({"版本": "收口", "环节": "下一步", "话术": script["closing"], "看屏幕": "交付包与试点工作台"})
    return rows


def _assets_rows(assets: dict) -> list[dict]:
    rows = []
    for section_name in ["一页式方案摘要", "客户沟通纪要模板", "试点方案清单", "下一步行动计划"]:
        for item in assets[section_name]:
            rows.append({"资产": section_name, "内容": "；".join(f"{key}：{value}" for key, value in item.items())})
    return rows


def _pilot_rows(pilot: dict) -> list[dict]:
    rows = []
    for section_name in ["试点目标", "阶段路线图", "字段清单", "样本清单", "验收指标", "风险与依赖"]:
        for item in pilot[section_name]:
            rows.append({"模块": section_name, "内容": "；".join(f"{key}：{value}" for key, value in item.items())})
    return rows


def _dict_to_markdown(data: dict) -> str:
    rows = [{"项目": key, "内容": value} for key, value in data.items()]
    return _rows_to_markdown(rows)


def _rows_to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "暂无内容"
    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def _markdown_cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")
