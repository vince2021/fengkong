"""Persistent tenant, membership, and API client access registry."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db_models import ApiClientRecord, TenantMembershipRecord, TenantOutcomeLabelDefinitionRecord, TenantRecord


PLATFORM_INTERNAL_TENANT_ID = "tenant-platform-internal"


def active_business_tenant_ids(session: Session) -> list[str]:
    return list(session.scalars(
        select(TenantRecord.id).where(
            TenantRecord.status == "active",
            TenantRecord.id != PLATFORM_INTERNAL_TENANT_ID,
        ).order_by(TenantRecord.id)
    ).all())


class TenantAccessError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TenantRegistry:
    def __init__(self, session: Session) -> None:
        self.session = session

    def authorize(self, tenant_id: str, client_id: str, subject: str, token_roles: tuple[str, ...]) -> dict:
        tenant = self.session.get(TenantRecord, tenant_id)
        if tenant is None or tenant.status != "active":
            raise TenantAccessError("TENANT_UNAVAILABLE", "租户不存在或未启用")

        membership = self.session.scalars(
            select(TenantMembershipRecord).where(
                TenantMembershipRecord.tenant_id == tenant_id,
                TenantMembershipRecord.subject == subject,
            )
        ).first()
        if membership is None or membership.status != "active" or _expired(membership.expires_at):
            raise TenantAccessError("TENANT_MEMBERSHIP_DENIED", "当前身份不属于该租户或成员关系未启用")

        allowed_roles = {str(role) for role in membership.roles_json or []}
        unauthorized_roles = sorted(set(token_roles) - allowed_roles)
        if unauthorized_roles:
            raise TenantAccessError("TENANT_ROLE_DENIED", "令牌角色超出租户成员授权范围")

        client = self.session.scalars(
            select(ApiClientRecord).where(
                ApiClientRecord.tenant_id == tenant_id,
                ApiClientRecord.client_id == client_id,
            )
        ).first()
        if client is None or client.status != "active" or _expired(client.expires_at):
            raise TenantAccessError("API_CLIENT_DENIED", "API 客户端不存在、已停用或已过期")

        return {
            "tenant": tenant,
            "membership": membership,
            "client": client,
        }

    def client_profile(self, tenant_id: str, client_id: str) -> dict:
        tenant = self.session.get(TenantRecord, tenant_id)
        client = self.session.scalars(
            select(ApiClientRecord).where(
                ApiClientRecord.tenant_id == tenant_id,
                ApiClientRecord.client_id == client_id,
            )
        ).first()
        if tenant is None or client is None:
            raise TenantAccessError("API_CLIENT_DENIED", "API 客户端配置不存在")
        return {
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "deployment_mode": tenant.deployment_mode,
            "client_id": client.client_id,
            "client_name": client.name,
            "key_id": client.key_id,
            "key_fingerprint": client.key_fingerprint,
            "status": client.status,
            "qps_limit": client.qps_limit,
            "concurrent_job_limit": client.concurrent_job_limit,
            "daily_item_quota": client.daily_item_quota,
            "allowed_cidrs": list(client.allowed_cidrs_json or []),
            "rotated_at": _iso(client.rotated_at),
            "expires_at": _iso(client.expires_at),
            "last_used_at": _iso(client.last_used_at),
        }


def seed_development_tenant_registry(session: Session) -> None:
    tenants = [
        ("tenant-demo-hengxin", "恒信演示租户", "saas"),
        ("tenant-demo-alt", "第二隔离演示租户", "saas"),
        ("tenant-platform-internal", "平台内部租户", "dedicated"),
    ]
    for tenant_id, name, deployment_mode in tenants:
        if session.get(TenantRecord, tenant_id) is None:
            session.add(
                TenantRecord(
                    id=tenant_id,
                    name=name,
                    deployment_mode=deployment_mode,
                    status="active",
                    data_region="cn",
                )
            )
    session.flush()

    default_definition = {
        "code": "90_days_default", "version": 1, "name": "90 天企业违约口径",
        "description": "用于企业评级与授信模型延迟监督的标准违约定义；观察窗口届满后确认逾期或违约事实。",
        "event_type": "default", "event_threshold": {"days_past_due": 90},
        "observation_window_days": 90, "maturity_grace_days": 0,
        "source_priorities": [
            {"source": "贷后核心系统", "priority": 1},
            {"source": "贷后结果系统", "priority": 2},
            {"source": "贷后结果仓", "priority": 3},
        ],
        "applicable_model_keys": ["general", "general-next", "corporate_credit_v2"],
        "require_loss_amount": False, "require_exposure_amount": False,
    }
    canonical = json.dumps(default_definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    definition_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    for tenant_id, _, _ in tenants:
        existing = session.scalars(select(TenantOutcomeLabelDefinitionRecord).where(
            TenantOutcomeLabelDefinitionRecord.tenant_id == tenant_id,
            TenantOutcomeLabelDefinitionRecord.code == default_definition["code"],
            TenantOutcomeLabelDefinitionRecord.version == 1,
        )).first()
        if existing is None:
            session.add(TenantOutcomeLabelDefinitionRecord(
                id=str(uuid5(NAMESPACE_URL, f"fengkong:{tenant_id}:90_days_default:1")),
                tenant_id=tenant_id, code=default_definition["code"], version=1,
                name=default_definition["name"], description=default_definition["description"],
                event_type=default_definition["event_type"], event_threshold_json=default_definition["event_threshold"],
                observation_window_days=default_definition["observation_window_days"], maturity_grace_days=0,
                source_priorities_json=default_definition["source_priorities"],
                applicable_model_keys_json=default_definition["applicable_model_keys"],
                require_loss_amount=False, require_exposure_amount=False,
                status="published", is_active=True, config_hash=definition_hash,
                reviewed_by="system-seed", reviewed_by_name="系统预置",
                review_comment="平台标准口径初始化；不回填或改写历史标签绑定。",
                created_by="system-seed", created_by_name="系统预置",
            ))
    session.flush()

    identities = [
        ("tenant-demo-hengxin", "client-demo", "演示客户", ["client"]),
        ("tenant-demo-hengxin", "manager-demo", "客户经理", ["relationship_manager"]),
        ("tenant-demo-hengxin", "manager-peer-demo", "客户经理乙", ["relationship_manager"]),
        ("tenant-demo-hengxin", "risk-demo", "风控经理", ["risk_manager"]),
        ("tenant-demo-hengxin", "model-demo", "模型管理员", ["model_admin"]),
        ("tenant-demo-hengxin", "approver-demo", "授信审批人", ["approver"]),
        ("tenant-demo-hengxin", "approver-peer-demo", "授信审批人乙", ["approver"]),
        ("tenant-demo-hengxin", "auditor-demo", "审计人员", ["auditor"]),
        ("tenant-demo-hengxin", "operations-demo", "运营值班", ["operations"]),
        ("tenant-demo-hengxin", "integration-demo", "集成管理员", ["integration_admin"]),
        ("tenant-demo-alt", "integration-alt-demo", "另一租户集成管理员", ["integration_admin"]),
        ("tenant-platform-internal", "admin-demo", "平台管理员", ["admin"]),
        ("tenant-platform-internal", "admin-reviewer-demo", "平台复核人", ["admin"]),
    ]
    for tenant_id, subject, display_name, roles in identities:
        existing = session.scalars(
            select(TenantMembershipRecord).where(
                TenantMembershipRecord.tenant_id == tenant_id,
                TenantMembershipRecord.subject == subject,
            )
        ).first()
        if existing is None:
            session.add(
                TenantMembershipRecord(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    subject=subject,
                    display_name=display_name,
                    roles_json=roles,
                    status="active",
                )
            )

    clients = [
        ("tenant-demo-hengxin", "customer-portal", "客户门户", "portal-session", "OIDC:CUSTOMER:SESSION", 20, 3, 10000),
        ("tenant-demo-hengxin", "platform-console", "平台工作台", "internal-session", "OIDC:PLATFORM:SESSION", 50, 10, 50000),
        ("tenant-demo-hengxin", "erp-integration-sandbox", "ERP 集成沙箱", "key_sandbox_2026_09", "SHA256:8F:27:64:AD:91:CE", 20, 3, 10000),
        ("tenant-demo-alt", "erp-alt-sandbox", "第二租户 ERP 沙箱", "key_alt_sandbox_2026_09", "SHA256:ALT:27:64:AD:91", 10, 2, 5000),
        ("tenant-platform-internal", "platform-console", "平台管理控制台", "internal-session", "OIDC:PLATFORM:SESSION", 50, 10, 50000),
    ]
    for tenant_id, client_id, name, key_id, fingerprint, qps, concurrent, daily in clients:
        existing = session.scalars(
            select(ApiClientRecord).where(
                ApiClientRecord.tenant_id == tenant_id,
                ApiClientRecord.client_id == client_id,
            )
        ).first()
        if existing is None:
            session.add(
                ApiClientRecord(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    name=name,
                    status="active",
                    key_id=key_id,
                    key_fingerprint=fingerprint,
                    secret_reference=None,
                    qps_limit=qps,
                    concurrent_job_limit=concurrent,
                    daily_item_quota=daily,
                    allowed_cidrs_json=[],
                )
            )
    session.commit()


def _expired(value: datetime | None) -> bool:
    if value is None:
        return False
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized <= datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
