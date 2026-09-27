from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.database import get_db_session
from backend.tenant_registry import TenantAccessError, TenantRegistry


AUTH_MODE = os.getenv("AUTH_MODE", "dev").lower()
APP_ENV = os.getenv("APP_ENV", "development").lower()
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "risk-platform-api")
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", f"{OIDC_ISSUER.rstrip('/')}/protocol/openid-connect/certs" if OIDC_ISSUER else "")


ROLE_PERMISSIONS = {
    "client": {"counterparties:view", "documents:upload", "documents:view", "approvals:view", "approvals:act", "notifications:view", "notifications:act", "facilities:view", "indicator_data:view", "indicator_data:manage"},
    "relationship_manager": {"counterparties:view", "counterparties:manage", "counterparties:imports:view", "governance_evidence:view", "documents:upload", "documents:view", "approvals:create", "approvals:view", "approvals:act", "ratings:run", "ratings:view", "models:view", "notifications:view", "notifications:act", "facilities:view", "facilities:transact", "risk_events:create", "reports:view", "data_governance:view", "data_governance:import", "data_governance:resolve", "indicator_data:view", "indicator_data:manage", "authority_policy:view", "decision_api:view", "decision_api:execute"},
    "risk_manager": {"counterparties:view", "counterparties:imports:view", "governance_evidence:view", "documents:view", "documents:review", "approvals:view", "approvals:act", "ratings:run", "ratings:view", "models:view", "models:review", "tenant_assets:view", "tenant_assets:review", "audit:view", "notifications:view", "notifications:act", "notification_channels:view", "notification_channels:manage", "operations:view", "facilities:view", "facilities:review", "facilities:scan", "facilities:control", "facility_alerts:act", "risk_events:create", "reports:view", "reports:generate", "decisions:view", "data_governance:view", "data_governance:import", "data_governance:resolve", "data_governance:review", "indicator_data:view", "indicator_data:manage", "indicator_data:review", "authority_policy:view", "authority_policy:review", "authority_policy:anchor", "authority_policy:anchor_revoke", "decision_api:view", "decision_api:execute"},
    "model_admin": {"counterparties:view", "approvals:view", "approvals:act", "ratings:run", "ratings:view", "models:view", "models:manage", "models:scan", "tenant_assets:view", "tenant_assets:manage", "notifications:view", "notifications:act", "notification_channels:view", "notification_channels:manage", "data_governance:view", "indicator_data:view", "indicator_data:manage", "authority_policy:view", "authority_policy:manage", "decision_api:view", "decision_api:execute"},
    "approver": {"counterparties:view", "governance_evidence:view", "documents:view", "documents:review", "approvals:view", "approvals:act", "ratings:view", "models:view", "tenant_assets:view", "tenant_assets:review", "notifications:view", "notifications:act", "facilities:view", "facilities:control", "facility_alerts:act", "reports:view", "reports:generate", "decisions:view", "data_governance:view", "data_governance:review", "indicator_data:view", "indicator_data:review", "authority_policy:view", "authority_policy:manage", "authority_policy:review"},
    "auditor": {"counterparties:view", "counterparties:imports:view", "governance_evidence:view", "documents:view", "approvals:view", "ratings:view", "models:view", "tenant_assets:view", "audit:view", "operations:view", "facilities:view", "reports:view", "decisions:view", "data_governance:view", "indicator_data:view", "authority_policy:view", "authority_policy:anchor", "authority_policy:anchor_revoke", "decision_api:view"},
    "integration_admin": {"counterparties:view", "models:view", "models:scan", "notification_channels:view", "notification_channels:manage", "decision_api:view", "decision_api:execute"},
    "operations": {"approvals:view", "audit:view", "notifications:view", "notifications:act", "notification_channels:view", "notification_channels:manage", "operations:view", "sla:scan", "corrections:act", "tasks:manage", "facilities:view", "facilities:transact", "facilities:scan", "facility_alerts:act", "risk_events:create"},
    "admin": {"*", "tenant_admin:view", "tenant_admin:manage", "tenant_assets:view", "tenant_assets:manage", "tenant_assets:review"},
}

APPROVAL_STAGE_ROLES = {
    "registration": {"relationship_manager"},
    "document_upload": {"client", "relationship_manager"},
    "supplement": {"client", "relationship_manager"},
    "approval_submit": {"relationship_manager"},
    "model_selection": {"risk_manager", "model_admin"},
    "scoring": {"risk_manager", "model_admin"},
    "credit_proposal": {"approver"},
    "final_strategy": {"approver"},
}


DEV_PRINCIPALS = {
    "dev-client": {"sub": "client-demo", "name": "演示客户", "roles": ["client"], "tenant_id": "tenant-demo-hengxin", "client_id": "customer-portal", "counterparty_id": "cp_supplier_low_001"},
    "dev-manager": {"sub": "manager-demo", "name": "客户经理", "roles": ["relationship_manager"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-manager-peer": {"sub": "manager-peer-demo", "name": "客户经理乙", "roles": ["relationship_manager"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-risk": {"sub": "risk-demo", "name": "风控经理", "roles": ["risk_manager"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-model-admin": {"sub": "model-demo", "name": "模型管理员", "roles": ["model_admin"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-approver": {"sub": "approver-demo", "name": "授信审批人", "roles": ["approver"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-approver-peer": {"sub": "approver-peer-demo", "name": "授信审批人乙", "roles": ["approver"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-auditor": {"sub": "auditor-demo", "name": "审计人员", "roles": ["auditor"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-operations": {"sub": "operations-demo", "name": "运营值班", "roles": ["operations"], "tenant_id": "tenant-demo-hengxin", "client_id": "platform-console"},
    "dev-integration": {"sub": "integration-demo", "name": "集成管理员", "roles": ["integration_admin"], "tenant_id": "tenant-demo-hengxin", "client_id": "erp-integration-sandbox"},
    "dev-integration-alt": {"sub": "integration-alt-demo", "name": "另一租户集成管理员", "roles": ["integration_admin"], "tenant_id": "tenant-demo-alt", "client_id": "erp-alt-sandbox"},
    "dev-admin": {"sub": "admin-demo", "name": "平台管理员", "roles": ["admin"], "tenant_id": "tenant-platform-internal", "client_id": "platform-console"},
    "dev-admin-reviewer": {"sub": "admin-reviewer-demo", "name": "平台复核人", "roles": ["admin"], "tenant_id": "tenant-platform-internal", "client_id": "platform-console"},
}


TENANT_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    client_id: str
    subject: str


@dataclass(frozen=True)
class Principal:
    subject: str
    name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    tenant_id: str
    client_id: str
    counterparty_id: str | None = None

    def can(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(tenant_id=self.tenant_id, client_id=self.client_id, subject=self.subject)


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
) -> Principal:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少访问令牌", headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    claims = _decode_dev_token(token) if AUTH_MODE == "dev" else _decode_oidc_token(token)
    roles = tuple(_extract_roles(claims))
    permissions = frozenset(permission for role in roles for permission in ROLE_PERMISSIONS.get(role, set()))
    tenant_id = _required_scope_identifier(claims, "tenant_id")
    client_id = _scope_identifier(claims.get("client_id") or claims.get("azp") or claims.get("sub"), "client_id")
    subject = str(claims.get("sub", ""))
    try:
        TenantRegistry(session).authorize(tenant_id, client_id, subject, roles)
    except TenantAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return Principal(
        subject=subject,
        name=str(claims.get("name") or claims.get("preferred_username") or claims.get("sub", "")),
        roles=roles,
        permissions=permissions,
        tenant_id=tenant_id,
        client_id=client_id,
        counterparty_id=claims.get("counterparty_id"),
    )


def require_permissions(*required: str):
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        missing = [permission for permission in required if not principal.can(permission)]
        if missing:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"无权执行当前操作，缺少权限：{', '.join(missing)}")
        return principal

    return dependency


def enforce_counterparty_scope(principal: Principal, counterparty_id: str) -> None:
    if "client" in principal.roles and principal.counterparty_id != counterparty_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="客户账号只能访问本企业数据")


def enforce_approval_stage_role(principal: Principal, stage: str) -> None:
    if "admin" in principal.roles:
        return
    allowed_roles = APPROVAL_STAGE_ROLES.get(stage, set())
    if not allowed_roles.intersection(principal.roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"当前角色无权处理审批环节：{stage}")


def validate_security_configuration(
    app_env: str = APP_ENV,
    auth_mode: str = AUTH_MODE,
    oidc_issuer: str = OIDC_ISSUER,
    oidc_jwks_url: str = OIDC_JWKS_URL,
) -> None:
    if app_env == "production" and auth_mode == "dev":
        raise RuntimeError("生产环境禁止使用开发令牌认证")
    if auth_mode == "oidc" and (not oidc_issuer or not oidc_jwks_url):
        raise RuntimeError("OIDC 模式必须配置 issuer 和 JWKS URL")


def _decode_dev_token(token: str) -> dict:
    claims = DEV_PRINCIPALS.get(token)
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="开发访问令牌无效", headers={"WWW-Authenticate": "Bearer"})
    return claims


def _decode_oidc_token(token: str) -> dict:
    if not OIDC_ISSUER or not OIDC_JWKS_URL:
        raise HTTPException(status_code=500, detail="OIDC 认证参数未配置")
    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, algorithms=["RS256", "ES256"], audience=OIDC_AUDIENCE, issuer=OIDC_ISSUER)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问令牌校验失败", headers={"WWW-Authenticate": "Bearer"}) from exc


@lru_cache(maxsize=1)
def _get_jwk_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(OIDC_JWKS_URL)


def _extract_roles(claims: dict) -> list[str]:
    roles = _as_role_list(claims.get("roles", []))
    roles.extend(_as_role_list(claims.get("realm_access", {}).get("roles", [])))
    client_roles = claims.get("resource_access", {}).get(OIDC_AUDIENCE, {}).get("roles", [])
    roles.extend(_as_role_list(client_roles))
    return sorted(set(role for role in roles if role in ROLE_PERMISSIONS))


def _as_role_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return []


def _required_scope_identifier(claims: dict, claim_name: str) -> str:
    if claim_name not in claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"访问令牌缺少必需的 {claim_name} 声明",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _scope_identifier(claims.get(claim_name), claim_name)


def _scope_identifier(value: object, claim_name: str) -> str:
    identifier = str(value or "").strip()
    if not TENANT_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"访问令牌中的 {claim_name} 声明无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identifier
