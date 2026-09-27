from __future__ import annotations

import hashlib
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.credit_report import build_credit_report_snapshot, build_report_preview, render_credit_report_pdf
from backend.counterparty_repository import CounterpartyError, CounterpartyRepository
from backend.dependencies import get_approval_repository, get_counterparty_repository, get_credit_report_repository, get_document_repository, get_object_storage, get_rating_run_repository
from backend.repository import ApprovalCaseRepository, ConcurrentUpdateError, CreditReportRepository, DocumentRepository, RatingRunRepository, content_hash
from backend.schemas import CreditReportCreate
from backend.security import Principal, enforce_counterparty_scope, require_permissions
from backend.storage import ObjectStorage


router = APIRouter(prefix="/credit-reports", tags=["credit-reports"])


@router.get("")
def list_credit_reports(
    case_id: str | None = Query(default=None, max_length=128),
    repository: CreditReportRepository = Depends(get_credit_report_repository),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    principal: Principal = Depends(require_permissions("reports:view")),
) -> list[dict]:
    if case_id:
        case = approval_repository.get(principal.tenant_id, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="审批申请不存在")
        enforce_counterparty_scope(principal, case["counterparty_id"])
    return [_public_report(item) for item in repository.list(principal.tenant_id, case_id=case_id)]


@router.post("", status_code=201)
def create_credit_report(
    request: CreditReportCreate,
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    report_repository: CreditReportRepository = Depends(get_credit_report_repository),
    rating_repository: RatingRunRepository = Depends(get_rating_run_repository),
    document_repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
    principal: Principal = Depends(require_permissions("reports:generate")),
) -> dict:
    case = approval_repository.get(principal.tenant_id, request.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    enforce_counterparty_scope(principal, case["counterparty_id"])
    if case["status"] != "已完成":
        raise HTTPException(status_code=409, detail="只有完成最终审批的申请可以生成授信决策报告")
    final_strategy = case["data"].get("final_strategy")
    scoring = case["data"].get("scoring")
    if not final_strategy or not scoring:
        raise HTTPException(status_code=409, detail="审批单缺少最终策略或可信评级结果")
    rating_run = rating_repository.get(principal.tenant_id, scoring.get("rating_run_id", ""))
    if not rating_run or rating_run.get("case_id") != case["case_id"]:
        raise HTTPException(status_code=409, detail="审批单关联的评级运行不存在或归属不一致")
    if (
        scoring.get("model_snapshot_id") != rating_run.get("model_snapshot_id")
        or content_hash(rating_run["input"]) != rating_run.get("input_hash")
        or scoring.get("result_hash") != rating_run.get("result_hash")
        or content_hash(rating_run["result"]) != rating_run.get("result_hash")
    ):
        raise HTTPException(status_code=409, detail="评级运行输入或结果完整性校验失败")
    try:
        counterparty = counterparty_repository.get(
            principal.tenant_id,
            case["counterparty_id"],
            include_archived=True,
        )
    except CounterpartyError as exc:
        raise HTTPException(status_code=404, detail="客商不存在") from exc
    documents = document_repository.list(principal.tenant_id, case_id=case["case_id"])
    _verify_documents(documents, case["counterparty_id"], storage)
    snapshot = build_credit_report_snapshot(case, counterparty, rating_run, documents, counterparty)
    snapshot_hash = content_hash(snapshot)
    existing = report_repository.get_by_case_snapshot(principal.tenant_id, case["case_id"], snapshot_hash)
    if existing:
        return {**_public_report(existing), "idempotent": True}

    report_version = report_repository.next_version(principal.tenant_id, case["case_id"])
    report_id = str(uuid4())
    report_no = f"CR-{case['case_id'][-72:]}-{snapshot_hash[:10]}"
    object_key = f"reports/{principal.tenant_id}/{case['counterparty_id']}/{case['case_id']}/{snapshot_hash}.pdf"
    pdf_content = render_credit_report_pdf(snapshot, report_no, report_version)
    pdf_sha256 = hashlib.sha256(pdf_content).hexdigest()
    storage.put(object_key, pdf_content, "application/pdf")
    try:
        report, idempotent = report_repository.create(
            principal.tenant_id,
            {
                "id": report_id,
                "report_no": report_no,
                "case_id": case["case_id"],
                "counterparty_id": case["counterparty_id"],
                "report_version": report_version,
                "report_type": "credit_decision",
                "status": "sealed",
                "snapshot_json": snapshot,
                "snapshot_hash": snapshot_hash,
                "object_key": object_key,
                "pdf_sha256": pdf_sha256,
                "size_bytes": len(pdf_content),
            },
            principal.name,
        )
    except ConcurrentUpdateError as exc:
        storage.delete(object_key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        storage.delete(object_key)
        raise
    return {**_public_report(report), "idempotent": idempotent}


@router.get("/{report_id}")
def get_credit_report(
    report_id: str,
    repository: CreditReportRepository = Depends(get_credit_report_repository),
    principal: Principal = Depends(require_permissions("reports:view")),
) -> dict:
    report = _get_scoped_report(report_id, repository, principal)
    return _public_report(report, include_snapshot=True)


@router.get("/{report_id}/integrity")
def verify_credit_report_integrity(
    report_id: str,
    repository: CreditReportRepository = Depends(get_credit_report_repository),
    storage: ObjectStorage = Depends(get_object_storage),
    principal: Principal = Depends(require_permissions("reports:view")),
) -> dict:
    report = _get_scoped_report(report_id, repository, principal)
    snapshot_actual = content_hash(report["snapshot"])
    try:
        content = storage.get(report["object_key"])
        pdf_actual = hashlib.sha256(content).hexdigest()
        object_exists = True
    except FileNotFoundError:
        pdf_actual = None
        object_exists = False
    snapshot_valid = snapshot_actual == report["snapshot_hash"]
    pdf_valid = object_exists and pdf_actual == report["pdf_sha256"]
    return {
        "report_id": report["id"],
        "report_no": report["report_no"],
        "status": "verified" if snapshot_valid and pdf_valid else "failed",
        "valid": snapshot_valid and pdf_valid,
        "snapshot": {"valid": snapshot_valid, "expected_sha256": report["snapshot_hash"], "actual_sha256": snapshot_actual},
        "pdf": {"valid": pdf_valid, "object_exists": object_exists, "expected_sha256": report["pdf_sha256"], "actual_sha256": pdf_actual},
    }


@router.get("/{report_id}/download")
def download_credit_report(
    report_id: str,
    repository: CreditReportRepository = Depends(get_credit_report_repository),
    storage: ObjectStorage = Depends(get_object_storage),
    principal: Principal = Depends(require_permissions("reports:view")),
) -> Response:
    report = _get_scoped_report(report_id, repository, principal)
    if content_hash(report["snapshot"]) != report["snapshot_hash"]:
        raise HTTPException(status_code=409, detail="信用报告业务快照完整性校验失败")
    try:
        content = storage.get(report["object_key"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="信用报告归档文件不存在") from exc
    if hashlib.sha256(content).hexdigest() != report["pdf_sha256"]:
        raise HTTPException(status_code=409, detail="信用报告 PDF 文件指纹校验失败")
    filename = quote(f"{report['report_no']}-信用评级与授信决策报告.pdf")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Report-Snapshot-SHA256": report["snapshot_hash"],
            "X-Report-PDF-SHA256": report["pdf_sha256"],
        },
    )


def _verify_documents(documents: list[dict], counterparty_id: str, storage: ObjectStorage) -> None:
    for document in documents:
        if document["counterparty_id"] != counterparty_id:
            raise HTTPException(status_code=409, detail="审批资料归属完整性校验失败")
        try:
            content = storage.get(document["object_key"])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=f"资料对象不存在：{document['original_name']}") from exc
        if hashlib.sha256(content).hexdigest() != document["sha256"]:
            raise HTTPException(status_code=409, detail=f"资料文件指纹校验失败：{document['original_name']}")


def _get_scoped_report(report_id: str, repository: CreditReportRepository, principal: Principal) -> dict:
    report = repository.get(principal.tenant_id, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="信用报告不存在")
    enforce_counterparty_scope(principal, report["counterparty_id"])
    return report


def _public_report(report: dict, include_snapshot: bool = False) -> dict:
    payload = {
        key: value
        for key, value in report.items()
        if key not in {"object_key", "snapshot"}
    }
    payload["preview"] = build_report_preview(report["snapshot"])
    if include_snapshot:
        payload["snapshot"] = report["snapshot"]
    return payload
