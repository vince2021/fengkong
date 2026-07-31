from __future__ import annotations

import unittest

from backend.document_policy import document_type_satisfied, missing_document_types
from rating.approval_workflow import WORKFLOW_STAGES, advance_approval_case, build_workflow_progress, create_approval_case


class ApprovalWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.counterparty = {"id": "CP-001", "name": "测试企业"}

    def test_builds_complete_sequential_workflow(self) -> None:
        case = create_approval_case(self.counterparty)
        self.assertEqual(len(WORKFLOW_STAGES), 8)
        self.assertEqual(case["current_stage"], "registration")
        case = advance_approval_case(case, {"registered_name": "测试企业", "unified_social_credit_code": "914400001", "contact_name": "张三"}, "客户经理")
        self.assertEqual(case["current_stage"], "document_upload")
        self.assertEqual(build_workflow_progress(case)[0]["状态"], "已完成")

    def test_rejects_incomplete_documents(self) -> None:
        case = create_approval_case(self.counterparty)
        case = advance_approval_case(case, {"registered_name": "测试企业", "unified_social_credit_code": "914400001", "contact_name": "张三"}, "客户经理")
        with self.assertRaises(ValueError):
            advance_approval_case(case, {"documents": ["营业执照"]}, "客户")

    def test_supplement_gate_accepts_catalog_financial_and_contract_equivalents(self) -> None:
        verified = {"营业执照", "近三年审计报告", "征信授权书", "主要业务合同"}

        self.assertTrue(document_type_satisfied("财务报表", verified))
        self.assertTrue(document_type_satisfied("业务合同", verified))
        self.assertEqual(
            missing_document_types({"营业执照", "财务报表", "征信授权书", "业务合同"}, verified),
            [],
        )


if __name__ == "__main__":
    unittest.main()
