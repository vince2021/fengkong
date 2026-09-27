from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.counterparty_repository import CounterpartyError, CounterpartyRepository
from backend.dependencies import get_approval_repository, get_counterparty_repository, get_document_repository, get_object_storage
from backend.document_comparison import build_document_version_comparison
from backend.document_policy import ALLOWED_DOCUMENT_TYPES, DOCUMENT_REVIEW_CHECKS, assess_renewal_document_carryover, build_document_checklist
from backend.document_precheck import precheck_document
from backend.repository import ApprovalCaseRepository, ConcurrentUpdateError, DocumentRepository, TaskOwnershipConflict
from backend.schemas import DocumentCaseLinkRequest, DocumentReviewRequest, RenewalDocumentCarryoverRequest
from backend.security import Principal, enforce_counterparty_scope, require_permissions
from backend.storage import ObjectStorage


router = APIRouter(prefix="/documents", tags=["documents"])
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/plain"}


@router.post("", status_code=201)
async def upload_document(
    counterparty_id: str = Form(),
    document_type: str = Form(),
    file: UploadFile = File(),
    case_id: str | None = Form(default=None),
    correction_id: str | None = Form(default=None),
    principal: Principal = Depends(require_permissions("documents:upload")),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    try:
        counterparty_repository.get(principal.tenant_id, counterparty_id)
    except CounterpartyError as exc:
        raise HTTPException(status_code=404, detail="客商不存在") from exc
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(status_code=422, detail="资料类型不在允许清单中")
    if correction_id:
        correction = repository.get_correction(principal.tenant_id, correction_id)
        if not correction:
            raise HTTPException(status_code=404, detail="补件任务不存在")
        enforce_counterparty_scope(principal, correction["counterparty_id"])
        if correction["status"] != "open":
            raise HTTPException(status_code=422, detail="补件任务当前不允许上传替换资料")
        if correction["counterparty_id"] != counterparty_id or correction["case_id"] != case_id or correction["document_type"] != document_type:
            raise HTTPException(status_code=422, detail="替换资料与补件任务的企业、审批单或资料类型不匹配")
    if case_id:
        approval_case = approval_repository.get(principal.tenant_id, case_id)
        if not approval_case:
            raise HTTPException(status_code=404, detail="审批申请不存在")
        if approval_case["counterparty_id"] != counterparty_id:
            raise HTTPException(status_code=422, detail="审批申请与客商不匹配")
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="不支持的文件类型")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="文件不能为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件大小不能超过 20 MB")
    suffix = _safe_suffix(file.filename or "")
    if not _matches_declared_type(content_type, suffix, content):
        raise HTTPException(status_code=415, detail="文件内容与声明类型或扩展名不一致")
    document_id = str(uuid4())
    object_key = f"{principal.tenant_id}/{counterparty_id}/{document_id}{suffix}"
    digest = hashlib.sha256(content).hexdigest()
    storage.put(object_key, content, content_type)
    try:
        return repository.create(
            principal.tenant_id,
            {
                "id": document_id,
                "counterparty_id": counterparty_id,
                "case_id": case_id,
                "document_type": document_type,
                "original_name": file.filename or "未命名文件",
                "object_key": object_key,
                "content_type": content_type,
                "size_bytes": len(content),
                "sha256": digest,
                "uploaded_by": principal.subject,
                "status": "待检查",
                "review_status": "pending_review",
            },
            principal.name,
            correction_id,
            principal.subject,
        )
    except (LookupError, ValueError) as exc:
        storage.delete(object_key)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskOwnershipConflict as exc:
        storage.delete(object_key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        storage.delete(object_key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        storage.delete(object_key)
        raise


@router.get("")
def list_documents(
    counterparty_id: str | None = None,
    case_id: str | None = None,
    principal: Principal = Depends(require_permissions("documents:view")),
    repository: DocumentRepository = Depends(get_document_repository),
) -> list[dict]:
    if "client" in principal.roles:
        counterparty_id = principal.counterparty_id
    return repository.list(principal.tenant_id, counterparty_id, case_id)


@router.get("/checklist")
def get_document_checklist(
    counterparty_id: str,
    template_key: str = "general",
    case_id: str | None = None,
    principal: Principal = Depends(require_permissions("documents:view")),
    repository: DocumentRepository = Depends(get_document_repository),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    return build_document_checklist(repository.list(principal.tenant_id, counterparty_id, case_id), template_key)


@router.get("/renewal-carryover")
def get_renewal_document_carryover(
    case_id: str,
    template_key: str = "general",
    principal: Principal = Depends(require_permissions("documents:view")),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    repository: DocumentRepository = Depends(get_document_repository),
) -> dict:
    approval_case, source_case_id = _renewal_document_context(case_id, approval_repository, principal)
    assessment = assess_renewal_document_carryover(
        repository.list(principal.tenant_id, case_id=source_case_id),
        repository.list(principal.tenant_id, case_id=case_id),
        template_key,
    )
    return {
        **assessment,
        "case_id": case_id,
        "source_case_id": source_case_id,
        "counterparty_id": approval_case["counterparty_id"],
    }


@router.post("/renewal-carryover")
def carry_over_renewal_documents(
    request: RenewalDocumentCarryoverRequest,
    principal: Principal = Depends(require_permissions("documents:upload")),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> dict:
    approval_case, source_case_id = _renewal_document_context(request.case_id, approval_repository, principal)
    if approval_case["row_version"] != request.expected_case_row_version:
        raise HTTPException(status_code=409, detail=f"审批记录版本已变化，当前版本为 {approval_case['row_version']}")
    if approval_case["status"] not in {"处理中", "待补件"} or approval_case["current_stage"] not in {"document_upload", "supplement"}:
        raise HTTPException(status_code=409, detail="只有资料上传或补件环节可以承接历史资料")
    assessment = assess_renewal_document_carryover(
        repository.list(principal.tenant_id, case_id=source_case_id),
        repository.list(principal.tenant_id, case_id=request.case_id),
        request.template_key,
    )
    reusable = [item for item in assessment["items"] if item["action"] == "reusable" and item["source_document"]]
    if not reusable:
        if assessment["summary"]["carried_count"]:
            return {
                **assessment,
                "case_id": request.case_id,
                "source_case_id": source_case_id,
                "carried_documents": [],
                "created_count": 0,
                "idempotent": True,
            }
        raise HTTPException(status_code=422, detail="原授信没有符合时效与核验要求的可承接资料")

    copied_objects: list[tuple[str, str]] = []
    metadata_rows = []
    now = datetime.now(timezone.utc)
    try:
        for item in reusable:
            source = item["source_document"]
            try:
                content = storage.get(source["object_key"])
            except FileNotFoundError as exc:
                raise HTTPException(status_code=409, detail=f"来源资料对象不存在：{source['original_name']}") from exc
            if hashlib.sha256(content).hexdigest() != source["sha256"]:
                raise HTTPException(status_code=409, detail=f"来源资料指纹校验失败：{source['original_name']}")
            document_id = str(uuid4())
            suffix = _safe_suffix(source["original_name"])
            object_key = f"{principal.tenant_id}/{approval_case['counterparty_id']}/{document_id}{suffix}"
            storage.put(object_key, content, source["content_type"])
            copied_objects.append((document_id, object_key))
            metadata_rows.append(
                {
                    "id": document_id,
                    "counterparty_id": approval_case["counterparty_id"],
                    "case_id": request.case_id,
                    "document_type": source["document_type"],
                    "original_name": source["original_name"],
                    "object_key": object_key,
                    "content_type": source["content_type"],
                    "size_bytes": source["size_bytes"],
                    "sha256": source["sha256"],
                    "uploaded_by": source["uploaded_by"],
                    "status": "历史可信资料承接",
                    "checklist_json": source["checklist"],
                    "review_status": "verified",
                    "review_comment": f"续授信沿用原核验结论：{source.get('review_comment') or '历史资料已逐项核验通过'}",
                    "reviewed_by": source["reviewed_by"],
                    "reviewed_by_name": source["reviewed_by_name"],
                    "reviewed_at": datetime.fromisoformat(source["reviewed_at"]) if source["reviewed_at"] else now,
                    "source_document_id": source["id"],
                    "source_row_version": source["row_version"],
                    "carried_over_by": principal.name,
                    "carried_over_at": now,
                }
            )
        result = repository.carry_over(principal.tenant_id, metadata_rows, principal.name)
        created_ids = set(result["created_ids"])
        for document_id, object_key in copied_objects:
            if document_id not in created_ids:
                storage.delete(object_key)
        refreshed = assess_renewal_document_carryover(
            repository.list(principal.tenant_id, case_id=source_case_id),
            repository.list(principal.tenant_id, case_id=request.case_id),
            request.template_key,
        )
        return {
            **refreshed,
            "case_id": request.case_id,
            "source_case_id": source_case_id,
            "carried_documents": result["documents"],
            "created_count": len(result["created_ids"]),
            "idempotent": result["idempotent"],
        }
    except HTTPException:
        for _, object_key in copied_objects:
            storage.delete(object_key)
        raise
    except (LookupError, ValueError) as exc:
        for _, object_key in copied_objects:
            storage.delete(object_key)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        for _, object_key in copied_objects:
            storage.delete(object_key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        for _, object_key in copied_objects:
            storage.delete(object_key)
        raise


@router.get("/corrections")
def get_document_corrections(
    counterparty_id: str | None = None,
    case_id: str | None = None,
    principal: Principal = Depends(require_permissions("documents:view")),
    repository: DocumentRepository = Depends(get_document_repository),
) -> list[dict]:
    if "client" in principal.roles:
        counterparty_id = principal.counterparty_id
    if not counterparty_id and not case_id:
        raise HTTPException(status_code=422, detail="补件任务必须指定客商或审批申请")
    if counterparty_id:
        enforce_counterparty_scope(principal, counterparty_id)
    rows = repository.list_corrections(principal.tenant_id, counterparty_id, case_id)
    for row in rows:
        enforce_counterparty_scope(principal, row["counterparty_id"])
    return rows


@router.get("/corrections/{correction_id}/comparison")
def get_document_correction_comparison(
    correction_id: str,
    principal: Principal = Depends(require_permissions("documents:view")),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> dict:
    correction = repository.get_correction(principal.tenant_id, correction_id)
    if not correction:
        raise HTTPException(status_code=404, detail="补件任务不存在")
    enforce_counterparty_scope(principal, correction["counterparty_id"])
    version_ids = correction["version_document_ids"]
    if len(version_ids) < 2:
        raise HTTPException(status_code=422, detail="补件任务尚无可比较的替换版本")
    previous_document = repository.get(principal.tenant_id, version_ids[-2])
    current_document = repository.get(principal.tenant_id, version_ids[-1])
    if not previous_document or not current_document:
        raise HTTPException(status_code=409, detail="补件版本链引用的资料不存在")
    if current_document["id"] != correction["current_document_id"]:
        raise HTTPException(status_code=409, detail="补件当前版本与版本链不一致")
    try:
        counterparty = counterparty_repository.get(
            principal.tenant_id,
            correction["counterparty_id"],
            include_archived=True,
        )
    except CounterpartyError as exc:
        raise HTTPException(status_code=404, detail="客商不存在") from exc
    try:
        previous_content = storage.get(previous_document["object_key"])
    except FileNotFoundError:
        previous_content = b""
    try:
        current_content = storage.get(current_document["object_key"])
    except FileNotFoundError:
        current_content = b""
    return build_document_version_comparison(
        correction,
        previous_document,
        current_document,
        precheck_document(previous_document, previous_content, counterparty),
        precheck_document(current_document, current_content, counterparty),
    )


@router.get("/prechecks")
def get_document_prechecks(
    counterparty_id: str | None = None,
    case_id: str | None = None,
    principal: Principal = Depends(require_permissions("documents:view")),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> list[dict]:
    if "client" in principal.roles:
        counterparty_id = principal.counterparty_id
    if not counterparty_id and not case_id:
        raise HTTPException(status_code=422, detail="资料预检必须指定客商或审批申请")
    if counterparty_id:
        enforce_counterparty_scope(principal, counterparty_id)
    results = []
    for document in repository.list(principal.tenant_id, counterparty_id, case_id):
        enforce_counterparty_scope(principal, document["counterparty_id"])
        try:
            counterparty = counterparty_repository.get(
                principal.tenant_id,
                document["counterparty_id"],
                include_archived=True,
            )
        except CounterpartyError as exc:
            raise HTTPException(status_code=404, detail="客商不存在") from exc
        try:
            content = storage.get(document["object_key"])
        except FileNotFoundError:
            content = b""
        results.append(precheck_document(document, content, counterparty))
    return results


@router.post("/{document_id}/review")
def review_document(
    document_id: str,
    request: DocumentReviewRequest,
    principal: Principal = Depends(require_permissions("documents:review")),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> dict:
    document = repository.get(principal.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    enforce_counterparty_scope(principal, document["counterparty_id"])
    check_definitions = {item["key"]: item for item in DOCUMENT_REVIEW_CHECKS}
    expected_checks = set(check_definitions)
    provided_checks = [item.key for item in request.checks]
    if set(provided_checks) != expected_checks or len(provided_checks) != len(expected_checks):
        raise HTTPException(status_code=422, detail="必须逐项完成全部资料检查项，且不能重复")
    canonical_checks = [
        {
            "key": item.key,
            "label": check_definitions[item.key]["label"],
            "status": item.status,
            "note": item.note,
        }
        for item in request.checks
    ]
    integrity_check = next(item for item in canonical_checks if item["key"] == "integrity")
    try:
        stored_content = storage.get(document["object_key"])
        stored_hash_matches = hashlib.sha256(stored_content).hexdigest() == document["sha256"]
    except FileNotFoundError:
        stored_hash_matches = False
    if integrity_check["status"] == "pass" and not stored_hash_matches:
        raise HTTPException(status_code=409, detail="资料对象不存在或文件指纹已变化，完整性检查不能通过")
    try:
        return repository.review(
            principal.tenant_id,
            document_id,
            request.expected_row_version,
            request.decision,
            request.comment,
            canonical_checks,
            principal.subject,
            principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskOwnershipConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{document_id}/case")
def link_document_to_case(
    document_id: str,
    request: DocumentCaseLinkRequest,
    principal: Principal = Depends(require_permissions("documents:upload")),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    repository: DocumentRepository = Depends(get_document_repository),
) -> dict:
    document = repository.get(principal.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    enforce_counterparty_scope(principal, document["counterparty_id"])
    approval_case = approval_repository.get(principal.tenant_id, request.case_id)
    if not approval_case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    if approval_case["counterparty_id"] != document["counterparty_id"]:
        raise HTTPException(status_code=422, detail="资料所属客商与审批申请不匹配")
    try:
        return repository.link_case(principal.tenant_id, document_id, request.case_id, request.expected_row_version, principal.name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    principal: Principal = Depends(require_permissions("documents:view")),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> Response:
    document = repository.get(principal.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    enforce_counterparty_scope(principal, document["counterparty_id"])
    try:
        content = storage.get(document["object_key"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="资料对象不存在") from exc
    filename = quote(document["original_name"])
    return Response(content=content, media_type=document["content_type"], headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}", "X-Content-SHA256": document["sha256"]})


def _renewal_document_context(
    case_id: str,
    approval_repository: ApprovalCaseRepository,
    principal: Principal,
) -> tuple[dict, str]:
    approval_case = approval_repository.get(principal.tenant_id, case_id)
    if not approval_case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    enforce_counterparty_scope(principal, approval_case["counterparty_id"])
    if approval_case.get("application_type") != "renewal" or not approval_case.get("source_facility_id"):
        raise HTTPException(status_code=422, detail="当前申请不是续授信，不能承接历史资料")
    source_case_id = approval_case.get("data", {}).get("_workflow", {}).get("renewal_request", {}).get("source_case_id")
    if not source_case_id:
        raise HTTPException(status_code=409, detail="续授信缺少原审批血缘，不能承接历史资料")
    source_case = approval_repository.get(principal.tenant_id, source_case_id)
    if not source_case or source_case["counterparty_id"] != approval_case["counterparty_id"]:
        raise HTTPException(status_code=409, detail="续授信原审批不存在或主体不一致")
    return approval_case, source_case_id


def _safe_suffix(filename: str) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix if suffix in {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx", ".txt"} else ""


def _matches_declared_type(content_type: str, suffix: str, content: bytes) -> bool:
    checks = {
        "application/pdf": ({".pdf"}, lambda value: value.startswith(b"%PDF-")),
        "image/png": ({".png"}, lambda value: value.startswith(b"\x89PNG\r\n\x1a\n")),
        "image/jpeg": ({".jpg", ".jpeg"}, lambda value: value.startswith(b"\xff\xd8\xff")),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ({".docx"}, lambda value: _has_zip_members(value, {"[Content_Types].xml", "word/document.xml"})),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ({".xlsx"}, lambda value: _has_zip_members(value, {"[Content_Types].xml", "xl/workbook.xml"})),
        "text/plain": ({".txt"}, lambda value: b"\x00" not in value[:4096]),
    }
    allowed_suffixes, signature_check = checks[content_type]
    return suffix in allowed_suffixes and signature_check(content)


def _has_zip_members(content: bytes, required_members: set[str]) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return required_members.issubset(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False
