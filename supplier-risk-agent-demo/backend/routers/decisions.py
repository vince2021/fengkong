"""Customer integration endpoints for immutable synchronous decisions."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.database import get_db_session
from backend.decision_api import (
    DecisionApiError,
    DecisionExecutionRepository,
    execute_decision,
    get_decision_contract,
    get_sandbox_package,
    serialize_execution,
)
from backend.counterparty_repository import CounterpartyRepository
from backend.dependencies import get_counterparty_repository, get_demo_repository, get_model_governance_repository
from backend.repository import DemoRepository, ModelGovernanceRepository
from backend.schemas import DecisionExecuteRequest
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/decisions", tags=["decision-api"])


@router.post("")
def run_decision(
    body: dict,
    session: Session = Depends(get_db_session),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("decision_api:execute")),
):
    try:
        request = DecisionExecuteRequest.model_validate(body)
        response, _ = execute_decision(request, session, demo_repository, counterparty_repository, governance, principal)
        return response
    except ValidationError as exc:
        return _error_response(
            DecisionApiError(
                "DECISION_REQUEST_INVALID",
                "请求契约校验失败",
                422,
                {"validation_errors": exc.errors(include_url=False, include_context=False)},
            )
        )
    except DecisionApiError as exc:
        return _error_response(exc)
    except Exception:
        session.rollback()
        return _error_response(
            DecisionApiError(
                "DECISION_EXECUTION_FAILED",
                "决策执行发生未预期错误，请使用 trace_id 联系平台运维",
                500,
            )
        )


@router.get("/contract")
def decision_contract(
    session: Session = Depends(get_db_session),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("decision_api:view")),
) -> dict:
    return get_decision_contract(session, demo_repository, principal.tenant_id)


@router.get("/sandbox")
def decision_sandbox(
    session: Session = Depends(get_db_session),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("decision_api:view")),
) -> dict:
    contract = get_decision_contract(session, demo_repository, principal.tenant_id)
    return get_sandbox_package(demo_repository, contract)


@router.get("/{request_id}")
def get_decision(
    request_id: str,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("decision_api:view")),
):
    record = DecisionExecutionRepository(session).get_by_request_id(principal.tenant_id, request_id)
    if record is None:
        return _error_response(
            DecisionApiError(
                "DECISION_NOT_FOUND",
                "决策请求记录不存在",
                404,
                {"tenant_id": principal.tenant_id, "request_id": request_id},
            )
        )
    return serialize_execution(record)


def _error_response(error: DecisionApiError) -> JSONResponse:
    trace_id = str(error.details.get("trace_id") or uuid4())
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "trace_id": trace_id,
                "details": error.details,
            }
        },
    )
