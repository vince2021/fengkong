from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from typing import Any, Callable


MAPPING_VERSION = "corporate-governed-input-v1"
NORMAL_REGISTRATION_STATUSES = {"存续", "在业", "在营（开业）", "在营", "开业"}


def _get(data: dict, path: str) -> Any:
    value: Any = data
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def _set(data: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = data
    for segment in parts[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            child = {}
            cursor[segment] = child
        cursor = child
    cursor[parts[-1]] = value


def _direct(path: str) -> Callable[[dict, date], Any]:
    return lambda profile, _: _get(profile, path)


def _latest_period_value(key: str, divisor: float = 1.0) -> Callable[[dict, date], Any]:
    def extract(profile: dict, _: date) -> Any:
        periods = _get(profile, "financial_statements.periods")
        if not isinstance(periods, list):
            return None
        valid = [item for item in periods if isinstance(item, dict) and item.get(key) is not None]
        if not valid:
            return None
        latest = max(valid, key=lambda item: int(item.get("year", 0)))
        return round(float(latest[key]) / divisor, 6)

    return extract


def _weighted_period_value(key: str) -> Callable[[dict, date], Any]:
    def extract(profile: dict, _: date) -> Any:
        periods = _get(profile, "financial_statements.periods")
        if not isinstance(periods, list):
            return None
        values = [
            (int(item.get("year", 0)), float(item[key]))
            for item in periods
            if isinstance(item, dict) and item.get(key) is not None
        ]
        values.sort()
        if not values:
            return None
        values = values[-3:]
        weights = {1: [1.0], 2: [0.3, 0.7], 3: [0.2, 0.3, 0.5]}[len(values)]
        return round(sum(value * weight for (_, value), weight in zip(values, weights, strict=True)), 4)

    return extract


def _established_years(profile: dict, as_of: date) -> int | None:
    raw = _get(profile, "entity.established_date")
    if not raw:
        return None
    established = date.fromisoformat(str(raw)[:10])
    return max(0, as_of.year - established.year - ((as_of.month, as_of.day) < (established.month, established.day)))


def _normal_operation(profile: dict, _: date) -> bool | None:
    status = _get(profile, "entity.registration_status")
    return str(status).strip() in NORMAL_REGISTRATION_STATUSES if status is not None else None


def _governance_complete(profile: dict, _: date) -> bool | None:
    managers = _get(profile, "ownership.key_management")
    return len(managers) >= 3 if isinstance(managers, list) else None


def _latest_tax_credit(profile: dict, _: date) -> str | None:
    values = _get(profile, "external_risk.tax_credit")
    if not isinstance(values, dict) or not values:
        return None
    return str(values[max(values, key=lambda value: int(value))])


def _rule(target: str, label: str, source_paths: list[str], formula: str, extractor: Callable[[dict, date], Any], required: bool = False) -> dict:
    return {"target_path": target, "label": label, "source_paths": source_paths, "formula": formula, "extractor": extractor, "required": required}


CORPORATE_INPUT_RULES = [
    _rule("external.registration_status", "主体经营状态", ["entity.registration_status"], "原值映射", _direct("entity.registration_status"), True),
    _rule("external.established_years", "成立年限", ["entity.established_date"], "模型截止日与成立日期的完整年差", _established_years),
    _rule("corporate_profile.external.normal_operation", "主体正常经营", ["entity.registration_status"], "经营状态属于存续/在业/在营/开业", _normal_operation, True),
    _rule("corporate_profile.business.industry_risk_level", "行业风险档位", ["external_risk.industry_risk.sp_industry_risk_level"], "标普行业风险档位原值映射", _direct("external_risk.industry_risk.sp_industry_risk_level"), True),
    _rule("corporate_profile.business.total_assets_yi", "资产总额", ["financial_statements.periods"], "最新期资产总额（万元）÷10000", _latest_period_value("total_assets", 10_000), True),
    _rule("corporate_profile.business.revenue_yi", "营业收入", ["financial_statements.derived_features.weighted_revenue_wan_cny"], "三年加权营业收入（万元）÷10000", lambda p, _: _divide(_get(p, "financial_statements.derived_features.weighted_revenue_wan_cny"), 10_000), True),
    _rule("corporate_profile.business.patent_count", "专利储备", ["operations.patent_count"], "原值映射", _direct("operations.patent_count")),
    _rule("corporate_profile.business.qualification_count", "资质认证", ["operations.qualification_count"], "原值映射", _direct("operations.qualification_count")),
    _rule("corporate_profile.operations.total_asset_turnover", "总资产周转次数", ["financial_statements.derived_features.weighted_total_asset_turnover"], "三年加权总资产周转次数", _direct("financial_statements.derived_features.weighted_total_asset_turnover")),
    _rule("corporate_profile.operations.sales_growth_pct", "营业收入增长率", ["financial_statements.derived_features.two_year_weighted_sales_growth_pct"], "近两年按30%/70%加权", _direct("financial_statements.derived_features.two_year_weighted_sales_growth_pct"), True),
    _rule("corporate_profile.operations.profit_growth_pct", "利润增长率", ["financial_statements.periods"], "最近两期利润增长率按30%/70%加权", _weighted_period_value("profit_growth_pct")),
    _rule("corporate_profile.governance.structure_complete", "治理结构完整", ["ownership.key_management"], "关键管理人员不少于3人", _governance_complete),
    _rule("corporate_profile.financial.total_profit_yi", "利润总额", ["financial_statements.derived_features.weighted_total_profit_wan_cny"], "三年加权利润总额（万元）÷10000", lambda p, _: _divide(_get(p, "financial_statements.derived_features.weighted_total_profit_wan_cny"), 10_000)),
    _rule("corporate_profile.financial.net_profit_margin_pct", "净利润率", ["financial_statements.derived_features.weighted_net_profit_margin_pct"], "三年加权净利润率", _direct("financial_statements.derived_features.weighted_net_profit_margin_pct")),
    _rule("corporate_profile.financial.net_profit_margin_change_pct", "净利润率变化", ["external_risk.report_rule_hits"], "报告规则命中的净利润率下降幅度", lambda p, _: _rule_hit_value(p, "净利润率下降幅度")),
    _rule("corporate_profile.financial.return_on_equity_pct", "净资产收益率", ["financial_statements.derived_features.weighted_return_on_equity_pct"], "三年加权净资产收益率", _direct("financial_statements.derived_features.weighted_return_on_equity_pct")),
    _rule("corporate_profile.financial.debt_to_assets_pct", "资产负债率", ["financial_statements.derived_features.weighted_debt_to_assets_pct"], "三年加权资产负债率", _direct("financial_statements.derived_features.weighted_debt_to_assets_pct"), True),
    _rule("corporate_profile.financial.asset_growth_pct", "资产增长率", ["financial_statements.periods"], "可用年度资产增长率按20%/30%/50%或30%/70%加权", _weighted_period_value("asset_growth_pct")),
    _rule("corporate_profile.financial.capital_preservation_pct", "资本保值增值率", ["financial_statements.periods"], "可用年度资本保值增值率按20%/30%/50%或30%/70%加权", _weighted_period_value("capital_preservation_pct")),
    _rule("corporate_profile.financial.cash_to_short_debt", "现金类资产/短期债务", ["financial_statements.derived_features.cash_to_short_debt"], "原值映射", _direct("financial_statements.derived_features.cash_to_short_debt")),
    _rule("corporate_profile.financial.ebitda_interest_coverage", "EBITDA利息倍数", ["financial_statements.derived_features.ebitda_interest_coverage"], "原值映射", _direct("financial_statements.derived_features.ebitda_interest_coverage")),
    _rule("corporate_profile.financial.debt_to_ebitda", "债务/EBITDA", ["financial_statements.derived_features.debt_to_ebitda"], "原值映射", _direct("financial_statements.derived_features.debt_to_ebitda")),
    _rule("corporate_profile.financial.ffo_to_debt_pct", "FFO/债务", ["financial_statements.derived_features.ffo_to_debt_pct"], "原值映射", _direct("financial_statements.derived_features.ffo_to_debt_pct")),
    _rule("external.tax_credit_level", "纳税信用等级", ["external_risk.tax_credit"], "选择最新年度纳税信用等级", _latest_tax_credit),
    _rule("external.dishonesty_count", "失信记录", ["external_risk.dishonesty_count"], "原值映射", _direct("external_risk.dishonesty_count")),
    _rule("external.enforcement_count", "被执行记录", ["external_risk.enforcement_count"], "原值映射", _direct("external_risk.enforcement_count")),
    _rule("external.legal_cases_count", "涉诉案件", ["external_risk.legal_case_count"], "原值映射", _direct("external_risk.legal_case_count")),
    _rule("external.operating_abnormal_count", "经营异常", ["external_risk.operating_abnormal_count"], "原值映射", _direct("external_risk.operating_abnormal_count")),
    _rule("external.admin_penalty_count", "行政处罚", ["external_risk.admin_penalty_count"], "原值映射", _direct("external_risk.admin_penalty_count")),
    _rule("external.equity_freeze_count", "股权冻结", ["external_risk.equity_freeze_count"], "原值映射", _direct("external_risk.equity_freeze_count")),
    _rule("external.related_party_high_risk", "关联方高风险", ["ownership.related_party_high_risk"], "原值映射", _direct("ownership.related_party_high_risk")),
    _rule("internal.delivery_fulfillment_rate", "交付达成率", ["internal_transaction_data.delivery_fulfillment_rate"], "比率原值映射", _direct("internal_transaction_data.delivery_fulfillment_rate")),
    _rule("internal.invoice_match_rate", "发票匹配率", ["internal_transaction_data.invoice_match_rate"], "比率原值映射", _direct("internal_transaction_data.invoice_match_rate")),
    _rule("internal.contract_dispute_count", "合同争议次数", ["internal_transaction_data.contract_dispute_count"], "原值映射", _direct("internal_transaction_data.contract_dispute_count")),
    _rule("financial.overdue_rate", "逾期率", ["internal_transaction_data.overdue_rate"], "比率原值映射", _direct("internal_transaction_data.overdue_rate")),
    _rule("financial.avg_collection_days", "平均回款周期", ["internal_transaction_data.avg_collection_days"], "原值映射", _direct("internal_transaction_data.avg_collection_days")),
    _rule("financial.limit_utilization_rate", "额度使用率", ["internal_transaction_data.limit_utilization_rate"], "比率原值映射", _direct("internal_transaction_data.limit_utilization_rate")),
    _rule("internal.order_amount_12m", "近12月交易金额", ["internal_transaction_data.total_transaction_amount_cny"], "原值映射", _direct("internal_transaction_data.total_transaction_amount_cny")),
    _rule("requested_limit", "申请额度", ["internal_transaction_data.requested_credit_limit_cny"], "原值映射", _direct("internal_transaction_data.requested_credit_limit_cny")),
]


def prepare_rating_input(counterparty: dict, governed: dict, template_key: str, config: dict) -> tuple[dict, dict]:
    if config.get("scorecard_type") != "corporate_credit_v2" or not governed.get("effective_fields"):
        readiness = _legacy_readiness(template_key, counterparty, config, bool(governed.get("effective_fields")))
        prepared = deepcopy(counterparty)
        prepared["_data_governance"] = deepcopy(readiness)
        return prepared, readiness

    profile = governed["profile"]
    prepared = deepcopy(counterparty)
    effective_by_path = {item["field_path"]: item for item in governed["effective_fields"]}
    as_of = _mapping_as_of(governed)
    conflict_paths = set(governed.get("conflict_paths", []))
    mapping_rows: list[dict] = []
    for rule in CORPORATE_INPUT_RULES:
        value = rule["extractor"](profile, as_of)
        _set(prepared, rule["target_path"], value)
        sources = [effective_by_path[path] for path in rule["source_paths"] if path in effective_by_path]
        stale = bool(sources) and any(item["freshness_status"] == "stale" for item in sources)
        conflicted = any(path in conflict_paths for path in rule["source_paths"])
        mapping_rows.append({
            "target_path": rule["target_path"], "label": rule["label"], "value": value,
            "source_paths": rule["source_paths"], "source_field_ids": [item["id"] for item in sources],
            "source_names": sorted({item["source_name"] for item in sources}), "formula": rule["formula"],
            "required": rule["required"], "status": "missing" if value is None else "conflict" if conflicted else "stale" if stale else "mapped",
        })

    transaction_targets = {
        "internal.delivery_fulfillment_rate", "internal.invoice_match_rate", "internal.contract_dispute_count",
        "financial.overdue_rate", "financial.avg_collection_days", "financial.limit_utilization_rate",
    }
    transaction_complete = all(row["value"] is not None for row in mapping_rows if row["target_path"] in transaction_targets)
    prepared.setdefault("data_quality", {})["internal_transaction_complete"] = transaction_complete
    prepared["data_quality"]["governed_profile"] = True
    prepared["requested_limit"] = max(float(prepared.get("requested_limit") or 0), 0)

    required_missing = [row["target_path"] for row in mapping_rows if row["required"] and row["value"] is None]
    stale_required = [row["target_path"] for row in mapping_rows if row["required"] and row["status"] == "stale"]
    mapped_count = sum(row["value"] is not None for row in mapping_rows)
    coverage = round(mapped_count / len(mapping_rows), 4)
    quality_score = float(governed.get("summary", {}).get("quality_score", 0))
    ready_for_scoring = not required_missing
    auto_approval_ready = ready_for_scoring and coverage >= 0.85 and transaction_complete and not stale_required and not conflict_paths and quality_score >= 0.8
    gate_status = "pass" if auto_approval_ready else "review" if ready_for_scoring else "blocked"
    warnings = []
    if required_missing:
        warnings.append(f"缺少 {len(required_missing)} 个计算必需字段")
    if stale_required:
        warnings.append(f"{len(stale_required)} 个必需字段已超期")
    if conflict_paths:
        warnings.append(f"存在 {len(conflict_paths)} 个字段值冲突")
    if not transaction_complete:
        warnings.append("内部交易六项指标未完整接入，额度与账期必须人工复核")
    if quality_score < 0.8:
        warnings.append("治理画像质量评分低于80%")

    readiness = {
        "mapping_version": MAPPING_VERSION, "template_key": template_key, "model_version": config["version"],
        "source_mode": "governed", "as_of_date": as_of.isoformat(), "gate_status": gate_status,
        "ready_for_scoring": ready_for_scoring, "auto_approval_ready": auto_approval_ready,
        "mapped_count": mapped_count, "total_mapping_count": len(mapping_rows), "coverage_rate": coverage,
        "required_missing": required_missing, "stale_required": stale_required,
        "conflict_paths": sorted(conflict_paths), "transaction_complete": transaction_complete,
        "quality_score": quality_score, "warnings": warnings, "mappings": mapping_rows,
        "data_snapshot_hash": _hash_value({
            "effective_fields": sorted(
                (
                    item["field_path"], item["value_hash"], item["id"],
                    item.get("selection_method", "automatic"), item.get("resolution_id"),
                )
                for item in governed["effective_fields"]
            ),
            "unresolved_conflict_paths": sorted(governed.get("conflict_paths", [])),
            "resolved_conflict_paths": sorted(governed.get("resolved_conflict_paths", [])),
        }),
    }
    readiness["mapping_snapshot_hash"] = _hash_value(mapping_rows)
    prepared["data_quality"]["missing_critical_fields"] = required_missing
    prepared["_data_governance"] = deepcopy(readiness)
    return prepared, readiness


def readiness_summary(readiness: dict) -> dict:
    return {key: deepcopy(value) for key, value in readiness.items() if key != "mappings"}


def _legacy_readiness(template_key: str, counterparty: dict, config: dict, governed_exists: bool) -> dict:
    return {
        "mapping_version": MAPPING_VERSION, "template_key": template_key, "model_version": config["version"],
        "source_mode": "legacy_static", "as_of_date": None, "gate_status": "legacy",
        "ready_for_scoring": True, "auto_approval_ready": False, "mapped_count": 0, "total_mapping_count": 0,
        "coverage_rate": 0, "required_missing": [], "stale_required": [], "conflict_paths": [],
        "transaction_complete": bool(counterparty.get("data_quality", {}).get("internal_transaction_complete", True)),
        "quality_score": None, "warnings": ["当前模型或客商尚未启用治理字段映射，继续使用兼容静态输入" if not governed_exists else "当前模型暂未配置治理字段映射"],
        "mappings": [], "data_snapshot_hash": _hash_value(counterparty), "mapping_snapshot_hash": None,
    }


def _mapping_as_of(governed: dict) -> date:
    dates = [datetime.fromisoformat(item["as_of_date"].replace("Z", "+00:00")).date() for item in governed.get("recent_imports", []) if item.get("as_of_date")]
    return max(dates) if dates else date.today()


def _divide(value: Any, divisor: float) -> float | None:
    return round(float(value) / divisor, 6) if value is not None else None


def _rule_hit_value(profile: dict, contains: str) -> float | None:
    hits = _get(profile, "external_risk.report_rule_hits")
    if not isinstance(hits, list):
        return None
    match = next((item for item in hits if isinstance(item, dict) and contains in str(item.get("rule", ""))), None)
    return float(match["actual_pct"]) if match and match.get("actual_pct") is not None else None


def _hash_value(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
