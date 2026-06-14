from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_macro  # noqa: E402


class FetchMacroTest(unittest.TestCase):
    def test_parse_h15_html_extracts_fed_funds_and_treasury_curve(self) -> None:
        html = """
        <table>
          <tr><th>Instruments</th><th>2026 Jun 10</th><th>2026 Jun 11</th></tr>
          <tr><th>Federal funds (effective) 1 2 3</th><td>3.62</td><td>3.62</td></tr>
          <tr><th>Treasury constant maturities</th><td></td><td></td></tr>
          <tr><th>Nominal 9</th><td></td><td></td></tr>
          <tr><th>2-year</th><td>4.13</td><td>4.05</td></tr>
          <tr><th>10-year</th><td>4.55</td><td>4.45</td></tr>
          <tr><th>30-year</th><td>5.03</td><td>4.95</td></tr>
          <tr><th>Inflation indexed</th><td></td><td></td></tr>
        </table>
        """

        data = fetch_macro.parse_h15_html(html)

        self.assertEqual(data["latest_date"], "2026 Jun 11")
        self.assertEqual(data["effective_federal_funds_rate"], 3.62)
        self.assertEqual(data["treasury_10y_year"], 4.45)
        self.assertEqual(data["treasury_10y_year_change_bp"], -10.0)

    def test_build_macro_items_outputs_fomc_ten_year_and_future_event_window(self) -> None:
        items = fetch_macro.build_macro_items(
            {
                "latest_date": "2026 Jun 11",
                "effective_federal_funds_rate": 3.62,
                "treasury_2y_year": 4.05,
                "treasury_10y_year": 4.45,
                "treasury_10y_year_change_bp": -10.0,
                "treasury_30y_year": 4.95,
            },
            "2026-06-12",
        )

        self.assertEqual(len(items), 3)
        self.assertTrue(all(item["category"] == "宏观与风险事件" for item in items))
        self.assertIn("6月FOMC", items[0]["title"])
        self.assertIn("10 年期国债收益率 4.45%", items[1]["summary"])
        self.assertIn("2026-06-16", items[0]["summary"])
        self.assertIn("未来宏观数据窗口", items[2]["title"])
        self.assertIn("2026-06-25 美国5月PCE", items[2]["summary"])
        self.assertIn("2026-07-02 美国6月非农就业", items[2]["summary"])
        self.assertIn("A股资金流向", items[2]["summary"])

    def test_build_macro_items_keeps_future_events_even_when_h15_is_missing(self) -> None:
        items = fetch_macro.build_macro_items({}, "2026-06-12")

        titles = [item["title"] for item in items]
        self.assertIn("未来宏观数据窗口：PCE、非农、CPI/PPI将影响资金流向", titles)


if __name__ == "__main__":
    unittest.main()
