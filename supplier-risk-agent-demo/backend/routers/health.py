from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "supplier-risk-api", "api_version": "v1"}
