from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.dependencies import get_demo_repository, get_model_governance_repository
from backend.repository import DemoRepository, ModelGovernanceRepository
from backend.sales_demo import (
    build_sales_demo_brief,
    build_sales_demo_champion_challenger,
    build_sales_demo_overview,
    build_sales_demo_pilot_package,
    build_sales_demo_post_credit_alert,
    build_sales_demo_run,
    build_sales_demo_value_dashboard,
)
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/sales-demo", tags=["sales-demo"])


@router.get("/overview")
def get_sales_demo_overview(
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    return build_sales_demo_overview(demo_repository, model_repository)


@router.get("/value-dashboard")
def get_sales_demo_value_dashboard(
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    try:
        return build_sales_demo_value_dashboard(demo_repository, model_repository)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/showcases/champion-challenger")
def get_sales_demo_champion_challenger(
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    try:
        return build_sales_demo_champion_challenger(demo_repository, model_repository)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/showcases/post-credit-alert")
def get_sales_demo_post_credit_alert(
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    try:
        return build_sales_demo_post_credit_alert(demo_repository, model_repository)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/pilot-package")
def download_sales_demo_pilot_package(
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> Response:
    try:
        package_bytes, manifest = build_sales_demo_pilot_package(demo_repository, model_repository)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = "enterprise-credit-platform-roadshow-pilot-package.zip"
    disposition = f"attachment; filename=roadshow-pilot-package.zip; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=package_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": disposition,
            "X-Evidence-Hash": manifest["manifest_hash"],
            "X-Package-Hash": manifest["package_hash"],
        },
    )


@router.get("/scenarios/{scenario_key}")
def get_sales_demo_scenario(
    scenario_key: str,
    story: str | None = Query(default=None),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    try:
        return build_sales_demo_run(scenario_key, story, demo_repository, model_repository)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "不存在" in str(exc) else 422, detail=str(exc)) from exc


@router.get("/scenarios/{scenario_key}/brief")
def download_sales_demo_brief(
    scenario_key: str,
    story: str | None = Query(default=None),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> Response:
    try:
        run = build_sales_demo_run(scenario_key, story, demo_repository, model_repository)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "不存在" in str(exc) else 422, detail=str(exc)) from exc
    filename = f"{scenario_key}-{run['story']['key']}-executive-brief.md"
    disposition = f"attachment; filename=executive-brief.md; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=build_sales_demo_brief(run),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": disposition, "X-Evidence-Hash": run["evidence"]["evidence_hash"]},
    )
