from __future__ import annotations


DOCUMENT_REVIEW_CHECKS = [
    {"key": "integrity", "label": "文件格式与指纹完整"},
    {"key": "entity_match", "label": "企业名称及统一信用代码一致"},
    {"key": "validity", "label": "证照、报告或证明仍在有效期"},
    {"key": "completeness", "label": "关键页、签章和附件完整"},
    {"key": "legibility", "label": "内容清晰可读且不存在明显涂改"},
]


DOCUMENT_REQUIREMENTS = [
    {"key": "business_license", "document_type": "营业执照", "description": "营业执照正副本或电子营业执照", "required": True, "models": ["all"]},
    {"key": "articles", "document_type": "公司章程", "description": "现行有效章程及最近一次修订页", "required": True, "models": ["all"]},
    {"key": "legal_rep_identity", "document_type": "法定代表人身份证明", "description": "法人身份证明及授权签字材料", "required": True, "models": ["all"]},
    {"key": "shareholder_register", "document_type": "股权结构及股东名册", "description": "穿透至最终自然人或国资主体", "required": True, "models": ["all"]},
    {"key": "ubo_statement", "document_type": "实控人及受益所有人说明", "description": "实际控制人与受益所有人声明", "required": True, "models": ["all"]},
    {"key": "audited_financials", "document_type": "近三年审计报告", "description": "审计意见、财务报表及附注", "required": True, "models": ["all"]},
    {"key": "latest_financials", "document_type": "最近一期财务报表", "description": "资产负债表、利润表与现金流量表", "required": True, "models": ["all"]},
    {"key": "credit_authorization", "document_type": "征信授权书", "description": "企业及必要关联方征信查询授权", "required": True, "models": ["all"]},
    {"key": "tax_certificate", "document_type": "纳税及完税证明", "description": "近一年纳税申报或完税证明", "required": False, "models": ["all"]},
    {"key": "major_contracts", "document_type": "主要业务合同", "description": "主要客户、供应商或在手订单合同", "required": True, "models": ["all"]},
    {"key": "fulfillment_ledger", "document_type": "订单履约台账", "description": "交付、验收、退换货及争议记录", "required": False, "models": ["all"]},
    {"key": "receivables_aging", "document_type": "应收账款账龄表", "description": "应收余额、账龄与逾期明细", "required": False, "models": ["all"]},
    {"key": "qualification_certificates", "document_type": "行业资质证书", "description": "许可、认证及有效期证明", "required": False, "models": ["all"]},
    {"key": "supplement", "document_type": "补充说明", "description": "异常事项解释与补充证明", "required": False, "models": ["all"]},
    {"key": "high_tech_certificate", "document_type": "高新技术企业证书", "description": "高企证书及有效期证明", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "specialized_new", "document_type": "专精特新认定证明", "description": "国家、省或市级专精特新证明", "required": False, "models": ["tech_enterprise_basic"]},
    {"key": "ip_list", "document_type": "知识产权清单", "description": "专利、软著、权属人及有效状态", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "rd_staff", "document_type": "研发人员名单", "description": "核心研发人员、岗位及劳动关系证明", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "rd_investment", "document_type": "研发投入专项说明", "description": "近三年研发费用及收入匹配表", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "investor_proof", "document_type": "投资机构入股证明", "description": "投资协议、股权变更及资金到位证明", "required": False, "models": ["tech_enterprise_basic"]},
    {"key": "support_orders", "document_type": "政府支持及重点订单证明", "description": "政府补助、政府采购或龙头客户订单", "required": False, "models": ["tech_enterprise_basic"]},
    {"key": "controller_background", "document_type": "实控人学历及从业经历证明", "description": "学历、五百强或战略客户任职、创业及行业专家证明", "required": False, "models": ["tech_enterprise_basic"]},
    {"key": "management_stability", "document_type": "董监高及持股变更说明", "description": "近三年持股董事、实际控制人及核心团队变更情况", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "bank_credit_list", "document_type": "合作授信银行及余额清单", "description": "合作银行数量、授信提用余额及前两位银行", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "environmental_compliance", "document_type": "环保合规及处罚说明", "description": "近两年环保处罚查询结果及整改证明", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "tech_financial_metrics", "document_type": "科创准入财务指标表", "description": "收入、净资产、增长率、负债率、毛利率、现金储备及研发投入计算底稿", "required": True, "models": ["tech_enterprise_basic"]},
    {"key": "cfda_new_drug", "document_type": "CFDA认证或新药研发证明", "description": "适用营业收入增长率豁免时提供的认证及研发证明", "required": False, "models": ["tech_enterprise_basic"]},
]


ALLOWED_DOCUMENT_TYPES = {item["document_type"] for item in DOCUMENT_REQUIREMENTS} | {"财务报表", "业务合同"}
INITIAL_DOCUMENT_TYPES = {"营业执照"}
INITIAL_SUPPORTING_TYPES = {"财务报表", "业务合同", "征信授权书", "近三年审计报告", "最近一期财务报表", "主要业务合同"}
SUPPLEMENT_REQUIRED_TYPES = {"营业执照", "财务报表", "征信授权书"}


def document_requirement_catalog(template_key: str | None = None) -> list[dict]:
    key = template_key or "general"
    return [
        dict(item)
        for item in DOCUMENT_REQUIREMENTS
        if "all" in item["models"] or key in item["models"]
    ]


def build_document_checklist(documents: list[dict], template_key: str | None = None) -> dict:
    catalog = document_requirement_catalog(template_key)
    latest_by_type: dict[str, dict] = {}
    for document in documents:
        latest_by_type.setdefault(document["document_type"], document)
    items = []
    for requirement in catalog:
        document = latest_by_type.get(requirement["document_type"])
        if not document:
            status = "missing"
        else:
            status = document.get("review_status") or "pending_review"
        items.append({**requirement, "status": status, "document": document})
    required_items = [item for item in items if item["required"]]
    return {
        "template_key": template_key or "general",
        "items": items,
        "review_checks": DOCUMENT_REVIEW_CHECKS,
        "summary": {
            "total_count": len(items),
            "required_count": len(required_items),
            "uploaded_count": sum(item["document"] is not None for item in items),
            "verified_count": sum(item["status"] == "verified" for item in items),
            "pending_count": sum(item["status"] == "pending_review" for item in items),
            "missing_required_count": sum(item["required"] and item["status"] == "missing" for item in items),
            "exception_count": sum(item["status"] in {"needs_supplement", "rejected"} for item in items),
        },
    }
