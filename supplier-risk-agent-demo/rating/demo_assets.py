from __future__ import annotations


def build_demo_assets(flow: dict, guidance: dict) -> dict:
    company_name = flow["scenario_title"].split("｜", 1)[0]
    role_label = guidance["role_label"]
    result_text = _result_text(flow)

    solution_summary = [
        {"模块": "目标客户", "内容": f"面向{role_label}，围绕{guidance['core_question']}展开沟通。"},
        {"模块": "当前样本结论", "内容": result_text},
        {"模块": "核心价值", "内容": "把客商准入中的外部数据、内部履约、评分卡、强规则、人工复核和审计留痕串成完整工作流。"},
        {"模块": "角色关注点", "内容": "、".join(guidance["focus_points"])},
        {"模块": "可交付物", "内容": "；".join(f"{item['交付物']}：{item['用途']}" for item in flow["final_outputs"])},
    ]

    meeting_note_template = [
        {"记录项": "客户角色与部门", "待记录内容": role_label},
        {"记录项": "当前风险管理现状", "待记录内容": "记录客户现有供应商/客户准入、评级、复核、报告流程。"},
        {"记录项": "最关注的问题", "待记录内容": guidance["core_question"]},
        {"记录项": "认可的 Demo 环节", "待记录内容": "记录客户对流程、规则、报告、留痕或集成能力的反馈。"},
        {"记录项": "关键异议", "待记录内容": "记录客户对数据、模型、人机边界、系统集成、试点成本的疑问。"},
        {"记录项": "下一步承诺", "待记录内容": guidance["next_action"]},
    ]

    pilot_checklist = [
        {"阶段": "试点准备", "事项": "确认试点客商范围", "产出": "20-50 家客户/供应商样本清单"},
        {"阶段": "字段梳理", "事项": "确认内外部数据字段", "产出": "字段映射表和缺失字段说明"},
        {"阶段": "规则共创", "事项": "确认评分卡、强规则和人工复核条件", "产出": "准入规则清单和策略矩阵"},
        {"阶段": "历史回放", "事项": "用历史样本回放评级结果", "产出": "模型结果与历史表现对比"},
        {"阶段": "报告定稿", "事项": "确认评级报告模板和审计留痕字段", "产出": "可归档的报告样式"},
    ]

    action_plan = [
        {"事项": "确认试点样本范围", "负责人": "客户业务/风控负责人", "建议周期": "1-3 天"},
        {"事项": "收集字段清单与样本数据", "负责人": "客户 IT/数据负责人", "建议周期": "3-5 天"},
        {"事项": "共创规则与报告模板", "负责人": "双方项目组", "建议周期": "3-5 天"},
        {"事项": "完成一次样本回放演示", "负责人": "方案团队", "建议周期": "1 周"},
        {"事项": "形成试点评估与正式接入建议", "负责人": "双方负责人", "建议周期": "1-2 天"},
    ]

    return {
        "asset_title": f"{company_name}｜{role_label}获客资产包",
        "一页式方案摘要": solution_summary,
        "客户沟通纪要模板": meeting_note_template,
        "试点方案清单": pilot_checklist,
        "下一步行动计划": action_plan,
    }


def build_assets_markdown(assets: dict) -> str:
    sections = [f"# {assets['asset_title']}"]
    for section_name in ["一页式方案摘要", "客户沟通纪要模板", "试点方案清单", "下一步行动计划"]:
        sections.append(f"## {section_name}")
        sections.append(_rows_to_markdown(assets[section_name]))
    return "\n\n".join(sections)


def _rows_to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "暂无内容"
    headers = list(rows[0].keys())
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(row.get(header, "")) for header in headers) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator_line, *body])


def _markdown_cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _result_text(flow: dict) -> str:
    summary = flow["summary"]
    return f"{summary['最终评级']} / {summary['准入策略']} / {summary['风险分层']}，人工复核：{summary['人工复核']}"
