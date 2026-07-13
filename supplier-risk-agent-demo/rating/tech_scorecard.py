from __future__ import annotations


def rate_tech_enterprise(counterparty: dict, config: dict) -> dict:
    profile = counterparty.get("tech_enterprise")
    if not profile:
        return {
            "ok": False,
            "error": "缺少科创企业评分字段",
            "counterparty_id": counterparty["id"],
            "counterparty_name": counterparty["name"],
        }

    rules = config["tech_scorecard"]["editable_rules"]
    base_items = _calculate_base_items(profile, rules["base"])
    bonus_items = _calculate_bonus_items(profile, rules["bonus"])
    deduction_items = _calculate_deduction_items(profile, rules["deduction"])
    support_items = _calculate_support_data_items(counterparty, profile)

    base_score = round(sum(item["score"] for item in base_items), 2)
    bonus_score = round(sum(item["score"] for item in bonus_items), 2)
    deduction_score = round(sum(item["score"] for item in deduction_items), 2)
    total_score = round(base_score + bonus_score + deduction_score, 2)
    limit_strategy = _map_limit(total_score, config["tech_scorecard"]["limit_mapping"])

    from rating.rules import apply_rule_actions, evaluate_strong_rules

    base_strategy = {
        "rating": limit_strategy["rating"],
        "risk_segment": limit_strategy["risk_segment"],
        "access_strategy": limit_strategy["access_strategy"],
        "suggested_limit": min(counterparty.get("requested_limit", 0), limit_strategy["limit_cap"]),
        "payment_term_days": _payment_term_by_rating(limit_strategy["rating"]),
        "monitoring_frequency": "月度" if limit_strategy["rating"] in {"B", "D"} else "季度",
        "review_required": limit_strategy["rating"] in {"B", "D"},
        "base_limit_multiplier": 1.0,
    }
    strong_rule_hits = evaluate_strong_rules(counterparty, config)
    final_strategy = apply_rule_actions(base_strategy, strong_rule_hits, counterparty)

    return {
        "ok": True,
        "counterparty_id": counterparty["id"],
        "counterparty_name": counterparty["name"],
        "counterparty_type": counterparty["counterparty_type"],
        "model_version": config["version"],
        "total_score": total_score,
        "base_score": base_score,
        "bonus_score": bonus_score,
        "deduction_score": deduction_score,
        "rating": final_strategy["rating"],
        "raw_rating": limit_strategy["rating"],
        "risk_segment": final_strategy["risk_segment"],
        "access_strategy": final_strategy["access_strategy"],
        "suggested_limit": final_strategy["suggested_limit"],
        "suggested_payment_term_days": final_strategy["payment_term_days"],
        "monitoring_frequency": final_strategy["monitoring_frequency"],
        "limit_text": limit_strategy["limit_text"],
        "credit_limit_text": limit_strategy["credit_limit_text"],
        "dimension_scores": {
            "base_score": base_score,
            "bonus_score": bonus_score,
            "deduction_score": deduction_score,
            "support_data_pass_count": sum(1 for item in support_items if item["passed"]),
        },
        "indicator_explanations": base_items + bonus_items + deduction_items,
        "support_data_items": support_items,
        "strong_rule_hits": strong_rule_hits,
        "review_required": final_strategy["review_required"] or bool(strong_rule_hits),
        "main_deductions": [item for item in deduction_items if item["score"] < 0],
        "main_positive_factors": [item["indicator"] for item in base_items + bonus_items if item["score"] > 0][:5],
    }


def _calculate_base_items(profile: dict, rules: dict) -> list[dict]:
    items = []

    ip_score = min(
        profile.get("software_copyright_count", 0) * rules["software_copyright_points"]
        + profile.get("invention_patent_count", 0) * rules["invention_patent_points"]
        + profile.get("pct_patent_count", 0) * rules["pct_patent_points"]
        + min(profile.get("utility_model_patent_count", 0) * rules["utility_model_points"], rules["utility_model_cap"]),
        rules["ip_module_cap"],
    )
    items.append(_item("基础评分", "自主创新技术", "企业或主要股东拥有知识产权的质量和数量", ip_score, "软件著作权、发明专利、PCT、实用新型按规则折算，模块封顶 10 分"))

    investor_scores = []
    for field in ["known_vc_invested", "government_guidance_fund_invested", "industrial_investor_invested", "broker_investor_invested"]:
        if profile.get(field):
            investor_scores.append(rules["premium_investor_points"])
    other_vc_count = profile.get("other_vc_count", 0)
    if other_vc_count == 1:
        investor_scores.append(rules["other_vc_one_points"])
    elif other_vc_count >= 2:
        investor_scores.append(rules["other_vc_two_or_more_points"])
    investor_score = min(max(investor_scores or [0]), rules["investor_module_cap"])
    items.append(_item("基础评分", "商业模式的可行性", "已入股投资机构的质量和数量", investor_score, "知名创投、政府引导基金、产业投资者、券商机构或其他创投机构入股"))

    order_scores = []
    order_score_fields = [
        ("famous_company_order", rules["famous_company_order_points"]),
        ("strategic_bank_customer_order", rules["strategic_bank_customer_order_points"]),
        ("government_procurement_order", rules["government_procurement_order_points"]),
        ("industry_leader_order", rules["industry_leader_order_points"]),
        ("aa_minus_customer_order", rules["aa_minus_customer_order_points"]),
        ("government_industrial_space_support", rules["government_industrial_space_points"]),
    ]
    for field, score in order_score_fields:
        if profile.get(field):
            order_scores.append(score)
    if profile.get("continuous_government_subsidy_or_reward"):
        order_scores.append(rules["continuous_government_subsidy_points"])
    elif profile.get("government_subsidy_or_reward"):
        order_scores.append(rules["government_subsidy_points"])
    order_score = min(sum(order_scores), rules["order_module_cap"])
    items.append(_item("基础评分", "商业模式的可行性", "获得政府支持或知名企业订单情况", order_score, "政府支持、知名企业订单、行业龙头订单等叠加封顶 30 分"))

    education = profile.get("controller_education_level", "none")
    education_score = rules["master_or_above_points"] if education in {"master", "doctor"} else rules["bachelor_points"] if education == "bachelor" else 0
    items.append(_item("基础评分", "企业家精神", "实际控制人教育背景", education_score, "本科 3 分，硕士及以上 5 分"))

    experience_score = rules["controller_experience_points"] if profile.get("controller_top500_experience") or profile.get("applicant_or_team_industry_expert") else 0
    items.append(_item("基础评分", "企业家精神", "实际控制人从业经历", experience_score, "500 强/战略客户经历，或申请人/团队为领域专家"))

    startup_score = rules["entrepreneurship_points"] if profile.get("previous_startup_count", 0) >= 1 or profile.get("entrepreneurship_years", 0) >= 5 else 0
    items.append(_item("基础评分", "企业家精神", "实际控制人创业经历", startup_score, "创立前有创业经历或 5 年以上创业经历"))

    shareholding_score = rules["shareholding_ratio_points"] if profile.get("top_two_natural_person_shareholding_ratio", 0) > rules["shareholding_ratio_threshold"] else 0
    items.append(_item("基础评分", "团队稳定性", "最大股东持股比例", shareholding_score, "前两大自然人股东持股比例超过 50%"))

    director_score = rules["director_stability_points"] if profile.get("shareholding_directors_no_exit_3y") else 0
    items.append(_item("基础评分", "团队稳定性", "持股董事的变更情况", director_score, "近三年公司管理层持股董事未退出"))

    audit_score = rules["audited_report_points"] if profile.get("audited_financial_report") else 0
    items.append(_item("基础评分", "企业经营规范程度", "财务报表是否经过审计", audit_score, "能够提供经审计的财务报告"))

    return items


def _calculate_bonus_items(profile: dict, rules: dict) -> list[dict]:
    items = []
    if profile.get("high_level_talent_shareholder"):
        items.append(_item("加分项", "人才资质", "股东含深圳市高层次人才/海外高层次人才", rules["high_level_talent_points"], "符合高层次人才或孔雀计划等认定"))

    level = profile.get("specialized_new_enterprise_level", "none")
    level_score = {
        "national": rules["specialized_new_national_points"],
        "provincial": rules["specialized_new_provincial_points"],
        "municipal": rules["specialized_new_municipal_points"],
    }.get(level, 0)
    if level_score:
        items.append(_item("加分项", "企业资质", "专精特新中小企业", level_score, "国家级 30 分，省级 20 分，市级 10 分，级别不累计"))

    if profile.get("rd_expense_revenue_ratio_3y", 0) >= rules["rd_expense_revenue_ratio_3y_threshold"]:
        items.append(_item("加分项", "研发投入", "最近三年累计研发费用/营业收入占比达到阈值", rules["rd_expense_revenue_ratio_3y_points"], f"当前比例：{profile.get('rd_expense_revenue_ratio_3y', 0):.0%}"))

    if profile.get("annual_income_tax_paid", 0) >= rules["annual_income_tax_paid_threshold"]:
        items.append(_item("加分项", "纳税贡献", "近一年缴纳企业所得税达到阈值", rules["annual_income_tax_paid_points"], f"当前金额：{profile.get('annual_income_tax_paid', 0):,.0f} 元"))

    return items


def _calculate_deduction_items(profile: dict, rules: dict) -> list[dict]:
    items = []
    if profile.get("bank_credit_count", 0) >= rules["bank_credit_count_threshold"]:
        items.append(_item("减分项", "融资结构", "合作授信银行数达到阈值", rules["bank_credit_count_points"], f"当前合作授信银行数：{profile.get('bank_credit_count', 0)} 家"))

    if profile.get("top_two_credit_banks_include_major_bank"):
        items.append(_item("减分项", "融资结构", "授信提用余额前两位含主要银行", rules["major_bank_top_two_points"], "工、农、中、建、招商等任一银行在前两位"))

    if profile.get("controller_changed_3y"):
        items.append(_item("减分项", "控制权稳定", "近三年实际控制人发生变化", rules["controller_changed_3y_points"], "近三年实控人变更"))

    if profile.get("environmental_penalty_2y"):
        items.append(_item("减分项", "合规风险", "近两年受到环保处罚", rules["environmental_penalty_2y_points"], "近两年环保处罚记录"))

    return items


def _calculate_support_data_items(counterparty: dict, profile: dict) -> list[dict]:
    checks = [
        ("注册地粤港澳大湾区九市企业", profile.get("gba_registration") is True),
        ("成立一年以上", counterparty.get("external", {}).get("established_years", 0) >= 1),
        ("实控人及核心团队控股比例 ≥40%", profile.get("core_team_shareholding_ratio", 0) >= 0.4),
        ("核心研发人员占比 ≥10%", profile.get("rd_staff_ratio", 0) >= 0.1),
        ("主营业务收入 ≥1000 万元", profile.get("main_business_revenue", 0) >= 10000000),
        ("最近一期净资产 ≥1000 万元", profile.get("latest_net_assets", 0) >= 10000000),
        ("最近一年营业收入增长率 ≥20%", profile.get("revenue_growth_rate", 0) >= 0.2),
        ("企业资产负债率 ≤70%", profile.get("asset_liability_ratio", 1) <= 0.7),
        ("毛利率 ≥30%", profile.get("gross_margin", 0) >= 0.3),
        ("现金储备/年三项费用 ≥1", profile.get("cash_reserve_to_three_expenses", 0) >= 1),
        ("研发费用占当年收入 ≥5%", profile.get("rd_expense_revenue_ratio_current", 0) >= 0.05),
    ]
    return [{"indicator": name, "passed": passed} for name, passed in checks]


def _map_limit(total_score: float, limit_mapping: list[dict]) -> dict:
    for item in limit_mapping:
        if item["score_min"] <= total_score <= item["score_max"]:
            result = dict(item)
            result["limit_cap"] = _parse_limit_cap(item["limit_text"])
            return result
    result = dict(limit_mapping[0])
    result["limit_cap"] = 0
    return result


def _parse_limit_cap(limit_text: str) -> int:
    if "5000" in limit_text:
        return 50000000
    if "2000" in limit_text:
        return 20000000
    if "500" in limit_text:
        return 5000000
    return 0


def _payment_term_by_rating(rating: str) -> int:
    return {"AA": 60, "A": 45, "B": 30, "D": 0}.get(rating, 0)


def _item(category: str, module: str, indicator: str, score: float, evidence: str) -> dict:
    return {
        "category": category,
        "module": module,
        "indicator": indicator,
        "score": round(score, 2),
        "evidence": evidence,
    }
