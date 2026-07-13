from __future__ import annotations

import unittest

from rating.ui_presenters import badge_html, key_value_panel_html, risk_tone, rows_table_html


class UiPresentersTest(unittest.TestCase):
    def test_maps_business_status_to_visual_tone(self) -> None:
        self.assertEqual(risk_tone("AA"), "success")
        self.assertEqual(risk_tone("自动准入"), "success")
        self.assertEqual(risk_tone("人工复核"), "warning")
        self.assertEqual(risk_tone("重点监控"), "warning")
        self.assertEqual(risk_tone("禁入"), "danger")
        self.assertEqual(risk_tone("D"), "danger")
        self.assertEqual(risk_tone("-"), "neutral")

    def test_badge_html_escapes_label_and_uses_tone_class(self) -> None:
        html = badge_html("<禁入>", "danger")

        self.assertIn('class="risk-badge risk-badge-danger"', html)
        self.assertIn("&lt;禁入&gt;", html)
        self.assertNotIn("<禁入>", html)

    def test_rows_table_html_renders_enterprise_table_and_escapes_content(self) -> None:
        html = rows_table_html(
            [
                {
                    "客商名称": "深圳<星海>科技",
                    "评级": "AA",
                    "风险分层": "优质客商",
                    "准入策略": "自动准入",
                    "需复核": "否",
                }
            ]
        )

        self.assertIn('class="risk-table"', html)
        self.assertIn("&lt;星海&gt;", html)
        self.assertIn('class="risk-badge risk-badge-success"', html)

    def test_key_value_panel_html_uses_review_badge_for_boolean_values(self) -> None:
        html = key_value_panel_html({"企业名称": "江门启航智能装备有限公司", "需人工复核": True})

        self.assertIn('class="kv-panel"', html)
        self.assertIn("江门启航智能装备有限公司", html)
        self.assertIn("需要", html)
        self.assertIn('risk-badge-warning', html)


if __name__ == "__main__":
    unittest.main()
