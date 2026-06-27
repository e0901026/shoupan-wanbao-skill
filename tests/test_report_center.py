from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_pdf  # noqa: E402
import install  # noqa: E402
import render_index  # noqa: E402
import report_calendar  # noqa: E402
import run_morning  # noqa: E402
import run_report_center  # noqa: E402
import run_weekly  # noqa: E402


class ReportCenterTest(unittest.TestCase):
    def test_trade_calendar_uses_cache_and_skips_weekends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "trade_calendar_2026.json"
            cache.write_text(
                json.dumps(
                    {
                        "days": [
                            {"date": "2026-06-19", "is_open": False},
                            {"date": "2026-06-22", "is_open": True},
                            {"date": "2026-06-23", "is_open": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            cal = report_calendar.TradeCalendar(cache)

            self.assertFalse(cal.is_trading_day("2026-06-19"))
            self.assertFalse(cal.is_trading_day("2026-06-20"))
            self.assertTrue(cal.is_trading_day("2026-06-22"))
            self.assertEqual(cal.trading_days_between("2026-06-19", "2026-06-23"), ["2026-06-22", "2026-06-23"])

    def test_report_center_catches_up_missing_daily_and_weekly(self) -> None:
        calls = []

        def fake_run(cmd, check):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "output").mkdir()
            cache = root / "data" / "trade_calendar_2026.json"
            cache.parent.mkdir()
            cache.write_text(
                json.dumps(
                    {
                        "days": [
                            {"date": "2026-06-22", "is_open": True},
                            {"date": "2026-06-23", "is_open": True},
                            {"date": "2026-06-24", "is_open": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            state = root / "data" / "report_center_state.json"
            state.write_text(json.dumps({"last_daily_date": "2026-06-22"}), encoding="utf-8")

            plan = run_report_center.build_run_plan(
                today="2026-06-24",
                now_time="16:05",
                root=root,
                calendar=report_calendar.TradeCalendar(cache),
                state_file=state,
            )

            self.assertEqual(plan.daily_dates, ["2026-06-23", "2026-06-24"])
            with patch("subprocess.run", side_effect=fake_run):
                run_report_center.execute_plan(plan, config="config.yaml", py=sys.executable)

            command_text = [" ".join(cmd) for cmd in calls]
            self.assertTrue(any("scripts/run_daily.py" in cmd and "2026-06-23" in cmd for cmd in command_text))
            self.assertTrue(any("scripts/run_daily.py" in cmd and "2026-06-24" in cmd for cmd in command_text))
            self.assertTrue(any("scripts/render_index.py" in cmd for cmd in command_text))

    def test_weekly_report_aggregates_daily_archives_and_divergences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "data" / "archive"
            output = root / "output"
            archive.mkdir(parents=True)
            output.mkdir()
            for idx, date in enumerate(["2026-06-22", "2026-06-23"]):
                payload = {
                    "quotes": {"quotes": {"600519": {"收盘价": 1200 + idx, "涨跌幅": -1 + idx, "成交额（亿）": 50 + idx}}},
                    "daily_review": {"lines": [f"资金流动面：贵州茅台净流入+{idx + 1}.00亿，超大单+2.00亿，大单-1.00亿，小单-0.01亿；白酒Ⅱ净流入-{idx + 3}.00亿、涨跌幅-1.00%；资金主攻方向集中在半导体 +10.00亿。"]},
                    "fund_flow": {
                        "inflow_top5": [{"板块": "半导体", "净流入（亿）": 10 + idx}],
                        "outflow_top5": [{"板块": "通信设备", "净流入（亿）": -20 - idx}],
                        "divergence_net_inflow_price_down": [{"板块": "计算机设备", "净流入（亿）": 3}],
                        "divergence_net_outflow_price_up": [{"板块": "消费电子", "净流入（亿）": -4}],
                        "divergence_super_in_large_out": [{"板块": "光学光电子", "净流入（亿）": 5}],
                        "divergence_super_out_large_in": [{"板块": "半导体", "净流入（亿）": -6}],
                    },
                }
                (archive / f"analysis_{date}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            out = run_weekly.write_weekly_report(root=root, dates=["2026-06-22", "2026-06-23"], output_dir=output)

            html = out.read_text(encoding="utf-8")
            self.assertIn("2026年06月22日-06月23日贵州茅台周报", html)
            self.assertIn("四大背离", html)
            self.assertIn("净流入 TOP10", html)
            self.assertIn("通信设备", html)
            self.assertIn("半导体", html)

    def test_weekly_report_includes_review_news_sentiment_and_full_fund_flow_fields(self) -> None:
        analyses = {
            "2026-06-22": {
                "quotes": {"quotes": {"600519": {"收盘价": 1241.41, "涨跌幅": 2.17, "成交额（亿）": 71.63}}},
                "daily_review": {"lines": ["结论：今日贵州茅台上涨+2.17%。", "资金流动面：贵州茅台净流入+0.66亿，超大单-0.67亿，大单+1.33亿，小单-0.00亿；白酒Ⅱ净流入+0.01亿、涨跌幅+1.79%；资金主攻方向集中在证券Ⅱ +48.86亿。"]},
                "news": {"items": [{"title": "贵州茅台分红", "url": "https://example.com/a", "source": "新浪", "time": "2026-06-22", "summary": "分红摘要", "category": "主标的新闻"}]},
                "sentiment": {"summary": {"line": "散户情绪分歧", "sample_count": 40}},
                "summary": {"fund_sentiment_line": "分歧偏强"},
                "fund_flow": {
                    "inflow_top5": [{"板块": "证券Ⅱ", "净流入（亿）": 48.86, "超大单（亿）": 41.19, "大单（亿）": 7.67, "小单（亿）": -29.25, "涨跌幅 %": 9.0, "成交额（亿）": 743.29, "净流入率 %": 6.57}],
                    "outflow_top5": [{"板块": "元件", "净流入（亿）": -97.77, "超大单（亿）": -69.47, "大单（亿）": -28.30, "小单（亿）": 67.67, "涨跌幅 %": -0.27, "成交额（亿）": 1660.34, "净流入率 %": -5.89}],
                    "divergence_net_inflow_price_down": [{"板块": "金属新材料", "净流入（亿）": 5.23, "超大单（亿）": 4, "大单（亿）": 1.23, "小单（亿）": -2, "涨跌幅 %": -1, "成交额（亿）": 100, "净流入率 %": 5.23}],
                    "divergence_net_outflow_price_up": [{"板块": "消费电子", "净流入（亿）": -80.16, "超大单（亿）": -70, "大单（亿）": -10.16, "小单（亿）": 20, "涨跌幅 %": 1, "成交额（亿）": 1000, "净流入率 %": -8.02}],
                    "divergence_super_in_large_out": [{"板块": "光学光电子", "净流入（亿）": 34.68, "超大单（亿）": 40, "大单（亿）": -5.32, "小单（亿）": -20, "涨跌幅 %": 2, "成交额（亿）": 900, "净流入率 %": 3.85}],
                    "divergence_super_out_large_in": [{"板块": "半导体", "净流入（亿）": -288.70, "超大单（亿）": -300, "大单（亿）": 11.3, "小单（亿）": 100, "涨跌幅 %": -1, "成交额（亿）": 5000, "净流入率 %": -5.77}],
                },
            },
            "2026-06-23": {
                "quotes": {"quotes": {"600519": {"收盘价": 1222.45, "涨跌幅": -1.53, "成交额（亿）": 71.80}}},
                "daily_review": {"lines": ["结论：今日贵州茅台下跌-1.53%。", "资金流动面：贵州茅台净流入+1.09亿，超大单+2.27亿，大单-1.18亿，小单-0.04亿；白酒Ⅱ净流入-9.63亿、涨跌幅-1.06%；资金主攻方向集中在银行Ⅱ +28.69亿。"]},
                "news": {"items": [{"title": "贵州茅台分红", "url": "https://example.com/a", "source": "新浪", "time": "2026-06-22", "summary": "重复新闻", "category": "主标的新闻"}]},
                "sentiment": {"summary": {"line": "散户情绪谨慎", "sample_count": 38}},
                "summary": {"fund_sentiment_line": "分歧偏弱"},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-22", "2026-06-23")

        self.assertIn("本周复盘", html)
        self.assertIn("本周复盘校正", html)
        self.assertIn("要闻速览时间线", html)
        self.assertNotIn("市场情绪时间线", html)
        self.assertIn("板块资金流向变化", html)
        self.assertIn("超大单（亿）", html)
        self.assertIn("净流入率 %", html)
        self.assertNotIn("重复新闻", html)

    def test_weekly_flow_tables_net_sectors_before_splitting_inflow_outflow(self) -> None:
        analyses = {
            "2026-06-22": {
                "quotes": {"quotes": {"600519": {}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "fund_flow": {
                    "inflow_top5": [{"板块": "证券Ⅱ", "净流入（亿）": 10, "超大单（亿）": 6, "大单（亿）": 4, "小单（亿）": -5, "涨跌幅 %": 1, "成交额（亿）": 100, "净流入率 %": 10}],
                    "outflow_top5": [{"板块": "半导体", "净流入（亿）": -20, "超大单（亿）": -18, "大单（亿）": -2, "小单（亿）": 8, "涨跌幅 %": -1, "成交额（亿）": 200, "净流入率 %": -10}],
                    "divergence_net_inflow_price_down": [],
                    "divergence_net_outflow_price_up": [],
                    "divergence_super_in_large_out": [],
                    "divergence_super_out_large_in": [],
                },
            },
            "2026-06-23": {
                "quotes": {"quotes": {"600519": {}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "fund_flow": {
                    "inflow_top5": [{"板块": "半导体", "净流入（亿）": 5, "超大单（亿）": 4, "大单（亿）": 1, "小单（亿）": -2, "涨跌幅 %": 2, "成交额（亿）": 80, "净流入率 %": 6.25}],
                    "outflow_top5": [],
                    "divergence_net_inflow_price_down": [],
                    "divergence_net_outflow_price_up": [],
                    "divergence_super_in_large_out": [],
                    "divergence_super_out_large_in": [],
                },
            },
        }

        inflow_rows = run_weekly.weekly_net_flow_rows(analyses, "in")
        outflow_rows = run_weekly.weekly_net_flow_rows(analyses, "out")

        self.assertNotIn("半导体", [row[0] for row in inflow_rows])
        self.assertIn(["半导体", "2/2", "-15.00", "-14.00", "-1.00", "+6.00", "+0.50", "280.00", "-1.88"], outflow_rows)

    def test_weekly_report_keeps_liquor_and_moutai_fixed_in_fund_flow_section(self) -> None:
        analyses = {
            "2026-06-26": {
                "quotes": {"quotes": {"600519": {}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "summary": {},
                "fund_flow": {
                    "inflow_top5": [{"板块": "证券Ⅱ", "净流入（亿）": 10}],
                    "outflow_top5": [{"板块": "半导体", "净流入（亿）": -20}],
                    "liquor_compare": [
                        {"板块": "白酒Ⅱ", "净流入（亿）": -12.69, "超大单（亿）": -5.20, "大单（亿）": -7.49, "小单（亿）": 7.08, "涨跌幅 %": -3.19, "成交额（亿）": 144.83, "净流入率 %": -8.76},
                        {"板块": "贵州茅台", "净流入（亿）": -0.49, "超大单（亿）": 0.58, "大单（亿）": -1.07, "小单（亿）": -0.02, "涨跌幅 %": -1.30, "成交额（亿）": 59.22, "净流入率 %": -0.82},
                    ],
                    "divergence_net_inflow_price_down": [],
                    "divergence_net_outflow_price_up": [],
                    "divergence_super_in_large_out": [],
                    "divergence_super_out_large_in": [],
                },
            }
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-26", "2026-06-26")

        self.assertIn("白酒与茅台固定观察", html)
        self.assertIn("白酒Ⅱ", html)
        self.assertIn("贵州茅台", html)
        self.assertIn("不按 TOP10 筛选", html)

    def test_weekly_return_uses_daily_pct_compounding_not_raw_close_change(self) -> None:
        analyses = {
            "2026-06-22": {
                "quotes": {"quotes": {"600519": {"收盘价": 1241.41, "涨跌幅": 2.17, "成交额（亿）": 71.63}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
            "2026-06-23": {
                "quotes": {"quotes": {"600519": {"收盘价": 1222.45, "涨跌幅": -1.53, "成交额（亿）": 71.80}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
            "2026-06-24": {
                "quotes": {"quotes": {"600519": {"收盘价": 1207.68, "涨跌幅": -1.21, "成交额（亿）": 55.17}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
            "2026-06-25": {
                "quotes": {"quotes": {"600519": {"收盘价": 1212.10, "涨跌幅": 0.37, "成交额（亿）": 58.60}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
            "2026-06-26": {
                "quotes": {"quotes": {"600519": {"收盘价": 1168.63, "涨跌幅": -1.30, "成交额（亿）": 59.22}}},
                "daily_review": {"lines": []},
                "news": {"items": []},
                "sentiment": {"summary": {}},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
        }

        corporate_actions = {
            "dividend": {
                "cash_dividend_per_share": 28.02423,
                "ex_dividend_date": "2026-06-26",
                "title": "贵州茅台2025年年度权益分派实施公告",
            }
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-22", "2026-06-26", corporate_actions=corporate_actions)

        self.assertIn("含分红总回报", html)
        self.assertIn("-1.51%", html)
        self.assertIn("行情日涨跌累计为 -1.54%", html)
        self.assertIn("首尾收盘价裸变化为 -5.86%", html)
        self.assertIn("2026-06-26 每股现金分红 28.02元", html)
        self.assertIn("行情日涨跌幅", html)

    def test_weekly_report_summarizes_review_corrections_and_orders_timelines_latest_first(self) -> None:
        analyses = {
            "2026-06-24": {
                "quotes": {"quotes": {"600519": {"收盘价": 1207.68, "涨跌幅": -1.21, "成交额（亿）": 55.17}}},
                "daily_review": {"lines": ["结论：今日贵州茅台下跌。", "资金流动面：贵州茅台净流入+1.21亿，超大单+2.38亿，大单-1.17亿，小单-0.01亿；白酒Ⅱ净流入-7.26亿、涨跌幅-2.92%；资金主攻方向集中在半导体 +212.53亿。", "大作手式判断：超大单承接但价格未确认。"]},
                "news": {"items": [{"title": "贵州茅台公告", "url": "https://example.com/old", "source": "上交所", "time": "2026-06-24", "summary": "公告摘要", "category": "主标的新闻"}]},
                "sentiment": {"summary": {"line": "散户情绪偏谨慎", "sample_count": 40}},
                "summary": {"fund_sentiment_line": "承接偏弱"},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
            "2026-06-26": {
                "quotes": {"quotes": {"600519": {"收盘价": 1168.63, "涨跌幅": -1.30, "成交额（亿）": 59.22}}},
                "daily_review": {"lines": ["结论：今日贵州茅台下跌。", "资金流动面：贵州茅台净流入-0.49亿，超大单+0.58亿，大单-1.07亿，小单-0.02亿；白酒Ⅱ净流入-12.69亿、涨跌幅-3.19%；资金主攻方向集中在光学光电子 +37.77亿。", "大作手式判断：分红未能抵消板块卖压。"]},
                "news": {
                    "items": [
                        {"title": "贵州茅台，今日分红", "url": "https://example.com/dividend-a", "source": "新浪", "time": "2026-06-26 10:52", "summary": "贵州茅台分红", "category": "主标的新闻"},
                        {"title": "每10股派280.24元！贵州茅台今日分红350亿元", "url": "https://example.com/dividend-b", "source": "新浪", "time": "2026-06-26 09:49", "summary": "现金分红落地", "category": "主标的新闻"},
                    ]
                },
                "sentiment": {"summary": {"line": "散户情绪分歧", "sample_count": 40}},
                "summary": {"fund_sentiment_line": "分歧偏弱"},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-24", "2026-06-26")

        self.assertIn("本周复盘校正", html)
        self.assertIn("后续日报策略优化", html)
        self.assertIn("此前承接信号", html)
        self.assertNotIn("每日复盘时间线", html)
        news_start = html.index("<h2>要闻速览时间线</h2>")
        verification_start = html.index("<h2>板块基金/机构抛售验证</h2>")
        news_section = html[news_start:verification_start]
        self.assertLess(news_section.index("2026-06-26"), news_section.index("2026-06-24"))
        self.assertEqual(news_section.count("现金分红"), 1)
        self.assertNotIn("市场情绪时间线", html)

    def test_weekly_report_includes_institutional_selloff_verification_matrix(self) -> None:
        analyses = {
            "2026-06-22": {
                "quotes": {"quotes": {"600519": {"收盘价": 1241.41, "涨跌幅": 2.17, "成交额（亿）": 71.63}}},
                "daily_review": {"lines": ["资金流动面：贵州茅台净流入+0.66亿，超大单-0.67亿，大单+1.33亿，小单-0.00亿；白酒Ⅱ净流入+0.01亿、涨跌幅+1.79%；资金主攻方向集中在证券Ⅱ +48.86亿。"]},
                "news": {"items": []},
                "sentiment": {"summary": {"line": "散户情绪偏乐观", "fund_line": "融资端：融资余额199.19亿元，较前一交易日-0.17亿元；当日融资买入6.16亿元、偿还6.33亿元，融资净买入-0.16亿元；融券余量9.76万股，较前一交易日-1.17万股。大宗交易：贵州茅台现2笔大宗交易，溢价率0.00%。", "sample_count": 40}},
                "summary": {},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            },
            "2026-06-26": {
                "quotes": {"quotes": {"600519": {"收盘价": 1168.63, "涨跌幅": -1.30, "成交额（亿）": 59.22}}},
                "daily_review": {"lines": ["资金流动面：贵州茅台净流入-0.49亿，超大单+0.58亿，大单-1.07亿，小单-0.02亿；白酒Ⅱ净流入-12.69亿、涨跌幅-3.19%；资金主攻方向集中在光学光电子 +37.77亿。"]},
                "news": {"items": []},
                "sentiment": {"summary": {"line": "散户情绪分歧", "fund_line": "融资端：融资余额195.67亿元，较前一交易日-5.63亿元；当日融资买入3.99亿元、偿还9.62亿元，融资净买入-5.63亿元；融券余量10.68万股，较前一交易日-0.06万股。大宗交易：暂缺。情绪判断：分歧偏弱。", "sample_count": 40}},
                "summary": {},
                "fund_flow": {
                    "liquor_compare": [
                        {"板块": "白酒Ⅱ", "净流入（亿）": -12.69, "超大单（亿）": -5.20, "大单（亿）": -7.49, "小单（亿）": 7.08, "涨跌幅 %": -3.19, "成交额（亿）": 144.83, "净流入率 %": -8.76},
                        {"板块": "贵州茅台", "净流入（亿）": -0.49, "超大单（亿）": 0.58, "大单（亿）": -1.07, "小单（亿）": -0.02, "涨跌幅 %": -1.30, "成交额（亿）": 59.22, "净流入率 %": -0.82},
                    ],
                    "inflow_top5": [],
                    "outflow_top5": [],
                    "divergence_net_inflow_price_down": [],
                    "divergence_net_outflow_price_up": [],
                    "divergence_super_in_large_out": [],
                    "divergence_super_out_large_in": [],
                },
            }
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-26", "2026-06-26")

        self.assertIn("板块基金/机构抛售验证", html)
        self.assertIn("不能直接判定机构主动抛售", html)
        self.assertIn("ETF份额变化", html)
        self.assertIn("基金持仓", html)
        self.assertIn("北向/外资", html)
        self.assertIn("融资余额 199.19亿 → 195.67亿，周变化 -3.52亿", html)
        self.assertIn("融券余量 9.76万股 → 10.68万股，周变化 +0.92万股", html)
        self.assertNotIn("较前一交易日-5.63亿元", html)
        self.assertIn("白酒Ⅱ：净流入 -12.69亿；超大单 -5.20亿；大单 -7.49亿；小单 +7.08亿", html)

    def test_weekly_report_uses_structured_institutional_evidence_when_available(self) -> None:
        analyses = {
            "2026-06-26": {
                "quotes": {"quotes": {"600519": {"收盘价": 1168.63, "涨跌幅": -1.30, "成交额（亿）": 59.22}}},
                "daily_review": {"lines": ["资金流动面：贵州茅台净流入-0.49亿，超大单+0.58亿，大单-1.07亿，小单-0.02亿；白酒Ⅱ净流入-12.69亿、涨跌幅-3.19%；资金主攻方向集中在光学光电子 +37.77亿。"]},
                "news": {"items": []},
                "sentiment": {"summary": {"fund_line": "融资端：融资余额195.67亿元；融券余量10.68万股。大宗交易：暂缺。"}},
                "summary": {},
                "fund_flow": {
                    "liquor_compare": [
                        {"板块": "白酒Ⅱ", "净流入（亿）": -12.69, "超大单（亿）": -5.20, "大单（亿）": -7.49, "小单（亿）": 7.08},
                        {"板块": "贵州茅台", "净流入（亿）": -0.49, "超大单（亿）": 0.58, "大单（亿）": -1.07, "小单（亿）": -0.02},
                    ],
                    "inflow_top5": [],
                    "outflow_top5": [],
                    "divergence_net_inflow_price_down": [],
                    "divergence_net_outflow_price_up": [],
                    "divergence_super_in_large_out": [],
                    "divergence_super_out_large_in": [],
                },
            }
        }
        evidence = {
            "block_trades": {
                "total_amount_yuan": 6207000,
                "items": [
                    {"premium_ratio": 0, "amount_yuan": 3103500, "seller": "中信证券股份有限公司总部(非营业场所)", "buyer": "广发证券贵阳营业部"},
                    {"premium_ratio": 0, "amount_yuan": 3103500, "seller": "中信证券股份有限公司总部(非营业场所)", "buyer": "广发证券广州营业部"},
                ],
            },
            "lhb": {"items": [], "summary": "本周未上龙虎榜，无席位级别异动披露。"},
            "northbound": {"items": [], "summary": "接口可访问，但 600519 最新可用日期为 2024-08-16，无法验证 2026-06-22 至 2026-06-26。"},
            "etf": {
                "items": [
                    {"code": "512690", "name": "酒ETF", "share_change": -127800000, "share_change_pct": -0.37},
                    {"code": "515170", "name": "食品饮料", "share_change": -69000000, "share_change_pct": -0.75},
                ]
            },
            "fund_holdings": {
                "summary": "最新截止 2026-03-31，996 只基金持有，合计 2300.00 万股；该数据为季报滞后口径。",
                "items": [
                    {"基金名称": "招商中证白酒指数C", "持仓数量": 5083356, "占流通股比例": 0.4059},
                    {"基金名称": "华泰柏瑞沪深300ETF", "持仓数量": 5038482, "占流通股比例": 0.4023},
                ],
            },
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-26", "2026-06-26", evidence)

        self.assertIn("合计 0.06 亿元", html)
        self.assertIn("ETF份额变化", html)
        self.assertIn("512690 酒ETF 份额 -1.28 亿份", html)
        self.assertIn("不等同于已经卖出茅台", html)
        self.assertIn("招商中证白酒指数C", html)
        self.assertIn("最新可用日期为 2024-08-16", html)
        self.assertIn("源滞后时不得参与本周买卖判断", html)
        self.assertIn("本周未上龙虎榜", html)

    def test_weekly_report_removes_low_value_sentiment_timeline_but_keeps_evidence(self) -> None:
        analyses = {
            "2026-06-26": {
                "quotes": {"quotes": {"600519": {"收盘价": 1168.63, "涨跌幅": -1.30, "成交额（亿）": 59.22}}},
                "daily_review": {"lines": ["资金流动面：贵州茅台净流入-0.49亿，超大单+0.58亿，大单-1.07亿，小单-0.02亿；白酒Ⅱ净流入-12.69亿、涨跌幅-3.19%；资金主攻方向集中在光学光电子 +37.77亿。"]},
                "news": {"items": []},
                "summary": {},
                "sentiment": {
                    "summary": {
                        "fund_line": "主力方向：主力净流入居前的是 光学光电子（+37.77 亿）。净流出居前的是 通信设备（-395.53 亿）。 白酒观察：非白酒净流入 -0.07 亿，板块涨跌幅 -1.63%。 融资端：融资余额195.67亿元，较前一交易日-5.63亿元；当日融资买入3.99亿元、偿还9.62亿元，融资净买入-5.63亿元；融券余量10.68万股，较前一交易日-0.06万股。 大宗交易：暂缺。 情绪判断：分歧偏弱：茅台超大单净流入；融券余量下降；白酒Ⅱ净流出且下跌；茅台下跌且主力净流出；融资端杠杆资金减仓。",
                        "line": "散户舆论近窗有效样本 40 条（今日头条 10、东方财富股吧 30），正向 1 / 负向 2 / 中性 37，散户情绪分歧。",
                        "sample_count": 40,
                    }
                },
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            }
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-26", "2026-06-26")

        self.assertNotIn("市场情绪时间线", html)
        verification_start = html.index("<h2>板块基金/机构抛售验证</h2>")
        verification_end = html.index("<h2>板块资金流向变化</h2>")
        verification_section = html[verification_start:verification_end]
        self.assertIn("融资余额 195.67亿", verification_section)
        self.assertIn("仅1日数据，暂不能计算周变化", verification_section)
        self.assertIn("大宗交易：暂缺", verification_section)
        self.assertNotIn("主力方向：主力净流入居前的是", verification_section)
        self.assertNotIn("当日融资买入3.99亿元", verification_section)

    def test_weekly_core_view_calls_out_dividend_events(self) -> None:
        analyses = {
            "2026-06-26": {
                "quotes": {"quotes": {"600519": {"收盘价": 1168.63, "涨跌幅": -1.30, "成交额（亿）": 59.22}}},
                "daily_review": {"lines": ["资金流动面：贵州茅台净流入-0.49亿，超大单+0.58亿，大单-1.07亿，小单-0.02亿；白酒Ⅱ净流入-12.69亿、涨跌幅-3.19%；资金主攻方向集中在光学光电子 +37.77亿。"]},
                "news": {"items": [{"title": "每10股派280.24元！贵州茅台今日分红350亿元", "url": "https://example.com/dividend", "source": "新浪", "time": "2026-06-26", "summary": "贵州茅台现金分红落地", "category": "主标的新闻"}]},
                "sentiment": {"summary": {"line": "散户情绪分歧", "sample_count": 40}},
                "fund_flow": {"inflow_top5": [], "outflow_top5": [], "divergence_net_inflow_price_down": [], "divergence_net_outflow_price_up": [], "divergence_super_in_large_out": [], "divergence_super_out_large_in": []},
            }
        }

        html = run_weekly.build_weekly_html(analyses, "2026-06-26", "2026-06-26")

        core_start = html.index("<h2>核心判断</h2>")
        core_end = html.index("<h2>本周复盘</h2>")
        core = html[core_start:core_end]
        self.assertIn("分红", core)
        self.assertIn("现金回报", core)
        self.assertIn("不能抵消", core)

    def test_weekly_report_can_fallback_to_existing_daily_html_without_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            (output / "a_share_evening_report_2026-06-22.html").write_text(
                """
                <h1>A股收盘晚报 2026-06-22</h1>
                <p>💹 贵州茅台（600519.SH） 收盘：1241.41 元（+2.17%）</p>
                <p>成交额：71.63 亿</p>
                <h2>🧭 今日复盘：今日上涨的核心原因</h2>
                <ul><li>结论：今日贵州茅台上涨。</li><li>资金流动面：贵州茅台净流入+0.66亿，超大单-0.67亿，大单+1.33亿，小单-0.00亿；白酒Ⅱ净流入+0.01亿、涨跌幅+1.79%；资金主攻方向集中在证券Ⅱ +48.86亿。</li><li>大作手式判断：今日资金情绪为“分歧偏强”。</li></ul>
                <h2>📰 要闻速览</h2><p>2026-06-22 · <a href="https://example.com/a">贵州茅台公告</a> · 上交所 · 重要性：高 摘要：公告摘要</p>
                <h3>🔥 净流入 TOP 10</h3><table><tr><th>板块</th><th>净流入（亿）</th><th>超大单（亿）</th><th>大单（亿）</th><th>小单（亿）</th><th>涨跌幅 %</th><th>成交额（亿）</th><th>净流入率 %</th></tr><tr><td>证券Ⅱ</td><td>+48.86</td><td>+41.19</td><td>+7.67</td><td>-29.25</td><td>+9.00%</td><td>743.29</td><td>+6.57%</td></tr></table>
                <h3>💧 净流出 TOP 10</h3><table><tr><th>板块</th><th>净流入（亿）</th><th>超大单（亿）</th><th>大单（亿）</th><th>小单（亿）</th><th>涨跌幅 %</th><th>成交额（亿）</th><th>净流入率 %</th></tr><tr><td>元件</td><td>-97.77</td><td>-69.47</td><td>-28.30</td><td>+67.67</td><td>-0.27%</td><td>1660.34</td><td>-5.89%</td></tr></table>
                <h2>🍶 白酒板块对比</h2><p>这里不是资金表。</p>
                <h2>🍶 白酒板块</h2><table><tr><th>板块</th><th>净流入（亿）</th><th>超大单（亿）</th><th>大单（亿）</th><th>小单（亿）</th><th>涨跌幅 %</th><th>成交额（亿）</th><th>净流入率 %</th></tr><tr><td>白酒Ⅱ</td><td>-12.69</td><td>-5.20</td><td>-7.49</td><td>+7.08</td><td>-3.19%</td><td>144.83</td><td>-8.76%</td></tr><tr><td>贵州茅台</td><td>-0.49</td><td>+0.58</td><td>-1.07</td><td>-0.02</td><td>-1.30%</td><td>59.22</td><td>-0.82%</td></tr></table>
                """,
                encoding="utf-8",
            )

            analyses = run_weekly.load_daily_analyses(root, ["2026-06-22"])

            self.assertIn("2026-06-22", analyses)
            html = run_weekly.build_weekly_html(analyses, "2026-06-22", "2026-06-22")
            self.assertIn("贵州茅台公告", html)
            self.assertIn("证券Ⅱ", html)
            self.assertEqual(analyses["2026-06-22"]["fund_flow"]["liquor_compare"][0]["板块"], "白酒Ⅱ")

    def test_morning_report_uses_rest_window_without_market_tables(self) -> None:
        html = run_morning.build_morning_html(
            title_date="2026-06-29",
            window_start="2026-06-26 15:00",
            window_end="2026-06-29 08:30",
            news={
                "items": [
                    {"title": "贵州茅台周末公告", "url": "https://example.com/a", "source": "上交所", "time": "2026-06-28", "summary": "公告摘要", "category": "主标的新闻"}
                ]
            },
            research={"items": []},
            sentiment={"summary": {"line": "散户情绪分歧", "sample_count": 10}},
            macro={"items": [{"title": "美债收益率观察", "summary": "10年美债仍需跟踪", "time": "2026-06-28", "url": "https://example.com/m"}]},
            corporate_actions={},
        )

        self.assertIn("开盘早报", html)
        self.assertIn("2026-06-26 15:00 至 2026-06-29 08:30", html)
        self.assertIn("贵州茅台周末公告", html)
        self.assertNotIn("板块资金流向", html)
        self.assertNotIn("收盘价", html)

    def test_index_scans_three_report_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "a_share_evening_report_2026-06-26.html").write_text("<h1>A股收盘晚报 2026-06-26</h1><p>摘要A</p>", encoding="utf-8")
            (output / "a_share_weekly_report_2026-06-22_2026-06-26.html").write_text("<h1>2026年06月22日-06月26日贵州茅台周报</h1><p>摘要B</p>", encoding="utf-8")
            (output / "a_share_morning_report_2026-06-29.html").write_text("<h1>开盘早报 2026-06-29</h1><p>摘要C</p>", encoding="utf-8")

            out = render_index.write_index(output)

            html = out.read_text(encoding="utf-8")
            self.assertIn("开盘早报", html)
            self.assertIn("收盘晚报", html)
            self.assertIn("周报分析", html)
            self.assertIn("2026年06月22日-06月26日贵州茅台周报", html)
            self.assertIn("a_share_evening_report_2026-06-26.html", html)
            self.assertIn('class="pdf-export"', html)
            self.assertIn('href="index.pdf"', html)
            self.assertIn('class="pdf-export"', (output / "a_share_evening_report_2026-06-26.html").read_text(encoding="utf-8"))

    def test_pdf_export_uses_pandoc_fallback_when_browser_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "report.html"
            html_path.write_text("<h1>报告</h1>", encoding="utf-8")
            calls = []

            def fake_run(cmd, check):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0)

            def fake_which(name):
                return "/opt/homebrew/bin/pandoc" if name == "pandoc" else ("/usr/local/bin/pdflatex" if name == "pdflatex" else None)

            with patch.object(export_pdf, "find_browser_pdf_engine", return_value=None), patch("shutil.which", side_effect=fake_which), patch("subprocess.run", side_effect=fake_run):
                pdf = export_pdf.export_pdf(html_path, mode="print")

            self.assertEqual(pdf, html_path.with_suffix(".pdf"))
            self.assertIn("pandoc", calls[0][0])

    def test_pdf_export_screenshot_mode_wraps_full_page_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "report.html"
            html_path.write_text("<h1>报告</h1>", encoding="utf-8")

            def fake_capture(html_file, png_file, width=1280, device_scale_factor=1.0):
                from PIL import Image

                Image.new("RGB", (320, 960), color="white").save(png_file)
                return png_file

            with patch.object(export_pdf, "capture_full_page_png", side_effect=fake_capture):
                pdf = export_pdf.export_pdf(html_path)

            self.assertEqual(pdf, html_path.with_suffix(".pdf"))
            self.assertTrue(pdf.exists())

    def test_install_builds_launchd_plist_dry_run(self) -> None:
        plist = install.build_launchd_plist(
            repo_dir=Path("/repo"),
            python_path=Path("/python"),
            label="com.example.report-center",
        )

        self.assertIn("<key>Label</key>", plist)
        self.assertIn("scripts/run_report_center.py", plist)
        self.assertIn("<integer>16</integer>", plist)


if __name__ == "__main__":
    unittest.main()
