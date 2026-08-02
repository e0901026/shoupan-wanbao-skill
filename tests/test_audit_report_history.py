from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_report_history  # noqa: E402


class AuditReportHistoryTest(unittest.TestCase):
    def valid_analysis(self) -> dict:
        row = {
            "板块": "半导体",
            "净流入（亿）": 3.0,
            "超大单（亿）": 2.0,
            "大单（亿）": 1.0,
            "小单（亿）": -1.0,
            "涨跌幅 %": 1.0,
        }
        liquor = [
            {**row, "板块": "白酒Ⅱ"},
            {**row, "板块": "贵州茅台"},
        ]
        return {
            "quality_issues": [],
            "quotes": {
                "quotes": {
                    "600519": {
                        "交易日期": "2026-07-17",
                        "前收盘价": 1258.99,
                        "收盘价": 1253.0,
                        "涨跌额": -5.99,
                        "涨跌幅": -0.48,
                    }
                },
                "cross_checks": {"600519": {"status": "matched"}},
            },
            "fund_flow": {
                "quality": {"level": "complete", "source_mode": "tushare_sw2_stock_moneyflow_aggregate"},
                "inflow_top5": [row],
                "outflow_top5": [{**row, "板块": "银行", "净流入（亿）": -3.0, "超大单（亿）": -2.0, "大单（亿）": -1.0}],
                "divergence_net_inflow_price_down": [],
                "divergence_net_outflow_price_up": [],
                "divergence_super_in_large_out": [],
                "divergence_super_out_large_in": [],
                "baijiu": liquor,
            },
            "macro": {"h15": {"latest_date": "2026-07-17", "treasury_10y_year_observation_date": "2026-07-17"}},
        }

    def test_valid_analysis_passes(self) -> None:
        self.assertEqual(audit_report_history.audit_analysis("2026-07-17", self.valid_analysis()), [])

    def test_wrong_fund_equation_fails(self) -> None:
        analysis = self.valid_analysis()
        analysis["fund_flow"]["baijiu"][0]["净流入（亿）"] = 9.0
        issues = audit_report_history.audit_analysis("2026-07-17", analysis)
        self.assertTrue(any("主力净流入不等于" in issue for issue in issues))

    def test_future_macro_observation_fails(self) -> None:
        analysis = self.valid_analysis()
        analysis["macro"]["h15"]["latest_date"] = "2026-07-30"
        issues = audit_report_history.audit_analysis("2026-07-17", analysis)
        self.assertTrue(any("宏观利率发生历史穿越" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
