from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_decision_governance_repository
from backend.repository import DecisionGovernanceRepository
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/decision-governance", tags=["decision-governance"])
DIRECTIONS = {"aligned", "stricter", "relaxed", "mixed", "rejected"}
MATERIALITIES = {"none", "minor", "material"}


@router.get("/variances")
def list_decision_variances(
    case_id: str | None = None,
    direction: str | None = None,
    materiality: str | None = None,
    repository: DecisionGovernanceRepository = Depends(get_decision_governance_repository),
    principal: Principal = Depends(require_permissions("decisions:view")),
) -> list[dict]:
    if direction and direction not in DIRECTIONS:
        raise HTTPException(status_code=422, detail="不支持的偏差方向")
    if materiality and materiality not in MATERIALITIES:
        raise HTTPException(status_code=422, detail="不支持的重要性等级")
    return repository.list(principal.tenant_id, case_id=case_id, direction=direction, materiality=materiality)


@router.get("/summary")
def get_decision_governance_summary(
    repository: DecisionGovernanceRepository = Depends(get_decision_governance_repository),
    principal: Principal = Depends(require_permissions("decisions:view")),
) -> dict:
    return repository.summary(principal.tenant_id)
