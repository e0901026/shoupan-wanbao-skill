from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_report  # noqa: E402


class AnalyzeReportTest(unittest.TestCase):
    def test_build_market_summary_uses_quote_and_fund_flow_data(self) -> None:
        summary = analyze_report.build_market_summary(
            {
                "quotes": {
                    "600519": {"收盘价": 1291.91, "涨跌幅": 1.01},
                }
            },
            {
                "inflow_top5": [{"板块": "工业金属", "净流入（亿）": 83.69}],
                "outflow_top5": [{"板块": "电机Ⅱ", "净流入（亿）": -1.32}],
                "baijiu": [{"板块": "白酒Ⅱ", "净流入（亿）": 1.53, "涨跌幅 %": 1.1}],
            },
        )

        self.assertEqual(summary["moutai_line"], "贵州茅台收于 1291.91 元，涨跌幅 +1.01%。")
        self.assertEqual(summary["main_inflow_line"], "主力净流入居前的是 工业金属（+83.69 亿）。")
        self.assertEqual(summary["main_outflow_line"], "净流出居前的是 电机Ⅱ（-1.32 亿）。")
        self.assertEqual(summary["baijiu_line"], "白酒Ⅱ净流入 +1.53 亿，板块涨跌幅 +1.10%。")

    def test_build_market_summary_extracts_block_trade_and_judges_fund_sentiment(self) -> None:
        summary = analyze_report.build_market_summary(
            {
                "quotes": {
                    "600519": {"收盘价": 1291.91, "涨跌幅": 1.01, "成交额（亿）": 64.78},
                }
            },
            {
                "inflow_top5": [{"板块": "证券Ⅱ", "净流入（亿）": 57.28}],
                "outflow_top5": [{"板块": "光学光电子", "净流入（亿）": -49.99}],
                "baijiu": [
                    {"板块": "白酒Ⅱ", "净流入（亿）": 4.42, "涨跌幅 %": 0.56},
                    {"板块": "贵州茅台", "净流入（亿）": -0.69, "超大单（亿）": -0.73, "大单（亿）": 1.72, "小单（亿）": -0.04, "涨跌幅 %": 1.01},
                ],
            },
            block_trades={
                "items": [
                    {
                        "title": "6月12日贵州茅台现2笔大宗交易 机构净卖出3681.94万元",
                        "source": "新浪财经个股资讯",
                        "url": "https://example.com/block-1",
                    },
                    {
                        "title": "贵州茅台6月12日现2笔大宗交易 总成交金额2.13亿元 溢价率为-5.00%",
                        "source": "新浪财经个股资讯",
                        "url": "https://example.com/block-2",
                    },
                ]
            },
        )

        self.assertEqual(summary["block_trade_line"], "贵州茅台现2笔大宗交易，总成交金额2.13亿元，机构净卖出3681.94万元，折价率-5.00%。")
        self.assertIn("分歧偏弱", summary["fund_sentiment_line"])
        self.assertIn("白酒Ⅱ净流入且上涨", summary["fund_sentiment_line"])
        self.assertIn("茅台主力净流出", summary["fund_sentiment_line"])
        self.assertIn("大宗交易机构净卖出且折价", summary["fund_sentiment_line"])

    def test_build_market_summary_includes_margin_financing_signal(self) -> None:
        margin_financing = {
            "item": {
                "date": "2026-06-12",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "financing_balance_yi": 191.94,
                "financing_buy_yi": 4.54,
                "financing_repay_yi": 4.5,
                "financing_net_buy_yi": 0.04,
                "financing_balance_change_yi": 0.04,
                "short_balance_shares": 138228,
                "short_balance_change_shares": 4593,
            }
        }

        line = analyze_report.build_margin_financing_summary(margin_financing)["line"]
        summary = analyze_report.build_market_summary(
            {
                "quotes": {
                    "600519": {"收盘价": 1291.91, "涨跌幅": 1.01},
                }
            },
            {
                "inflow_top5": [{"板块": "证券Ⅱ", "净流入（亿）": 57.28}],
                "outflow_top5": [{"板块": "光学光电子", "净流入（亿）": -49.99}],
                "baijiu": [
                    {"板块": "白酒Ⅱ", "净流入（亿）": 4.42, "涨跌幅 %": 0.56},
                    {"板块": "贵州茅台", "净流入（亿）": -0.69, "超大单（亿）": -0.73, "涨跌幅 %": 1.01},
                ],
            },
            margin_financing=margin_financing,
        )

        self.assertIn("融资余额191.94亿元", line)
        self.assertIn("融资净买入+0.04亿元", line)
        self.assertIn("融券余量13.82万股", line)
        self.assertIn("融资端杠杆资金小幅加仓", summary["fund_sentiment_line"])
        self.assertEqual(summary["margin_financing_line"], line)

    def test_fund_flow_sanity_flags_impossible_values_and_missing_baijiu(self) -> None:
        issues = analyze_report.fund_flow_sanity_issues(
            [
                {
                    "板块": "异常板块",
                    "净流入（亿）": 120.0,
                    "超大单（亿）": 10.0,
                    "大单（亿）": 20.0,
                    "涨跌幅 %": 1.0,
                    "成交额（亿）": 10.0,
                    "净流入率 %": 1.0,
                }
            ],
            [],
        )

        issue_types = {issue["type"] for issue in issues}
        self.assertIn("fund_flow_main_net_mismatch", issue_types)
        self.assertIn("fund_flow_net_exceeds_amount", issue_types)
        self.assertIn("fund_flow_rate_mismatch", issue_types)
        self.assertIn("baijiu_table_empty", issue_types)

    def test_fund_flow_sanity_accepts_main_net_equal_super_large_plus_large(self) -> None:
        issues = analyze_report.fund_flow_sanity_issues(
            [],
            [
                {
                    "板块": "贵州茅台",
                    "净流入（亿）": -0.58,
                    "超大单（亿）": 0.85,
                    "大单（亿）": -1.43,
                    "小单（亿）": -0.01,
                    "涨跌幅 %": -1.21,
                    "成交额（亿）": 44.0,
                    "净流入率 %": -1.32,
                }
            ],
        )

        self.assertEqual(issues, [])

    def test_normalize_fund_flow_quality_expands_tushare_bucket_definition(self) -> None:
        sector = {
            "quality": {
                "source_mode": "tushare_sw2_stock_moneyflow_aggregate",
                "summary": "申万二级行业资金流由 Tushare moneyflow 个股资金流按申万二级成分股聚合；超大单/大单/小单为数据源分档字段。",
            }
        }

        normalized = analyze_report.normalize_fund_flow_quality(sector)

        summary = normalized["quality"]["summary"]
        self.assertIn("小单<5万元", summary)
        self.assertIn("大单20-100万元", summary)
        self.assertIn("特大单/超大单>=100万元", summary)
        self.assertIn("主动买卖单", summary)

    def test_main_uses_separate_top_n_for_inflow_outflow_and_divergences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "analysis.json"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "fund_flow": {
                            "inflow_outflow_top_n": 10,
                            "divergence_top_n": 5,
                            "baijiu_keywords": ["白酒"],
                        }
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            rows = []
            for idx in range(12):
                rows.append(
                    {
                        "板块": f"流入行业{idx}",
                        "净流入（亿）": 100 - idx,
                        "超大单（亿）": 20 - idx,
                        "大单（亿）": -1,
                        "涨跌幅 %": -0.5,
                        "成交额（亿）": 1000,
                        "净流入率 %": 1,
                    }
                )
                rows.append(
                    {
                        "板块": f"流出行业{idx}",
                        "净流入（亿）": -100 + idx,
                        "超大单（亿）": -20 + idx,
                        "大单（亿）": 1,
                        "涨跌幅 %": 0.5,
                        "成交额（亿）": 1000,
                        "净流入率 %": -1,
                    }
                )
            rows.append(
                {
                    "板块": "白酒Ⅱ",
                    "净流入（亿）": 1.53,
                    "超大单（亿）": 0.27,
                    "大单（亿）": 1.26,
                    "涨跌幅 %": 1.1,
                    "成交额（亿）": 147.17,
                    "净流入率 %": 1.04,
                }
            )
            (data_dir / "sector_fund_flow.json").write_text(
                json.dumps({"rows": rows, "sources": ["test"], "quality": {"level": "complete"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            for name in ["quotes", "news", "research"]:
                (data_dir / f"{name}.json").write_text("{}", encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "analyze_report.py",
                    "--config",
                    str(config_path),
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_path),
                ],
            ):
                analyze_report.main()

            analysis = json.loads(out_path.read_text(encoding="utf-8"))
            fund_flow = analysis["fund_flow"]
            self.assertEqual(len(fund_flow["inflow_top5"]), 10)
            self.assertEqual(len(fund_flow["outflow_top5"]), 10)
            self.assertEqual(len(fund_flow["divergence_net_inflow_price_down"]), 5)
            self.assertEqual(len(fund_flow["divergence_net_outflow_price_up"]), 5)
            self.assertEqual(len(fund_flow["divergence_super_in_large_out"]), 5)
            self.assertEqual(len(fund_flow["divergence_super_out_large_in"]), 5)

    def test_main_appends_primary_stock_row_to_baijiu_table_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "analysis.json"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "fund_flow": {
                            "inflow_outflow_top_n": 3,
                            "divergence_top_n": 3,
                            "baijiu_keywords": ["白酒"],
                        }
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            sector_rows = [
                {
                    "板块": "白酒Ⅱ",
                    "净流入（亿）": 4.42,
                    "超大单（亿）": 1.2,
                    "大单（亿）": 0.8,
                    "小单（亿）": -0.5,
                    "涨跌幅 %": 0.56,
                    "成交额（亿）": 170.0,
                    "净流入率 %": 2.6,
                },
                {
                    "板块": "证券Ⅱ",
                    "净流入（亿）": 57.28,
                    "超大单（亿）": 6.09,
                    "大单（亿）": 1.18,
                    "小单（亿）": -0.93,
                    "涨跌幅 %": 3.41,
                    "成交额（亿）": 410.85,
                    "净流入率 %": 13.94,
                },
            ]
            stock_rows = [
                {
                    "板块": "贵州茅台",
                    "净流入（亿）": 0.19,
                    "超大单（亿）": 0.03,
                    "大单（亿）": 0.05,
                    "小单（亿）": -0.02,
                    "涨跌幅 %": 1.01,
                    "成交额（亿）": None,
                    "净流入率 %": 0.4,
                    "板块代码": "600519.SH",
                    "sector_type": "stock_as_sector",
                }
            ]
            (data_dir / "sector_fund_flow.json").write_text(
                json.dumps(
                    {
                        "rows": sector_rows,
                        "stock_rows": stock_rows,
                        "sources": ["tushare.moneyflow.sw2_aggregate"],
                        "stock_sources": ["tushare.moneyflow.stock"],
                        "quality": {"level": "complete"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "quotes.json").write_text(
                json.dumps(
                    {
                        "quotes": {
                            "600519": {
                                "股票名称": "贵州茅台",
                                "股票代码": "600519",
                                "涨跌幅": 1.01,
                                "成交额（亿）": 48.0,
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name in ["news", "research"]:
                (data_dir / f"{name}.json").write_text("{}", encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "analyze_report.py",
                    "--config",
                    str(config_path),
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_path),
                ],
            ):
                analyze_report.main()

            analysis = json.loads(out_path.read_text(encoding="utf-8"))
            fund_flow = analysis["fund_flow"]
            self.assertEqual([row["板块"] for row in fund_flow["baijiu"]], ["白酒Ⅱ", "贵州茅台"])
            self.assertEqual(fund_flow["baijiu"][1]["成交额（亿）"], 48.0)
            self.assertNotIn("贵州茅台", [row["板块"] for row in fund_flow["inflow_top5"]])
            self.assertIn("tushare.moneyflow.stock", fund_flow["stock_sources"])

    def test_main_keeps_research_reports_out_of_news_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "analysis.json"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "fund_flow": {"baijiu_keywords": ["白酒"]},
                        "news": {"max_items": 30, "per_section": 10, "lookback_days": 30},
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (data_dir / "sector_fund_flow.json").write_text(
                json.dumps(
                    {
                        "rows": [],
                        "quality": {"target_date": "2026-06-12"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "quotes.json").write_text("{}", encoding="utf-8")
            (data_dir / "news.json").write_text(
                json.dumps(
                    {
                        "sources": ["上交所公告"],
                        "quality": {"level": "ok"},
                        "lookback_days": 30,
                        "items": [],
                        "sections": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "research.json").write_text(
                json.dumps(
                    {
                        "sources": ["新浪财经研究报告"],
                        "items": [
                            {
                                "title": "贵州茅台(600519)：动态调价纵深推进 市场化改革渐入佳境",
                                "institution": "中国国际金融股份有限公司",
                                "rating": "跑赢行业",
                                "target_price": "1670.98 元",
                                "date": "2026-05-16",
                                "url": "https://example.com/research",
                                "summary": "动态调价和市场化改革是本期核心事件，维持跑赢行业评级，目标价1670.98元。",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "analyze_report.py",
                    "--config",
                    str(config_path),
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_path),
                ],
            ):
                analyze_report.main()

            analysis = json.loads(out_path.read_text(encoding="utf-8"))
            news_titles = [
                item["title"]
                for section in analysis["news"].get("sections", [])
                for item in section.get("items", [])
            ]
            self.assertNotIn("贵州茅台(600519)：动态调价纵深推进 市场化改革渐入佳境", news_titles)
            self.assertEqual(analysis["research"]["items"][0]["institution"], "中国国际金融股份有限公司")
            self.assertEqual(analysis["research"]["items"][0]["target_price"], "1670.98 元")
            self.assertEqual(analysis["research"]["items"][0]["rating"], "跑赢行业")

    def test_main_moves_institution_view_news_into_research_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "analysis.json"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "fund_flow": {"baijiu_keywords": ["白酒"]},
                        "news": {"max_items": 30, "per_section": 10, "lookback_days": 30},
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (data_dir / "sector_fund_flow.json").write_text(
                json.dumps({"rows": [], "quality": {"target_date": "2026-06-12"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "quotes.json").write_text("{}", encoding="utf-8")
            (data_dir / "news.json").write_text(
                json.dumps(
                    {
                        "sources": ["新浪财经个股资讯"],
                        "quality": {"level": "ok", "summary": "新闻可用"},
                        "lookback_days": 30,
                        "items": [
                            {
                                "title": "高盛：维持贵州茅台买入评级，目标价上调近30%",
                                "source": "新浪财经个股资讯",
                                "time": "2026-06-12 20:30",
                                "url": "https://example.com/goldman",
                                "category": "主标的新闻",
                                "summary": "高盛：买入，目标价1616元。",
                                "institution_view": {"institution": "高盛", "rating": "买入", "target_price": "1616 元"},
                            }
                        ],
                        "sections": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "research.json").write_text(
                json.dumps({"sources": ["新浪财经研究报告"], "items": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "analyze_report.py",
                    "--config",
                    str(config_path),
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_path),
                ],
            ):
                analyze_report.main()

            analysis = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(analysis["research"]["items"][0]["institution"], "高盛")
            self.assertEqual(analysis["research"]["items"][0]["target_price"], "1616 元")
            news_titles = [
                item["title"]
                for section in analysis["news"].get("sections", [])
                for item in section.get("items", [])
            ]
            self.assertNotIn("高盛：维持贵州茅台买入评级，目标价上调近30%", news_titles)
            self.assertNotIn("高盛：维持贵州茅台买入评级，目标价上调近30%", [item["title"] for item in analysis["news"].get("items", [])])

    def test_main_exposes_public_opinion_items_from_news(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "analysis.json"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "fund_flow": {"baijiu_keywords": ["白酒"]},
                        "news": {"max_items": 30, "per_section": 10, "lookback_days": 30},
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (data_dir / "sector_fund_flow.json").write_text(
                json.dumps({"rows": [], "quality": {"target_date": "2026-06-12"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "quotes.json").write_text("{}", encoding="utf-8")
            item = {
                "title": "年轻人不喝白酒 低度酒替代成为消费趋势",
                "source": "东方财富",
                "time": "2026-06-10",
                "url": "https://example.com/young",
                "category": "行业新闻",
                "summary": "公开报道关注年轻消费者对白酒消费意愿变化。",
                "importance": "中",
                "impact_targets": ["白酒行业", "消费板块"],
                "impact_direction": "待观察",
                "impact_period": "中期（1-3个月）",
            }
            (data_dir / "news.json").write_text(
                json.dumps(
                    {
                        "sources": ["东方财富"],
                        "quality": {"level": "ok"},
                        "lookback_days": 30,
                        "items": [item],
                        "sections": [{"title": "行业新闻", "items": [item]}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "research.json").write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "analyze_report.py",
                    "--config",
                    str(config_path),
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_path),
                ],
            ):
                analyze_report.main()

            analysis = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(analysis["news"]["public_opinion"][0]["title"], "年轻人不喝白酒 低度酒替代成为消费趋势")

    def test_main_merges_macro_events_into_macro_risk_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "analysis.json"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "fund_flow": {"baijiu_keywords": ["白酒"]},
                        "news": {"max_items": 30, "per_section": 10, "lookback_days": 30},
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (data_dir / "sector_fund_flow.json").write_text(json.dumps({"rows": []}, ensure_ascii=False), encoding="utf-8")
            (data_dir / "quotes.json").write_text("{}", encoding="utf-8")
            (data_dir / "news.json").write_text(
                json.dumps({"sources": [], "quality": {"level": "ok"}, "items": [], "sections": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "research.json").write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")
            macro_item = {
                "title": "美国10年期国债收益率处于高位，估值折现率压力需跟踪",
                "source": "Federal Reserve H.15",
                "time": "2026-06-12",
                "url": "https://www.federalreserve.gov/releases/h15/",
                "category": "宏观与风险事件",
                "summary": "美国 10 年期国债收益率 4.45%。",
                "importance": "高",
                "impact_targets": ["A股市场", "全球市场"],
                "impact_direction": "利空",
                "impact_period": "中期（1-3个月）",
            }
            (data_dir / "macro.json").write_text(
                json.dumps({"sources": ["Federal Reserve H.15"], "items": [macro_item]}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "analyze_report.py",
                    "--config",
                    str(config_path),
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_path),
                ],
            ):
                analyze_report.main()

            analysis = json.loads(out_path.read_text(encoding="utf-8"))
            risk_section = next(section for section in analysis["news"]["sections"] if section["title"] == "宏观与风险事件")
            self.assertEqual(risk_section["items"][0]["title"], "美国10年期国债收益率处于高位，估值折现率压力需跟踪")
            self.assertIn("Federal Reserve H.15", analysis["news"]["sources"])
            self.assertEqual(analysis["macro"]["items"][0]["summary"], "美国 10 年期国债收益率 4.45%。")

    def test_merge_news_institution_views_into_research_keeps_target_price(self) -> None:
        research = {
            "sources": ["新浪财经研究报告"],
            "quality": {"level": "ok"},
            "items": [
                {
                    "title": "贵州茅台深度研究",
                    "institution": "华创证券有限责任公司",
                    "date": "2026-06-09",
                    "rating": "评级暂缺",
                    "target_price": "目标价暂缺",
                    "summary": "维持一年目标价2030 元和“强推”评级。",
                }
            ],
        }
        news = {
            "items": [
                {
                    "title": "高盛：维持贵州茅台买入评级，目标价上调近30%",
                    "source": "新浪财经个股资讯",
                    "time": "2026-06-12 20:30",
                    "url": "https://example.com/goldman",
                    "summary": "高盛：买入，目标价1616元。",
                    "institution_view": {"institution": "高盛", "rating": "买入", "target_price": "1616 元"},
                }
            ]
        }

        normalized = analyze_report.normalize_research_signal_fields(research)
        merged = analyze_report.merge_news_institution_views_into_research(normalized, news)

        self.assertEqual(merged["items"][0]["institution"], "高盛")
        self.assertEqual(merged["items"][0]["target_price"], "1616 元")
        self.assertEqual(merged["items"][1]["target_price"], "2030 元")
        self.assertEqual(merged["items"][1]["rating"], "强推")
        self.assertIn("机构评级新闻", merged["sources"])

    def test_filter_research_items_requires_rating_and_target_price(self) -> None:
        research = {
            "quality": {"summary": "机构观点数据可用，已获取 3 条公开研报记录。"},
            "items": [
                {"title": "完整观点", "institution": "D", "rating": "买入", "target_price": "1600 元", "summary": "完整观点摘要" * 20},
                {"title": "有评级", "institution": "A", "rating": "买入", "target_price": "目标价暂缺", "summary": ""},
                {"title": "有目标价", "institution": "B", "rating": "评级暂缺", "target_price": "1600 元", "summary": ""},
                {"title": "空观点", "institution": "C", "rating": "评级暂缺", "target_price": "目标价暂缺", "summary": ""},
            ],
        }

        filtered = analyze_report.filter_actionable_research_items(research)

        self.assertEqual([item["title"] for item in filtered["items"]], ["完整观点"])
        self.assertLessEqual(len(filtered["items"][0]["summary"]), 90)
        self.assertIn("保留 1 条同时具备评级和目标价的机构观点", filtered["quality"]["summary"])

    def test_build_core_views_leads_with_corporate_actions_and_earnings_calendar(self) -> None:
        views = analyze_report.build_core_views(
            {
                "corporate_actions": {
                    "dividend": {
                        "cash_dividend_per_share": 28.02423,
                        "cash_dividend_per_10_shares": 280.2423,
                        "approved_date": "2026-06-11",
                    },
                    "buyback": {
                        "completion_date": "2026-05-27",
                        "actual_shares_wan": 218.86,
                        "actual_amount_yi": 30.0,
                        "price_low": 1252.63,
                        "price_high": 1499.74,
                    },
                    "earnings": {"line": "财报节奏：最新定期报告为2026-04-25披露的《贵州茅台2026年第一季度报告》。"},
                },
                "summary": {"fund_sentiment_line": "偏强：白酒Ⅱ净流入且上涨。"},
            }
        )

        self.assertTrue(views[0].startswith("公司行动："))
        self.assertIn("每股28.02423元", views[0])
        self.assertIn("218.86万股/30.00亿元", views[0])
        self.assertTrue(views[1].startswith("财报节奏："))

    def test_build_earnings_deep_analysis_combines_report_with_market_context(self) -> None:
        analysis = {
            "corporate_actions": {
                "earnings": {
                    "latest_report": {
                        "title": "贵州茅台2026年第一季度报告",
                        "date": "2026-04-25",
                        "url": "https://example.com/q1.pdf",
                        "deep_analysis_ready": True,
                        "metrics": {
                            "revenue_yi": 539.09,
                            "revenue_yoy_pct": 6.54,
                            "net_profit_yi": 272.43,
                            "net_profit_yoy_pct": 1.47,
                            "operating_cash_flow_yi": 269.1,
                            "operating_cash_flow_yoy_pct": 205.48,
                            "i_moutai_revenue_yi": 215.53,
                        },
                    }
                }
            },
            "news": {"sections": [{"title": "主标的新闻", "items": [{"title": "贵州茅台分红方案通过"}]}]},
            "summary": {
                "fund_sentiment_line": "分歧偏弱：茅台主力净流出但股价上涨。",
                "baijiu_line": "白酒Ⅱ净流入 +4.42 亿，板块涨跌幅 +0.56%。",
            },
            "research": {"items": [{"institution": "高盛", "rating": "买入", "target_price": "1616 元"}]},
            "sentiment": {"summary": {"line": "东方财富股吧样本偏乐观。"}},
        }

        deep = analyze_report.build_earnings_deep_analysis(analysis)

        self.assertEqual(deep["title"], "贵州茅台2026年第一季度报告")
        joined = " ".join(deep["lines"])
        self.assertIn("营业收入539.09亿元", joined)
        self.assertIn("净利润272.43亿元", joined)
        self.assertIn("i茅台215.53亿元", joined)
        self.assertIn("资金情绪", joined)
        self.assertIn("高盛 买入 1616 元", joined)


if __name__ == "__main__":
    unittest.main()
