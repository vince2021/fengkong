"""Batch Decision API, webhook evidence, and customer integration endpoints."""
from __future__ import annotations

import csv
import io
import json
import zipfile

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.counterparty_repository import CounterpartyRepository
from backend.database import get_db_session
from backend.decision_api import DecisionApiError
from backend.decision_jobs import DecisionJobRepository, client_profile, preview_field_mapping, serialize_job
from backend.dependencies import get_counterparty_repository, get_demo_repository, get_model_governance_repository
from backend.repository import DemoRepository, ModelGovernanceRepository
from backend.schemas import DecisionFieldMappingPreview, DecisionJobCreate
from backend.security import Principal, require_permissions


router = APIRouter(tags=["decision-jobs"])


@router.post("/decision-jobs", status_code=202)
def create_decision_job(
    body: dict,
    session: Session = Depends(get_db_session),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("decision_api:execute")),
):
    try:
        payload = DecisionJobCreate.model_validate(body)
        result, _ = DecisionJobRepository(session).create(payload, principal, demo_repository)
        return result
    except ValidationError as exc:
        return _error_response(
            DecisionApiError(
                "DECISION_JOB_REQUEST_INVALID", "批量任务契约校验失败", 422,
                {"validation_errors": exc.errors(include_url=False, include_context=False)},
            )
        )
    except DecisionApiError as exc:
        return _error_response(exc)


@router.get("/decision-jobs")
def list_decision_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:view")),
) -> list[dict]:
    return DecisionJobRepository(session).list(principal, limit)


@router.get("/decision-jobs/{job_id}")
def get_decision_job(
    job_id: str,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:view")),
):
    try:
        return serialize_job(DecisionJobRepository(session).get(job_id, principal))
    except DecisionApiError as exc:
        return _error_response(exc)


@router.post("/decision-jobs/{job_id}/run")
def run_decision_job(
    job_id: str,
    session: Session = Depends(get_db_session),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("decision_api:execute")),
):
    try:
        return DecisionJobRepository(session).run(job_id, principal, demo_repository, counterparty_repository, governance)
    except DecisionApiError as exc:
        return _error_response(exc)
    except Exception:
        session.rollback()
        return _error_response(DecisionApiError("DECISION_JOB_EXECUTION_FAILED", "批量决策任务执行失败", 500))


@router.get("/decision-jobs/{job_id}/results.csv")
def download_decision_job_results(
    job_id: str,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:view")),
):
    try:
        job = DecisionJobRepository(session).get(job_id, principal)
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["index", "request_id", "outcome", "counterparty_id", "rating", "final_admission", "total_score", "trace_id", "evidence_hash", "idempotent", "error_code", "error_message"],
        )
        writer.writeheader()
        rows = [
            {**item, "outcome": "success", "error_code": "", "error_message": ""}
            for item in (job.results_json or [])
        ]
        rows.extend(
            {"index": item["index"], "request_id": item["request_id"], "outcome": "failed", "error_code": item["code"], "error_message": item["message"]}
            for item in (job.failures_json or [])
        )
        writer.writerows(sorted(rows, key=lambda item: item["index"]))
        content = "\ufeff" + output.getvalue()
        return Response(
            content=content.encode("utf-8"), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{job.job_key}-results.csv"'},
        )
    except DecisionApiError as exc:
        return _error_response(exc)


@router.get("/decision-jobs/{job_id}/webhooks")
def list_decision_job_webhooks(
    job_id: str,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:view")),
):
    try:
        return DecisionJobRepository(session).list_webhooks(job_id, principal)
    except DecisionApiError as exc:
        return _error_response(exc)


@router.post("/decision-webhooks/{delivery_id}/retry")
def retry_decision_webhook(
    delivery_id: str,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:execute")),
):
    try:
        return DecisionJobRepository(session).retry_webhook(delivery_id, principal)
    except DecisionApiError as exc:
        return _error_response(exc)


@router.post("/decision-webhooks/{delivery_id}/redeliver")
def redeliver_decision_webhook(
    delivery_id: str,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:execute")),
):
    try:
        return DecisionJobRepository(session).retry_webhook(delivery_id, principal, redeliver=True)
    except DecisionApiError as exc:
        return _error_response(exc)


@router.get("/decisions/client-profile")
def get_decision_client_profile(
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:view")),
) -> dict:
    return client_profile(principal, session)


@router.post("/decisions/field-mapping/preview")
def field_mapping_preview(
    body: dict,
    _: Principal = Depends(require_permissions("decision_api:execute")),
):
    try:
        return preview_field_mapping(DecisionFieldMappingPreview.model_validate(body))
    except ValidationError as exc:
        return _error_response(
            DecisionApiError(
                "FIELD_MAPPING_REQUEST_INVALID", "字段映射预检契约校验失败", 422,
                {"validation_errors": exc.errors(include_url=False, include_context=False)},
            )
        )


@router.get("/decisions/integration-kit")
def download_integration_kit(
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:view")),
) -> Response:
    profile = client_profile(principal, session)
    readme = f"""# 恒信决策 API 沙箱接入包

环境：sandbox
租户：{profile['tenant_id']}
客户端：{profile['client_id']}

1. 使用 `POST /api/v1/decisions` 完成单笔联调。
2. 使用 `POST /api/v1/decision-jobs` 创建批量任务，再调用 `/run`。
3. Webhook 使用 HMAC-SHA256 校验，签名原文为 `timestamp.canonical_json_body`。
4. 沙箱不包含、展示或下载任何生产密钥。
"""
    collection = {
        "info": {"name": "Hengxin Decision API Sandbox", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "variable": [{"key": "baseUrl", "value": "http://127.0.0.1:8000/api/v1"}, {"key": "token", "value": "dev-integration"}],
        "item": [
            {"name": "Get contract", "request": {"method": "GET", "header": [{"key": "Authorization", "value": "Bearer {{token}}"}], "url": "{{baseUrl}}/decisions/contract"}},
            {"name": "List jobs", "request": {"method": "GET", "header": [{"key": "Authorization", "value": "Bearer {{token}}"}], "url": "{{baseUrl}}/decision-jobs"}},
        ],
    }
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", readme)
        archive.writestr("postman_collection.json", json.dumps(collection, ensure_ascii=False, indent=2))
        archive.writestr("client_profile.json", json.dumps(profile, ensure_ascii=False, indent=2))
    return Response(
        content=memory.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="hengxin-decision-api-sandbox-kit.zip"'},
    )


def _error_response(error: DecisionApiError) -> JSONResponse:
    from uuid import uuid4

    trace_id = str(error.details.get("trace_id") or uuid4())
    headers = {}
    if error.status_code == 429:
        headers["Retry-After"] = str(error.details.get("retry_after_seconds", 1))
    return JSONResponse(
        status_code=error.status_code, headers=headers,
        content={"error": {"code": error.code, "message": error.message, "trace_id": trace_id, "details": error.details}},
    )
