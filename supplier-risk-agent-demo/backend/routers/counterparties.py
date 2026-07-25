from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_demo_repository
from backend.repository import DemoRepository
from backend.security import Principal, enforce_counterparty_scope, require_permissions


router = APIRouter(prefix="/counterparties", tags=["counterparties"])


@router.get("")
def list_counterparties(
    repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> list[dict]:
    return repository.list_counterparties()


@router.get("/{counterparty_id}")
def get_counterparty(
    counterparty_id: str,
    repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> dict:
    counterparty = repository.get_counterparty(counterparty_id)
    if not counterparty:
        raise HTTPException(status_code=404, detail="客商不存在")
    enforce_counterparty_scope(principal, counterparty_id)
    return counterparty


@router.get("/{counterparty_id}/raw-profile")
def get_counterparty_raw_profile(
    counterparty_id: str,
    repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> dict:
    counterparty = repository.get_counterparty(counterparty_id)
    if not counterparty:
        raise HTTPException(status_code=404, detail="客商不存在")
    enforce_counterparty_scope(principal, counterparty_id)
    profile = repository.get_raw_profile(counterparty_id)
    if not profile:
        raise HTTPException(status_code=404, detail="当前客商暂无材料提炼原始数据")
    return {
        **profile,
        "counterparty_id": counterparty_id,
        "recommended_model": counterparty.get("data_quality", {}).get("recommended_model", "general"),
        "missing_critical_fields": counterparty.get("data_quality", {}).get("missing_critical_fields", []),
    }
