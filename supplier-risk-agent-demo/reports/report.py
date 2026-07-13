from __future__ import annotations

from datetime import datetime

from rating.risk_intelligence import build_agent_timeline, build_counterparty_profile


def build_report(
    supplier: dict,
    external: dict,
    internal: dict,
    evaluation: dict,
    human_decision: str,
    human_reason: str,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reject_lines = _format_rules(evaluation["strong_rejects"])
    warning_lines = _format_rules(evaluation["warnings"])
    review_lines = _format_review(evaluation["review_items"])

    return f"""# 供应商准入风险审核报告

生成时间：{generated_at}

## 一、供应商基本信息

- 企业名称：{supplier["name"]}
- 统一社会信用代码：{supplier["credit_code"]}
- 采购品类：{supplier["category"]}
- 申请合作金额：{supplier["request_amount"]:,} 元
- 合同周期：{supplier["contract_months"]} 个月
- 是否关键供应商：{"是" if supplier["is_key_supplier"] else "否"}

## 二、外部企业数据摘要

- 数据模式：{external.get("data_mode", "样本数据")}
- 登记状态：{external["registration_status"]}
- 注册资本：{external["registered_capital"]}
- 成立年限：{external["established_years"]} 年
- 司法案件：{external["legal_cases_count"]} 条
- 重大诉讼金额：{external["major_litigation_amount"]:,} 元
- 失信记录：{external["dishonesty_count"]} 条
- 行政处罚：{external["admin_penalty_count"]} 条
- 经营异常：{external["operating_abnormal_count"]} 条
- 纳税信用等级：{external["tax_credit_level"]}

## 三、内部业务数据摘要

- 近 12 月订单数：{internal["orders_12m"]} 笔
- 近 12 月订单金额：{internal["order_amount_12m"]:,} 元
- 发票匹配率：{internal["invoice_match_rate"]:.0%}
- 履约延期次数：{internal["delivery_delay_count"]} 次
- 质量异常次数：{internal["quality_issue_count"]} 次
- 合同争议次数：{internal["contract_dispute_count"]} 次
- 退货率：{internal["return_rate"]:.0%}
- 合作年限：{internal["cooperation_years"]} 年

## 四、规则命中结果

### 强拒规则
{reject_lines}

### 预警规则
{warning_lines}

### 需人工确认事项
{review_lines}

## 五、系统评级与建议

- 风险评分：{evaluation["score"]} / 100
- 风险评级：{evaluation["rating"]}
- 系统建议：{evaluation["suggestion"]}
- 建议额度：{evaluation["suggested_limit"]:,} 元
- 决策类型：{evaluation["decision_type"]}

## 六、人工复核结论

- 人工结论：{human_decision}
- 调整原因：{human_reason or "未填写"}

## 七、审计留痕说明

本报告保留供应商输入、外部数据摘要、内部业务数据摘要、规则命中、系统建议、人工复核结论和报告生成时间。生产环境需进一步记录数据版本、规则版本、操作人、审批流节点和原始证据链接。
"""


def _format_rules(items: list[dict]) -> str:
    if not items:
        return "- 未命中"
    return "\n".join(
        f"- {item['rule_id']}：{item['reason']}；证据：{item['evidence']}；扣分：{item['points']}"
        for item in items
    )


def _format_review(items: list[dict]) -> str:
    if not items:
        return "- 无"
    return "\n".join(
        f"- {item['rule_id']}：{item['reason']}；证据：{item['evidence']}"
        for item in items
    )


def build_credit_rating_report(
    counterparty: dict,
    result: dict,
    model_config: dict,
    review_records: list[dict] | None = None,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    review_records = review_records or []
    profile = build_counterparty_profile(counterparty, result)
    timeline = build_agent_timeline(counterparty, result)
    return f"""# 客商信用评级审核报告

生成时间：{generated_at}
模型版本：{model_config["version"]}
模型名称：{model_config["name"]}

## 一、模型评级结论

- 客商名称：{result["counterparty_name"]}
- 客商类型：{_counterparty_type(result["counterparty_type"])}
- 总分：{result["total_score"]}
- 模型评级：{result["rating"]}
- 原始评级：{result["raw_rating"]}
- 风险分层：{result["risk_segment"]}
- 准入策略：{result["access_strategy"]}
- 建议额度：{_money(result["suggested_limit"])}
- 建议账期：{result["suggested_payment_term_days"]} 天
- 人工复核：{"需要" if result["review_required"] else "无需"}

### 核心结论摘要

{_format_summary(profile)}

## 二、评分卡逐项解释

{_format_indicator_explanations(result)}

## 三、强规则命中

{_format_strong_rule_hits(result["strong_rule_hits"])}

## 四、额度审批数据依据

{_format_support_data_items(result.get("support_data_items", []))}

## 五、人工复核与审计留痕

{_format_review_records(review_records, result["counterparty_name"])}

## 六、企业风险画像

- 统一社会信用代码：{counterparty.get("credit_code", "-")}
- 申请额度：{_money(counterparty.get("requested_limit", 0))}
- 主体状态：{counterparty.get("external", {}).get("registration_status", "-")}
- 成立年限：{counterparty.get("external", {}).get("established_years", "-")} 年
- 纳税信用：{counterparty.get("external", {}).get("tax_credit_level", "-")}
- 合作年限：{counterparty.get("internal", {}).get("cooperation_years", "-")} 年

### 主体画像

{_format_bullets(profile["主体画像"])}

### 外部风险

{_format_bullets(profile["外部风险"])}

### 内部履约

{_format_bullets(profile["内部履约"])}

### 财务质量

{_format_bullets(profile["财务质量"])}

### 科创能力

{_format_bullets(profile["科创能力"])}

### 核心优势

{_format_bullets(profile["core_strengths"])}

### 核心风险

{_format_bullets(profile["core_risks"])}

## 七、Agent 执行链路

{_format_agent_timeline(timeline)}

## 八、后续监控建议

{_format_bullets(profile["management_suggestions"])}

## 九、审计说明

本报告用于 Demo 演示，记录模型版本、评分结论、规则命中、额度依据和人工复核意见。生产环境应继续补充原始证据链接、数据批次、审批节点、操作人、导出流水号和不可篡改留痕。
"""


def _counterparty_type(value: str) -> str:
    return "客户" if value == "customer" else "供应商"


def _money(value: int | float) -> str:
    return f"{value:,.0f} 元"


def _format_indicator_explanations(result: dict) -> str:
    items = result.get("indicator_explanations", [])
    if not items:
        return "- 未产生逐项解释"

    rows = []
    for item in items:
        if "score" in item:
            rows.append(
                f"- {item['category']}｜{item['module']}｜{item['indicator']}：{item['score']} 分；依据：{item['evidence']}"
            )
        else:
            rows.append(
                f"- {item['dimension_label']}｜{item['indicator']}：扣分 {item['points']}；原因：{item['reason']}；依据：{item['evidence']}"
            )
    return "\n".join(rows)


def _format_strong_rule_hits(rule_hits: list[dict]) -> str:
    if not rule_hits:
        return "- 未命中强规则"
    rows = []
    for hit in rule_hits:
        conditions = "；".join(condition["label"] for condition in hit["matched_conditions"])
        rows.append(
            f"- {hit['rule_id']}：{hit['rule_name']}；命中条件：{conditions}；动作：{hit['action'].get('access_strategy', '-')}"
        )
    return "\n".join(rows)


def _format_support_data_items(items: list[dict]) -> str:
    if not items:
        return "- 当前模板未配置额度审批数据依据"
    return "\n".join(
        f"- {item['indicator']}：{'满足' if item['passed'] else '不满足'}"
        for item in items
    )


def _format_review_records(records: list[dict], counterparty_name: str) -> str:
    matched = [item for item in records if item.get("客商") == counterparty_name]
    if not matched:
        return "- 暂无人工复核记录"
    return "\n".join(
        "- "
        f"{item['时间']}｜{item['复核动作']}｜模型策略：{item['模型策略']}｜复核后策略：{item['复核后策略']}｜"
        f"模型额度：{item['模型额度']}｜复核后额度：{item['复核后额度']}｜原因：{item['复核原因']}"
        for item in matched
    )


def _format_summary(profile: dict) -> str:
    strengths = "；".join(profile["core_strengths"][:2])
    risks = "；".join(profile["core_risks"][:2])
    suggestions = "；".join(profile["management_suggestions"][:2])
    return f"- 核心优势：{strengths}\n- 核心风险：{risks}\n- 管理建议：{suggestions}"


def _format_bullets(items: list[str]) -> str:
    if not items:
        return "- 无"
    return "\n".join(f"- {item}" for item in items)


def _format_agent_timeline(timeline: list[dict]) -> str:
    rows = []
    for item in timeline:
        rows.append(
            f"- {item['step']}｜执行方：{item['owner']}｜输入：{item['input']}｜输出：{item['output']}｜人机边界：{item['human_boundary']}"
        )
    return "\n".join(rows)
