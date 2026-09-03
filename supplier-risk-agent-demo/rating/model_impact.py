from __future__ import annotations

from copy import deepcopy

from rating.models import DIMENSIONS
from rating.rules import get_field_value
from rating.scorecard import rate_counterparty
from rating.enterprise_indicator_pool import build_model_indicator_details, evaluate_indicator_pool


EDITABLE_INDICATORS = [
    {"path": "external.major_litigation_amount", "label": "重大诉讼金额", "unit": "元", "step": 100000.0, "min": 0.0, "max": 10000000000.0},
    {"path": "external.dishonesty_count", "label": "失信记录", "unit": "条", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "external.operating_abnormal_count", "label": "经营异常", "unit": "条", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "external.admin_penalty_count", "label": "行政处罚", "unit": "条", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "external.equity_freeze_count", "label": "股权冻结", "unit": "条", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "internal.delivery_delay_count", "label": "履约延期次数", "unit": "次", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "internal.contract_dispute_count", "label": "合同争议次数", "unit": "次", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "internal.invoice_match_rate", "label": "发票匹配率", "unit": "%", "step": 0.01, "min": 0.0, "max": 1.0},
    {"path": "internal.delivery_fulfillment_rate", "label": "交付达成率", "unit": "%", "step": 0.01, "min": 0.0, "max": 1.0},
    {"path": "financial.overdue_rate", "label": "逾期率", "unit": "%", "step": 0.01, "min": 0.0, "max": 1.0},
    {"path": "financial.avg_collection_days", "label": "平均回款周期", "unit": "天", "step": 5.0, "min": 0.0, "max": 3650.0},
    {"path": "financial.limit_utilization_rate", "label": "额度使用率", "unit": "%", "step": 0.01, "min": 0.0, "max": 1.0},
    {"path": "external.established_years", "label": "成立年限", "unit": "年", "step": 1.0, "min": 0.0, "max": 200.0},
]

CORPORATE_EDITABLE_INDICATORS = [
    {"path": "corporate_profile.operations.sales_growth_pct", "label": "跨期营业收入增长率", "unit": "%", "value_scale": "whole", "step": 1.0, "min": -100.0, "max": 300.0},
    {"path": "corporate_profile.operations.profit_growth_pct", "label": "跨期利润增长率", "unit": "%", "value_scale": "whole", "step": 1.0, "min": -100.0, "max": 500.0},
    {"path": "corporate_profile.financial.net_profit_margin_change_pct", "label": "净利润率变动", "unit": "%", "value_scale": "whole", "step": 1.0, "min": -100.0, "max": 500.0},
    {"path": "corporate_profile.financial.debt_to_assets_pct", "label": "跨期资产负债率", "unit": "%", "value_scale": "whole", "step": 1.0, "min": 0.0, "max": 150.0},
    {"path": "corporate_profile.financial.net_profit_margin_pct", "label": "跨期净利润率", "unit": "%", "value_scale": "whole", "step": 0.5, "min": -100.0, "max": 100.0},
    {"path": "corporate_profile.financial.return_on_equity_pct", "label": "跨期净资产收益率", "unit": "%", "value_scale": "whole", "step": 1.0, "min": -500.0, "max": 500.0},
    {"path": "corporate_profile.operations.total_asset_turnover", "label": "跨期总资产周转次数", "unit": "次", "step": 0.05, "min": 0.0, "max": 20.0},
    {"path": "corporate_profile.business.total_assets_yi", "label": "资产总额", "unit": "亿元", "step": 1.0, "min": 0.0, "max": 100000.0},
    {"path": "corporate_profile.business.revenue_yi", "label": "跨期营业收入", "unit": "亿元", "step": 1.0, "min": 0.0, "max": 100000.0},
    {"path": "corporate_profile.business.patent_count", "label": "专利储备", "unit": "项", "step": 1.0, "min": 0.0, "max": 100000.0},
]

TECH_EDITABLE_INDICATORS = [
    {"path": "tech_enterprise.software_copyright_count", "label": "软件著作权数量", "unit": "项", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "tech_enterprise.invention_patent_count", "label": "国内发明专利数量", "unit": "项", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "tech_enterprise.pct_patent_count", "label": "国际 PCT 专利数量", "unit": "项", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "tech_enterprise.utility_model_patent_count", "label": "实用新型专利数量", "unit": "项", "step": 1.0, "min": 0.0, "max": 10000.0},
    {"path": "tech_enterprise.other_vc_count", "label": "其他创投机构数量", "unit": "家", "step": 1.0, "min": 0.0, "max": 100.0},
    {"path": "tech_enterprise.entrepreneurship_years", "label": "实际控制人创业年限", "unit": "年", "step": 1.0, "min": 0.0, "max": 100.0},
    {"path": "tech_enterprise.top_two_natural_person_shareholding_ratio", "label": "前两大自然人股东持股比例", "unit": "%", "step": 0.01, "min": 0.0, "max": 1.0},
    {"path": "tech_enterprise.rd_expense_revenue_ratio_3y", "label": "近三年研发费用/营收", "unit": "%", "step": 0.005, "min": 0.0, "max": 1.0},
    {"path": "tech_enterprise.annual_income_tax_paid", "label": "近一年企业所得税", "unit": "元", "step": 10000.0, "min": 0.0, "max": 10000000000.0},
    {"path": "tech_enterprise.bank_credit_count", "label": "合作授信银行数量", "unit": "家", "step": 1.0, "min": 0.0, "max": 100.0},
    {"path": "tech_enterprise.core_team_shareholding_ratio", "label": "核心团队持股比例", "unit": "%", "step": 0.01, "min": 0.0, "max": 1.0},
    {"path": "tech_enterprise.rd_staff_ratio", "label": "核心研发人员占比", "unit": "%", "step": 0.01, "min": 0.0, "max": 1.0},
    {"path": "tech_enterprise.main_business_revenue", "label": "主营业务收入", "unit": "元", "step": 100000.0, "min": 0.0, "max": 100000000000.0},
    {"path": "tech_enterprise.latest_net_assets", "label": "最近一期净资产", "unit": "元", "step": 100000.0, "min": -100000000000.0, "max": 100000000000.0},
    {"path": "tech_enterprise.revenue_growth_rate", "label": "最近一年营业收入增长率", "unit": "%", "step": 0.01, "min": -1.0, "max": 10.0},
    {"path": "tech_enterprise.asset_liability_ratio", "label": "资产负债率", "unit": "%", "step": 0.01, "min": 0.0, "max": 2.0},
    {"path": "tech_enterprise.gross_margin", "label": "毛利率", "unit": "%", "step": 0.01, "min": -1.0, "max": 1.0},
    {"path": "tech_enterprise.cash_reserve_to_three_expenses", "label": "现金储备/年三项费用", "unit": "倍", "step": 0.1, "min": 0.0, "max": 100.0},
    {"path": "tech_enterprise.rd_expense_revenue_ratio_current", "label": "当年研发费用/收入", "unit": "%", "step": 0.005, "min": 0.0, "max": 1.0},
]


def get_editable_indicators(config: dict) -> list[dict]:
    if config.get("scorecard_type") == "corporate_credit_v2":
        native = CORPORATE_EDITABLE_INDICATORS
    elif config.get("scorecard_type") == "tech_enterprise_basic":
        native = TECH_EDITABLE_INDICATORS
    else:
        native = EDITABLE_INDICATORS
    rows = [dict(item) for item in native]
    existing_paths = {item["path"] for item in rows}
    for indicator in (config.get("scorecard_binding") or {}).get("config", {}).get("indicators", []):
        if indicator.get("data_type") != "numeric" or indicator.get("field_path") in existing_paths:
            continue
        boundaries = [value for band in indicator.get("bins", []) for value in (band.get("lower"), band.get("upper")) if value is not None]
        rows.append({"path": indicator["field_path"], "label": f"[治理评分卡] {indicator['indicator_name']}", "unit": "数值", "step": 1.0, "min": min(boundaries, default=0) - 100, "max": max(boundaries, default=100) + 100, "source": "governed_scorecard"})
        existing_paths.add(indicator["field_path"])
    for indicator in build_model_indicator_details(config):
        if not indicator["enabled"] or indicator["scoring"]["type"] == "composite_boolean" or indicator["field_path"] in existing_paths:
            continue
        data_type = indicator["data_type"]
        rows.append(
            {
                "path": indicator["field_path"],
                "label": f"[企业风险池] {indicator['name']}",
                "unit": {"boolean": "0/1", "count": "次", "amount": "元", "years": "年", "numeric": "数值"}[data_type],
                "step": 10000.0 if data_type == "amount" else 0.01 if data_type == "numeric" else 1.0,
                "min": 0.0,
                "max": {"boolean": 1.0, "count": 100000.0, "amount": 100000000000.0, "years": 200.0, "numeric": 100000000000.0}[data_type],
                "source": "enterprise_risk_pool",
            }
        )
        existing_paths.add(indicator["field_path"])
    return rows


def build_score_calculation_trace(counterparty: dict, config: dict) -> dict:
    result = rate_counterparty(counterparty, config)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "当前模型配置无法完成评分"),
            "result": result,
            "dimension_contributions": [],
            "indicator_deductions": [],
            "formula": "总分 = Σ（维度得分 × 维度权重），当前需先修正模型配置后才能计算。",
        }
    if result.get("scorecard_execution"):
        return _build_governed_scorecard_trace(result)
    if result.get("scorecard_type") == "corporate_credit_v2":
        return _build_corporate_trace(result, config)
    if config.get("scorecard_type") == "tech_enterprise_basic":
        return _build_tech_trace(result)

    weights = config.get("weights", {})
    dimension_rows = []
    for key, score in result.get("dimension_scores", {}).items():
        weight = float(weights.get(key, 0))
        dimension_rows.append(
            {
                "维度": DIMENSIONS.get(key, key),
                "维度得分": score,
                "权重": f"{weight:.0%}",
                "加权贡献": round(score * weight, 2),
                "计算公式": f"{score:g} × {weight:.0%} = {score * weight:.2f}",
            }
        )
    deductions = [
        {
            "维度": DIMENSIONS.get(item["dimension"], item["dimension"]),
            "指标": item["indicator"],
            "扣分": item["points"],
            "证据": item["evidence"],
            "运算": f"维度基础分 100 - {item['points']:g}",
        }
        for item in result.get("indicator_explanations", [])
    ]
    return {
        "ok": True,
        "result": result,
        "dimension_contributions": dimension_rows,
        "indicator_deductions": deductions,
        "formula": "总分 = Σ（维度得分 × 维度权重），经强规则处理后，再由企业风险贷策层按最严格结果收紧",
    }


def _build_governed_scorecard_trace(result: dict) -> dict:
    execution = result["scorecard_execution"]
    indicator_rows = [
        {
            "维度": "治理评分卡", "指标组": f"{execution['code']}@v{execution['version']}",
            "指标": item["indicator_name"], "原始值": "缺失" if item["missing"] else str(item["actual_value"]),
            "标准分": item["score"], "有效权重": f"{item['weight']:g}%",
            "扣分": round(max(0, item["max_score"] - item["score"]) * item["weight"] / 100, 2),
            "证据": f"{item['field_path']} @ {item['indicator_version']}",
            "运算": f"命中 {item['bin_label']}，箱分 {item['score']:g} × 权重 {item['weight']:g}%",
            "数据状态": "待补充" if item["missing"] else "已取得",
        }
        for item in execution["details"]
    ]
    return {
        "ok": True, "result": result,
        "dimension_contributions": [{"维度": "治理评分卡", "维度得分": execution["normalized_score"], "权重": "100%", "加权贡献": execution["normalized_score"], "计算公式": f"原始分 {execution['raw_score']:g} 映射至标准分 {execution['normalized_score']:g}"}],
        "indicator_deductions": indicator_rows,
        "data_quality": {"缺失指标": str(execution["missing_count"]), "评分卡版本": f"{execution['code']}@v{execution['version']}", "配置哈希": execution["config_hash"]},
        "formula": f"评分卡业务刻度分 {execution['scaled_score']:g}；标准分 {execution['normalized_score']:g} 用于既有评级与策略区间",
    }


def simulate_indicator_change(counterparty: dict, config: dict, field_path: str, new_value) -> dict:
    changed = deepcopy(counterparty)
    old_value = get_field_value(counterparty, field_path)
    _set_field_value(changed, field_path, new_value)
    before = rate_counterparty(counterparty, config)
    after = rate_counterparty(changed, config)
    if not before.get("ok") or not after.get("ok"):
        return {
            "ok": False,
            "error": before.get("error") or after.get("error") or "当前模型配置无法完成敏感性分析",
            "field_path": field_path,
            "old_value": old_value,
            "new_value": new_value,
        }
    risk_before = before.get("enterprise_risk_screening") or evaluate_indicator_pool(counterparty, config)
    risk_after = after.get("enterprise_risk_screening") or evaluate_indicator_pool(changed, config)
    policy_hits_before = [item["id"] for item in before.get("risk_screening_policy", {}).get("hits", [])]
    policy_hits_after = [item["id"] for item in after.get("risk_screening_policy", {}).get("hits", [])]
    return {
        "ok": True,
        "field_path": field_path,
        "old_value": old_value,
        "new_value": new_value,
        "before": before,
        "after": after,
        "before_enterprise_risk_screening": risk_before,
        "after_enterprise_risk_screening": risk_after,
        "impact": {
            "总分变化": round(after["total_score"] - before["total_score"], 1),
            "评级变化": f"{before['rating']} → {after['rating']}",
            "策略变化": f"{before['access_strategy']} → {after['access_strategy']}",
            "额度变化": after["suggested_limit"] - before["suggested_limit"],
            "账期变化": after["suggested_payment_term_days"] - before["suggested_payment_term_days"],
            "强规则变化": f"{len(before['strong_rule_hits'])} → {len(after['strong_rule_hits'])}",
            "业务风险档位变化": f"{before.get('business_risk_band', '-')} → {after.get('business_risk_band', '-')}",
            "财务风险档位变化": f"{before.get('financial_risk_band', '-')} → {after.get('financial_risk_band', '-')}",
            "完整度变化": round(after.get("data_completeness", 0) - before.get("data_completeness", 0), 4),
            "企业风险筛查分变化": round(risk_after["normalized_score"] - risk_before["normalized_score"], 1),
            "企业风险完整度变化": round(risk_after["completeness"] - risk_before["completeness"], 4),
            "企业风险贷策命中变化": f"{','.join(policy_hits_before) or '无'} → {','.join(policy_hits_after) or '无'}",
        },
    }


def _build_corporate_trace(result: dict, config: dict) -> dict:
    weights = config["weights"]
    dimensions = []
    for key, score in result["dimension_scores"].items():
        weight = float(weights[key])
        dimensions.append(
            {
                "维度": DIMENSIONS.get(key, key),
                "维度得分": score,
                "权重": f"{weight:.0%}",
                "加权贡献": round(score * weight, 2),
                "计算公式": f"{score:g} × {weight:.0%} = {score * weight:.2f}",
            }
        )
    indicator_rows = []
    for item in result["indicator_calculations"]:
        actual = "缺失" if item["actual_value"] is None else f"{item['actual_value']}{item['unit']}"
        indicator_rows.append(
            {
                "维度": item["dimension_label"],
                "指标组": item["group_label"],
                "指标": item["indicator"],
                "原始值": actual,
                "标准分": item["score"],
                "有效权重": f"{item['effective_weight']:.1%}",
                "扣分": item["effective_loss"],
                "证据": f"{actual}；来源：{item['source']}",
                "运算": item["formula"] if item["available"] else item["missing_policy"],
                "数据状态": "已取得" if item["available"] else "待补充",
            }
        )
    return {
        "ok": True,
        "result": result,
        "dimension_contributions": dimensions,
        "matrix_inputs": [
            {"子模型": "业务风险", "得分": result["submodel_scores"]["business_risk"], "档位": result["business_risk_band"]},
            {"子模型": "财务风险", "得分": result["submodel_scores"]["financial_risk"], "档位": result["financial_risk_band"]},
            {"子模型": "矩阵查询", "得分": result["dimension_scores"]["business_financial_anchor"], "档位": f"B{result['business_risk_band']} × F{result['financial_risk_band']}"},
        ],
        "indicator_deductions": indicator_rows,
        "data_quality": {
            "整体完整度": f"{result['data_completeness']:.1%}",
            "业务风险": f"{result['submodel_completeness']['business_risk']:.1%}",
            "财务风险": f"{result['submodel_completeness']['financial_risk']:.1%}",
            "外部信用": f"{result['submodel_completeness']['external_credit']:.1%}",
            "交易行为": f"{result['submodel_completeness']['transaction_behavior']:.1%}",
        },
        "limit_calculation": result["limit_calculation"],
        "formula": f"{result['calculation_formula']}；经强规则处理后，再由企业风险贷策层按最严格结果收紧",
    }


def _build_tech_trace(result: dict) -> dict:
    dimension_rows = [
        {
            "维度": "基础评分",
            "维度得分": result["base_score"],
            "权重": "直接计分",
            "加权贡献": result["base_score"],
            "计算公式": f"基础模块命中得分合计 = {result['base_score']:g}",
        },
        {
            "维度": "加分项",
            "维度得分": result["bonus_score"],
            "权重": "直接计分",
            "加权贡献": result["bonus_score"],
            "计算公式": f"资质、研发与纳税加分合计 = {result['bonus_score']:g}",
        },
        {
            "维度": "减分项",
            "维度得分": result["deduction_score"],
            "权重": "直接计分",
            "加权贡献": result["deduction_score"],
            "计算公式": f"融资结构、控制权与合规扣分合计 = {result['deduction_score']:g}",
        },
    ]
    indicator_rows = []
    for item in result.get("indicator_explanations", []):
        score = float(item.get("score", 0))
        indicator_rows.append(
            {
                "维度": item.get("category", "科创评分"),
                "指标组": item.get("module"),
                "指标": item.get("indicator", "未命名指标"),
                "标准分": score,
                "扣分": abs(min(score, 0)),
                "证据": item.get("evidence", "待补充证据"),
                "运算": f"按科创评分卡命中规则计 {score:+g} 分",
                "数据状态": "已取得",
            }
        )
    return {
        "ok": True,
        "result": result,
        "dimension_contributions": dimension_rows,
        "indicator_deductions": indicator_rows,
        "formula": "科创总分 = 基础评分 + 加分项 + 减分项，经强规则处理后，再由企业风险贷策层按最严格结果收紧",
    }


def _set_field_value(data: dict, field_path: str, value) -> None:
    parts = field_path.split(".")
    current = data
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value
