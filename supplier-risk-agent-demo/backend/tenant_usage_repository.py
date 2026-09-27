"""Tenant commercial usage ledgers built from sealed operational evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db_models import (
    DecisionExecutionRecord,
    DecisionJobRecord,
    DocumentRecord,
    PortfolioRatingBatchRecord,
    RuleCenterReplayRun,
    TenantAssetBindingRecord,
    TenantEntitlementRecord,
    TenantRecord,
    TenantUsageDailyRecord,
    TenantUsageStatementRecord,
)
from backend.product_package_repository import ProductPackageError
from backend.repository import content_hash
from backend.security import Principal


class TenantUsageRepository:
    """Derives commercial measurements without changing the decision execution path."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def refresh_day(self, tenant_id: str, usage_date: date, principal: Principal) -> dict:
        self._tenant(tenant_id)
        usage, watermark = self._aggregate_day(tenant_id, usage_date)
        evidence_hash = content_hash({"tenant_id": tenant_id, "usage_date": usage_date.isoformat(), "usage": usage, "sources": watermark})
        record = self.session.scalar(select(TenantUsageDailyRecord).where(
            TenantUsageDailyRecord.tenant_id == tenant_id, TenantUsageDailyRecord.usage_date == usage_date,
        ))
        if record is None:
            record = TenantUsageDailyRecord(
                id=str(uuid4()), tenant_id=tenant_id, usage_date=usage_date, usage_json=usage,
                source_watermark_json=watermark, evidence_hash=evidence_hash,
            )
            self.session.add(record)
        else:
            record.usage_json = usage
            record.source_watermark_json = watermark
            record.evidence_hash = evidence_hash
            record.computed_at = self._now()
        self.session.commit()
        self.session.refresh(record)
        return self._daily_view(record)

    def summary(self, tenant_id: str, billing_month: date) -> dict:
        self._tenant(tenant_id)
        month_start, month_end = self._month_window(billing_month)
        records = self.session.scalars(select(TenantUsageDailyRecord).where(
            TenantUsageDailyRecord.tenant_id == tenant_id,
            TenantUsageDailyRecord.usage_date >= month_start,
            TenantUsageDailyRecord.usage_date < month_end,
        ).order_by(TenantUsageDailyRecord.usage_date.desc())).all()
        daily = [self._daily_view(row) for row in records]
        totals = self._totals(daily)
        current_quota = self._quota_snapshot(tenant_id, month_end - timedelta(days=1))
        return {
            "tenant_id": tenant_id, "billing_month": month_start.isoformat(), "daily_records": daily,
            "totals": totals, "quota_snapshot": current_quota,
            "metering_scope": self._metering_scope(),
            "statements": self.list_statements(tenant_id, month_start),
        }

    def create_statement(self, tenant_id: str, billing_month: date, principal: Principal) -> dict:
        self._tenant(tenant_id)
        month_start, month_end = self._month_window(billing_month)
        daily_records = self.session.scalars(select(TenantUsageDailyRecord).where(
            TenantUsageDailyRecord.tenant_id == tenant_id,
            TenantUsageDailyRecord.usage_date >= month_start,
            TenantUsageDailyRecord.usage_date < month_end,
        ).order_by(TenantUsageDailyRecord.usage_date)).all()
        daily = [self._daily_view(row) for row in daily_records]
        snapshot = {
            "schema_version": "tenant-usage-statement-v1",
            "statement_type": "reconciliation_evidence_not_invoice",
            "tenant_id": tenant_id,
            "billing_month": month_start.isoformat(),
            "daily_ledger": daily,
            "totals": self._totals(daily),
            "quota_snapshot": self._quota_snapshot(tenant_id, month_end - timedelta(days=1)),
            "metering_scope": self._metering_scope(),
        }
        version = int(self.session.scalar(select(func.max(TenantUsageStatementRecord.statement_version)).where(
            TenantUsageStatementRecord.tenant_id == tenant_id,
            TenantUsageStatementRecord.billing_month == month_start,
        )) or 0) + 1
        snapshot["statement_version"] = version
        statement_hash = content_hash(snapshot)
        record = TenantUsageStatementRecord(
            id=str(uuid4()), tenant_id=tenant_id, billing_month=month_start, statement_version=version,
            status="generated", statement_json=snapshot, statement_hash=statement_hash,
            generated_by=principal.subject, generated_by_name=principal.name,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._statement_view(record)

    def list_statements(self, tenant_id: str | None = None, billing_month: date | None = None) -> list[dict]:
        statement = select(TenantUsageStatementRecord)
        if tenant_id:
            statement = statement.where(TenantUsageStatementRecord.tenant_id == tenant_id)
        if billing_month:
            statement = statement.where(TenantUsageStatementRecord.billing_month == self._month_window(billing_month)[0])
        rows = self.session.scalars(statement.order_by(
            TenantUsageStatementRecord.billing_month.desc(), TenantUsageStatementRecord.statement_version.desc(),
        )).all()
        return [self._statement_view(row) for row in rows]

    def export_rows(self, statement_id: str) -> tuple[dict, list[dict]]:
        record = self.session.get(TenantUsageStatementRecord, statement_id)
        if record is None:
            raise ProductPackageError("USAGE_STATEMENT_NOT_FOUND", "月度对账证据不存在", 404)
        snapshot = deepcopy(record.statement_json or {})
        rows = []
        for day in snapshot.get("daily_ledger", []):
            usage = day.get("usage", {})
            rows.append({
                "usage_date": day["usage_date"], "sync_decision_requests": usage.get("sync_decision_requests", 0),
                "async_job_items": usage.get("async_job_items", 0), "portfolio_candidates": usage.get("portfolio_candidates", 0),
                "replay_samples": usage.get("replay_samples", 0), "document_storage_bytes": usage.get("document_storage_bytes", 0),
                "evidence_hash": day["evidence_hash"],
            })
        return self._statement_view(record), rows

    def _aggregate_day(self, tenant_id: str, usage_date: date) -> tuple[dict, dict]:
        start, end = self._day_window(usage_date)
        executions = self.session.scalars(select(DecisionExecutionRecord).where(
            DecisionExecutionRecord.tenant_id == tenant_id,
            DecisionExecutionRecord.created_at >= start, DecisionExecutionRecord.created_at < end,
        )).all()
        jobs = self.session.scalars(select(DecisionJobRecord).where(
            DecisionJobRecord.tenant_id == tenant_id,
            DecisionJobRecord.created_at >= start, DecisionJobRecord.created_at < end,
        )).all()
        job_request_ids = {
            str(item.get("request_id")) for job in self.session.scalars(select(DecisionJobRecord).where(
                DecisionJobRecord.tenant_id == tenant_id,
            )).all() for item in (job.request_json or {}).get("requests", []) if item.get("request_id")
        }
        sync_executions = [item for item in executions if item.request_id not in job_request_ids]
        batches = self.session.scalars(select(PortfolioRatingBatchRecord).where(
            PortfolioRatingBatchRecord.tenant_id == tenant_id,
            PortfolioRatingBatchRecord.created_at >= start, PortfolioRatingBatchRecord.created_at < end,
        )).all()
        replays = self.session.scalars(select(RuleCenterReplayRun).where(
            RuleCenterReplayRun.tenant_id == tenant_id,
            RuleCenterReplayRun.created_at >= start, RuleCenterReplayRun.created_at < end,
        )).all()
        documents = self.session.scalars(select(DocumentRecord).where(
            DocumentRecord.tenant_id == tenant_id,
            DocumentRecord.created_at >= start, DocumentRecord.created_at < end,
        )).all()
        quota = self._quota_snapshot(tenant_id, usage_date)
        async_items = sum(int(item.total_count) for item in jobs)
        usage = {
            "sync_decision_requests": len(sync_executions), "async_jobs": len(jobs),
            "async_job_items": async_items,
            "async_succeeded_items": sum(int(item.succeeded_count) for item in jobs),
            "async_failed_items": sum(int(item.failed_count) for item in jobs),
            "portfolio_rating_batches": len(batches), "portfolio_candidates": sum(int(item.candidate_count) for item in batches),
            "portfolio_successes": sum(int(item.success_count) for item in batches),
            "replay_runs": len(replays), "replay_samples": sum(int(item.sample_count) for item in replays),
            "documents_uploaded": len(documents), "document_storage_bytes": sum(int(item.size_bytes) for item in documents),
            "active_asset_bindings": self._active_asset_count(tenant_id),
            "daily_item_quota": quota.get("daily_item_quota"), "daily_item_utilization": self._ratio(async_items, quota.get("daily_item_quota")),
        }
        watermark = {
            "method": "sealed_operational_records_v1",
            "sync_executions": self._source_mark(sync_executions, "id", "evidence_hash"),
            "async_jobs": self._source_mark(jobs, "id", "request_hash"),
            "portfolio_batches": self._source_mark(batches, "id", "result_hash"),
            "replay_runs": self._source_mark(replays, "id", "evidence_hash"),
            "documents": self._source_mark(documents, "id", "sha256"),
            "quota_snapshot": quota,
        }
        return usage, watermark

    def _quota_snapshot(self, tenant_id: str, as_of: date) -> dict:
        _, end = self._day_window(as_of)
        row = self.session.scalar(select(TenantEntitlementRecord).where(
            TenantEntitlementRecord.tenant_id == tenant_id,
            TenantEntitlementRecord.starts_at < end,
            TenantEntitlementRecord.expires_at >= end,
            TenantEntitlementRecord.status.in_(("active", "scheduled", "expired")),
        ).order_by(TenantEntitlementRecord.starts_at.desc()))
        quotas = deepcopy(row.effective_quotas_json) if row else {}
        return {
            "entitlement_id": row.id if row else None, "package_code": row.package_code if row else None,
            "package_version": row.package_version if row else None, "package_config_hash": row.package_config_hash if row else None,
            "qps_limit": quotas.get("qps_limit"), "concurrent_job_limit": quotas.get("concurrent_job_limit"),
            "daily_item_quota": quotas.get("daily_item_quota"), "max_asset_bindings": quotas.get("max_asset_bindings"),
        }

    def _active_asset_count(self, tenant_id: str) -> int:
        return int(self.session.scalar(select(func.count(TenantAssetBindingRecord.id)).where(
            TenantAssetBindingRecord.tenant_id == tenant_id, TenantAssetBindingRecord.status == "active",
        )) or 0)

    @staticmethod
    def _source_mark(rows: list, identifier: str, evidence: str) -> dict:
        items = sorted(f"{getattr(row, identifier)}:{getattr(row, evidence) or ''}" for row in rows)
        latest = max((TenantUsageRepository._iso(getattr(row, "created_at", None)) or "" for row in rows), default=None)
        return {"count": len(items), "latest_created_at": latest, "source_hash": content_hash(items)}

    @staticmethod
    def _metering_scope() -> dict:
        return {
            "source": "已封存业务记录聚合，不依赖前端统计",
            "billable_dimensions": ["同步决策请求", "异步决策项目", "组合评级样本", "回放样本", "文档存储"],
            "enforcement_scope": "异步决策任务已执行日项目数、并发和 QPS 门禁；同步决策请求仅计量，尚未启用全局日限额强制。",
            "asset_scope": "活动资产绑定为账本生成时的目录快照，不回溯历史目录状态。",
        }

    @staticmethod
    def _totals(daily: list[dict]) -> dict:
        keys = ("sync_decision_requests", "async_jobs", "async_job_items", "async_succeeded_items", "async_failed_items", "portfolio_rating_batches", "portfolio_candidates", "portfolio_successes", "replay_runs", "replay_samples", "documents_uploaded", "document_storage_bytes")
        return {key: sum(int(item["usage"].get(key) or 0) for item in daily) for key in keys}

    @staticmethod
    def _ratio(used: int, limit: int | None) -> float | None:
        return round(used / limit, 6) if limit else None

    @staticmethod
    def _day_window(value: date) -> tuple[datetime, datetime]:
        start = datetime.combine(value, time.min, tzinfo=timezone.utc)
        return start, start + timedelta(days=1)

    @staticmethod
    def _month_window(value: date) -> tuple[date, date]:
        start = value.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, end

    def _tenant(self, tenant_id: str) -> TenantRecord:
        record = self.session.get(TenantRecord, tenant_id)
        if record is None:
            raise ProductPackageError("TENANT_NOT_FOUND", "租户不存在", 404, {"tenant_id": tenant_id})
        return record

    @staticmethod
    def _daily_view(record: TenantUsageDailyRecord) -> dict:
        return {"id": record.id, "tenant_id": record.tenant_id, "usage_date": record.usage_date.isoformat(), "usage": deepcopy(record.usage_json or {}), "source_watermark": deepcopy(record.source_watermark_json or {}), "evidence_hash": record.evidence_hash, "computed_at": TenantUsageRepository._iso(record.computed_at)}

    @staticmethod
    def _statement_view(record: TenantUsageStatementRecord) -> dict:
        return {"id": record.id, "tenant_id": record.tenant_id, "billing_month": record.billing_month.isoformat(), "statement_version": record.statement_version, "status": record.status, "statement": deepcopy(record.statement_json or {}), "statement_hash": record.statement_hash, "generated_by": record.generated_by, "generated_by_name": record.generated_by_name, "created_at": TenantUsageRepository._iso(record.created_at)}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
