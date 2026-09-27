from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.dependencies import get_counterparty_governance_evidence_repository
from backend.governance_evidence import CounterpartyGovernanceEvidenceRepository, GovernanceEvidenceError, verify_counterparty_governance_evidence_package
from backend.security import Principal, enforce_counterparty_scope, require_permissions


router = APIRouter(prefix="/governance-evidence", tags=["governance-evidence"])


class EvidenceVerificationRequest(BaseModel):
    package: dict
    expected_package_hash: str | None = Field(default=None, min_length=64, max_length=64)


@router.get("/counterparties/{counterparty_id}")
def counterparty_evidence(
    counterparty_id: str,
    repository: CounterpartyGovernanceEvidenceRepository = Depends(get_counterparty_governance_evidence_repository),
    principal: Principal = Depends(require_permissions("governance_evidence:view")),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    try:
        return repository.build(principal.tenant_id, counterparty_id)
    except GovernanceEvidenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/counterparties/{counterparty_id}/download")
def download_counterparty_evidence(
    counterparty_id: str,
    repository: CounterpartyGovernanceEvidenceRepository = Depends(get_counterparty_governance_evidence_repository),
    principal: Principal = Depends(require_permissions("governance_evidence:view")),
) -> Response:
    package = counterparty_evidence(counterparty_id, repository, principal)
    filename = f"counterparty-governance-evidence-{counterparty_id}.json"
    return Response(
        json.dumps(package, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/verify")
def verify_counterparty_evidence(
    request: EvidenceVerificationRequest,
    _: Principal = Depends(require_permissions("governance_evidence:view")),
) -> dict:
    return verify_counterparty_governance_evidence_package(request.package, request.expected_package_hash)
