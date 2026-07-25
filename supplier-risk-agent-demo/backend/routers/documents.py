from __future__ import annotations

import hashlib
import io
import zipfile
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.dependencies import get_approval_repository, get_demo_repository, get_document_repository, get_object_storage
from backend.document_policy import ALLOWED_DOCUMENT_TYPES, DOCUMENT_REVIEW_CHECKS, build_document_checklist
from backend.document_precheck import precheck_document
from backend.repository import ApprovalCaseRepository, DemoRepository, DocumentRepository
from backend.repository import ConcurrentUpdateError
from backend.schemas import DocumentCaseLinkRequest, DocumentReviewRequest
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
    demo_repository: DemoRepository = Depends(get_demo_repository),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    if not demo_repository.get_counterparty(counterparty_id):
        raise HTTPException(status_code=404, detail="客商不存在")
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(status_code=422, detail="资料类型不在允许清单中")
    if correction_id:
        correction = repository.get_correction(correction_id)
        if not correction:
            raise HTTPException(status_code=404, detail="补件任务不存在")
        enforce_counterparty_scope(principal, correction["counterparty_id"])
        if correction["status"] != "open":
            raise HTTPException(status_code=422, detail="补件任务当前不允许上传替换资料")
        if correction["counterparty_id"] != counterparty_id or correction["case_id"] != case_id or correction["document_type"] != document_type:
            raise HTTPException(status_code=422, detail="替换资料与补件任务的企业、审批单或资料类型不匹配")
    if case_id:
        approval_case = approval_repository.get(case_id)
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
    object_key = f"{counterparty_id}/{document_id}{suffix}"
    digest = hashlib.sha256(content).hexdigest()
    storage.put(object_key, content, content_type)
    try:
        return repository.create(
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
        )
    except (LookupError, ValueError) as exc:
        storage.delete(object_key)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    return repository.list(counterparty_id, case_id)


@router.get("/checklist")
def get_document_checklist(
    counterparty_id: str,
    template_key: str = "general",
    case_id: str | None = None,
    principal: Principal = Depends(require_permissions("documents:view")),
    repository: DocumentRepository = Depends(get_document_repository),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    return build_document_checklist(repository.list(counterparty_id, case_id), template_key)


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
    rows = repository.list_corrections(counterparty_id, case_id)
    for row in rows:
        enforce_counterparty_scope(principal, row["counterparty_id"])
    return rows


@router.get("/prechecks")
def get_document_prechecks(
    counterparty_id: str | None = None,
    case_id: str | None = None,
    principal: Principal = Depends(require_permissions("documents:view")),
    demo_repository: DemoRepository = Depends(get_demo_repository),
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
    for document in repository.list(counterparty_id, case_id):
        enforce_counterparty_scope(principal, document["counterparty_id"])
        try:
            content = storage.get(document["object_key"])
        except FileNotFoundError:
            content = b""
        results.append(precheck_document(document, content, demo_repository.get_counterparty(document["counterparty_id"])))
    return results


@router.post("/{document_id}/review")
def review_document(
    document_id: str,
    request: DocumentReviewRequest,
    principal: Principal = Depends(require_permissions("documents:review")),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> dict:
    document = repository.get(document_id)
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
    document = repository.get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    enforce_counterparty_scope(principal, document["counterparty_id"])
    approval_case = approval_repository.get(request.case_id)
    if not approval_case:
        raise HTTPException(status_code=404, detail="审批申请不存在")
    if approval_case["counterparty_id"] != document["counterparty_id"]:
        raise HTTPException(status_code=422, detail="资料所属客商与审批申请不匹配")
    try:
        return repository.link_case(document_id, request.case_id, request.expected_row_version, principal.name)
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
    document = repository.get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    enforce_counterparty_scope(principal, document["counterparty_id"])
    try:
        content = storage.get(document["object_key"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="资料对象不存在") from exc
    filename = quote(document["original_name"])
    return Response(content=content, media_type=document["content_type"], headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}", "X-Content-SHA256": document["sha256"]})


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
