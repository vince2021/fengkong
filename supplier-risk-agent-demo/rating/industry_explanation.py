from __future__ import annotations

from rating.industry_context import preferred_industry_label
from rating.models import DIMENSIONS


INDUSTRY_PLAYBOOKS = {
    "general": {
        "positioning": "适用于尚未明确行业差异的供应商/客户准入、评级和复核场景，先建立统一的风险语言和模型治理框架。",
        "risk_assumptions": [
            "外部工商、司法、经营异常是跨行业准入底线，优先作为强规则和复核信号。",
            "内部履约、合同争议、发票匹配和逾期表现决定合作过程中的额度、账期和监控频率。",
            "评分卡先服务解释和分层，再逐步积累样本用于模型校准。",
        ],
        "dimension_rationale": {
            "external_risk": "先识别主体、司法和经营风险，避免明显高风险客商进入合作池。",
            "internal_performance": "用订单、合同、发票、履约记录验证合作质量。",
            "financial_credit": "用逾期、额度使用和信用表现评估资金占用风险。",
            "relationship_stability": "用合作年限、关联稳定性和经营持续性辅助判断长期合作价值。",
        },
    },
    "pharma": {
        "positioning": "适用于药品、器械、医药流通企业的供应商/客户风险管理，重点关注合规资质、司法风险和回款压力。",
        "risk_assumptions": [
            "药品和器械流通链条受监管约束强，主体异常、行政处罚和司法风险会直接影响合作准入。",
            "回款周期、票据匹配和历史逾期会放大资金占用风险，需要和额度、账期联动。",
            "客户希望看到的不只是评分，而是每个风险信号能否沉淀为审核依据。",
        ],
        "dimension_rationale": {
            "external_risk": "医药流通对主体合规和外部风险更敏感，因此外部风险权重更高。",
            "internal_performance": "履约表现用于验证配送、结算和合同执行质量。",
            "financial_credit": "逾期、额度使用和付款周期决定账期和额度策略。",
            "relationship_stability": "长期稳定合作可作为辅助加分，但不能覆盖底线风险。",
        },
    },
    "manufacturing": {
        "positioning": "适用于制造业供应商准入和客户信用评级，重点关注交付稳定性、质量履约和订单连续性。",
        "risk_assumptions": [
            "制造业合作风险更多发生在交付、质量、合同争议和供应连续性上。",
            "内部订单、履约、发票和售后记录比单纯外部工商信息更能反映真实合作风险。",
            "模型需要把供应中断、延期交付和争议记录转成可解释的准入和账期策略。",
        ],
        "dimension_rationale": {
            "external_risk": "外部风险仍是底线检查，但不是唯一判断依据。",
            "internal_performance": "制造业更依赖历史履约和交付稳定性，因此内部履约权重最高。",
            "financial_credit": "财务信用用于识别资金占用和回款风险。",
            "relationship_stability": "持续合作和经营稳定性有助于判断供应可靠性。",
        },
    },
    "construction": {
        "positioning": "适用于工程建筑客户/供应商风险管理，重点关注诉讼纠纷、回款风险、项目履约和大额敞口。",
        "risk_assumptions": [
            "工程建筑行业项目周期长、金额大，诉讼、执行和合同纠纷对合作风险影响明显。",
            "应收逾期、垫资压力和大额授信需要更审慎的额度与账期策略。",
            "模型输出必须保留人工复核空间，因为项目背景和履约责任往往需要业务解释。",
        ],
        "dimension_rationale": {
            "external_risk": "工程建筑外部诉讼和执行风险高，必须提高外部风险敏感度。",
            "internal_performance": "履约记录用于判断项目执行质量，但需要结合项目阶段解释。",
            "financial_credit": "大额应收和垫资压力使财务信用成为关键判断项。",
            "relationship_stability": "合作稳定性可辅助判断，但不能替代项目级风险复核。",
        },
    },
    "logistics": {
        "positioning": "适用于物流承运商、仓配服务商和供应链客户管理，重点关注履约稳定、运营异常和持续服务能力。",
        "risk_assumptions": [
            "物流合作强调时效、稳定和异常处置，延期、争议和服务中断会直接影响业务连续性。",
            "外部风险和内部履约需要同时看，单一工商信息不足以判断承运服务质量。",
            "模型要把风险分层转成监控频率、账期限制和是否需要人工复核。",
        ],
        "dimension_rationale": {
            "external_risk": "外部风险用于识别主体异常和经营稳定性问题。",
            "internal_performance": "物流服务质量高度依赖履约表现，因此内部履约权重较高。",
            "financial_credit": "财务信用用于判断账期和额度安排。",
            "relationship_stability": "稳定合作有助于判断服务连续性和替代风险。",
        },
    },
    "tech_enterprise_basic": {
        "positioning": "适用于科创企业基础评价，重点关注创新能力、经营稳定、授信结构和可持续发展信号。",
        "risk_assumptions": [
            "科创企业不能只看传统财务结果，需要结合研发、知识产权、税务和成长性信号。",
            "外部风险仍是底线，环保处罚、实控人变化和授信结构会影响稳定性判断。",
            "评分结论要能解释为什么给额度、为什么需要复核，以及哪些证据支持判断。",
        ],
        "dimension_rationale": {
            "external_risk": "科创企业仍需先排除主体和重大负面风险。",
            "internal_performance": "内部经营和合作记录用于验证商业化能力。",
            "financial_credit": "财务信用用于判断授信承载能力和资金压力。",
            "relationship_stability": "实控人、经营和合作稳定性影响持续发展判断。",
        },
    },
}


def build_industry_explanation(template_key: str, model_config: dict) -> dict:
    playbook = INDUSTRY_PLAYBOOKS.get(template_key, INDUSTRY_PLAYBOOKS["general"])
    label = preferred_industry_label(template_key)
    weights = model_config.get("weights", {})

    return {
        "industry_label": label,
        "model_name": model_config.get("name", "-"),
        "model_version": model_config.get("version", "-"),
        "positioning": playbook["positioning"],
        "risk_assumptions": [{"行业判断": item} for item in playbook["risk_assumptions"]],
        "weight_rationale": _build_weight_rationale(weights, playbook["dimension_rationale"]),
        "strong_rule_rationale": _build_strong_rule_rationale(model_config.get("strong_rules", [])),
        "human_boundaries": _build_human_boundaries(label),
        "talk_track": _build_talk_track(label, playbook["positioning"]),
    }


def _build_weight_rationale(weights: dict, dimension_rationale: dict) -> list[dict]:
    rows = []
    for key in weights:
        label = DIMENSIONS.get(key, key)
        rows.append(
            {
                "指标维度": label,
                "权重": f"{weights.get(key, 0):.0%}",
                "配置原因": dimension_rationale.get(key, "用于补充行业风险判断。"),
                "面客解释": f"这部分回答客户：{label} 为什么会影响准入、额度和监控策略。",
            }
        )
    return rows


def _build_strong_rule_rationale(strong_rules: list[dict]) -> list[dict]:
    rows = []
    for rule in strong_rules:
        rows.append(
            {
                "规则": f"{rule.get('id', '-')}-{rule.get('name', '-')}",
                "条件关系": "全部满足" if rule.get("condition_relation") == "all" else "任一命中",
                "模型动作": rule.get("action", {}).get("access_strategy", "人工复核"),
                "解释口径": _rule_explanation(rule),
            }
        )
    return rows


def _rule_explanation(rule: dict) -> str:
    labels = [condition.get("label", "") for condition in rule.get("conditions", []) if condition.get("label")]
    if not labels:
        return "用于把不可接受或需要复核的风险信号前置。"
    return "；".join(labels)


def _build_human_boundaries(industry_label: str) -> list[dict]:
    return [
        {
            "环节": "机器自动处理",
            "适合机器做": "批量取数、主体核验、工商司法经营风险扫描、评分计算、策略映射、报告初稿生成。",
            "人机边界": "机器负责一致性和效率，不替代业务负责人做最终合作判断。",
        },
        {
            "环节": "人工必须介入",
            "适合机器做": "提示命中原因、展示证据链、给出建议额度和账期。",
            "人机边界": f"{industry_label} 场景中，重大项目背景、战略客户例外、历史合作争议需要人工复核并留痕。",
        },
        {
            "环节": "审计留痕",
            "适合机器做": "记录模型版本、规则命中、人工调整前后结果和调整原因。",
            "人机边界": "人工可以调整结论，但必须写明原因，便于内控、审计和模型复盘。",
        },
    ]


def _build_talk_track(industry_label: str, positioning: str) -> list[dict]:
    return [
        {"讲解节点": "行业切入", "建议话术": f"这个模板不是通用评分卡换名字，而是围绕{industry_label}的真实合作风险来配置。"},
        {"讲解节点": "风险假设", "建议话术": positioning},
        {"讲解节点": "模型解释", "建议话术": "我们把权重、阈值、强规则和策略映射全部显性化，业务负责人能看懂，也能调整。"},
        {"讲解节点": "人机协同", "建议话术": "Agent 负责取数、计算和留痕，人工负责例外判断、业务解释和最终审批。"},
    ]
