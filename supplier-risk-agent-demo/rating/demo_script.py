from __future__ import annotations


def build_demo_script(flow: dict) -> dict:
    summary = flow["summary"]
    scenario_title = flow["scenario_title"]
    company_name = scenario_title.split("｜", 1)[0]

    executive_version = [
        {
            "section": "开场定位",
            "talk_track": (
                f"今天用 {company_name} 做一条完整演示。系统会从资料接收、主体核验、风险扫描、评分计算到报告输出，"
                f"最终给出 {summary['最终评级']} 评级、{summary['准入策略']} 策略，并说明为什么。"
            ),
            "screen_focus": "演示流程 Tab 的企业选择和状态条。",
        },
        {
            "section": "业务价值",
            "talk_track": "这不是单点数据查询，而是把外部数据、内部履约数据、评分卡、强规则和人工复核串成一条可审计流程。",
            "screen_focus": "流程总览表和当前步骤卡片。",
        },
        {
            "section": "人机边界",
            "talk_track": "机器负责采集、计算、解释和留痕；人负责判断风险是否影响合作，以及最终审批责任。",
            "screen_focus": "人工判断字段。",
        },
        {
            "section": "收口",
            "talk_track": f"最后输出的是评级结论、风险证据链和审核报告，能够服务准入审批、管理层汇报和后续审计。",
            "screen_focus": "最终可交付物表。",
        },
    ]

    business_version = [
        {
            "section": "客户痛点",
            "talk_track": "传统客商准入经常分散在资料收集、外部查询、Excel 评分、邮件审批和报告归档里，效率低且难解释。",
            "screen_focus": "演示流程 Tab。",
        },
        *_step_tracks(flow["steps"]),
        {
            "section": "配置验证",
            "talk_track": "如果客户关心模型是不是黑盒，可以切到模型配置中心，展示权重、阈值、强规则、策略映射都能调整。",
            "screen_focus": "模型配置中心 Tab。",
        },
        {
            "section": "落地方式",
            "talk_track": "真实落地时，外部企业数据可以通过 API/MCP 接入，内部数据通过业务系统、数据仓库或 RAG 知识库接入。",
            "screen_focus": "流程中的外部风险扫描和内部数据匹配步骤。",
        },
    ]

    return {
        "versions": {
            "5 分钟高管版": executive_version,
            "15 分钟业务版": business_version,
        },
        "objection_responses": _objection_responses(summary),
        "pre_demo_checklist": [
            {"item": "准备一个高风险样本和一个优质样本", "reason": "便于展示强规则、人工复核和自动准入的差异。"},
            {"item": "先确认客户角色", "reason": "管理层看价值闭环，风控/内控看规则配置和审计留痕。"},
            {"item": "提前说明 Demo 数据边界", "reason": "外部数据可换成真实企查查数据，内部数据当前为模拟样本。"},
            {"item": "准备一个配置调整动作", "reason": "现场展示模型结果会随权重、阈值或强规则变化。"},
        ],
        "closing": (
            f"这套原型已经能跑通从准入申请到评级报告的核心链路。当前样本结论是 "
            f"{summary['最终评级']} / {summary['准入策略']} / {summary['风险分层']}。"
            "下一步可以用贵司真实字段做一次小范围试点，先验证流程、规则和报告模板，再讨论系统集成。"
        ),
    }


def _step_tracks(steps: list[dict]) -> list[dict]:
    tracks = []
    for step in steps:
        tracks.append(
            {
                "section": step["step_name"],
                "talk_track": f"这一环节的重点是：{step['demo_value']}",
                "screen_focus": f"演示流程中的 {step['step_name']} 步骤卡片。",
            }
        )
    return tracks


def _objection_responses(summary: dict) -> list[dict]:
    return [
        {
            "question": "AI 会不会替代审批人，出了问题责任算谁？",
            "answer": "不会替代。这里的人机边界很明确：AI 负责采集、计算、解释和留痕，审批人负责最终业务判断和责任确认。",
        },
        {
            "question": "模型是不是黑盒，业务人员能不能看懂？",
            "answer": "不是黑盒。Demo 中的权重、阈值、强规则和策略映射都能配置，输出也会保留评分解释和命中依据。",
        },
        {
            "question": "内部数据现在没有准备好，还能不能先做？",
            "answer": "可以先用外部数据和少量模拟内部字段跑 MVP，确认流程和报告模板后，再逐步接入订单、合同、发票、履约等数据。",
        },
        {
            "question": "为什么这家企业是这个结论？",
            "answer": f"可以沿着证据链解释：当前结果为 {summary['最终评级']} / {summary['准入策略']}，每一步都有数据来源、规则依据和人工复核入口。",
        },
    ]
