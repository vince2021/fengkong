from __future__ import annotations

from rating.industry_context import preferred_industry_label


ROUTE_BLUEPRINT = [
    {
        "page_key": "product_samples",
        "page_label": "样本场景",
        "target_area": "客户演示",
        "title": "先选客户故事",
        "demo_action": "按当前行业模板筛选样本，选择一个优质、关注或禁入样本作为演示主线。",
        "talk_track": "我们先不讲抽象能力，先用一个客户真实能理解的客商样本进入场景。",
        "customer_signal": "客户开始讨论自己有哪些供应商/客户样本，以及哪些风险故事最典型。",
        "handoff": "进入行业模板，解释为什么这个行业要这样看风险。",
    },
    {
        "page_key": "industry_template",
        "page_label": "行业模板",
        "target_area": "客户演示",
        "title": "解释行业化配置",
        "demo_action": "展示行业风险假设、权重配置、强规则和人机边界。",
        "talk_track": "这不是通用评分卡换名字，而是把行业风险、数据可得性和人工复核边界显性化。",
        "customer_signal": "客户开始追问指标、权重、阈值和强规则是否能按自身制度调整。",
        "handoff": "进入演示流程，展示这些配置如何串成端到端 Agent 工作流。",
    },
    {
        "page_key": "demo_flow",
        "page_label": "演示流程",
        "target_area": "客户演示",
        "title": "跑通端到端流程",
        "demo_action": "从资料接收、外部风险扫描、内部数据补充、评分评级、人工复核到报告输出逐步讲。",
        "talk_track": "客户看到的不是单点数据查询，而是一整套可落地的准入、评级、复核和留痕流程。",
        "customer_signal": "客户开始判断这套流程能否映射到现有部门、系统和审批节点。",
        "handoff": "进入演示脚本，根据客户角色切换讲法。",
    },
    {
        "page_key": "demo_script",
        "page_label": "演示脚本",
        "target_area": "客户演示",
        "title": "切换角色化讲法",
        "demo_action": "按业务负责人、风控/内控、管理层或 IT/数据角色切换演示版本。",
        "talk_track": "不同角色关心的问题不同，同一个 Demo 要能换成不同沟通语言。",
        "customer_signal": "客户开始明确谁会参与试点评审，以及下一轮要对谁重点讲。",
        "handoff": "进入客户问答，集中处理数据、技术、模型和审计疑问。",
    },
    {
        "page_key": "customer_qa",
        "page_label": "客户问答",
        "target_area": "客户演示",
        "title": "处理现场异议",
        "demo_action": "按数据接入、技术架构、模型解释、人机边界、审计合规和落地周期选择客户问题。",
        "talk_track": "客户问得越具体，越说明他已经开始把 Demo 代入自己的业务和系统。",
        "customer_signal": "客户愿意提供字段、样本、流程和系统边界信息。",
        "handoff": "进入获客资产，生成拜访后可带走的材料。",
    },
    {
        "page_key": "sales_assets",
        "page_label": "获客资产",
        "target_area": "售前推进",
        "title": "沉淀跟进材料",
        "demo_action": "生成一页式方案摘要、客户沟通纪要、试点清单和下一步行动。",
        "talk_track": "演示结束后，客户内部转述需要材料，不能只靠口头印象。",
        "customer_signal": "客户愿意把材料转给业务、IT、内控或管理层。",
        "handoff": "进入试点工作台，把意向变成可执行试点范围。",
    },
    {
        "page_key": "pilot_workspace",
        "page_label": "试点工作台",
        "target_area": "售前推进",
        "title": "推进试点立项",
        "demo_action": "确认试点目标、阶段路线图、字段清单、样本清单、验收指标和风险依赖。",
        "talk_track": "最终要把一次 Demo 变成 2 到 4 周的小范围验证，而不是停留在概念交流。",
        "customer_signal": "客户愿意指定牵头人、准备样本和确认试点验收口径。",
        "handoff": "进入下一轮真实样本验证、字段盘点和方案报价。",
    },
]


def build_demo_route(template_key: str, model_config: dict) -> dict:
    industry_label = preferred_industry_label(template_key)
    return {
        "industry_label": industry_label,
        "model_name": model_config.get("name", "-"),
        "model_version": model_config.get("version", "-"),
        "opening": f"面向{industry_label}场景，把客户演示和售前推进串成一条可点击路线，减少现场来回找页面。",
        "steps": [
            {
                "step_no": f"{index:02d}",
                **step,
            }
            for index, step in enumerate(ROUTE_BLUEPRINT, start=1)
        ],
    }


def build_demo_route_markdown(route: dict) -> str:
    lines = [
        "# 面客演示路线手卡",
        "",
        f"- 行业：{route['industry_label']}",
        f"- 模型名称：{route['model_name']}",
        f"- 模型版本：{route['model_version']}",
        f"- 路线目标：{route['opening']}",
        "",
        "## 路线总览",
        "",
    ]
    for step in route["steps"]:
        lines.append(f"- {step['step_no']}. {step['page_label']}｜{step['title']}｜{step['target_area']}")

    for step in route["steps"]:
        lines.extend(
            [
                "",
                f"## {step['step_no']}. {step['page_label']}",
                "",
                f"- 所在区域：{step['target_area']}",
                f"- 演示目标：{step['title']}",
                f"- 现场动作：{step['demo_action']}",
                f"- 讲解主线：{step['talk_track']}",
                f"- 客户信号：{step['customer_signal']}",
                f"- 下一步承接：{step['handoff']}",
            ]
        )

    lines.extend(
        [
            "",
            "## 使用建议",
            "",
            "- 拜访前：按路线预演 1 遍，确认当前客户最适合的样本和行业模板。",
            "- 拜访中：如果客户追问技术、模型或审计问题，直接切到客户问答页。",
            "- 拜访后：用获客资产和试点工作台沉淀下一步行动。",
        ]
    )
    return "\n".join(lines)
