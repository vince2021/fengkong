from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


AUTH_MODE = os.getenv("AUTH_MODE", "dev").lower()
APP_ENV = os.getenv("APP_ENV", "development").lower()
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "risk-platform-api")
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", f"{OIDC_ISSUER.rstrip('/')}/protocol/openid-connect/certs" if OIDC_ISSUER else "")


ROLE_PERMISSIONS = {
    "client": {"documents:upload", "documents:view", "approvals:view", "approvals:act", "notifications:view", "notifications:act", "facilities:view", "indicator_data:view", "indicator_data:manage"},
    "relationship_manager": {"counterparties:view", "documents:upload", "documents:view", "approvals:create", "approvals:view", "approvals:act", "ratings:run", "ratings:view", "models:view", "notifications:view", "notifications:act", "facilities:view", "facilities:transact", "risk_events:create", "reports:view", "data_governance:view", "data_governance:import", "data_governance:resolve", "indicator_data:view", "indicator_data:manage", "authority_policy:view"},
    "risk_manager": {"counterparties:view", "documents:view", "documents:review", "approvals:view", "approvals:act", "ratings:run", "ratings:view", "models:view", "models:review", "audit:view", "notifications:view", "notifications:act", "operations:view", "facilities:view", "facilities:review", "facilities:scan", "facilities:control", "facility_alerts:act", "risk_events:create", "reports:view", "reports:generate", "decisions:view", "data_governance:view", "data_governance:import", "data_governance:resolve", "data_governance:review", "indicator_data:view", "indicator_data:manage", "indicator_data:review", "authority_policy:view", "authority_policy:review", "authority_policy:anchor", "authority_policy:anchor_revoke"},
    "model_admin": {"counterparties:view", "approvals:view", "approvals:act", "ratings:run", "ratings:view", "models:view", "models:manage", "notifications:view", "notifications:act", "data_governance:view", "indicator_data:view", "indicator_data:manage", "authority_policy:view", "authority_policy:manage"},
    "approver": {"counterparties:view", "documents:view", "documents:review", "approvals:view", "approvals:act", "ratings:view", "models:view", "notifications:view", "notifications:act", "facilities:view", "facilities:control", "facility_alerts:act", "reports:view", "reports:generate", "decisions:view", "data_governance:view", "data_governance:review", "indicator_data:view", "indicator_data:review", "authority_policy:view", "authority_policy:manage", "authority_policy:review"},
    "auditor": {"counterparties:view", "documents:view", "approvals:view", "ratings:view", "models:view", "audit:view", "operations:view", "facilities:view", "reports:view", "decisions:view", "data_governance:view", "indicator_data:view", "authority_policy:view", "authority_policy:anchor", "authority_policy:anchor_revoke"},
    "operations": {"approvals:view", "audit:view", "notifications:view", "notifications:act", "operations:view", "sla:scan", "corrections:act", "tasks:manage", "facilities:view", "facilities:transact", "facilities:scan", "facility_alerts:act", "risk_events:create"},
    "admin": {"*"},
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
    "dev-client": {"sub": "client-demo", "name": "演示客户", "roles": ["client"], "counterparty_id": "cp_supplier_low_001"},
    "dev-manager": {"sub": "manager-demo", "name": "客户经理", "roles": ["relationship_manager"]},
    "dev-manager-peer": {"sub": "manager-peer-demo", "name": "客户经理乙", "roles": ["relationship_manager"]},
    "dev-risk": {"sub": "risk-demo", "name": "风控经理", "roles": ["risk_manager"]},
    "dev-model-admin": {"sub": "model-demo", "name": "模型管理员", "roles": ["model_admin"]},
    "dev-approver": {"sub": "approver-demo", "name": "授信审批人", "roles": ["approver"]},
    "dev-approver-peer": {"sub": "approver-peer-demo", "name": "授信审批人乙", "roles": ["approver"]},
    "dev-auditor": {"sub": "auditor-demo", "name": "审计人员", "roles": ["auditor"]},
    "dev-operations": {"sub": "operations-demo", "name": "运营值班", "roles": ["operations"]},
    "dev-admin": {"sub": "admin-demo", "name": "平台管理员", "roles": ["admin"]},
}


@dataclass(frozen=True)
class Principal:
    subject: str
    name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    counterparty_id: str | None = None

    def can(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> Principal:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少访问令牌", headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    claims = _decode_dev_token(token) if AUTH_MODE == "dev" else _decode_oidc_token(token)
    roles = tuple(_extract_roles(claims))
    permissions = frozenset(permission for role in roles for permission in ROLE_PERMISSIONS.get(role, set()))
    return Principal(
        subject=str(claims.get("sub", "")),
        name=str(claims.get("name") or claims.get("preferred_username") or claims.get("sub", "")),
        roles=roles,
        permissions=permissions,
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
