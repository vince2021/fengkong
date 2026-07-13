from __future__ import annotations


AUDIENCE_OPTIONS = [
    {"key": "management", "label": "管理层"},
    {"key": "risk_control", "label": "风控/内控负责人"},
    {"key": "procurement", "label": "采购/供应商管理"},
    {"key": "sales_customer", "label": "销售/客户管理"},
    {"key": "it_data", "label": "IT/数据负责人"},
]


ROLE_PROFILES = {
    "management": {
        "label": "管理层",
        "core_question": "这套系统能不能提升决策效率、降低风险暴露，并形成可管理的试点路径？",
        "focus_points": ["决策效率", "风险暴露压降", "跨部门协同", "审计与管理层汇报"],
        "screen_route": "先看演示流程的状态条，再看驾驶舱的额度压降和高风险/禁入数量，最后看收口话术。",
        "success_criteria": ["能看到风险识别结果", "能看到额度和准入建议", "能形成小范围试点方案"],
        "next_action": "建议用贵司 20-50 家真实客商做小范围试点，验证流程、规则、报告模板和管理看板。",
    },
    "risk_control": {
        "label": "风控/内控负责人",
        "core_question": "模型规则是否可解释、强规则是否可治理、人工复核和审计留痕是否完整？",
        "focus_points": ["强规则治理", "评分解释", "人工复核", "审计留痕", "模型版本管理"],
        "screen_route": "重点看演示流程的人机边界、企业评分详情、模型配置中心和审核报告预览。",
        "success_criteria": ["规则可配置", "证据可解释", "人工调整有原因", "审计链路可追溯"],
        "next_action": "建议先共创一版准入规则清单和报告模板，再用历史案例做回放验证。",
    },
    "procurement": {
        "label": "采购/供应商管理",
        "core_question": "能不能更快判断供应商是否准入、是否限额、是否需要补充材料？",
        "focus_points": ["供应商准入效率", "补充材料判断", "供应商分层", "履约风险预警"],
        "screen_route": "先看资料接收和主体核验，再看内部履约证据、强规则判断和人工复核入口。",
        "success_criteria": ["减少重复查询", "缩短准入周期", "统一供应商风险口径", "沉淀供应商证据链"],
        "next_action": "建议选一个供应商准入流程做试点，把资料清单、外部查询和内部履约字段先跑通。",
    },
    "sales_customer": {
        "label": "销售/客户管理",
        "core_question": "能不能判断客户是否值得赊销、给多少额度、账期怎么控？",
        "focus_points": ["客户信用分层", "赊销额度建议", "账期策略", "回款和逾期风险"],
        "screen_route": "重点看评分卡计算、额度策略、风险分层和报告输出。",
        "success_criteria": ["额度建议可解释", "账期策略可落地", "高风险客户能提前识别", "销售和风控口径一致"],
        "next_action": "建议用一批存量客户做评级回放，比较模型建议与历史回款表现是否一致。",
    },
    "it_data": {
        "label": "IT/数据负责人",
        "core_question": "外部数据、内部系统、模型规则和报告输出如何集成，数据边界在哪里？",
        "focus_points": ["API/MCP 接入", "内部数据字段", "系统集成", "权限和留痕", "数据质量"],
        "screen_route": "重点看外部风险扫描、内部数据匹配、模型配置中心和报告输出。",
        "success_criteria": ["字段清单明确", "接口边界清楚", "权限和日志可设计", "能先以低代码方式试点"],
        "next_action": "建议先确认字段映射、接口方式和系统落点，再决定是否接入正式业务系统。",
    },
}


def build_audience_guidance(role_key: str, flow: dict) -> dict:
    resolved_key = role_key if role_key in ROLE_PROFILES else "risk_control"
    profile = ROLE_PROFILES[resolved_key]
    summary = flow["summary"]
    company_name = flow["scenario_title"].split("｜", 1)[0]

    return {
        "role_key": resolved_key,
        "role_label": profile["label"],
        "core_question": profile["core_question"],
        "opening_line": (
            f"如果今天面对的是{profile['label']}，建议先说：我们用 {company_name} 演示一条完整准入链路，"
            f"当前结论是 {summary['最终评级']} / {summary['准入策略']}，重点看这套结论如何被解释、复核和落地。"
        ),
        "focus_points": profile["focus_points"],
        "screen_route": profile["screen_route"],
        "success_criteria": profile["success_criteria"],
        "likely_questions": _likely_questions(resolved_key, summary),
        "next_action": profile["next_action"],
    }


def _likely_questions(role_key: str, summary: dict) -> list[dict]:
    common = [
        {
            "question": "这个结论为什么可信？",
            "answer": f"因为当前 {summary['最终评级']} / {summary['准入策略']} 不是单一模型分数，而是外部数据、内部证据、强规则和人工复核共同形成的结论。",
        },
        {
            "question": "AI 会不会替代人工审批？",
            "answer": "不会。人机边界是：AI 负责采集、计算、解释和留痕，人负责风险是否影响合作的判断和最终审批责任。",
        },
    ]
    role_specific = {
        "management": [
            {"question": "投入产出怎么判断？", "answer": "先看准入周期、人工查询成本、高风险识别率和额度压降，再用小范围试点验证收益。"},
        ],
        "risk_control": [
            {"question": "规则后续怎么维护？", "answer": "强规则、阈值、策略映射和模型版本都应由风控/内控负责治理，并保留调整原因和版本记录。"},
        ],
        "procurement": [
            {"question": "供应商材料不齐怎么办？", "answer": "先让 Agent 标记缺失材料和影响判断的风险点，再由采购或供应商补充材料。"},
        ],
        "sales_customer": [
            {"question": "销售觉得额度太低怎么办？", "answer": "可以走人工复核，但必须说明业务理由、补充证据并保留额度调整记录。"},
        ],
        "it_data": [
            {"question": "内部系统暂时接不了怎么办？", "answer": "可以先用导入表或模拟字段跑 MVP，确认规则和流程后再接 API、数据仓库或业务系统。"},
        ],
    }
    return common + role_specific.get(role_key, [])
