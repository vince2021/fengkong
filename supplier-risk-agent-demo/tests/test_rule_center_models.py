from __future__ import annotations

import unittest
import uuid

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

import backend.database as database
from backend.database import Base
from backend.db_models import (
    DecisionPipelineDefinition,
    RuleCenterReleasePackage,
    RuleCenterReleasePackageMember,
    RuleCenterReplayComparisonRun,
    RuleCenterReplayDataset,
    RuleCenterReplayDatasetSnapshot,
    RuleCenterReplayRun,
    RuleDefinition,
    RuleSetDefinition,
)
from tests.database_support import IsolatedTestDatabase


class TestRuleCenterModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)

    def test_rule_definitions_table_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("rule_definitions", insp.get_table_names())
        cols = {c.name for c in RuleDefinition.__table__.columns}
        for expected in (
            "id", "code", "name", "rule_type", "category", "enabled",
            "conditions_json", "condition_relation", "actions_json",
            "priority", "version", "status", "is_active", "row_version",
            "created_at", "updated_at", "created_by",
        ):
            self.assertIn(expected, cols, f"missing column: {expected}")

    def test_rule_set_definitions_table_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("rule_set_definitions", insp.get_table_names())
        cols = {c.name for c in RuleSetDefinition.__table__.columns}
        for expected in (
            "id", "code", "name", "rule_codes", "evaluation_strategy",
            "version", "status", "is_active", "row_version",
        ):
            self.assertIn(expected, cols, f"missing column: {expected}")

    def test_decision_pipeline_definitions_table_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("decision_pipeline_definitions", insp.get_table_names())
        cols = {c.name for c in DecisionPipelineDefinition.__table__.columns}
        for expected in (
            "id", "code", "name", "stages_json",
            "version", "status", "is_active", "row_version",
        ):
            self.assertIn(expected, cols, f"missing column: {expected}")

    def test_rule_definition_has_single_active_index(self):
        indexes = RuleDefinition.__table__.indexes
        index_names = {idx.name for idx in indexes}
        self.assertIn("uq_rule_single_active", index_names)

    def test_rule_set_definition_has_single_active_index(self):
        indexes = RuleSetDefinition.__table__.indexes
        index_names = {idx.name for idx in indexes}
        self.assertIn("uq_rule_set_single_active", index_names)

    def test_pipeline_definition_has_single_active_index(self):
        indexes = DecisionPipelineDefinition.__table__.indexes
        index_names = {idx.name for idx in indexes}
        self.assertIn("uq_pipeline_single_active", index_names)

    def test_release_package_tables_and_constraints_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("rule_center_release_packages", insp.get_table_names())
        self.assertIn("rule_center_release_package_members", insp.get_table_names())
        package_columns = {column.name for column in RuleCenterReleasePackage.__table__.columns}
        member_columns = {column.name for column in RuleCenterReleasePackageMember.__table__.columns}
        self.assertTrue({"config_hash", "dependency_snapshot_json", "impact_json", "row_version"}.issubset(package_columns))
        self.assertTrue({"package_id", "change_id", "asset_type", "code", "candidate_version", "sequence"}.issubset(member_columns))
        constraints = {constraint.name for constraint in RuleCenterReleasePackageMember.__table__.constraints}
        self.assertIn("uq_rule_center_package_change", constraints)
        self.assertIn("uq_rule_center_package_asset", constraints)

    def test_replay_run_table_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("rule_center_replay_runs", insp.get_table_names())
        columns = {column.name for column in RuleCenterReplayRun.__table__.columns}
        self.assertTrue({
            "package_id", "package_config_hash", "model_key", "pipeline_code",
            "dataset_snapshot_id", "dataset_snapshot_hash",
            "thresholds_json", "metrics_json", "details_json", "gate_json",
            "evidence_hash", "created_by",
        }.issubset(columns))

    def test_replay_dataset_snapshot_tables_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("rule_center_replay_datasets", insp.get_table_names())
        self.assertIn("rule_center_replay_dataset_snapshots", insp.get_table_names())
        dataset_columns = {column.name for column in RuleCenterReplayDataset.__table__.columns}
        snapshot_columns = {column.name for column in RuleCenterReplayDatasetSnapshot.__table__.columns}
        self.assertTrue({"code", "name", "description", "status", "created_by"}.issubset(dataset_columns))
        self.assertTrue({
            "dataset_id", "version", "as_of_date", "field_mapping_json",
            "samples_json", "coverage_json", "source_hash", "content_hash",
        }.issubset(snapshot_columns))
        constraints = {constraint.name for constraint in RuleCenterReplayDatasetSnapshot.__table__.constraints}
        self.assertIn("uq_rule_center_replay_dataset_version", constraints)
        self.assertIn("uq_rule_center_replay_dataset_source", constraints)

    def test_replay_comparison_table_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("rule_center_replay_comparison_runs", insp.get_table_names())
        columns = {column.name for column in RuleCenterReplayComparisonRun.__table__.columns}
        self.assertTrue({
            "dataset_snapshot_id", "dataset_snapshot_hash", "champion_model_key",
            "champion_model_version", "challenger_model_key", "challenger_model_version",
            "champion_pipeline_code", "champion_pipeline_version",
            "challenger_pipeline_code", "challenger_pipeline_version",
            "segment_field", "evidence_level", "config_json", "metrics_json",
            "details_json", "evidence_hash", "created_by",
        }.issubset(columns))


def _make_rule(code, is_active=False):
    return RuleDefinition(
        id=str(uuid.uuid4()),
        code=code,
        name=f"Rule {code}",
        rule_type="strong_rule",
        enabled=True,
        conditions_json=[{"expression": "x > 0", "operator": ">", "value": 0}],
        condition_relation="all",
        actions_json=[{"type": "override", "field": "rating", "value": "D"}],
        priority=1,
        version=1,
        status="draft",
        is_active=is_active,
        row_version=1,
        created_by="test",
    )


class TestRuleSingleActiveConstraint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)

    def test_two_active_same_code_rejected(self):
        session = database.SessionLocal()
        try:
            r1 = _make_rule("SR-001", is_active=True)
            session.add(r1)
            session.commit()
            r2 = _make_rule("SR-001", is_active=True)
            r2.version = 2  # different version, same code → partial unique should reject
            session.add(r2)
            with self.assertRaises(IntegrityError):
                session.commit()
        finally:
            session.rollback()
            session.close()

    def test_multiple_inactive_same_code_allowed(self):
        session = database.SessionLocal()
        try:
            r1 = _make_rule("SR-002", is_active=False)
            r2 = _make_rule("SR-002", is_active=False)
            r2.version = 2  # (code, version) must be unique
            session.add(r1)
            session.add(r2)
            session.commit()
            count = session.query(RuleDefinition).filter_by(code="SR-002").count()
            self.assertEqual(count, 2)
        finally:
            session.rollback()
            session.close()


if __name__ == "__main__":
    unittest.main()
