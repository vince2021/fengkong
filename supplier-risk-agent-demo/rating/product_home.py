from __future__ import annotations


AREA_USAGE = {
    "客户演示": "客户刚进入 Demo 时使用，用于建立场景理解、展示完整工作流和角色化讲法。",
    "售前推进": "客户产生兴趣后使用，用于生成跟进材料、试点计划和完整交付包。",
    "模型工作台": "客户追问模型、规则、数据和结果时使用，用于展示可配置、可解释和可复核能力。",
}


def build_product_home(navigation_groups: list[dict]) -> dict:
    return {
        "title": "客商信用评级与风险分层 Agent",
        "subtitle": "面向大型企业供应商/客户风险管理场景，把外部企业数据、内部履约数据、评分卡、强规则、人工复核和审计留痕串成一套可演示、可试点、可产品化的工作流。",
        "positioning": [
            {"标签": "目标客户", "内容": "大型企业的风控、内控、采购、销售、客户管理、IT/数据团队"},
            {"标签": "核心场景", "内容": "供应商/客户准入、信用评级、风险分层、额度与账期建议、人工复核、报告归档"},
            {"标签": "演示目标", "内容": "让客户从看懂流程，推进到愿意提供真实样本和字段做小范围试点"},
        ],
        "areas": [_area_card(group) for group in navigation_groups],
        "recommended_path": [
            {"步骤": "1", "target_area": "客户演示", "动作": "先走一遍演示流程，说明人机边界和端到端链路"},
            {"步骤": "2", "target_area": "客户演示", "动作": "按客户角色切换演示脚本，调整讲法和关注点"},
            {"步骤": "3", "target_area": "模型工作台", "动作": "客户追问规则时，展示评分详情、模型配置和评级变化"},
            {"步骤": "4", "target_area": "售前推进", "动作": "生成获客资产、试点工作台和完整交付包"},
        ],
        "deliverables": [
            {"name": "评级审核报告", "value": "用于准入审批、风险解释和审计归档"},
            {"name": "获客资产包", "value": "用于拜访后跟进和内部复盘"},
            {"name": "试点工作台", "value": "用于确认样本、字段、规则、验收指标和系统依赖"},
            {"name": "完整交付包", "value": "用于客户转发、立项沟通和试点启动"},
        ],
    }


def _area_card(group: dict) -> dict:
    return {
        "name": group["name"],
        "description": group["description"],
        "when_to_use": AREA_USAGE[group["name"]],
        "pages": "、".join(page["label"] for page in group["pages"]),
    }
