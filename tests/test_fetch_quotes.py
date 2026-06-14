from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_quotes  # noqa: E402


class FetchQuotesTest(unittest.TestCase):
    def test_parse_sohu_historical_quote(self) -> None:
        payload = [
            {
                "status": 0,
                "hq": [["2026-06-12", "1271.18", "1291.91", "12.91", "1.01%", "1265.01", "1295.00", "50495", "647791.00", "0.40%"]],
                "code": "cn_600519",
            }
        ]

        quote = fetch_quotes.parse_sohu_historical_quote(payload, "600519", "贵州茅台")

        self.assertEqual(quote["交易日期"], "2026-06-12")
        self.assertEqual(quote["收盘价"], 1291.91)
        self.assertEqual(quote["涨跌幅"], 1.01)
        self.assertEqual(quote["成交额（亿）"], 64.78)
        self.assertEqual(quote["开盘价"], 1271.18)
        self.assertEqual(quote["最低价"], 1265.01)
        self.assertEqual(quote["最高价"], 1295.0)
        self.assertEqual(quote["换手率"], 0.4)
        self.assertEqual(quote["source"], "sohu.hisHq")

    def test_build_quote_from_tushare_rows(self) -> None:
        quote = fetch_quotes.build_quote_from_tushare_rows(
            "600519",
            "贵州茅台",
            {
                "ts_code": "600519.SH",
                "trade_date": "20260612",
                "open": 1271.18,
                "high": 1295.0,
                "low": 1265.01,
                "close": 1291.91,
                "pct_chg": 1.009,
                "amount": 6477910.214,
            },
            {
                "ts_code": "600519.SH",
                "pe": 19.52,
                "total_mv": 161499300.0,
                "turnover_rate": 0.40,
            },
        )

        self.assertEqual(quote["交易日期"], "2026-06-12")
        self.assertEqual(quote["收盘价"], 1291.91)
        self.assertEqual(quote["涨跌幅"], 1.01)
        self.assertEqual(quote["成交额（亿）"], 64.78)
        self.assertEqual(quote["PE"], 19.52)
        self.assertEqual(quote["总市值（亿）"], 16149.93)
        self.assertEqual(quote["source"], "tushare.daily+daily_basic")

    def test_parse_tencent_quote_line(self) -> None:
        line = (
            'v_sh600519="1~贵州茅台~600519~1291.91~1279.00~1271.18~50495~24976~25519~'
            '1291.91~87~1291.90~1~1291.89~1~1291.88~42~1291.75~3~1292.00~11~1292.32~5~'
            '1292.33~1~1292.38~1~1292.40~6~~20260612161418~12.91~1.01~1295.00~1265.01~'
            '1291.91/50495/6477910214~50495~647791~0.40~19.52~~1295.00~1265.01~2.34~'
            '16149.93~16149.93~6.03~1406.90~1151.10~1.63~110~1282.89~14.82~19.62";'
        )

        quote = fetch_quotes.parse_tencent_quote_line(line, "600519", "贵州茅台")

        self.assertEqual(quote["股票名称"], "贵州茅台")
        self.assertEqual(quote["股票代码"], "600519")
        self.assertEqual(quote["交易日期"], "2026-06-12")
        self.assertEqual(quote["收盘价"], 1291.91)
        self.assertEqual(quote["涨跌幅"], 1.01)
        self.assertEqual(quote["成交额（亿）"], 64.78)
        self.assertEqual(quote["PE"], 19.52)

    def test_enrich_quote_fills_missing_fields_without_overwriting_price(self) -> None:
        quote = {
            "收盘价": 1291.91,
            "PE": None,
            "总市值（亿）": None,
            "source": "tushare.daily+daily_basic",
        }
        fallback = {
            "收盘价": 1290.0,
            "PE": 19.52,
            "总市值（亿）": 16149.93,
            "振幅": 2.34,
            "source": "tencent.qt.gtimg.quote",
        }

        fetch_quotes.enrich_quote_missing_fields(quote, fallback, "tencent.enrich")

        self.assertEqual(quote["收盘价"], 1291.91)
        self.assertEqual(quote["PE"], 19.52)
        self.assertEqual(quote["总市值（亿）"], 16149.93)
        self.assertEqual(quote["振幅"], 2.34)
        self.assertEqual(quote["source"], "tushare.daily+daily_basic+tencent.enrich")


if __name__ == "__main__":
    unittest.main()
