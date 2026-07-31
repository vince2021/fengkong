from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.authority_policy_repository import AuthorityPolicyRepository
from backend.credit_authority import build_credit_authority, current_authority_slot, ensure_credit_authority, record_authority_signoff
from backend.decision_governance import build_decision_variance, validate_decision_variance
from backend.dependencies import get_approval_repository, get_authority_policy_repository, get_credit_facility_repository, get_decision_governance_repository, get_demo_repository, get_document_repository, get_enterprise_data_repository, get_enterprise_indicator_observation_repository, get_model_governance_repository, get_object_storage, get_rating_run_repository
from backend.document_policy import ALLOWED_DOCUMENT_TYPES, INITIAL_DOCUMENT_TYPES, INITIAL_SUPPORTING_TYPES, SUPPLEMENT_REQUIRED_TYPES, document_type_satisfied, missing_document_types
from backend.indicator_observations import apply_effective_observations
from backend.rating_input_mapping import prepare_rating_input, readiness_summary
from backend.repository import ApprovalCaseRepository, ConcurrentUpdateError, CreditFacilityRepository, DecisionGovernanceRepository, DemoRepository, DocumentRepository, EnterpriseDataRepository, EnterpriseIndicatorObservationRepository, ModelGovernanceRepository, RatingRunRepository, content_hash
from backend.schemas import ApprovalActionRequest, ApprovalAdvanceRequest, ApprovalAutomateRequest, ApprovalCaseCreate, ApprovalSignoffRequest
from backend.security import Principal, enforce_approval_stage_role, enforce_counterparty_scope, require_permissions
from backend.storage import ObjectStorage
from backend.task_lease import assignment_values_are_active
from rating.approval_workflow import WORKFLOW_STAGES, advance_approval_case, build_workflow_progress, create_approval_case, stage_index, stage_label
from rating.enterprise_indicator_pool import evaluate_indicator_pool
from rating.scorecard import rate_counterparty


router = APIRouter(prefix="/approval-cases", tags=["approval-workflow"])
AUTOMATED_STAGES = {"document_upload", "supplement", "model_selection", "scoring", "credit_proposal"}
TERMINAL_STATUSES = {"已完成", "已拒绝", "已撤回"}
ACTION_ROLES = {
    "return_for_supplement": {"relationship_manager", "risk_manager", "approver"},
    "reject": {"risk_manager", "approver"},
    "withdraw": {"relationship_manager"},
    "comment": {"client", "relationship_manager", "risk_manager", "model_admin", "approver"},
}


def _enforce_personal_task_owner(principal: Principal, case: dict) -> None:
    active_assignment = assignment_values_are_active(
        case.get("assigned_to"),
        case.get("assignment_expires_at"),
        case.get("assigned_at"),
    )
    if active_assignment and case["assigned_to"] != principal.subject and "admin" not in principal.roles:
        raise HTTPException(status_code=409, detail=f"当前审批任务已由{case.get('assigned_to_name') or '其他人员'}认领")


@router.get("")
def list_approval_cases(
    repository: ApprovalCaseRepository = Depends(get_approval_repository),
    principal: Principal = Depends(require_permissions("approvals:view")),
) -> list[dict]:
    cases = repository.list(principal.counterparty_id if "client" in principal.roles else None)
    for case in cases:
        if case["current_stage"] == "final_strategy":
            ensure_credit_authority(case)
    return cases


@router.post("", status_code=201)
def create_case(
    request: ApprovalCaseCreate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    principal: Principal = Depends(require_permissions("approvals:create")),
) -> dict:
    counterparty = demo_repository.get_counterparty(request.counterparty_id)
    if not counterparty:
        raise HTTPException(status_code=404, detail="客商不存在")
    case = create_approval_case(counterparty)
    return approval_repository.save(case, actor=principal.name, event_type="approval_case_created")


@router.get("/{case_id}")
def get_case(
    case_id: str,
    repository: ApprovalCaseRepository = Depends(get_approval_repository),
    principal: Principal = Depends(require_permissions("approvals:view")),
) -> dict:
    case = repository.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    enforce_counterparty_scope(principal, case["counterparty_id"])
    if case["current_stage"] == "final_strategy":
        ensure_credit_authority(case)
    return {**case, "progress": build_workflow_progress(case)}


@router.post("/{case_id}/advance")
def advance_case(
    case_id: str,
    request: ApprovalAdvanceRequest,
    repository: ApprovalCaseRepository = Depends(get_approval_repository),
    facility_repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    decision_repository: DecisionGovernanceRepository = Depends(get_decision_governance_repository),
    principal: Principal = Depends(require_permissions("approvals:act")),
) -> dict:
    case = repository.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    if case["status"] in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="审批流程已经终止")
    enforce_counterparty_scope(principal, case["counterparty_id"])
    enforce_approval_stage_role(principal, case["current_stage"])
    _enforce_personal_task_owner(principal, case)
    if case["current_stage"] in AUTOMATED_STAGES:
        raise HTTPException(status_code=409, detail="当前环节必须通过自动编排接口执行")
    if request.expected_row_version != case["row_version"]:
        raise HTTPException(status_code=409, detail=f"审批记录版本已变化，当前版本为 {case['row_version']}")
    variance = None
    payload = deepcopy(request.payload)
    try:
        if case["current_stage"] == "final_strategy":
            authority = ensure_credit_authority(case)
            if authority["status"] != "approved":
                pending = current_authority_slot(case)
                label = pending.get("label") if pending else "授权会签"
                raise ValueError(f"最终策略尚未通过全部授权会签，当前待处理：{label}")
            final_approver = next(
                (
                    slot
                    for slot in reversed(authority["slots"])
                    if slot.get("role") == "approver" and slot.get("status") == "approved"
                ),
                None,
            )
            if (
                "admin" not in principal.roles
                and final_approver
                and final_approver.get("signed_by") != principal.subject
            ):
                raise HTTPException(status_code=403, detail="最终策略必须由最后一名有权审批会签人提交")
            payload.pop("decision_variance", None)
            variance = build_decision_variance(case.get("data", {}).get("credit_proposal", {}), payload)
            validate_decision_variance(variance)
            payload["decision_variance"] = deepcopy(variance)
        updated = advance_approval_case(case, payload, principal.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        if case["current_stage"] == "final_strategy":
            saved = repository.save(updated, actor=principal.name, event_type="approval_stage_completed", expected_row_version=request.expected_row_version, commit=False)
            decision_record = decision_repository.record(updated, variance or {}, principal.name)
            facility = facility_repository.create_from_completed_case(updated, principal.name)
            facility_repository.commit()
            return {**saved, "credit_facility": facility, "decision_variance_record": decision_record}
        return repository.save(updated, actor=principal.name, event_type="approval_stage_completed", expected_row_version=request.expected_row_version)
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        facility_repository.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{case_id}/actions")
def act_on_case(
    case_id: str,
    request: ApprovalActionRequest,
    repository: ApprovalCaseRepository = Depends(get_approval_repository),
    principal: Principal = Depends(require_permissions("approvals:act")),
) -> dict:
    case = repository.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    enforce_counterparty_scope(principal, case["counterparty_id"])
    if case["status"] in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="审批流程已经终止")
    if request.expected_row_version != case["row_version"]:
        raise HTTPException(status_code=409, detail=f"审批记录版本已变化，当前版本为 {case['row_version']}")
    if "admin" not in principal.roles and not ACTION_ROLES[request.action].intersection(principal.roles):
        raise HTTPException(status_code=403, detail="当前角色无权执行该异常流程动作")

    invalid_types = set(request.required_document_types) - ALLOWED_DOCUMENT_TYPES
    if invalid_types:
        raise HTTPException(status_code=422, detail=f"补件类型不在允许清单中：{', '.join(sorted(invalid_types))}")
    if request.action != "return_for_supplement" and request.required_document_types:
        raise HTTPException(status_code=422, detail="只有退回补件动作可以指定补件类型")

    updated = deepcopy(case)
    action_labels = {
        "return_for_supplement": "退回补件",
        "reject": "驳回申请",
        "withdraw": "撤回申请",
        "comment": "审批意见",
    }
    if request.action == "return_for_supplement":
        if case["current_stage"] not in {"model_selection", "scoring", "credit_proposal", "final_strategy"}:
            raise HTTPException(status_code=409, detail="当前环节不能退回补件")
        supplement_index = stage_index("supplement")
        updated["completed_stages"] = [item for item in updated["completed_stages"] if stage_index(item) < supplement_index]
        for workflow_stage in WORKFLOW_STAGES[supplement_index:]:
            updated["data"].pop(workflow_stage["key"], None)
        workflow_data = updated["data"].setdefault("_workflow", {})
        workflow_data["required_supplement_types"] = sorted(set(request.required_document_types))
        workflow_data["return_reason"] = request.reason
        workflow_data.pop("credit_authority", None)
        updated["current_stage"] = "supplement"
        updated["status"] = "待补件"
    elif request.action == "reject":
        if case["current_stage"] not in {"model_selection", "scoring", "credit_proposal", "final_strategy"}:
            raise HTTPException(status_code=409, detail="当前环节不能驳回申请")
        updated["status"] = "已拒绝"
    elif request.action == "withdraw":
        updated["status"] = "已撤回"

    updated["timeline"].append(
        {
            "类型": action_labels[request.action],
            "环节": stage_label(case["current_stage"]),
            "处理人": principal.name,
            "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "处理结果": request.reason,
        }
    )
    try:
        return repository.save(
            updated,
            actor=principal.name,
            event_type=f"approval_{request.action}",
            expected_row_version=request.expected_row_version,
            audit_payload={"action": request.action, "reason": request.reason, "required_document_types": request.required_document_types},
        )
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{case_id}/signoffs")
def signoff_case(
    case_id: str,
    request: ApprovalSignoffRequest,
    repository: ApprovalCaseRepository = Depends(get_approval_repository),
    principal: Principal = Depends(require_permissions("approvals:act")),
) -> dict:
    case = repository.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    if case["status"] in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="审批流程已经终止")
    if case["current_stage"] != "final_strategy":
        raise HTTPException(status_code=409, detail="授权会签仅在最终策略环节开放")
    enforce_counterparty_scope(principal, case["counterparty_id"])
    _enforce_personal_task_owner(principal, case)
    if request.expected_row_version != case["row_version"]:
        raise HTTPException(status_code=409, detail=f"审批记录版本已变化，当前版本为 {case['row_version']}")

    updated = deepcopy(case)
    authority = ensure_credit_authority(updated)
    try:
        signed_slot = record_authority_signoff(
            authority,
            slot_key=request.slot_key,
            decision=request.decision,
            comment=request.comment,
            signer_subject=principal.subject,
            signer_name=principal.name,
            signer_roles=principal.roles,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rejected = request.decision == "reject"
    if rejected:
        updated["status"] = "已拒绝"
    updated["timeline"].append(
        {
            "类型": "授权会签",
            "环节": stage_label(case["current_stage"]),
            "处理人": principal.name,
            "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "处理结果": f"{signed_slot['label']}：{'同意' if not rejected else '否决'}；{request.comment}",
        }
    )
    try:
        saved = repository.save(
            updated,
            actor=principal.name,
            event_type="approval_authority_signoff_recorded",
            expected_row_version=request.expected_row_version,
            audit_payload={
                "authority_tier": authority["tier"],
                "slot_key": request.slot_key,
                "decision": request.decision,
                "comment": request.comment,
                "signer_subject": principal.subject,
                "authority_status": authority["status"],
            },
            release_assignment=True,
        )
        return {**saved, "progress": build_workflow_progress(saved)}
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{case_id}/automate")
def automate_case_stage(
    case_id: str,
    request: ApprovalAutomateRequest,
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    document_repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
    run_repository: RatingRunRepository = Depends(get_rating_run_repository),
    enterprise_data_repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    indicator_observation_repository: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    authority_policy_repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("approvals:act")),
) -> dict:
    case = approval_repository.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    if case["status"] in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="审批流程已经终止")
    stage = case["current_stage"]
    if stage not in AUTOMATED_STAGES:
        raise HTTPException(status_code=409, detail="当前环节不支持自动编排")
    enforce_counterparty_scope(principal, case["counterparty_id"])
    enforce_approval_stage_role(principal, stage)
    _enforce_personal_task_owner(principal, case)
    if request.expected_row_version != case["row_version"]:
        raise HTTPException(status_code=409, detail=f"审批记录版本已变化，当前版本为 {case['row_version']}")

    counterparty = demo_repository.get_counterparty(case["counterparty_id"])
    if not counterparty:
        raise HTTPException(status_code=404, detail="客商不存在")

    if stage in {"document_upload", "supplement"}:
        documents = document_repository.list(case_id=case_id)
        for document in documents:
            if document["counterparty_id"] != case["counterparty_id"]:
                raise HTTPException(status_code=409, detail="审批资料归属完整性校验失败")
            try:
                content = storage.get(document["object_key"])
            except FileNotFoundError as exc:
                raise HTTPException(status_code=409, detail=f"资料对象不存在：{document['original_name']}") from exc
            if hashlib.sha256(content).hexdigest() != document["sha256"]:
                raise HTTPException(status_code=409, detail=f"资料文件指纹校验失败：{document['original_name']}")
        # Only reviewer-verified material may move the approval workflow forward.
        # Uploading and reviewing are deliberately separated for four-eye control.
        document_types = {
            item["document_type"]
            for item in documents
            if item.get("review_status") == "verified"
        }
        pending_document_types = {
            item["document_type"]
            for item in documents
            if item.get("review_status") == "pending_review"
        }
        if stage == "document_upload":
            missing = sorted(INITIAL_DOCUMENT_TYPES - document_types)
            if not INITIAL_SUPPORTING_TYPES.intersection(document_types):
                missing.append("财务报表/业务合同/征信授权书（至少一项）")
            if missing:
                pending = sorted((INITIAL_DOCUMENT_TYPES | INITIAL_SUPPORTING_TYPES) & pending_document_types)
                pending_hint = f"；已上传但待风控独立核验：{', '.join(pending)}" if pending else ""
                raise HTTPException(status_code=422, detail=f"初始资料尚未通过门禁，缺少已核验资料：{', '.join(missing)}{pending_hint}")
            payload = {
                "documents": [item["original_name"] for item in documents],
                "document_ids": [item["id"] for item in documents],
                "verified_document_types": sorted(document_types),
            }
        else:
            requested_types = set(case["data"].get("_workflow", {}).get("required_supplement_types", []))
            missing = missing_document_types(SUPPLEMENT_REQUIRED_TYPES | requested_types, document_types)
            if missing:
                pending = sorted(
                    document_type
                    for document_type in missing
                    if document_type_satisfied(document_type, pending_document_types)
                )
                pending_hint = f"；已上传但待风控独立核验：{', '.join(pending)}" if pending else ""
                raise HTTPException(status_code=422, detail=f"补件尚未通过门禁，缺少已核验资料：{', '.join(missing)}{pending_hint}")
            payload = {
                "supplement_status": "已补齐",
                "document_ids": [item["id"] for item in documents],
                "verified_document_types": sorted(document_types),
            }
    elif stage == "model_selection":
        template_key = request.template_key or "general"
        config = model_governance_repository.get_config(demo_repository, template_key)
        if not config:
            raise HTTPException(status_code=404, detail="模型模板不存在")
        rating_input, readiness = prepare_rating_input(counterparty, enterprise_data_repository.build_profile(counterparty["id"]), template_key, config)
        rating_input, readiness = apply_effective_observations(rating_input, readiness, indicator_observation_repository.effective(counterparty["id"]))
        if not readiness["ready_for_scoring"]:
            missing = ", ".join(readiness["required_missing"][:5])
            raise HTTPException(status_code=422, detail=f"治理数据未达到模型计算门槛，缺少：{missing}")
        validation_result = rate_counterparty(rating_input, config)
        if not validation_result.get("ok"):
            raise HTTPException(status_code=422, detail=f"模型与当前客商数据不兼容：{validation_result.get('error', '无法计算')}")
        payload = {"template_key": template_key, "model_name": config["name"], "model_version": config["version"], "input_readiness": readiness_summary(readiness)}
    elif stage == "scoring":
        selection = case["data"].get("model_selection", {})
        template_key = selection.get("template_key")
        selected_version = selection.get("model_version")
        config = model_governance_repository.get_config(demo_repository, template_key, selected_version) if template_key and selected_version else None
        if not config:
            raise HTTPException(status_code=409, detail="审批单缺少有效的模型选择结果")
        rating_input, readiness = prepare_rating_input(counterparty, enterprise_data_repository.build_profile(counterparty["id"]), template_key, config)
        rating_input, readiness = apply_effective_observations(rating_input, readiness, indicator_observation_repository.effective(counterparty["id"]))
        if not readiness["ready_for_scoring"]:
            missing = ", ".join(readiness["required_missing"][:5])
            raise HTTPException(status_code=422, detail=f"治理数据未达到模型计算门槛，缺少：{missing}")
        selected_data_hash = selection.get("input_readiness", {}).get("data_snapshot_hash")
        if selected_data_hash and selected_data_hash != readiness.get("data_snapshot_hash"):
            raise HTTPException(status_code=409, detail="治理数据已在选模后发生变化，请重新执行模型选择与数据预检")
        result = rate_counterparty(rating_input, config)
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result.get("error", "评级计算失败"))
        result["input_readiness"] = readiness_summary(readiness)
        result["enterprise_risk_screening"] = evaluate_indicator_pool(rating_input, config)
        run = run_repository.save_run(rating_input, template_key, config, result, actor=principal.name, case_id=case_id, commit=False)
        payload = {
            "total_score": result["total_score"],
            "rating": result["rating"],
            "rating_run_id": run["id"],
            "model_snapshot_id": run["model_snapshot_id"],
            "result_hash": run["result_hash"],
        }
    else:
        scoring = case["data"].get("scoring", {})
        run = run_repository.get(scoring.get("rating_run_id", ""))
        if not run or run.get("case_id") != case_id:
            raise HTTPException(status_code=409, detail="审批单缺少可信评级运行结果")
        result = run["result"]
        if (
            run.get("counterparty_id") != case["counterparty_id"]
            or content_hash(run["input"]) != run.get("input_hash")
            or scoring.get("result_hash") != run.get("result_hash")
            or scoring.get("model_snapshot_id") != run.get("model_snapshot_id")
            or content_hash(result) != run.get("result_hash")
        ):
            raise HTTPException(status_code=409, detail="评级运行输入或结果完整性校验失败")
        payload = {
            "suggested_limit": result["suggested_limit"],
            "suggested_payment_term_days": result["suggested_payment_term_days"],
            "rating_run_id": run["id"],
            "access_strategy": result["access_strategy"],
            "monitoring_frequency": result["monitoring_frequency"],
        }

    try:
        updated = advance_approval_case(case, payload, principal.name)
        if stage == "supplement":
            updated["data"].get("_workflow", {}).pop("required_supplement_types", None)
        if stage == "credit_proposal":
            updated["data"].setdefault("_workflow", {})["credit_authority"] = build_credit_authority(
                updated,
                authority_policy_repository.active_snapshot(),
            )
        return approval_repository.save(updated, actor=principal.name, event_type=f"approval_{stage}_automated", expected_row_version=request.expected_row_version)
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
