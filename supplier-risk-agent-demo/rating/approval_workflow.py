from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from uuid import uuid4


WORKFLOW_STAGES = [
    {"key": "registration", "label": "客户注册", "owner": "客户经理"},
    {"key": "document_upload", "label": "上传资料", "owner": "客户/供应商"},
    {"key": "supplement", "label": "补充资料", "owner": "客户/供应商"},
    {"key": "approval_submit", "label": "发起审批", "owner": "客户经理"},
    {"key": "model_selection", "label": "选择模型", "owner": "风控经理"},
    {"key": "scoring", "label": "形成评分", "owner": "评级 Agent"},
    {"key": "credit_proposal", "label": "额度与授信期", "owner": "授信审批人"},
    {"key": "final_strategy", "label": "最终策略", "owner": "有权审批人"},
]

STAGE_SLA_HOURS = {
    "registration": 8,
    "document_upload": 48,
    "supplement": 48,
    "approval_submit": 8,
    "model_selection": 8,
    "scoring": 2,
    "credit_proposal": 16,
    "final_strategy": 24,
}


def create_approval_case(counterparty: dict) -> dict:
    return {
        "case_id": f"CR-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:10].upper()}",
        "counterparty_id": counterparty["id"],
        "counterparty_name": counterparty["name"],
        "current_stage": "registration",
        "status": "处理中",
        "completed_stages": [],
        "data": {},
        "timeline": [],
    }


def advance_approval_case(case: dict, payload: dict, actor: str, occurred_at: str | None = None) -> dict:
    updated = deepcopy(case)
    stage = updated["current_stage"]
    error = validate_stage_payload(stage, payload)
    if error:
        raise ValueError(error)

    updated["data"][stage] = deepcopy(payload)
    updated["completed_stages"].append(stage)
    updated["timeline"].append(
        {
            "环节": stage_label(stage),
            "处理人": actor,
            "处理时间": occurred_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "处理结果": _stage_result(stage, payload),
        }
    )
    index = stage_index(stage)
    if index == len(WORKFLOW_STAGES) - 1:
        updated["status"] = "已完成"
    else:
        updated["current_stage"] = WORKFLOW_STAGES[index + 1]["key"]
        updated["status"] = "处理中"
    return updated


def build_workflow_progress(case: dict) -> list[dict]:
    current_index = stage_index(case["current_stage"])
    rows = []
    for index, stage in enumerate(WORKFLOW_STAGES):
        if stage["key"] in case["completed_stages"]:
            status = "已完成"
        elif case["status"] in {"已拒绝", "已撤回"}:
            status = "已终止"
        elif case["status"] == "已完成":
            status = "已完成"
        elif index == current_index:
            status = "待补件" if case["status"] == "待补件" else "处理中"
        else:
            status = "待处理"
        rows.append({"序号": index + 1, "审批环节": stage["label"], "负责角色": stage["owner"], "状态": status})
    return rows


def validate_stage_payload(stage: str, payload: dict) -> str:
    required = {
        "registration": ["registered_name", "unified_social_credit_code", "contact_name"],
        "document_upload": ["documents"],
        "supplement": ["supplement_status"],
        "approval_submit": ["business_type", "requested_limit", "requested_term_days"],
        "model_selection": ["model_name", "model_version"],
        "scoring": ["total_score", "rating"],
        "credit_proposal": ["suggested_limit", "suggested_payment_term_days"],
        "final_strategy": ["decision", "access_strategy", "monitoring_frequency"],
    }
    missing = [key for key in required[stage] if payload.get(key) in (None, "", [])]
    if missing:
        return f"{stage_label(stage)}缺少必填项：{', '.join(missing)}"
    if stage == "document_upload" and len(payload["documents"]) < 2:
        return "至少需要上传营业执照和一项业务/财务资料"
    if stage == "supplement" and payload["supplement_status"] != "已补齐":
        return "资料缺口尚未补齐，不能进入审批"
    if stage == "final_strategy" and "facility_validity_days" in payload:
        try:
            validity_days = int(payload["facility_validity_days"])
        except (TypeError, ValueError):
            return "授信有效期必须是整数天数"
        if not 30 <= validity_days <= 1825:
            return "授信有效期必须介于 30 至 1825 天"
    if stage == "final_strategy":
        rejected = payload.get("decision") == "拒绝"
        prohibited = payload.get("access_strategy") in {"禁入", "不建议准入"}
        if rejected != prohibited:
            return "审批结论与准入策略不一致：拒绝必须对应禁入，通过类结论不能选择禁入"
    if stage == "final_strategy" and payload.get("decision") != "拒绝":
        if "approved_limit" in payload:
            try:
                approved_limit = float(payload["approved_limit"])
            except (TypeError, ValueError):
                return "最终批准额度必须是有效数字"
            if approved_limit <= 0:
                return "最终批准额度必须大于 0"
        if "approved_payment_term_days" in payload:
            try:
                payment_term_days = int(payload["approved_payment_term_days"])
            except (TypeError, ValueError):
                return "最终批准账期必须是整数天数"
            if not 0 <= payment_term_days <= 365:
                return "最终批准账期必须介于 0 至 365 天"
    return ""


def stage_index(stage: str) -> int:
    return next(index for index, item in enumerate(WORKFLOW_STAGES) if item["key"] == stage)


def stage_label(stage: str) -> str:
    return WORKFLOW_STAGES[stage_index(stage)]["label"]


def _stage_result(stage: str, payload: dict) -> str:
    if stage == "registration":
        return f"注册主体：{payload['registered_name']}"
    if stage == "document_upload":
        return f"已上传 {len(payload['documents'])} 份资料"
    if stage == "supplement":
        return payload["supplement_status"]
    if stage == "approval_submit":
        return f"申请额度 {payload['requested_limit']:,.0f} 元 / {payload['requested_term_days']} 天"
    if stage == "model_selection":
        return f"{payload['model_name']} / {payload['model_version']}"
    if stage == "scoring":
        return f"{payload['total_score']} 分 / {payload['rating']} 级"
    if stage == "credit_proposal":
        return f"建议额度 {payload['suggested_limit']:,.0f} 元 / {payload['suggested_payment_term_days']} 天"
    return f"{payload['decision']} / {payload['access_strategy']}"
