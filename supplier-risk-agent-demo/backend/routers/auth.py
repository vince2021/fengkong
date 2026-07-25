from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.security import Principal, get_current_principal


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me")
def current_user(principal: Principal = Depends(get_current_principal)) -> dict:
    return {"subject": principal.subject, "name": principal.name, "roles": principal.roles, "permissions": sorted(principal.permissions), "counterparty_id": principal.counterparty_id}
