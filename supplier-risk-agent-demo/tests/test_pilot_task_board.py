from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import MODEL_TEMPLATES_PATH, resolve_template
from rating.pilot_field_mapping import build_pilot_field_mapping_package
from rating.pilot_task_board import build_pilot_task_board, build_pilot_task_board_markdown


class PilotTaskBoardTest(unittest.TestCase):
    def setUp(self) -> None:
        templates = json.loads(Path(MODEL_TEMPLATES_PATH).read_text(encoding="utf-8"))["templates"]
        model_config = resolve_template("pharma", templates)
        self.mapping_package = build_pilot_field_mapping_package("pharma", model_config)

    def test_builds_task_board_from_data_readiness_checklist(self) -> None:
        board = build_pilot_task_board(self.mapping_package)

        self.assertEqual(board["title"], "医药流通试点任务看板")
        self.assertEqual(board["summary"]["任务总数"], "12 项")
        self.assertIn("status_summary", board)
        self.assertIn("columns", board)
        self.assertIn("risk_tasks", board)
        self.assertEqual(set(board["columns"].keys()), {"待客户提供", "已收到", "待映射", "有缺口", "已确认"})
        self.assertTrue(any(task["字段名"] == "统一社会信用代码" and task["状态"] == "待客户提供" for task in board["tasks"]))
        self.assertTrue(any(task["字段名"] == "模型版本" and task["状态"] == "已确认" for task in board["tasks"]))
        self.assertTrue(all("当前动作" in task and "截止时间" in task for task in board["tasks"]))

    def test_highlights_blocking_tasks(self) -> None:
        board = build_pilot_task_board(self.mapping_package)

        self.assertGreaterEqual(len(board["risk_tasks"]), 3)
        self.assertTrue(all(task["阻塞影响"] for task in board["risk_tasks"]))
        self.assertTrue(any(task["字段名"] == "统一社会信用代码" for task in board["risk_tasks"]))
        self.assertTrue(any(task["字段名"] == "登记状态" and task["状态"] == "待映射" for task in board["risk_tasks"]))
        self.assertTrue(any(task["字段名"] == "重大诉讼金额" and task["状态"] == "待映射" for task in board["risk_tasks"]))

    def test_markdown_is_customer_ready(self) -> None:
        board = build_pilot_task_board(self.mapping_package)
        markdown = build_pilot_task_board_markdown(board)

        self.assertIn("# 医药流通试点任务看板", markdown)
        self.assertIn("## 状态汇总", markdown)
        self.assertIn("## 待客户提供", markdown)
        self.assertIn("## 有缺口", markdown)
        self.assertIn("统一社会信用代码", markdown)
        self.assertNotIn("TODO", markdown)


if __name__ == "__main__":
    unittest.main()
