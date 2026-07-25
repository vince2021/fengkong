from __future__ import annotations

from rating.enterprise_indicator_pool import build_model_indicator_details
from rating.models import DIMENSIONS


TECH_BASE_LABELS = {
    "software_copyright_points": "软件著作权",
    "invention_patent_points": "国内发明专利",
    "pct_patent_points": "国际 PCT 专利",
    "utility_model_points": "实用新型专利",
    "utility_model_cap": "实用新型累计封顶",
    "ip_module_cap": "知识产权模块封顶",
    "premium_investor_points": "优质投资机构入股",
    "other_vc_one_points": "其他创投 1 家",
    "other_vc_two_or_more_points": "其他创投 2 家及以上",
    "investor_module_cap": "投资机构模块封顶",
    "industry_leader_order_points": "细分行业龙头订单",
    "aa_minus_customer_order_points": "AA- 以上客户订单",
    "order_module_cap": "订单/政府支持模块封顶",
    "bachelor_points": "实控人本科背景",
    "master_or_above_points": "实控人硕士及以上背景",
    "controller_experience_points": "实控人从业经历",
    "entrepreneurship_points": "创业经历",
    "shareholding_ratio_threshold": "前两大自然人持股比例阈值",
    "shareholding_ratio_points": "持股比例达标",
    "director_stability_points": "持股董事稳定",
    "audited_report_points": "经审计财务报告",
}

TECH_BONUS_LABELS = {
    "high_level_talent_points": "高层次人才股东",
    "specialized_new_national_points": "国家级专精特新",
    "specialized_new_provincial_points": "省级专精特新",
    "specialized_new_municipal_points": "市级专精特新",
    "rd_expense_revenue_ratio_3y_threshold": "三年研发费用/营收阈值",
    "rd_expense_revenue_ratio_3y_points": "研发投入达标",
    "annual_income_tax_paid_threshold": "所得税缴纳阈值",
    "annual_income_tax_paid_points": "所得税达标",
}

TECH_DEDUCTION_LABELS = {
    "bank_credit_count_threshold": "合作授信银行数阈值",
    "bank_credit_count_points": "合作授信银行数扣分",
    "major_bank_top_two_points": "主要银行位列前二扣分",
    "controller_changed_3y_points": "近三年实控人变化扣分",
    "environmental_penalty_2y_points": "近两年环保处罚扣分",
}

THRESHOLD_LABELS = {
    "major_litigation_amount": "重大诉讼金额阈值",
    "dishonesty_count": "失信记录阈值",
    "operating_abnormal_count": "经营异常阈值",
    "delivery_delay_count": "履约延期次数阈值",
    "invoice_match_rate": "发票匹配率最低要求",
    "overdue_rate": "逾期率阈值",
    "contract_dispute_count": "合同争议次数阈值",
}


def build_model_overview(config: dict) -> dict:
    indicators = build_indicator_library(config)
    return {
        "模型名称": config["name"],
        "模型版本": config["version"],
        "评分卡类型": _scorecard_type_label(config),
        "指标数量": len(indicators),
        "强规则数量": len(config.get("strong_rules", [])),
        "策略档位": len(build_strategy_matrix(config)),
        "配置方式": "业务低代码配置",
        "治理说明": "指标、规则、策略和版本均可审计追溯",
    }


def build_indicator_library(config: dict) -> list[dict]:
    if config.get("scorecard_type") == "tech_enterprise_basic":
        native_rows = _build_tech_indicator_library(config)
    elif config.get("scorecard_type") == "corporate_credit_v2":
        native_rows = _build_corporate_indicator_library(config)
    else:
        native_rows = _build_general_indicator_library(config)
    return native_rows + _build_enterprise_risk_pool_rows(config)


def _build_enterprise_risk_pool_rows(config: dict) -> list[dict]:
    return [
        {
            "指标类型": f"企业风险池 / {item['category']}",
            "指标名称": item["name"],
            "数据来源": item["data_source"],
            "配置项": f"{item['field_path']} / 相对权重 {item['model_weight']:g}",
            "当前配置": item["scoring"]["formula"],
            "解释口径": f"{item['statistics_period']}；1 分高风险、2 分关注或缺失、3 分低风险",
            "状态": "启用" if item["enabled"] else "停用",
        }
        for item in build_model_indicator_details(config)
    ]


def build_rule_matrix(config: dict) -> list[dict]:
    rows = []
    relation_labels = {"all": "同时满足", "any": "满足任一"}
    for rule in config.get("strong_rules", []):
        rows.append(
            {
                "规则编号": rule["id"],
                "规则名称": rule["name"],
                "启用状态": "启用" if rule.get("enabled", True) else "停用",
                "条件关系": relation_labels.get(rule.get("condition_relation", "all"), rule.get("condition_relation", "all")),
                "条件数量": len(rule.get("conditions", [])),
                "命中动作": rule.get("action", {}).get("access_strategy", "-"),
                "额度约束": _limit_cap_text(rule.get("action", {})),
                "复核要求": "需要" if rule.get("action", {}).get("review_required") else "不强制",
            }
        )
    return rows


def build_strategy_matrix(config: dict) -> list[dict]:
    if config.get("scorecard_type") == "tech_enterprise_basic":
        mapping = config.get("tech_scorecard", {}).get("limit_mapping", [])
        return [
            {
                "等级": item["rating"],
                "分数区间": f"{item['score_min']} - {item['score_max']}",
                "风险分层": item["risk_segment"],
                "准入策略": item["access_strategy"],
                "额度策略": item["limit_text"],
                "账期策略": item.get("credit_limit_text", "-"),
                "监控频率": _monitoring_frequency(item["rating"]),
            }
            for item in mapping
        ]

    return [
        {
            "等级": item["rating"],
            "分数区间": f"{item['score_min']} - {item['score_max']}",
            "风险分层": item["risk_segment"],
            "准入策略": item["access_strategy"],
            "额度策略": f"申请额度 × {item['limit_multiplier']:.0%}",
            "账期策略": f"{item['payment_term_days']} 天" if item["payment_term_days"] else "预付款",
            "监控频率": item["monitoring_frequency"],
        }
        for item in config.get("strategy_mapping", [])
    ]


def _build_general_indicator_library(config: dict) -> list[dict]:
    rows = []
    for key, weight in config.get("weights", {}).items():
        rows.append(
            {
                "指标类型": "一级维度",
                "指标名称": DIMENSIONS.get(key, key),
                "数据来源": _dimension_source(key),
                "配置项": "权重",
                "当前配置": f"{weight:.0%}",
                "解释口径": "按维度得分加权进入总分",
                "状态": "启用",
            }
        )
    for key, value in config.get("thresholds", {}).items():
        rows.append(
            {
                "指标类型": "阈值",
                "指标名称": THRESHOLD_LABELS.get(key, key),
                "数据来源": _threshold_source(key),
                "配置项": key,
                "当前配置": _format_value(value),
                "解释口径": "达到或突破阈值后影响扣分或强规则",
                "状态": "启用",
            }
        )
    return rows


def _build_corporate_indicator_library(config: dict) -> list[dict]:
    rows = []
    for key, weight in config.get("weights", {}).items():
        rows.append(
            {
                "指标类型": "决策层",
                "指标名称": DIMENSIONS.get(key, key),
                "数据来源": "子模型/矩阵",
                "配置项": "决策层权重",
                "当前配置": f"{weight:.0%}",
                "解释口径": "业务与财务先形成矩阵锚点，再与外部信用、交易行为合成",
                "状态": "启用",
            }
        )
    for dimension in config["indicator_model"]["dimensions"].values():
        for group in dimension["groups"]:
            for indicator in group["indicators"]:
                rows.append(
                    {
                        "指标类型": dimension["label"],
                        "指标名称": indicator["label"],
                        "数据来源": indicator.get("source", "待配置"),
                        "配置项": f"{group['label']} / {indicator['path']}",
                        "当前配置": f"组权重 {group['weight']:.0%}，指标权重 {indicator['weight']:.0%}",
                        "解释口径": f"{indicator['scoring']['type']} 分箱；缺失按中性分并降低完整度",
                        "状态": "启用",
                    }
                )
    return rows


def _build_tech_indicator_library(config: dict) -> list[dict]:
    rules = config["tech_scorecard"]["editable_rules"]
    rows = []
    rows.extend(_tech_rows("基础评分", rules["base"], TECH_BASE_LABELS))
    rows.extend(_tech_rows("加分项", rules["bonus"], TECH_BONUS_LABELS))
    rows.extend(_tech_rows("减分项", rules["deduction"], TECH_DEDUCTION_LABELS))
    for item in config["tech_scorecard"].get("limit_mapping", []):
        rows.append(
            {
                "指标类型": "策略映射",
                "指标名称": f"{item['rating']} 额度审批区间",
                "数据来源": "评分卡结果",
                "配置项": f"{item['score_min']} - {item['score_max']}",
                "当前配置": f"{item['risk_segment']} / {item['access_strategy']} / {item['limit_text']}",
                "解释口径": item.get("credit_limit_text", "-"),
                "状态": "启用",
            }
        )
    return rows


def _tech_rows(indicator_type: str, rules: dict, labels: dict) -> list[dict]:
    return [
        {
            "指标类型": indicator_type,
            "指标名称": labels.get(key, key),
            "数据来源": _tech_source(key),
            "配置项": key,
            "当前配置": _format_value(value),
            "解释口径": _tech_explanation(indicator_type, key),
            "状态": "启用",
        }
        for key, value in rules.items()
    ]


def _scorecard_type_label(config: dict) -> str:
    if config.get("scorecard_type") == "tech_enterprise_basic":
        return "科创企业基本评价模型"
    if config.get("scorecard_type") == "corporate_credit_v2":
        return "分层矩阵工商企业模型"
    return "通用加权评分模型"


def _dimension_source(key: str) -> str:
    return {
        "external_risk": "外部工商/司法/经营风险",
        "internal_performance": "内部订单/履约/合同/发票",
        "financial_credit": "财务应收/逾期/额度使用",
        "relationship_stability": "主体年限/关联稳定性",
    }.get(key, "综合数据")


def _threshold_source(key: str) -> str:
    if key in {"major_litigation_amount", "dishonesty_count", "operating_abnormal_count"}:
        return "外部企业风险数据"
    if key in {"delivery_delay_count", "invoice_match_rate", "contract_dispute_count"}:
        return "内部履约数据"
    if key == "overdue_rate":
        return "财务应收数据"
    return "模型配置"


def _tech_source(key: str) -> str:
    if "patent" in key or "copyright" in key or "ip_" in key:
        return "知识产权数据"
    if "investor" in key or "vc" in key:
        return "股权融资/投资机构数据"
    if "order" in key or "subsidy" in key or "government" in key:
        return "订单/政府支持数据"
    if "controller" in key or "entrepreneurship" in key or "shareholding" in key or "director" in key:
        return "实控人/团队稳定性数据"
    if "rd_" in key:
        return "研发投入数据"
    if "tax" in key:
        return "纳税数据"
    if "bank" in key or "credit" in key:
        return "融资结构数据"
    if "environmental" in key:
        return "合规处罚数据"
    return "评分卡配置"


def _tech_explanation(indicator_type: str, key: str) -> str:
    if key.endswith("_threshold"):
        return "达到阈值后触发对应加减分或资格判断"
    if "cap" in key:
        return "用于限制模块累计得分上限"
    if indicator_type == "减分项":
        return "命中后从总分中扣减"
    return "命中后按当前配置计入评分"


def _limit_cap_text(action: dict) -> str:
    if "limit_multiplier_cap" not in action:
        return "-"
    return f"不超过申请额度 × {float(action['limit_multiplier_cap']):.0%}"


def _monitoring_frequency(rating: str) -> str:
    return "月度" if rating in {"B", "D"} else "季度"


def _format_value(value) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and 0 < value < 1:
        return f"{value:.0%}"
    if isinstance(value, (int, float)):
        return f"{value:,.0f}" if abs(value) >= 10000 else str(value)
    return str(value)
