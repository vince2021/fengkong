"""Tenant-scoped Champion/Challenger rollout governance endpoints."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from backend.dependencies import get_demo_repository, get_model_governance_repository, get_tenant_outcome_repository, get_tenant_rollout_repository
from backend.repository import DemoRepository, ModelGovernanceRepository
from backend.security import Principal, require_permissions
from backend.tenant_outcome_repository import TenantOutcomeRepository
from backend.tenant_rollout_repository import TenantRolloutError, TenantRolloutRepository
from backend.tenant_rollout_schemas import OutcomeImportCreate, OutcomeLabelCorrection, OutcomeLabelCreate, OutcomeLabelDefinitionAction, OutcomeLabelDefinitionCreate, OutcomeLabelDefinitionReview, OutcomeLabelDefinitionUpdate, OutcomeLabelVerification, RolloutIncidentAction, RolloutPolicyCreate, RolloutPolicyView, RolloutRestartAfterRelease, RolloutReview, RolloutStatusAction, RolloutVersionAction, SupervisedEvaluationCreate, SupervisedEvaluationReview, SupervisedEvaluationSubmit, SupervisedUpgradeDraftCreate, TenantMonitoringDiffCaseAssign, TenantMonitoringDiffCaseCreate, TenantMonitoringDiffCaseDisposition, TenantMonitoringDiffCaseRecompute, TenantMonitoringGenerate, TenantMonitoringRunCreate, TenantMonitoringRunReview, TenantMonitoringRunRetraction, TenantMonitoringRunSubmit


router = APIRouter(prefix="/model-governance/rollouts", tags=["tenant-rollouts"])
definition_router = APIRouter(prefix="/model-governance/outcome-label-definitions", tags=["outcome-label-definitions"])


@definition_router.get("")
def list_outcome_label_definitions(
    published_only: bool = False,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_definitions, principal.tenant_id, published_only)


@definition_router.post("", status_code=201)
def create_outcome_label_definition(
    body: OutcomeLabelDefinitionCreate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.create_definition, principal.tenant_id, body.model_dump(), principal)


@definition_router.put("/{definition_id}")
def update_outcome_label_definition(
    definition_id: str,
    body: OutcomeLabelDefinitionUpdate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.update_definition, principal.tenant_id, definition_id, body.model_dump(), principal)


@definition_router.post("/{definition_id}/submit")
def submit_outcome_label_definition(
    definition_id: str,
    body: OutcomeLabelDefinitionAction,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.submit_definition, principal.tenant_id, definition_id, body.model_dump(), principal)


@definition_router.post("/{definition_id}/review")
def review_outcome_label_definition(
    definition_id: str,
    body: OutcomeLabelDefinitionReview,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.review_definition, principal.tenant_id, definition_id, body.model_dump(), principal)


@router.get("/scans")
def list_rollout_scans(
    limit: int = Query(default=20, ge=1, le=100),
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return repository.list_scans(principal.tenant_id, limit)


@router.post("/monitoring-gates/scan")
def scan_tenant_monitoring_gates(
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.scan_monitoring_gates, principal.tenant_id, principal.subject)


@router.get("/monitoring-diff-cases/sla-dashboard")
def get_monitoring_diff_sla_dashboard(
    template_key: str | None = Query(default=None, min_length=1, max_length=64),
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.monitoring_diff_sla_dashboard, principal.tenant_id, template_key)


@router.post("/monitoring-diff-cases/sla-scan")
def scan_monitoring_diff_case_sla(
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.scan_monitoring_diff_case_sla, principal.tenant_id, principal.subject)


@router.post("/scan")
def scan_rollouts(
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.scan, principal.tenant_id, principal)


@router.get("", response_model=list[RolloutPolicyView])
def list_rollouts(
    model_key: str | None = None,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return repository.list_policies(principal.tenant_id, model_key)


@router.post("", status_code=201, response_model=RolloutPolicyView)
def create_rollout(
    body: RolloutPolicyCreate,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.create_policy, principal.tenant_id, body.model_dump(), principal)


@router.post("/{policy_id}/submit", response_model=RolloutPolicyView)
def submit_rollout(
    policy_id: str,
    body: RolloutVersionAction,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.submit, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/review", response_model=RolloutPolicyView)
def review_rollout(
    policy_id: str,
    body: RolloutReview,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.review, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/status", response_model=RolloutPolicyView)
def change_rollout_status(
    policy_id: str,
    body: RolloutStatusAction,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.change_status, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/restart-after-release")
def restart_rollout_after_release(
    policy_id: str,
    body: RolloutRestartAfterRelease,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.restart_after_release, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/incident", response_model=RolloutPolicyView)
def act_on_rollout_incident(
    policy_id: str,
    body: RolloutIncidentAction,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.incident_action, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.get("/{policy_id}/routes")
def list_rollout_routes(
    policy_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_routes, principal.tenant_id, policy_id, limit)


@router.get("/{policy_id}/evaluations")
def list_rollout_evaluations(
    policy_id: str,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_evaluations, principal.tenant_id, policy_id)


@router.post("/{policy_id}/evaluate")
def evaluate_rollout(
    policy_id: str,
    repository: TenantRolloutRepository = Depends(get_tenant_rollout_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.evaluate, principal.tenant_id, policy_id, principal)


@router.get("/{policy_id}/outcomes")
def list_rollout_outcomes(
    policy_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_labels, principal.tenant_id, policy_id)


@router.post("/{policy_id}/outcomes", status_code=201)
def create_rollout_outcome(
    policy_id: str,
    body: OutcomeLabelCreate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.create_label, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.get("/{policy_id}/outcome-imports")
def list_rollout_outcome_imports(
    policy_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_imports, principal.tenant_id, policy_id)


@router.post("/{policy_id}/outcome-imports", status_code=201)
def create_rollout_outcome_import(
    policy_id: str,
    body: OutcomeImportCreate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.create_import, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/outcome-imports/csv", status_code=201)
async def create_rollout_outcome_csv_import(
    policy_id: str,
    file: UploadFile = File(...),
    import_key: str = Form(...),
    source: str = Form(...),
    label_definition_id: str = Form(...),
    expected_count: int = Form(...),
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    """Validate a bounded CSV file, then route it through the canonical batch importer."""
    raw = await file.read()
    if len(raw) > 512 * 1024:
        raise _csv_error("OUTCOME_CSV_TOO_LARGE", "结果标签 CSV 不得超过 512KB", 413)
    if not raw:
        raise _csv_error("OUTCOME_CSV_EMPTY", "结果标签 CSV 不能为空", 422)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _csv_error("OUTCOME_CSV_ENCODING_INVALID", "结果标签 CSV 必须使用 UTF-8 编码", 422) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    required = {
        "external_label_id", "routing_decision_id", "counterparty_id", "observed_event",
        "observation_end", "loss_amount", "exposure_amount", "evidence_reference",
    }
    headers = set(reader.fieldnames or [])
    missing = sorted(required - headers)
    if missing:
        raise _csv_error("OUTCOME_CSV_HEADER_INVALID", "结果标签 CSV 缺少必需列", 422, {"missing": missing})
    rows: list[dict] = []
    errors: list[dict] = []
    for index, row in enumerate(reader, start=2):
        try:
            for field in ("external_label_id", "routing_decision_id", "counterparty_id", "evidence_reference"):
                if not (row.get(field) or "").strip():
                    raise _csv_error("OUTCOME_CSV_FIELD_EMPTY", f"第 {index} 行 {field} 不能为空", 422)
            rows.append({
                "external_label_id": (row.get("external_label_id") or "").strip(),
                "routing_decision_id": (row.get("routing_decision_id") or "").strip(),
                "counterparty_id": (row.get("counterparty_id") or "").strip(),
                "observed_event": _parse_csv_bool(row.get("observed_event", ""), index),
                "observation_end": _parse_csv_datetime(row.get("observation_end", ""), index),
                "loss_amount": _parse_csv_number(row.get("loss_amount"), index, "loss_amount"),
                "exposure_amount": _parse_csv_number(row.get("exposure_amount"), index, "exposure_amount"),
                "evidence_reference": (row.get("evidence_reference") or "").strip(),
            })
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "OUTCOME_CSV_ROW_INVALID", "message": str(exc.detail)}
            errors.append({"row": index, "code": detail.get("code"), "message": detail.get("message")})
    if errors:
        raise _csv_error("OUTCOME_CSV_ROW_INVALID", "结果标签 CSV 存在格式错误，未创建批次", 422, {"errors": errors[:50]})
    if not rows:
        raise _csv_error("OUTCOME_CSV_EMPTY", "结果标签 CSV 不包含数据行", 422)
    if len(rows) > 500:
        raise _csv_error("OUTCOME_CSV_TOO_MANY_ROWS", "结果标签 CSV 最多包含 500 条数据行", 422)
    if expected_count < 1 or expected_count > 500:
        raise _csv_error("OUTCOME_CSV_EXPECTED_COUNT_INVALID", "来源声明数量必须在 1 到 500 之间", 422)
    payload = {
        "import_key": import_key,
        "source": source,
        "label_definition_id": label_definition_id,
        "expected_count": expected_count,
        "outcomes": rows,
    }
    result = _run(repository.create_import, principal.tenant_id, policy_id, payload, principal)
    result["file"] = {
        "filename": file.filename or "outcomes.csv",
        "content_type": file.content_type or "text/csv",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "row_count": len(rows),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


@router.post("/{policy_id}/outcomes/{label_id}/verify")
def verify_rollout_outcome(
    policy_id: str,
    label_id: str,
    body: OutcomeLabelVerification,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.verify_label, principal.tenant_id, policy_id, label_id, body.model_dump(), principal)


@router.post("/{policy_id}/outcomes/{label_id}/correct", status_code=201)
def correct_rollout_outcome(
    policy_id: str,
    label_id: str,
    body: OutcomeLabelCorrection,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.correct_label, principal.tenant_id, policy_id, label_id, body.model_dump(), principal)


@router.get("/{policy_id}/supervised-evaluations")
def list_supervised_evaluations(
    policy_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_evaluations, principal.tenant_id, policy_id)


@router.get("/{policy_id}/tenant-monitoring-runs")
def list_tenant_monitoring_runs(
    policy_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_monitoring_runs, principal.tenant_id, policy_id)


@router.get("/{policy_id}/monitoring-diff-cases")
def list_tenant_monitoring_diff_cases(
    policy_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.list_monitoring_diff_cases, principal.tenant_id, policy_id)


@router.post("/{policy_id}/monitoring-diff-cases", status_code=201)
def create_tenant_monitoring_diff_case(
    policy_id: str,
    body: TenantMonitoringDiffCaseCreate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.create_monitoring_diff_case, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/monitoring-diff-cases/{case_id}/assign")
def assign_tenant_monitoring_diff_case(
    policy_id: str,
    case_id: str,
    body: TenantMonitoringDiffCaseAssign,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.assign_monitoring_diff_case, principal.tenant_id, policy_id, case_id, body.model_dump(), principal)


@router.post("/{policy_id}/monitoring-diff-cases/{case_id}/recompute")
def recompute_tenant_monitoring_diff_case(
    policy_id: str,
    case_id: str,
    body: TenantMonitoringDiffCaseRecompute,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.recompute_monitoring_diff_case, principal.tenant_id, policy_id, case_id, body.model_dump(), principal)


@router.post("/{policy_id}/monitoring-diff-cases/{case_id}/dispose")
def dispose_tenant_monitoring_diff_case(
    policy_id: str,
    case_id: str,
    body: TenantMonitoringDiffCaseDisposition,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.dispose_monitoring_diff_case, principal.tenant_id, policy_id, case_id, body.model_dump(), principal)


@router.get("/{policy_id}/tenant-monitoring-runs/{run_id}/gate")
def get_tenant_monitoring_gate(
    policy_id: str,
    run_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.monitoring_gate, principal.tenant_id, policy_id, run_id)


@router.post("/{policy_id}/tenant-monitoring-runs", status_code=201)
def create_tenant_monitoring_run(
    policy_id: str,
    body: TenantMonitoringRunCreate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.create_monitoring_run, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/tenant-monitoring-runs/{run_id}/submit", status_code=200)
def submit_tenant_monitoring_run(
    policy_id: str,
    run_id: str,
    body: TenantMonitoringRunSubmit,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(repository.submit_monitoring_run, principal.tenant_id, policy_id, run_id, body.model_dump(), principal)


@router.post("/{policy_id}/tenant-monitoring-runs/{run_id}/review", status_code=200)
def review_tenant_monitoring_run(
    policy_id: str,
    run_id: str,
    body: TenantMonitoringRunReview,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.review_monitoring_run, principal.tenant_id, policy_id, run_id, body.model_dump(), principal)


@router.post("/{policy_id}/tenant-monitoring-runs/{run_id}/retract", status_code=200)
def retract_tenant_monitoring_run(
    policy_id: str,
    run_id: str,
    body: TenantMonitoringRunRetraction,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.retract_monitoring_run, principal.tenant_id, policy_id, run_id, body.model_dump(), principal)


@router.get("/{policy_id}/tenant-monitoring-runs/{run_id}/diff")
def diff_tenant_monitoring_run(
    policy_id: str,
    run_id: str,
    against_run_id: str | None = Query(default=None, min_length=8, max_length=36),
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.monitoring_run_diff, principal.tenant_id, policy_id, run_id, against_run_id)


@router.post("/{policy_id}/tenant-monitoring-runs/generate", status_code=201)
def generate_tenant_monitoring_runs(
    policy_id: str,
    body: TenantMonitoringGenerate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.generate_monitoring_runs, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.get("/{policy_id}/supervised-evaluations/{evaluation_id}/verification-report")
def get_supervised_verification_report(
    policy_id: str,
    evaluation_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    return _run(repository.verification_report, principal.tenant_id, policy_id, evaluation_id)


@router.get("/{policy_id}/supervised-evaluations/{evaluation_id}/verification-report.csv")
def download_supervised_verification_report(
    policy_id: str,
    evaluation_id: str,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:view")),
):
    report = _run(repository.verification_report, principal.tenant_id, policy_id, evaluation_id)
    rows = [
        ("report_hash", report["report_hash"]),
        ("evaluation_id", report["evaluation"]["id"]),
        ("policy_id", report["evaluation"]["policy_id"]),
        ("evaluation_as_of", report["evaluation"]["evaluation_as_of"]),
        ("evidence_level", report["evaluation"]["evidence_level"]),
        ("status", report["evaluation"]["status"]),
        ("label_definition_hash", report["evaluation"].get("label_definition_hash") or ""),
        ("mature_count", report["coverage"].get("mature_count", 0)),
        ("verified_count", report["coverage"].get("verified_count", 0)),
        ("execution_linked_count", report["coverage"].get("execution_linked_count", 0)),
    ]
    for arm in ("champion", "challenger"):
        metrics = report["metrics"][arm]
        rows.extend([
            (f"{arm}.sample_count", metrics.get("sample_count", 0)),
            (f"{arm}.event_rate", metrics.get("event_rate")),
            (f"{arm}.event_rate_ci_lower", (metrics.get("event_rate_confidence_interval") or {}).get("lower")),
            (f"{arm}.event_rate_ci_upper", (metrics.get("event_rate_confidence_interval") or {}).get("upper")),
            (f"{arm}.auc", metrics.get("auc")),
            (f"{arm}.auc_ci_lower", (metrics.get("auc_confidence_interval") or {}).get("lower")),
            (f"{arm}.auc_ci_upper", (metrics.get("auc_confidence_interval") or {}).get("upper")),
            (f"{arm}.ks", metrics.get("ks")),
            (f"{arm}.ks_ci_lower", (metrics.get("ks_confidence_interval") or {}).get("lower")),
            (f"{arm}.ks_ci_upper", (metrics.get("ks_confidence_interval") or {}).get("upper")),
            (f"{arm}.bootstrap_resamples", metrics.get("bootstrap_resamples")),
            (f"{arm}.loss_rate", metrics.get("loss_rate")),
            (f"{arm}.total_loss_amount", metrics.get("total_loss_amount")),
            (f"{arm}.total_exposure_amount", metrics.get("total_exposure_amount")),
            (f"{arm}.statistical_reliability", metrics.get("statistical_reliability")),
        ])
    comparison = report["metrics"].get("comparison") or {}
    rows.extend([
        ("comparison.auc_delta", comparison.get("auc_delta")),
        ("comparison.auc_difference_ci_lower", (comparison.get("auc_difference_confidence_interval") or {}).get("lower")),
        ("comparison.auc_difference_ci_upper", (comparison.get("auc_difference_confidence_interval") or {}).get("upper")),
        ("comparison.auc_difference_signal", comparison.get("auc_difference_signal")),
        ("comparison.ks_delta", comparison.get("ks_delta")),
        ("comparison.ks_difference_ci_lower", (comparison.get("ks_difference_confidence_interval") or {}).get("lower")),
        ("comparison.ks_difference_ci_upper", (comparison.get("ks_difference_confidence_interval") or {}).get("upper")),
        ("comparison.ks_difference_signal", comparison.get("ks_difference_signal")),
    ])
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["metric", "value"])
    writer.writerows(rows)
    filename = f"supervised-verification-{evaluation_id[:8]}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{policy_id}/supervised-evaluate", status_code=201)
def evaluate_supervised_outcomes(
    policy_id: str,
    body: SupervisedEvaluationCreate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.evaluate, principal.tenant_id, policy_id, body.model_dump(), principal)


@router.post("/{policy_id}/supervised-evaluations/{evaluation_id}/submit")
def submit_supervised_evaluation(
    policy_id: str,
    evaluation_id: str,
    body: SupervisedEvaluationSubmit,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.submit_evaluation, principal.tenant_id, policy_id, evaluation_id, body.model_dump(), principal)


@router.post("/{policy_id}/supervised-evaluations/{evaluation_id}/review")
def review_supervised_evaluation(
    policy_id: str,
    evaluation_id: str,
    body: SupervisedEvaluationReview,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    principal: Principal = Depends(require_permissions("models:review")),
):
    return _run(repository.review_evaluation, principal.tenant_id, policy_id, evaluation_id, body.model_dump(), principal)


@router.post("/{policy_id}/supervised-evaluations/{evaluation_id}/create-change-draft", status_code=201)
def create_supervised_upgrade_draft(
    policy_id: str,
    evaluation_id: str,
    body: SupervisedUpgradeDraftCreate,
    repository: TenantOutcomeRepository = Depends(get_tenant_outcome_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
):
    return _run(
        repository.create_upgrade_draft,
        principal.tenant_id,
        policy_id,
        evaluation_id,
        body.model_dump(),
        principal,
        demo_repository,
        governance_repository,
    )


def _run(operation, *args):
    from fastapi import HTTPException

    try:
        return operation(*args)
    except TenantRolloutError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc


def _parse_csv_bool(value: str, row_number: int) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "是", "发生", "event"}:
        return True
    if normalized in {"false", "0", "no", "n", "否", "未发生", "normal"}:
        return False
    raise _csv_error("OUTCOME_CSV_BOOLEAN_INVALID", f"第 {row_number} 行 observed_event 不是有效布尔值", 422)


def _parse_csv_datetime(value: str, row_number: int) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise _csv_error("OUTCOME_CSV_DATETIME_INVALID", f"第 {row_number} 行 observation_end 不能为空", 422)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _csv_error("OUTCOME_CSV_DATETIME_INVALID", f"第 {row_number} 行 observation_end 不是 ISO 日期时间", 422) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_csv_number(value: str | None, row_number: int, field: str) -> float | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    try:
        number = float(normalized)
    except ValueError as exc:
        raise _csv_error("OUTCOME_CSV_NUMBER_INVALID", f"第 {row_number} 行 {field} 不是有效数字", 422) from exc
    if number < 0 or number != number or number in {float("inf"), float("-inf")}:
        raise _csv_error("OUTCOME_CSV_NUMBER_INVALID", f"第 {row_number} 行 {field} 数值无效", 422)
    if field == "exposure_amount" and number == 0:
        raise _csv_error("OUTCOME_CSV_NUMBER_INVALID", f"第 {row_number} 行风险暴露必须大于 0", 422)
    return number


def _csv_error(code: str, message: str, status_code: int, details: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, "details": details or {}})
