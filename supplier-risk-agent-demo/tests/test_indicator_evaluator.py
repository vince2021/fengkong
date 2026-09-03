from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import inspect

import backend.database as database
from backend.database import Base
from backend.db_models import IndicatorDefinition, ModelChangeRecord
from tests.database_support import IsolatedTestDatabase
from rating.indicator_evaluator import (
    CircularDependencyError,
    load_active_indicators,
    topological_sort,
)


class TestIndicatorDefinitionModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)

    def test_indicator_table_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("indicator_definitions", insp.get_table_names())

    def test_model_change_has_entity_type(self):
        cols = {c.name for c in ModelChangeRecord.__table__.columns}
        self.assertIn("entity_type", cols)


def _make_indicator(code, layer="atomic", deps=None, category="external_risk", status="published"):
    now = datetime.now(timezone.utc)
    return IndicatorDefinition(
        id=str(uuid.uuid4()), code=code, name=code, category=category,
        layer=layer, data_type="numeric",
        field_path=f"enterprise_risk.{code}" if layer == "atomic" else None,
        expression=f"{deps[0]} / 1" if deps else None,
        dependencies=deps, scoring_json={"type": "boolean_hit", "missing_score": 2},
        max_score=3, default_weight=1.0, seed_source="test",
        version=1, status=status, is_active=True, row_version=1,
        created_at=now, created_by="test",
    )


class TestLoadAndSort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = database.SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_load_active_filters_published_active(self):
        self.session.add(_make_indicator("A"))
        self.session.add(_make_indicator("B", status="draft"))
        self.session.commit()

        result = load_active_indicators()
        self.assertEqual([i.code for i in result], ["A"])

    def test_topological_sort_atomic_first(self):
        indicators = [
            _make_indicator("C", layer="derived", deps=["A"]),
            _make_indicator("A"),
            _make_indicator("B", layer="derived", deps=["A"]),
        ]
        sorted_list = topological_sort(indicators)
        codes = [i.code for i in sorted_list]
        self.assertEqual(codes[0], "A")
        self.assertLess(codes.index("A"), codes.index("C"))

    def test_circular_dependency_detected(self):
        indicators = [
            _make_indicator("A", layer="derived", deps=["B"]),
            _make_indicator("B", layer="derived", deps=["A"]),
        ]
        with self.assertRaises(CircularDependencyError):
            topological_sort(indicators)


from rating.indicator_evaluator import evaluate_indicator, evaluate_indicator_pool_v2


class TestEvaluateIndicator(unittest.TestCase):
    def test_atomic_direct_field(self):
        ind = _make_indicator("A")
        ind.scoring_json = {"type": "boolean_hit", "direction": "false_is_better",
            "bands": [{"operator": "==", "value": False, "score": 3},
                      {"operator": "==", "value": True, "score": 2}],
            "missing_score": 2}
        counterparty = {"enterprise_risk": {"A": False}}
        result = evaluate_indicator(ind, counterparty)
        self.assertEqual(result["score"], 3.0)
        self.assertEqual(result["data_status"], "已取得")

    def test_numeric_bands(self):
        ind = _make_indicator("NUM")
        ind.scoring_json = {"type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 3, "score": 1},
                      {"operator": "<", "value": 3, "score": 3}],
            "missing_score": 2}
        counterparty = {"enterprise_risk": {"NUM": 5}}
        result = evaluate_indicator(ind, counterparty)
        self.assertEqual(result["score"], 1.0)

    def test_missing_field_degrades(self):
        ind = _make_indicator("A")
        ind.scoring_json = {"type": "boolean_hit", "missing_score": 2}
        result = evaluate_indicator(ind, {})
        self.assertEqual(result["score"], 2.0)
        self.assertEqual(result["data_status"], "待补充")

    def test_zero_division_degrades(self):
        ind = _make_indicator("RATIO", layer="derived", deps=["a", "b"])
        ind.expression = "a / b"
        ind.scoring_json = {"type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 0, "score": 1}], "missing_score": 5}
        counterparty = {"a": 1, "b": 0}
        result = evaluate_indicator(ind, counterparty)
        self.assertEqual(result["score"], 5.0)


class TestPoolV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = database.SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_empty_returns_none(self):
        self.assertIsNone(evaluate_indicator_pool_v2({"id": "x"}, {}))

    def test_returns_pool_structure_aligned_with_v1(self):
        ind = _make_indicator("A")
        ind.scoring_json = {"type": "boolean_hit",
            "bands": [{"operator": "==", "value": False, "score": 3},
                      {"operator": "==", "value": True, "score": 2}],
            "missing_score": 2}
        self.session.add(ind)
        self.session.commit()
        result = evaluate_indicator_pool_v2(
            {"id": "x", "enterprise_risk": {"A": False}}, {}
        )
        self.assertIsNotNone(result)
        self.assertIn("normalized_score", result)
        self.assertIn("completeness", result)
        self.assertIn("missing_count", result)
        self.assertIn("details", result)
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(result["details"][0]["score"], 3.0)
        self.assertEqual(result["details"][0]["data_status"], "已取得")


if __name__ == "__main__":
    unittest.main()
