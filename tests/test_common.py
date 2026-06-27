from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402


class CommonTest(unittest.TestCase):
    def test_market_session_ignores_environment_proxies(self) -> None:
        session = common.market_session()

        self.assertFalse(session.trust_env)

    def test_fund_amount_normalization_preserves_internal_precision(self) -> None:
        rows = common.ensure_required_fund_columns(
            [
                {
                    "板块": "农业综合Ⅱ",
                    "净流入（亿）": -0.0036,
                    "超大单（亿）": -0.01,
                    "大单（亿）": 0.0064,
                    "小单（亿）": 0.02,
                    "涨跌幅 %": -1.98,
                    "成交额（亿）": 0.71,
                    "净流入率 %": -0.51,
                }
            ]
        )

        row = rows[0]
        self.assertEqual(row["净流入（亿）"], -0.0036)
        self.assertEqual(row["大单（亿）"], 0.0064)


if __name__ == "__main__":
    unittest.main()
