"""Versioned model-risk taxonomy used by governance screens and release evidence."""
from __future__ import annotations


_CATALOG = (
    {"code": "MR-LOW", "level": "low", "name": "低风险模型", "basis": ["仅辅助排序或预警", "不直接决定准入/额度"], "acceptance_roles": ["model_owner"], "review_days": 365, "regulatory_mapping": ["内部模型目录-低"], "required_evidence": ["数据质量", "稳定性"]},
    {"code": "MR-MEDIUM", "level": "medium", "name": "中风险模型", "basis": ["影响评级、账期或额度建议", "存在人工复核兜底"], "acceptance_roles": ["model_owner", "risk_manager"], "review_days": 180, "regulatory_mapping": ["内部模型目录-中", "模型风险管理指引-验证"], "required_evidence": ["样本代表性", "区分度", "稳定性", "独立验证"]},
    {"code": "MR-HIGH", "level": "high", "name": "高风险模型", "basis": ["直接影响准入或授信决策", "自动化执行且影响客户权益"], "acceptance_roles": ["model_owner", "risk_manager", "model_risk_committee"], "review_days": 90, "regulatory_mapping": ["内部模型目录-高", "模型风险管理指引-重大模型"], "required_evidence": ["监督区分度", "置信区间", "公平性", "压力测试", "独立验证"]},
)


def risk_catalog() -> list[dict]:
    return [dict(item, basis=list(item["basis"]), acceptance_roles=list(item["acceptance_roles"]), regulatory_mapping=list(item["regulatory_mapping"]), required_evidence=list(item["required_evidence"])) for item in _CATALOG]


def risk_level(level: str) -> dict:
    for item in _CATALOG:
        if item["level"] == level:
            return dict(item)
    raise ValueError(f"未知模型风险等级: {level}")
