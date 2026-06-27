from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_sector_fund_flow  # noqa: E402


class FetchSectorFundFlowTest(unittest.TestCase):
    def test_eastmoney_item_to_row_converts_yuan_to_yi_even_for_small_values(self) -> None:
        row = fetch_sector_fund_flow.eastmoney_item_to_row(
            {
                "f14": "农业综合Ⅱ",
                "f62": -233157.0,
                "f66": 2000000.0,
                "f72": -2233157.0,
                "f78": 1000000.0,
                "f84": -500000.0,
                "f3": 1.08,
                "f6": 127000000.0,
                "f184": -0.18,
                "f124": 1781249985,
                "f12": "BK0001",
            },
            "industry",
        )

        self.assertEqual(row["净流入（亿）"], -0.0023)
        self.assertEqual(row["超大单（亿）"], 0.02)
        self.assertEqual(row["大单（亿）"], -0.0223)
        self.assertEqual(row["小单（亿）"], -0.005)
        self.assertEqual(row["成交额（亿）"], 1.27)
        self.assertEqual(row["数据日期"], "2026-06-12")

    def test_aggregate_tushare_stock_moneyflow_to_sw2_industry(self) -> None:
        moneyflow_rows = [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260612",
                "buy_sm_amount": 100.0,
                "sell_sm_amount": 50.0,
                "buy_md_amount": 40.0,
                "sell_md_amount": 10.0,
                "buy_lg_amount": 300.0,
                "sell_lg_amount": 100.0,
                "buy_elg_amount": 500.0,
                "sell_elg_amount": 100.0,
                "net_mf_amount": 600.0,
            },
            {
                "ts_code": "000002.SZ",
                "trade_date": "20260612",
                "buy_sm_amount": 50.0,
                "sell_sm_amount": 70.0,
                "buy_md_amount": 10.0,
                "sell_md_amount": 20.0,
                "buy_lg_amount": 80.0,
                "sell_lg_amount": 130.0,
                "buy_elg_amount": 90.0,
                "sell_elg_amount": 120.0,
                "net_mf_amount": -100.0,
            },
        ]
        member_rows = [
            {
                "l2_code": "801081.SI",
                "l2_name": "半导体",
                "ts_code": "000001.SZ",
                "in_date": "20200101",
                "out_date": None,
                "is_new": "Y",
            },
            {
                "l2_code": "801081.SI",
                "l2_name": "半导体",
                "ts_code": "000002.SZ",
                "in_date": "20200101",
                "out_date": None,
                "is_new": "Y",
            },
        ]
        daily_rows = [
            {"ts_code": "000001.SZ", "pct_chg": 2.0, "amount": 100000.0},
            {"ts_code": "000002.SZ", "pct_chg": -1.0, "amount": 200000.0},
        ]

        rows = fetch_sector_fund_flow.aggregate_tushare_sw2_moneyflow(
            moneyflow_rows,
            member_rows,
            daily_rows,
            "2026-06-12",
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["板块"], "半导体")
        self.assertEqual(row["净流入（亿）"], 0.052)
        self.assertEqual(row["超大单（亿）"], 0.037)
        self.assertEqual(row["大单（亿）"], 0.015)
        self.assertEqual(row["小单（亿）"], 0.003)
        self.assertEqual(row["中单（亿）"], 0.002)
        self.assertEqual(row["成交额（亿）"], 3.0)
        self.assertEqual(row["净流入率 %"], 1.73)
        self.assertEqual(row["涨跌幅 %"], 0.0)
        self.assertEqual(row["数据日期"], "2026-06-12")
        self.assertEqual(row["source"], "tushare.moneyflow.sw2_aggregate")

    def test_build_tushare_stock_moneyflow_row_treats_stock_as_sector(self) -> None:
        row = fetch_sector_fund_flow.build_tushare_stock_moneyflow_row(
            {"name": "贵州茅台", "symbol": "600519", "market": "SH"},
            {
                "ts_code": "600519.SH",
                "trade_date": "20260612",
                "buy_sm_amount": 100.0,
                "sell_sm_amount": 300.0,
                "buy_md_amount": 120.0,
                "sell_md_amount": 80.0,
                "buy_lg_amount": 800.0,
                "sell_lg_amount": 500.0,
                "buy_elg_amount": 1000.0,
                "sell_elg_amount": 400.0,
                "net_mf_amount": 900.0,
            },
            {"ts_code": "600519.SH", "trade_date": "20260612", "pct_chg": 1.01, "amount": 500000.0},
            "2026-06-12",
        )

        self.assertEqual(row["板块"], "贵州茅台")
        self.assertEqual(row["净流入（亿）"], 0.09)
        self.assertEqual(row["超大单（亿）"], 0.06)
        self.assertEqual(row["大单（亿）"], 0.03)
        self.assertEqual(row["中单（亿）"], 0.004)
        self.assertEqual(row["小单（亿）"], -0.02)
        self.assertEqual(row["涨跌幅 %"], 1.01)
        self.assertEqual(row["成交额（亿）"], 5.0)
        self.assertEqual(row["净流入率 %"], 1.8)
        self.assertEqual(row["sector_type"], "stock_as_sector")
        self.assertEqual(row["source"], "tushare.moneyflow.stock")

    def test_build_tushare_stock_moneyflow_row_uses_large_plus_elg_as_main_net(self) -> None:
        row = fetch_sector_fund_flow.build_tushare_stock_moneyflow_row(
            {"name": "贵州茅台", "symbol": "600519", "market": "SH"},
            {
                "ts_code": "600519.SH",
                "trade_date": "20260616",
                "buy_sm_amount": 59.51,
                "sell_sm_amount": 158.92,
                "buy_md_amount": 258432.04,
                "sell_md_amount": 252541.64,
                "buy_lg_amount": 112942.64,
                "sell_lg_amount": 127245.31,
                "buy_elg_amount": 68561.56,
                "sell_elg_amount": 60049.89,
                "net_mf_amount": -93460.84,
            },
            {"ts_code": "600519.SH", "trade_date": "20260616", "pct_chg": -1.21, "amount": 4400000.0},
            "2026-06-16",
        )

        self.assertEqual(row["超大单（亿）"], 0.8512)
        self.assertEqual(row["大单（亿）"], -1.4303)
        self.assertEqual(row["小单（亿）"], -0.0099)
        self.assertEqual(row["净流入（亿）"], -0.5791)
        self.assertEqual(row["净流入率 %"], -1.32)
        self.assertEqual(row["Tushare原始净流入（亿）"], -9.3461)
        self.assertIn("主力净流入=超大单净额+大单净额", row["净流入口径"])

    def test_parse_eastmoney_stock_fflow_kline_treats_stock_as_sector(self) -> None:
        row = fetch_sector_fund_flow.parse_eastmoney_stock_fflow_kline(
            "2026-06-16,-544577072.0,-138353.0,544715424.0,-237836432.0,-306740640.0,-12.38,-0.00,12.38,-5.41,-6.97,1255.67,-1.21",
            {"name": "贵州茅台", "symbol": "600519", "market": "SH"},
            "2026-06-16",
        )

        self.assertEqual(row["板块"], "贵州茅台")
        self.assertEqual(row["净流入（亿）"], -5.4458)
        self.assertEqual(row["超大单（亿）"], -3.0674)
        self.assertEqual(row["大单（亿）"], -2.3784)
        self.assertEqual(row["中单（亿）"], 5.4472)
        self.assertEqual(row["小单（亿）"], -0.0014)
        self.assertEqual(row["涨跌幅 %"], -1.21)
        self.assertEqual(row["净流入率 %"], -12.38)
        self.assertEqual(row["source"], "eastmoney.stock.fflow.daykline")

    def test_parse_ths_sector_rows_to_required_schema(self) -> None:
        html = """
        <table class="m-table J-ajax-table">
          <tbody>
            <tr>
              <td>1</td><td>证券</td><td>1389.46</td><td>3.88%</td>
              <td>234.67</td><td>164.99</td><td>69.68</td><td>50</td>
              <td>财达证券</td><td>10.08%</td><td>6.99</td>
            </tr>
          </tbody>
        </table>
        """

        rows = fetch_sector_fund_flow.parse_ths_sector_rows(html, "industry")

        self.assertEqual(
            rows,
            [
                {
                    "板块": "证券",
                    "净流入（亿）": 69.68,
                    "超大单（亿）": None,
                    "大单（亿）": None,
                    "小单（亿）": None,
                    "涨跌幅 %": 3.88,
                    "成交额（亿）": None,
                    "净流入率 %": None,
                    "sector_type": "industry",
                    "source": "10jqka.funds.hyzjl",
                }
            ],
        )

    def test_assess_quality_marks_ths_rows_as_degraded(self) -> None:
        rows = [
            {
                "板块": "证券",
                "净流入（亿）": 69.68,
                "超大单（亿）": None,
                "大单（亿）": None,
                "小单（亿）": None,
                "涨跌幅 %": 3.88,
                "成交额（亿）": None,
                "净流入率 %": None,
            }
        ]

        quality = fetch_sector_fund_flow.assess_fund_flow_quality(rows, ["10jqka.funds.hyzjl"])

        self.assertEqual(quality["level"], "degraded")
        self.assertEqual(quality["source_mode"], "ths_degraded")
        self.assertEqual(
            quality["missing_fields"],
            ["超大单（亿）", "大单（亿）", "小单（亿）", "成交额（亿）", "净流入率 %"],
        )

    def test_assess_quality_marks_akshare_ths_rows_as_degraded(self) -> None:
        rows = [
            {
                "板块": "证券",
                "净流入（亿）": 69.68,
                "超大单（亿）": None,
                "大单（亿）": None,
                "小单（亿）": None,
                "涨跌幅 %": 3.88,
                "成交额（亿）": None,
                "净流入率 %": None,
            }
        ]

        quality = fetch_sector_fund_flow.assess_fund_flow_quality(rows, ["akshare.stock_fund_flow_industry"])

        self.assertEqual(quality["level"], "degraded")
        self.assertEqual(quality["source_mode"], "ths_degraded")

    def test_assess_quality_marks_complete_rows_as_complete(self) -> None:
        rows = [
            {
                "板块": "证券",
                "净流入（亿）": 69.68,
                "超大单（亿）": 12.3,
                "大单（亿）": 8.1,
                "小单（亿）": -5.2,
                "涨跌幅 %": 3.88,
                "成交额（亿）": 400.0,
                "净流入率 %": 17.42,
            }
        ]

        quality = fetch_sector_fund_flow.assess_fund_flow_quality(rows, ["eastmoney.push2.clist.sw2_fund_flow"])

        self.assertEqual(quality["level"], "complete")
        self.assertEqual(quality["source_mode"], "eastmoney_sw2_full")
        self.assertEqual(quality["missing_fields"], [])

    def test_assess_quality_fails_strict_target_date_mismatch(self) -> None:
        rows = [
            {
                "板块": "证券",
                "净流入（亿）": 69.68,
                "超大单（亿）": 12.3,
                "大单（亿）": 8.1,
                "小单（亿）": -5.2,
                "涨跌幅 %": 3.88,
                "成交额（亿）": 400.0,
                "净流入率 %": 17.42,
            }
        ]

        quality = fetch_sector_fund_flow.assess_fund_flow_quality(
            rows,
            ["eastmoney.push2.clist.fund_flow"],
            target_date="2026-06-12",
            data_dates=["2026-06-11"],
        )

        self.assertEqual(quality["level"], "date_mismatch")
        self.assertIn("2026-06-11", quality["data_dates"])

    def test_collect_eastmoney_pages_fetches_all_pages_until_total_is_reached(self) -> None:
        calls = []

        def fake_fetch_page(page: int):
            calls.append(page)
            if page == 1:
                return [{"f14": f"行业{i}", "f12": f"BK{i:04d}"} for i in range(100)], 128
            if page == 2:
                return [{"f14": f"行业{i}", "f12": f"BK{i:04d}"} for i in range(100, 128)], 128
            return [], 128

        rows = fetch_sector_fund_flow.collect_eastmoney_pages(fake_fetch_page)

        self.assertEqual(len(rows), 128)
        self.assertEqual(calls, [1, 2])

    def test_eastmoney_page_falls_back_to_delay_host_when_primary_fails(self) -> None:
        calls = []

        class FakeResponse:
            def __init__(self, host: str) -> None:
                self.host = host

            def raise_for_status(self) -> None:
                if self.host == "push2.eastmoney.com":
                    raise requests.HTTPError("502 Bad Gateway")

            def json(self) -> dict:
                return {
                    "data": {
                        "total": 1,
                        "diff": [
                            {
                                "f14": "半导体",
                                "f12": "BK1036",
                                "f62": 16343425024.0,
                                "f66": 13516902400.0,
                                "f72": 2826522624.0,
                                "f84": -4086112768.0,
                                "f3": 6.06,
                                "f6": 400901433900.0,
                                "f184": 4.08,
                                "f124": 1781509187,
                            }
                        ],
                    }
                }

        def fake_get(url: str, **kwargs):
            host = url.split("/")[2]
            calls.append(host)
            return FakeResponse(host)

        with patch.object(fetch_sector_fund_flow, "eastmoney_get", side_effect=fake_get):
            rows, total = fetch_sector_fund_flow.fetch_eastmoney_sector_page_once("m:90 s:4", 1)

        self.assertEqual(calls, ["push2.eastmoney.com", "push2delay.eastmoney.com"])
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["f14"], "半导体")

    def test_main_respects_configured_industry_only_sector_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "sector.json"
            config_path.write_text("fund_flow:\n  sector_types:\n    - industry\n", encoding="utf-8")
            calls = []

            def fake_fetch(fs: str, label: str):
                calls.append((fs, label))
                return [
                    {
                        "板块": "证券",
                        "净流入（亿）": 1.0,
                        "超大单（亿）": 0.4,
                        "大单（亿）": 0.6,
                        "小单（亿）": -0.1,
                        "涨跌幅 %": 1.2,
                        "成交额（亿）": 10.0,
                        "净流入率 %": 10.0,
                        "source": "eastmoney.push2.clist.fund_flow",
                    }
                ]

            with (
                patch.object(sys, "argv", ["fetch_sector_fund_flow.py", "--config", str(config_path), "--out", str(out_path)]),
                patch.object(fetch_sector_fund_flow, "fetch_eastmoney_sector", side_effect=fake_fetch),
            ):
                fetch_sector_fund_flow.main()

            self.assertEqual(calls, [("m:90 s:4", "industry")])

    def test_main_keeps_ths_rows_as_supplement_when_eastmoney_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "sector.json"
            config_path.write_text("fund_flow:\n  sector_types:\n    - industry\n", encoding="utf-8")

            eastmoney_rows = [
                {
                    "板块": "半导体",
                    "净流入（亿）": -33.38,
                    "超大单（亿）": -10.0,
                    "大单（亿）": -23.38,
                    "小单（亿）": 14.5,
                    "涨跌幅 %": -1.6,
                    "成交额（亿）": 1200.0,
                    "净流入率 %": -2.78,
                    "数据日期": "2026-06-12",
                    "source": "eastmoney.push2.clist.sw2_fund_flow",
                }
            ]
            ths_rows = [
                {
                    "板块": "半导体",
                    "净流入（亿）": -80.89,
                    "超大单（亿）": None,
                    "大单（亿）": None,
                    "小单（亿）": None,
                    "涨跌幅 %": -1.64,
                    "成交额（亿）": None,
                    "净流入率 %": None,
                    "source": "akshare.stock_fund_flow_industry",
                }
            ]

            with (
                patch.object(
                    sys,
                    "argv",
                    ["fetch_sector_fund_flow.py", "--config", str(config_path), "--out", str(out_path), "--date", "2026-06-12"],
                ),
                patch.object(fetch_sector_fund_flow, "fetch_eastmoney_sector", return_value=eastmoney_rows),
                patch.object(fetch_sector_fund_flow, "fetch_akshare_ths_sector", return_value=ths_rows),
                patch.object(fetch_sector_fund_flow, "fetch_ths_sector", return_value=[]),
            ):
                fetch_sector_fund_flow.main()

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["rows"][0]["净流入（亿）"], -33.38)
            self.assertEqual(payload["quality"]["source_mode"], "eastmoney_sw2_full")
            self.assertEqual(payload["supplements"]["coverage"][0]["source"], "akshare.stock_fund_flow_industry")
            self.assertEqual(payload["supplements"]["coverage"][0]["items"][0]["板块"], "半导体")

    def test_main_falls_back_to_tushare_when_eastmoney_date_mismatches_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "sector.json"
            config_path.write_text(
                "primary_stock:\n  name: 贵州茅台\n  symbol: '600519'\n  market: SH\nfund_flow:\n  sector_types:\n    - industry\n",
                encoding="utf-8",
            )
            eastmoney_rows = [
                {
                    "板块": "白酒Ⅱ",
                    "净流入（亿）": 1.0,
                    "超大单（亿）": 0.1,
                    "大单（亿）": 0.2,
                    "小单（亿）": -0.1,
                    "涨跌幅 %": 1.0,
                    "成交额（亿）": 20.0,
                    "净流入率 %": 5.0,
                    "数据日期": "2026-06-12",
                    "source": "eastmoney.push2.clist.sw2_fund_flow",
                }
            ]
            tushare_rows = [
                {
                    "板块": "白酒Ⅱ",
                    "净流入（亿）": 0.5,
                    "超大单（亿）": 0.1,
                    "大单（亿）": 0.2,
                    "小单（亿）": -0.1,
                    "涨跌幅 %": 0.3,
                    "成交额（亿）": 18.0,
                    "净流入率 %": 2.78,
                    "数据日期": "2026-06-11",
                    "source": "tushare.moneyflow.sw2_aggregate",
                }
            ]

            with (
                patch.dict("os.environ", {"TUSHARE_TOKEN": "token"}),
                patch.object(
                    sys,
                    "argv",
                    ["fetch_sector_fund_flow.py", "--config", str(config_path), "--out", str(out_path), "--date", "2026-06-11"],
                ),
                patch.object(fetch_sector_fund_flow, "fetch_eastmoney_sector", return_value=eastmoney_rows),
                patch.object(fetch_sector_fund_flow, "fetch_tushare_sw2_aggregate", return_value=tushare_rows),
                patch.object(fetch_sector_fund_flow, "fetch_tushare_stock_moneyflow", return_value=[]),
                patch.object(fetch_sector_fund_flow, "build_supplements", return_value=({"coverage": []}, [])),
            ):
                fetch_sector_fund_flow.main()

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["sources"], ["tushare.moneyflow.sw2_aggregate"])
            self.assertEqual(payload["quality"]["source_mode"], "tushare_sw2_stock_moneyflow_aggregate")
            self.assertIn("eastmoney returned non-target-date data", "；".join(payload["warnings"]))

    def test_main_falls_back_to_eastmoney_stock_moneyflow_when_tushare_stock_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "sector.json"
            config_path.write_text(
                "primary_stock:\n  name: 贵州茅台\n  symbol: '600519'\n  market: SH\n  secid: '1.600519'\nfund_flow:\n  sector_types:\n    - industry\n",
                encoding="utf-8",
            )
            eastmoney_rows = [
                {
                    "板块": "白酒Ⅱ",
                    "净流入（亿）": -2.94,
                    "超大单（亿）": -1.0,
                    "大单（亿）": -1.94,
                    "小单（亿）": 1.0,
                    "涨跌幅 %": -1.14,
                    "成交额（亿）": 80.0,
                    "净流入率 %": -3.68,
                    "数据日期": "2026-06-16",
                    "source": "eastmoney.push2.clist.sw2_fund_flow",
                }
            ]
            fallback_stock = [
                {
                    "板块": "贵州茅台",
                    "净流入（亿）": -5.45,
                    "超大单（亿）": -3.07,
                    "大单（亿）": -2.38,
                    "小单（亿）": 0.0,
                    "涨跌幅 %": -1.21,
                    "成交额（亿）": None,
                    "净流入率 %": -12.38,
                    "source": "eastmoney.stock.fflow.daykline",
                }
            ]

            with (
                patch.dict("os.environ", {"TUSHARE_TOKEN": "token"}),
                patch.object(
                    sys,
                    "argv",
                    ["fetch_sector_fund_flow.py", "--config", str(config_path), "--out", str(out_path), "--date", "2026-06-16"],
                ),
                patch.object(fetch_sector_fund_flow, "fetch_eastmoney_sector", return_value=eastmoney_rows),
                patch.object(fetch_sector_fund_flow, "fetch_tushare_stock_moneyflow", return_value=[]),
                patch.object(fetch_sector_fund_flow, "fetch_eastmoney_stock_moneyflow", return_value=fallback_stock),
                patch.object(fetch_sector_fund_flow, "build_supplements", return_value=({"coverage": []}, [])),
            ):
                fetch_sector_fund_flow.main()

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["stock_sources"], ["eastmoney.stock.fflow.daykline"])
            self.assertEqual(payload["stock_rows"][0]["板块"], "贵州茅台")
            self.assertIn("tushare primary stock moneyflow returned no rows", "；".join(payload["warnings"]))
            self.assertIn("eastmoney fallback", "；".join(payload["warnings"]))


if __name__ == "__main__":
    unittest.main()
