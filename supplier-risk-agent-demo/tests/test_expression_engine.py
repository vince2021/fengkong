from __future__ import annotations

import unittest

from rating.expression_engine import (
    ExpressionSecurityError,
    evaluate_expression,
)


class TestExpressionSecurity(unittest.TestCase):
    def test_rejects_attribute_access(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("().__class__", {})

    def test_rejects_import(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("import os", {})

    def test_rejects_subscript(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("x[0]", {"x": [1]})

    def test_rejects_unknown_function(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("eval('1')", {})


class TestExpressionEvaluation(unittest.TestCase):
    def test_binop_division(self):
        self.assertAlmostEqual(
            evaluate_expression("a / b", {"a": 80, "b": 200}), 0.4
        )

    def test_compare_and_boolop(self):
        self.assertTrue(
            evaluate_expression("a > 0.7 and b < 1.0", {"a": 0.8, "b": 0.5})
        )

    def test_safe_function_clamp(self):
        self.assertEqual(
            evaluate_expression("clamp(a * 100, 0, 100)", {"a": 1.2}), 100
        )

    def test_missing_field_raises(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("a + 1", {})


class TestExpressionDegrade(unittest.TestCase):
    def test_zero_division_propagates(self):
        with self.assertRaises(ZeroDivisionError):
            evaluate_expression("a / b", {"a": 1, "b": 0})


if __name__ == "__main__":
    unittest.main()
