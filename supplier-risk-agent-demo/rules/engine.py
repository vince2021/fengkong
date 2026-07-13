from __future__ import annotations


def evaluate_supplier(supplier: dict, external: dict, internal: dict) -> dict:
    strong_rejects = []
    warnings = []
    review_items = []
    score = 100

    def reject(rule_id: str, reason: str, evidence: str, points: int) -> None:
        nonlocal score
        strong_rejects.append({"rule_id": rule_id, "reason": reason, "evidence": evidence, "points": points})
        score -= points

    def warn(rule_id: str, reason: str, evidence: str, points: int) -> None:
        nonlocal score
        warnings.append({"rule_id": rule_id, "reason": reason, "evidence": evidence, "points": points})
        score -= points

    def review(rule_id: str, reason: str, evidence: str) -> None:
        review_items.append({"rule_id": rule_id, "reason": reason, "evidence": evidence})

    if external["registration_status"] not in ["存续", "在业"]:
        reject("SR-001", "企业主体状态异常", f"登记状态：{external['registration_status']}", 35)

    if external["dishonesty_count"] > 0:
        reject("SR-002", "存在失信被执行记录", f"失信记录：{external['dishonesty_count']} 条", 40)

    if external["major_litigation_amount"] >= 5000000:
        reject("SR-003", "重大诉讼金额过高", f"涉诉金额：{external['major_litigation_amount']:,} 元", 25)

    if external["operating_abnormal_count"] > 0:
        warn("WR-001", "存在经营异常记录", f"经营异常：{external['operating_abnormal_count']} 条", 12)

    if external["admin_penalty_count"] > 0:
        warn("WR-002", "存在行政处罚记录", f"行政处罚：{external['admin_penalty_count']} 条", 8)

    if external["shareholder_high_risk"]:
        warn("WR-003", "股东或关联方存在高风险信号", "外部关联风险字段命中", 8)

    if internal["invoice_match_rate"] < 0.9:
        warn("WR-004", "发票与订单匹配率偏低", f"匹配率：{internal['invoice_match_rate']:.0%}", 10)

    if internal["delivery_delay_count"] >= 3:
        warn("WR-005", "历史履约延期较多", f"近 12 月延期：{internal['delivery_delay_count']} 次", 8)

    if supplier["request_amount"] >= 2000000 and supplier["is_key_supplier"]:
        review("HR-001", "关键供应商且合作金额较高，需人工确认业务必要性", f"申请金额：{supplier['request_amount']:,} 元")

    if len(supplier["materials"]) < 3:
        review("HR-002", "供应商提交材料不足，需补充说明", f"已提交材料：{', '.join(supplier['materials'])}")

    score = max(score, 0)

    if strong_rejects:
        rating = "D"
        suggestion = "不建议准入"
        decision_type = "强拒"
    elif score >= 85:
        rating = "A"
        suggestion = "建议准入"
        decision_type = "自动通过"
    elif score >= 70:
        rating = "B"
        suggestion = "限制准入，建议人工复核后小额合作"
        decision_type = "人工复核"
    else:
        rating = "C"
        suggestion = "审慎准入，需补充材料并人工审批"
        decision_type = "人工复核"

    suggested_limit = _suggest_limit(supplier, rating, strong_rejects)

    return {
        "score": score,
        "rating": rating,
        "suggestion": suggestion,
        "decision_type": decision_type,
        "suggested_limit": suggested_limit,
        "strong_rejects": strong_rejects,
        "warnings": warnings,
        "review_items": review_items,
    }


def _suggest_limit(supplier: dict, rating: str, strong_rejects: list[dict]) -> int:
    if strong_rejects:
        return 0

    request_amount = supplier["request_amount"]
    ratio = {
        "A": 1.0,
        "B": 0.6,
        "C": 0.3,
        "D": 0,
    }.get(rating, 0.3)
    return int(request_amount * ratio)
