from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import inspect

import backend.database as database
from backend.database import Base
from backend.db_models import IndicatorDefinition, ModelChangeRecord
from rating.indicator_evaluator import (
    CircularDependencyError,
    MissingDependencyError,
    evaluate_indicator,
    evaluate_indicator_pool_v2,
    load_active_indicators,
    topological_sort,
)
from tests.database_support import IsolatedTestDatabase


def _make_indicator(
    code: str,
    *,
    layer: str = "atomic",
    dependencies: list[str] | None = None,
    category: str = "external_risk",
    status: str = "published",
    is_active: bool = True,
) -> IndicatorDefinition:
    return IndicatorDefinition(
        id=str(uuid.uuid4()),
        code=code,
        name=code,
        category=category,
        layer=layer,
        data_type="numeric",
        field_path=f"enterprise_risk.{code}" if layer == "atomic" else None,
        expression=f"{dependencies[0]} / 1" if dependencies else None,
        dependencies=dependencies,
        scoring_json={"type": "boolean_hit", "missing_score": 2},
        max_score=3,
        default_weight=1.0,
        seed_source="test",
        version=1,
        status=status,
        is_active=is_active,
        row_version=1,
        created_at=datetime.now(timezone.utc),
        created_by="test",
    )


class TestIndicatorDefinitionModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)

    def test_indicator_table_created(self):
        inspector = inspect(self.db.engine)
        self.assertIn("indicator_definitions", inspector.get_table_names())

    def test_model_change_has_entity_type(self):
        columns = {column.name for column in ModelChangeRecord.__table__.columns}
        self.assertIn("entity_type", columns)

    def test_indicator_version_and_active_indexes_created(self):
        inspector = inspect(self.db.engine)
        constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("indicator_definitions")
        }
        indexes = {
            index["name"]: index
            for index in inspector.get_indexes("indicator_definitions")
        }
        self.assertIn("uq_indicator_code_version", constraints)
        self.assertTrue(indexes["uq_indicator_single_active"]["unique"])


class TestLoadAndSort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = database.SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_load_active_filters_status_activity_and_category(self):
        self.session.add(_make_indicator("A"))
        self.session.add(_make_indicator("B", status="draft"))
        self.session.add(_make_indicator("C", is_active=False))
        self.session.add(_make_indicator("D", category="financial_credit"))
        self.session.commit()

        all_active = load_active_indicators()
        external = load_active_indicators(category="external_risk")

        self.assertEqual([indicator.code for indicator in all_active], ["A", "D"])
        self.assertEqual([indicator.code for indicator in external], ["A"])

    def test_topological_sort_places_dependencies_and_atomic_layer_first(self):
        indicators = [
            _make_indicator("C", layer="composite", dependencies=["B"]),
            _make_indicator("B", layer="derived", dependencies=["A"]),
            _make_indicator("Z", layer="derived"),
            _make_indicator("A"),
        ]

        codes = [indicator.code for indicator in topological_sort(indicators)]

        self.assertEqual(codes, ["A", "B", "Z", "C"])

    def test_circular_dependency_detected_with_path(self):
        indicators = [
            _make_indicator("A", layer="derived", dependencies=["B"]),
            _make_indicator("B", layer="derived", dependencies=["A"]),
        ]

        with self.assertRaisesRegex(CircularDependencyError, "A -> B -> A"):
            topological_sort(indicators)

    def test_missing_dependency_is_rejected(self):
        indicators = [
            _make_indicator("A", layer="derived", dependencies=["UNKNOWN"])
        ]

        with self.assertRaisesRegex(MissingDependencyError, "UNKNOWN"):
            topological_sort(indicators)


class TestEvaluateIndicator(unittest.TestCase):
    def test_atomic_direct_field(self):
        indicator = _make_indicator("A")
        indicator.scoring_json = {
            "type": "boolean_hit",
            "direction": "false_is_better",
            "bands": [
                {"operator": "==", "value": False, "score": 3},
                {"operator": "==", "value": True, "score": 2},
            ],
            "missing_score": 2,
        }

        result = evaluate_indicator(
            indicator, {"enterprise_risk": {"A": False}}
        )

        self.assertEqual(result["score"], 3.0)
        self.assertEqual(result["actual_value"], False)
        self.assertEqual(result["data_status"], "已取得")

    def test_numeric_bands_use_first_matching_band(self):
        indicator = _make_indicator("NUM")
        indicator.scoring_json = {
            "type": "numeric_bands",
            "bands": [
                {"operator": ">=", "value": 3, "score": 1},
                {"operator": "<", "value": 3, "score": 3},
            ],
            "missing_score": 2,
        }

        result = evaluate_indicator(
            indicator, {"enterprise_risk": {"NUM": 5}}
        )

        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["actual_display"], "5")

    def test_derived_expression_is_scored(self):
        indicator = _make_indicator(
            "RATIO", layer="derived", dependencies=["a", "b"]
        )
        indicator.expression = "a / b"
        indicator.scoring_json = {
            "type": "numeric_bands",
            "bands": [
                {"operator": "<=", "value": 0.5, "score": 3},
                {"operator": ">", "value": 0.5, "score": 1},
            ],
            "missing_score": 2,
            "formula": "a / b",
        }

        result = evaluate_indicator(indicator, {"a": 40, "b": 100})

        self.assertEqual(result["actual_value"], 0.4)
        self.assertEqual(result["score"], 3.0)
        self.assertEqual(result["formula"], "a / b")

    def test_composite_boolean_uses_configured_bands(self):
        indicator = _make_indicator(
            "COMPOSITE", layer="composite", dependencies=["a", "b"]
        )
        indicator.expression = "a > 0 and b > 0"
        indicator.scoring_json = {
            "type": "composite_boolean",
            "bands": [
                {"operator": "==", "value": True, "score": 1},
                {"operator": "==", "value": False, "score": 3},
            ],
            "missing_score": 2,
        }

        result = evaluate_indicator(indicator, {"a": 1, "b": 2})

        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["actual_display"], "已触发")

    def test_legacy_composite_boolean_uses_input_fields(self):
        indicator = _make_indicator("JOINT_CHANGE")
        indicator.scoring_json = {
            "type": "composite_boolean",
            "input_fields": ["external.legal_change", "external.key_change"],
            "bands": [
                {"operator": "both_true", "score": 1},
                {"operator": "any_true", "score": 2},
                {"operator": "none_true", "score": 3},
            ],
            "missing_score": 2,
        }

        result = evaluate_indicator(
            indicator,
            {"external": {"legal_change": 1, "key_change": 2}},
        )

        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["data_status"], "已取得")
        self.assertEqual(result["actual_display"], "复合命中 2/2")

    def test_missing_field_degrades(self):
        indicator = _make_indicator("A")
        indicator.scoring_json = {
            "type": "boolean_hit",
            "bands": [
                {"operator": "==", "value": False, "score": 3},
                {"operator": "==", "value": True, "score": 2},
            ],
            "missing_score": 2,
        }

        result = evaluate_indicator(indicator, {})

        self.assertEqual(result["score"], 2.0)
        self.assertEqual(result["data_status"], "待补充")

    def test_zero_division_degrades(self):
        indicator = _make_indicator(
            "RATIO", layer="derived", dependencies=["a", "b"]
        )
        indicator.expression = "a / b"
        indicator.scoring_json = {
            "type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 0, "score": 1}],
            "missing_score": 5,
        }

        result = evaluate_indicator(indicator, {"a": 1, "b": 0})

        self.assertEqual(result["score"], 5.0)
        self.assertIsNone(result["actual_value"])
        self.assertEqual(result["data_status"], "待补充")

    def test_invalid_scoring_configuration_degrades(self):
        indicator = _make_indicator("A")
        indicator.scoring_json = {
            "type": "boolean_hit",
            "bands": [{"operator": "contains", "value": True, "score": 1}],
            "missing_score": 2,
        }

        result = evaluate_indicator(
            indicator, {"enterprise_risk": {"A": True}}
        )

        self.assertEqual(result["score"], 2.0)
        self.assertEqual(result["data_status"], "待补充")


class TestPoolV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = database.SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_empty_pool_returns_none_for_v1_fallback(self):
        self.assertIsNone(evaluate_indicator_pool_v2({"id": "x"}, {}))

    def test_returns_pool_structure_aligned_with_v1(self):
        indicator = _make_indicator("A")
        indicator.scoring_json = {
            "type": "boolean_hit",
            "bands": [
                {"operator": "==", "value": False, "score": 3},
                {"operator": "==", "value": True, "score": 2},
            ],
            "missing_score": 2,
        }
        self.session.add(indicator)
        self.session.commit()

        result = evaluate_indicator_pool_v2(
            {"id": "x", "enterprise_risk": {"A": False}}, {}
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["pool_version"], "indicator-factory-v2")
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(result["available_count"], 1)
        self.assertEqual(result["missing_count"], 0)
        self.assertEqual(result["completeness"], 1.0)
        self.assertEqual(result["weighted_score"], 3.0)
        self.assertEqual(result["normalized_score"], 100.0)
        self.assertEqual(result["details"][0]["score"], 3.0)
        self.assertEqual(result["details"][0]["data_status"], "已取得")

    def test_injects_dependency_values_without_mutating_counterparty(self):
        atomic = _make_indicator("A")
        atomic.scoring_json = {
            "type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 0, "score": 3}],
            "missing_score": 2,
        }
        derived = _make_indicator(
            "DOUBLE_A", layer="derived", dependencies=["A"]
        )
        derived.expression = "A * 2"
        derived.scoring_json = {
            "type": "numeric_bands",
            "bands": [
                {"operator": ">=", "value": 8, "score": 1},
                {"operator": "<", "value": 8, "score": 3},
            ],
            "missing_score": 2,
        }
        self.session.add_all([derived, atomic])
        self.session.commit()
        counterparty = {"id": "x", "enterprise_risk": {"A": 4}}

        result = evaluate_indicator_pool_v2(counterparty, {})

        assert result is not None
        self.assertEqual(
            [detail["indicator_id"] for detail in result["details"]],
            ["A", "DOUBLE_A"],
        )
        self.assertEqual(result["details"][1]["actual_value"], 8)
        self.assertEqual(result["details"][1]["score"], 1.0)
        self.assertEqual(result["weighted_score"], 2.0)
        self.assertEqual(result["normalized_score"], 50.0)
        self.assertNotIn("A", counterparty)

    def test_missing_dependency_value_cascades_as_missing(self):
        atomic = _make_indicator("A")
        atomic.scoring_json = {
            "type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 0, "score": 3}],
            "missing_score": 2,
        }
        derived = _make_indicator(
            "DOUBLE_A", layer="derived", dependencies=["A"]
        )
        derived.expression = "A * 2"
        derived.scoring_json = {
            "type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 0, "score": 3}],
            "missing_score": 2,
        }
        self.session.add_all([atomic, derived])
        self.session.commit()

        result = evaluate_indicator_pool_v2({"id": "x"}, {})

        assert result is not None
        self.assertEqual(result["available_count"], 0)
        self.assertEqual(result["missing_count"], 2)
        self.assertEqual(result["completeness"], 0.0)
        self.assertTrue(
            all(detail["data_status"] == "待补充" for detail in result["details"])
        )

    def test_configured_selection_filters_pool_and_applies_weight(self):
        first = _make_indicator("A")
        second = _make_indicator("B")
        for indicator in (first, second):
            indicator.scoring_json = {
                "type": "numeric_bands",
                "bands": [{"operator": ">=", "value": 0, "score": 3}],
                "missing_score": 2,
            }
        self.session.add_all([first, second])
        self.session.commit()

        result = evaluate_indicator_pool_v2(
            {"enterprise_risk": {"A": 1, "B": 1}},
            {
                "indicator_selection": [
                    {"indicator_id": "B", "weight": 2.5, "enabled": True},
                    {"indicator_id": "A", "weight": 1, "enabled": False},
                ]
            },
        )

        assert result is not None
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(result["details"][0]["indicator_id"], "B")
        self.assertEqual(result["details"][0]["model_weight"], 2.5)

    def test_missing_configured_definition_requests_v1_fallback(self):
        self.session.add(_make_indicator("A"))
        self.session.commit()

        result = evaluate_indicator_pool_v2(
            {"enterprise_risk": {"A": False}},
            {
                "indicator_selection": [
                    {"indicator_id": "NOT_ACTIVE", "weight": 1, "enabled": True}
                ]
            },
        )

        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
