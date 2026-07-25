from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.enterprise_data_governance import flatten_payload
from backend.rating_input_mapping import MAPPING_VERSION, prepare_rating_input


BASE_DIR = Path(__file__).resolve().parents[1]


def _governed(profile: dict, quality_score: float = 0.75) -> dict:
    fields = [
        {
            "id": f"field-{index}", "field_path": path, "value": value,
            "value_hash": f"hash-{index}", "source_name": "材料信用报告",
            "freshness_status": "stale", "conflict_status": "none",
        }
        for index, (path, value) in enumerate(flatten_payload(profile).items())
    ]
    return {
        "profile": profile,
        "effective_fields": fields,
        "conflict_paths": [],
        "summary": {"quality_score": quality_score},
        "recent_imports": [{"as_of_date": "2024-08-15T00:00:00"}],
    }


def test_material_profile_maps_to_versioned_model_input() -> None:
    profile = json.loads((BASE_DIR / "data" / "raw_enterprise_profiles" / "inalfa_guangzhou.json").read_text(encoding="utf-8"))
    counterparty = next(item for item in json.loads((BASE_DIR / "data" / "counterparties.json").read_text(encoding="utf-8")) if item["id"] == "cp_inalfa_guangzhou_001")
    config = json.loads((BASE_DIR / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]["corporate_credit_v2"]

    prepared, readiness = prepare_rating_input(counterparty, _governed(profile), "corporate_credit_v2", config)

    assert readiness["mapping_version"] == MAPPING_VERSION
    assert readiness["source_mode"] == "governed"
    assert readiness["ready_for_scoring"] is True
    assert readiness["gate_status"] == "review"
    assert readiness["auto_approval_ready"] is False
    assert prepared["corporate_profile"]["business"]["total_assets_yi"] == pytest.approx(2.6015)
    assert prepared["corporate_profile"]["business"]["revenue_yi"] == pytest.approx(2.04659)
    assert prepared["corporate_profile"]["operations"]["profit_growth_pct"] == pytest.approx(-50.421)
    assert prepared["corporate_profile"]["financial"]["asset_growth_pct"] == pytest.approx(1.335)
    assert prepared["external"]["tax_credit_level"] == "A"
    assert prepared["data_quality"]["internal_transaction_complete"] is False
    assert readiness["data_snapshot_hash"]
    assert readiness["mapping_snapshot_hash"]


def test_incomplete_governed_profile_blocks_corporate_scoring() -> None:
    counterparty = {"id": "cp-minimal", "name": "最小企业", "data_quality": {}}
    config = {"version": "v1", "scorecard_type": "corporate_credit_v2"}
    profile = {"entity": {"unified_social_credit_code": "913000000000000000", "registration_status": "存续"}}

    _, readiness = prepare_rating_input(counterparty, _governed(profile, 0.3), "corporate_credit_v2", config)

    assert readiness["gate_status"] == "blocked"
    assert readiness["ready_for_scoring"] is False
    assert "corporate_profile.business.total_assets_yi" in readiness["required_missing"]


def test_non_governed_or_non_corporate_model_keeps_legacy_input() -> None:
    counterparty = {"id": "cp-legacy", "name": "旧样本", "data_quality": {}}
    config = {"version": "v1", "scorecard_type": "general"}

    prepared, readiness = prepare_rating_input(counterparty, {}, "general", config)

    assert readiness["source_mode"] == "legacy_static"
    assert readiness["gate_status"] == "legacy"
    assert prepared["_data_governance"]["source_mode"] == "legacy_static"
