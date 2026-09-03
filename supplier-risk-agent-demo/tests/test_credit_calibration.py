from __future__ import annotations

from copy import deepcopy
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

import backend.database as database
from backend.credit_calibration import analyze_credit_calibration, calibration_configuration
from backend.database import Base
from backend.db_models import CreditCalibrationPlan, CreditCalibrationRun, ModelChangeRecord, RuleCenterReplayDataset, RuleCenterReplayDatasetSnapshot
from backend.main import app
from backend.repository import DemoRepository, RuleCenterReplayDatasetRepository, content_hash
from tests.database_support import IsolatedTestDatabase


def _samples() -> list[dict]:
    repository = DemoRepository()
    base = repository.get_counterparty("cp_inalfa_guangzhou_001")
    assert base is not None
    rows = []
    for index, (label, requested_limit, complete) in enumerate([
        ("bad", 8_000_000, True),
        ("good", 5_000_000, True),
        ("good", 3_000_000, False),
    ]):
        sample = deepcopy(base)
        sample["id"] = f"calibration-{index}"
        sample["name"] = f"校准企业 {index + 1}"
        sample["requested_limit"] = requested_limit
        sample["data_quality"]["internal_transaction_complete"] = complete
        if complete:
            sample["internal"].update({
                "delivery_fulfillment_rate": 0.98,
                "invoice_match_rate": 0.97,
                "cooperation_years": 4,
                "order_amount_12m": 30_000_000,
            })
            sample["financial"].update({
                "overdue_rate": 0.04 if label == "good" else 0.2,
                "limit_utilization_rate": 0.55,
                "bad_debt_flag": False,
            })
        rows.append({"sample": sample, "label": label})
    return rows


def _request(candidate: dict | None = None) -> dict:
    config = DemoRepository().get_template("corporate_credit_v2")
    assert config is not None
    defaults = calibration_configuration(config)["default_candidate"]
    return {
        "dataset_snapshot_id": "snapshot-1",
        "template_key": "corporate_credit_v2",
        "positive_labels": ["bad", "default", "reject"],
        "sample_limit": 500,
        "candidate": {**defaults, **(candidate or {})},
    }


def _snapshot(samples: list[dict]) -> dict:
    return {
        "id": "snapshot-1",
        "dataset_id": "dataset-1",
        "dataset_code": "CORPORATE-CALIBRATION",
        "dataset_name": "企业授信校准样本",
        "version": 1,
        "as_of_date": "2026-08-31",
        "content_hash": content_hash(samples),
        "sample_count": len(samples),
        "coverage": {"overall_field_coverage_rate": 0.96},
        "samples": samples,
    }


def test_configuration_exposes_governed_baseline_and_parameter_notes() -> None:
    config = DemoRepository().get_template("corporate_credit_v2")
    assert config is not None

    result = calibration_configuration(config)

    assert result["template_key"] == "corporate_credit_v2"
    assert result["model_config_hash"] == content_hash(config)
    assert result["default_candidate"]["score_threshold_shift"] == 0
    assert "正值更严格" in result["parameter_notes"]["score_threshold_shift"]


def test_default_candidate_matches_baseline_and_evidence_hash_is_stable() -> None:
    config = DemoRepository().get_template("corporate_credit_v2")
    assert config is not None
    snapshot = _snapshot(_samples())

    first = analyze_credit_calibration(config, snapshot, _request())
    second = analyze_credit_calibration(config, snapshot, _request())

    assert first["baseline"] == first["candidate"]
    assert all(value in (0, 0.0) for value in first["deltas"].values() if value is not None)
    assert first["migration"]["rating_changed_count"] == 0
    assert first["sample"]["evidence_level"] == "supervised"
    assert first["evidence_hash"] == second["evidence_hash"]


def test_tighter_limit_and_payment_term_parameters_change_portfolio_capacity() -> None:
    config = DemoRepository().get_template("corporate_credit_v2")
    assert config is not None
    result = analyze_credit_calibration(
        config,
        _snapshot(_samples()),
        _request({"limit_multiplier_scale": 0.5, "revenue_limit_scale": 0.5, "order_amount_scale": 0.5, "payment_term_scale": 0.5}),
    )

    assert result["candidate"]["total_limit"] < result["baseline"]["total_limit"]
    assert result["candidate"]["average_payment_term_days"] <= result["baseline"]["average_payment_term_days"]
    assert result["deltas"]["total_limit"] < 0


def test_unlabeled_snapshot_is_explicitly_degraded() -> None:
    config = DemoRepository().get_template("corporate_credit_v2")
    assert config is not None
    samples = [{**row, "label": None} for row in _samples()]

    result = analyze_credit_calibration(config, _snapshot(samples), _request())

    assert result["sample"]["evidence_level"] == "degraded"
    assert result["sample"]["labeled_count"] == 0
    assert result["baseline"]["event_exposure_ratio"] is None
    assert any("非监督" in warning for warning in result["warnings"])


def test_governed_calibration_plan_requires_run_and_independent_review_before_model_change() -> None:
    isolated = IsolatedTestDatabase()
    isolated.start()
    client = TestClient(app)
    try:
        Base.metadata.create_all(isolated.engine)
        with database.SessionLocal() as session:
            dataset = RuleCenterReplayDataset(
                id=str(uuid4()), code="CREDIT-CALIBRATION-TEST", name="企业授信校准样本",
                description="固定校准证据测试", status="active", created_by="model-admin",
                created_by_name="模型管理员",
            )
            rows = _samples()
            snapshot = RuleCenterReplayDatasetSnapshot(
                id=str(uuid4()), dataset_id=dataset.id, version=1, source_name="test",
                schema_version="1", as_of_date=date(2026, 8, 31), evidence_reference="test://calibration",
                data_classification="synthetic", field_mapping_json={}, label_field="label",
                observed_at_field=None, sample_count=len(rows), samples_json=rows,
                coverage_json={"overall_field_coverage_rate": 0.96, "label_coverage_rate": 1},
                source_hash="a" * 64, content_hash="pending", created_by="model-admin",
                created_by_name="模型管理员",
            )
            session.add_all([dataset, snapshot])
            session.flush()
            snapshot.content_hash = RuleCenterReplayDatasetRepository.snapshot_content_hash(snapshot)
            snapshot_id = snapshot.id
            session.commit()

        headers = {"Authorization": "Bearer dev-admin"}
        review_headers = {"Authorization": "Bearer dev-risk"}
        request = _request({"score_threshold_shift": 2, "limit_multiplier_scale": 0.8, "payment_term_scale": 0.8})
        request["dataset_snapshot_id"] = snapshot_id
        plan_payload = {
            "code": "CORP-CREDIT-CALIBRATION", "name": "企业授信稳健校准",
            "template_key": request["template_key"], "candidate": request["candidate"],
            "positive_labels": request["positive_labels"], "sample_limit": request["sample_limit"],
            "business_basis": "基于固定企业样本收紧评级、额度与账期参数",
        }
        created_plan_response = client.post("/api/v1/indicator-center/credit-calibration/plans", json=plan_payload, headers=headers)
        assert created_plan_response.status_code == 201, created_plan_response.text
        plan = created_plan_response.json()
        assert plan["version"] == 1
        assert plan["status"] == "draft"

        missing_run = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{plan['id']}/submit", json={"expected_row_version": plan["row_version"]}, headers=headers)
        assert missing_run.status_code == 422
        assert "完成一次校准运行" in missing_run.json()["detail"]

        run_response = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{plan['id']}/runs", json={"expected_row_version": plan["row_version"], "dataset_snapshot_id": snapshot_id}, headers=headers)
        assert run_response.status_code == 201, run_response.text
        run = run_response.json()
        assert run["current_valid"] is True
        assert run["evidence_level"] == "supervised"

        submitted_response = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{plan['id']}/submit", json={"expected_row_version": plan["row_version"]}, headers=headers)
        assert submitted_response.status_code == 200, submitted_response.text
        submitted = submitted_response.json()
        assert submitted["status"] == "pending_review"

        self_review = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{plan['id']}/review", json={"expected_row_version": submitted["row_version"], "decision": "approve", "comment": "同意采纳本次校准结果"}, headers=headers)
        assert self_review.status_code == 403
        assert "必须分离" in self_review.json()["detail"]

        before_approval = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{plan['id']}/model-changes", json={"expected_row_version": submitted["row_version"], "run_id": run["id"], "candidate_version": "CORP-20260903-CAL1", "change_reason": plan_payload["business_basis"]}, headers=headers)
        assert before_approval.status_code == 422
        assert "已批准" in before_approval.json()["detail"]

        approved_response = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{plan['id']}/review", json={"expected_row_version": submitted["row_version"], "decision": "approve", "comment": "证据充分，同意进入模型候选比较"}, headers=review_headers)
        assert approved_response.status_code == 200, approved_response.text
        approved = approved_response.json()
        assert approved["status"] == "approved"
        assert approved["reviewed_by"] == "risk-demo"

        created_response = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{plan['id']}/model-changes", json={"expected_row_version": approved["row_version"], "run_id": run["id"], "candidate_version": "CORP-20260903-CAL1", "change_reason": plan_payload["business_basis"]}, headers=headers)
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        assert created["status"] == "draft"
        assert created["calibration_evidence"]["schema_version"] == "credit-calibration-evidence-v2"
        assert created["calibration_evidence"]["plan_id"] == plan["id"]
        assert created["calibration_evidence"]["calibration_run_id"] == run["id"]
        assert created["calibration_evidence"]["current_valid"] is True

        direct_response = client.post("/api/v1/indicator-center/credit-calibration/model-changes", json={**request, "candidate_version": "BYPASS", "change_reason": "尝试绕过方案复核直接生成草稿", "expected_evidence_hash": run["evidence_hash"]}, headers=headers)
        assert direct_response.status_code == 410
        assert "独立复核" in direct_response.json()["detail"]

        second_payload = deepcopy(plan_payload)
        second_payload["candidate"]["score_threshold_shift"] = 3
        second_payload["business_basis"] = "对照测试更严格的评级门槛并检查组合迁移"
        second_plan_response = client.post("/api/v1/indicator-center/credit-calibration/plans", json=second_payload, headers=headers)
        assert second_plan_response.status_code == 201, second_plan_response.text
        second_plan = second_plan_response.json()
        assert second_plan["version"] == 2
        second_run_response = client.post(f"/api/v1/indicator-center/credit-calibration/plans/{second_plan['id']}/runs", json={"expected_row_version": second_plan["row_version"], "dataset_snapshot_id": snapshot_id}, headers=headers)
        assert second_run_response.status_code == 201, second_run_response.text

        comparison_response = client.post("/api/v1/indicator-center/credit-calibration/comparisons", json={"plan_ids": [plan["id"], second_plan["id"]]}, headers=headers)
        assert comparison_response.status_code == 200, comparison_response.text
        comparison = comparison_response.json()
        assert comparison["comparable"] is True
        assert len(comparison["items"]) == 2
        assert comparison["compatibility"] == {"same_snapshot": True, "same_baseline": True}

        updated_payload = {**second_payload, "expected_row_version": second_plan["row_version"]}
        updated_payload["candidate"] = {**second_payload["candidate"], "score_threshold_shift": 4}
        updated_response = client.put(f"/api/v1/indicator-center/credit-calibration/plans/{second_plan['id']}", json=updated_payload, headers=headers)
        assert updated_response.status_code == 200, updated_response.text
        updated = updated_response.json()
        assert updated["latest_valid_run_id"] is None
        assert updated["runs"][0]["current_valid"] is False

        with database.SessionLocal() as session:
            assert session.query(CreditCalibrationPlan).count() == 2
            assert session.query(CreditCalibrationRun).count() == 2
            record = session.get(ModelChangeRecord, created["id"])
            assert record is not None
            tampered = deepcopy(record.calibration_evidence_json)
            tampered["analysis"]["sample"]["paired_success_count"] += 1
            record.calibration_evidence_json = tampered
            session.commit()
        listed = client.get(
            "/api/v1/model-governance/changes?template_key=corporate_credit_v2", headers=headers
        ).json()
        assert listed[0]["calibration_evidence"]["current_valid"] is False
        assert "哈希不一致" in listed[0]["calibration_evidence"]["current_error"]
    finally:
        client.close()
        isolated.stop()
