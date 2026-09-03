from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import AUTO_CREATE_SCHEMA, initialize_database
from backend.routers import approvals, audit, auth, authority_policies, counterparties, credit_facilities, credit_reports, decision_governance, documents, enterprise_data, health, indicator_center, indicator_observations, model_governance, models, notifications, operations, rule_center
from backend.security import validate_security_configuration


validate_security_configuration()
if AUTO_CREATE_SCHEMA:
    initialize_database()


app = FastAPI(
    title="客商信用风险平台 API",
    description="客户/供应商准入、评级、审批、额度策略与模型影响分析接口。",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"^http://(?:127\.0\.0\.1|localhost):(?:300\d|51\d{2})$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(counterparties.router, prefix=API_PREFIX)
app.include_router(models.router, prefix=API_PREFIX)
app.include_router(approvals.router, prefix=API_PREFIX)
app.include_router(authority_policies.router, prefix=API_PREFIX)
app.include_router(audit.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(documents.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(operations.router, prefix=API_PREFIX)
app.include_router(model_governance.router, prefix=API_PREFIX)
app.include_router(credit_facilities.router, prefix=API_PREFIX)
app.include_router(credit_reports.router, prefix=API_PREFIX)
app.include_router(decision_governance.router, prefix=API_PREFIX)
app.include_router(enterprise_data.router, prefix=API_PREFIX)
app.include_router(indicator_observations.router, prefix=API_PREFIX)
app.include_router(indicator_center.router, prefix=API_PREFIX)
app.include_router(rule_center.router, prefix=API_PREFIX)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"service": "supplier-risk-api", "docs": "/docs", "health": f"{API_PREFIX}/health"}
