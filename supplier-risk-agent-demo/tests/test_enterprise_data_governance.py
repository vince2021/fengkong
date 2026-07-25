from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.enterprise_data_governance import build_quality_summary, choose_effective_field, flatten_payload, freshness_status, source_priority


def test_flatten_payload_preserves_arrays_and_validates_keys() -> None:
    flattened = flatten_payload({"entity": {"name_cn": "测试企业"}, "operations": {"customers": ["A", "B"]}})
    assert flattened == {"entity.name_cn": "测试企业", "operations.customers": ["A", "B"]}
    with pytest.raises(ValueError, match="字段名不合法"):
        flatten_payload({"entity.bad.path": "x"})


def test_freshness_thresholds_are_domain_specific() -> None:
    now = datetime.now(timezone.utc)
    assert freshness_status("internal_transaction_data.overdue_rate", now - timedelta(days=31), now) == "stale"
    assert freshness_status("financial_statements.periods", now - timedelta(days=400), now) == "current"


def test_effective_value_prefers_current_then_source_priority() -> None:
    stale_official = {"id": "official", "freshness_status": "stale", "source_priority": 90, "observed_at": "2024-01-01", "created_at": "2024-01-01"}
    current_management = {"id": "management", "freshness_status": "current", "source_priority": 50, "observed_at": "2026-07-01", "created_at": "2026-07-01"}
    assert choose_effective_field([stale_official, current_management])["id"] == "management"
    current_official = {**stale_official, "freshness_status": "current", "observed_at": "2026-06-01"}
    assert choose_effective_field([current_official, current_management])["id"] == "official"


def test_source_priority_is_specific_to_the_field_domain() -> None:
    assert source_priority("official_registry", "entity.legal_representative") > source_priority("internal_erp", "entity.legal_representative")
    assert source_priority("internal_erp", "internal_transaction_data.overdue_rate") > source_priority("credit_report", "internal_transaction_data.overdue_rate")
    assert source_priority("audited_financial", "financial_statements.revenue") > source_priority("management_submission", "financial_statements.revenue")


def test_profile_quality_penalizes_conflicts_from_non_effective_candidates() -> None:
    fields = [{
        "field_path": "entity.name_cn",
        "freshness_status": "current",
        "conflict_status": "none",
        "validation_status": "valid",
        "evidence_reference": "registry://record",
    }]
    clean = build_quality_summary(fields, conflict_count=0)
    conflicted = build_quality_summary(fields, conflict_count=1)
    assert conflicted["conflict_count"] == 1
    assert conflicted["quality_score"] < clean["quality_score"]
