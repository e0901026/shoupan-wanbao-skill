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

import render_report  # noqa: E402


class RenderReportTest(unittest.TestCase):
    def test_render_report_exposes_template_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            data_dir = tmp_path / "data"
            out_path = tmp_path / "report.md"
            data_dir.mkdir()

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "primary_stock": {"name": "贵州茅台", "symbol": "600519"},
                        "peer_stocks": [{"name": "五粮液", "symbol": "000858"}],
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (data_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-12 17:30:00",
                        "quotes": {
                            "sources": ["test"],
                            "quotes": {
                                "600519": {"收盘价": 1500.0, "涨跌幅": 1.2},
                                "000858": {"收盘价": 120.0, "涨跌幅": -0.5},
                            },
                        },
                        "news": {"sources": [], "items": []},
                        "research": {"sources": [], "items": []},
                        "fund_flow": {
                            "sources": ["test"],
                            "inflow_top5": [],
                            "outflow_top5": [],
                            "divergence_net_inflow_price_down": [],
                            "divergence_net_outflow_price_up": [],
                            "divergence_super_in_large_out": [],
                            "divergence_super_out_large_in": [],
                            "baijiu": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "render_report.py",
                    "--config",
                    str(config_path),
                    "--data-dir",
                    str(data_dir),
                    "--date",
                    "2026-06-12",
                    "--out",
                    str(out_path),
                ],
            ):
                render_report.main()

            report = out_path.read_text(encoding="utf-8")
            self.assertIn("股市收盘晚报 | 2026年06月12日（周五）", report)
            self.assertIn("五粮液", report)
            self.assertIn("小单（亿）", report)
            self.assertIn("超大单、大单、小单表示数据源按成交分档统计后的净买入金额", report)
            self.assertIn("Tushare moneyflow 个股资金流口径：小单为成交额 5 万元以下", report)
            self.assertIn("大单为 20-100 万元，特大单/超大单为成交额 >=100 万元", report)
            self.assertIn("行业表由申万二级成分股按上述档位净额加总，不按板块成交或一手金额重新分档", report)
            self.assertIn("贵州茅台这类一手成交金额已超过小单阈值的高价股", report)
            self.assertIn("不能把其小单字段按普通低价股的散户小买单解读", report)
            self.assertNotIn("小单约为单笔低于 2 万股且低于 4 万元", report)
            self.assertNotIn("<abbr title=", report)
            self.assertNotIn("字段说明：", report)
            self.assertIn("贵州茅台当日收于 1500.00 元（+1.20%）", report)

    def test_render_report_handles_grouped_news_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            data_dir = tmp_path / "data"
            out_path = tmp_path / "report.md"
            data_dir.mkdir()

            config_path.write_text(
                yaml.safe_dump(
                    {
                        "primary_stock": {"name": "贵州茅台", "symbol": "600519"},
                        "peer_stocks": [],
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (data_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-12 17:30:00",
                        "quotes": {"sources": ["test"], "quotes": {"600519": {"收盘价": 1500.0, "涨跌幅": 1.2}}},
                        "news": {
                            "sources": ["test"],
                            "lookback_days": 30,
                            "brief": {},
                            "sections": [
                                {
                                    "title": "主标的新闻",
                                    "empty": "无",
                                    "items": [
                                        {
                                            "title": "贵州茅台发布年度分红方案",
                                            "source": "上交所公告",
                                            "time": "2026-06-12 09:30",
                                            "url": "https://example.com",
                                            "summary": "摘要",
                                            "impact_direction": "利好",
                                            "impact_targets": ["贵州茅台"],
                                            "impact_period": "长期（1年以上）",
                                            "impact_analysis": "分析",
                                            "importance": "高",
                                        }
                                    ],
                                }
                            ],
                            "items": [{"title": "贵州茅台发布年度分红方案"}],
                        },
                        "research": {"sources": [], "items": []},
                        "fund_flow": {
                            "sources": ["test"],
                            "inflow_top5": [],
                            "outflow_top5": [],
                            "divergence_net_inflow_price_down": [],
                            "divergence_net_outflow_price_up": [],
                            "divergence_super_in_large_out": [],
                            "divergence_super_out_large_in": [],
                            "baijiu": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                ["render_report.py", "--config", str(config_path), "--data-dir", str(data_dir), "--date", "2026-06-12", "--out", str(out_path)],
            ):
                render_report.main()

            report = out_path.read_text(encoding="utf-8")
            self.assertIn("#### 主标的新闻", report)
            self.assertIn("[贵州茅台发布年度分红方案](https://example.com)", report)
            self.assertIn("摘要：摘要", report)
            self.assertNotIn("投资影响：利好", report)
            self.assertNotIn("分析：分析", report)
            self.assertNotIn("原文链接：https://example.com", report)

    def test_render_report_merges_long_term_views_into_comprehensive_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            data_dir = tmp_path / "data"
            out_path = tmp_path / "report.md"
            data_dir.mkdir()
            config_path.write_text(
                yaml.safe_dump({"primary_stock": {"name": "贵州茅台", "symbol": "600519"}, "peer_stocks": []}, allow_unicode=True),
                encoding="utf-8",
            )
            (data_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-12 17:30:00",
                        "quotes": {"sources": ["test"], "quotes": {"600519": {"收盘价": 1500.0, "涨跌幅": 1.2}}},
                        "news": {"sources": [], "items": [], "sections": [], "lookback_days": 30},
                        "research": {"sources": [], "items": []},
                        "summary": {},
                        "core_views": ["资金情绪：测试观点。"],
                        "fund_flow": {
                            "sources": ["test"],
                            "inflow_top5": [],
                            "outflow_top5": [],
                            "divergence_net_inflow_price_down": [],
                            "divergence_net_outflow_price_up": [],
                            "divergence_super_in_large_out": [],
                            "divergence_super_out_large_in": [],
                            "baijiu": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                ["render_report.py", "--config", str(config_path), "--data-dir", str(data_dir), "--date", "2026-06-12", "--out", str(out_path)],
            ):
                render_report.main()

            report = out_path.read_text(encoding="utf-8")
            self.assertNotIn("### 🧭 长期投资关注结论", report)
            self.assertIn("## 📌 综合研判", report)
            self.assertEqual(report.count("- 资金情绪：测试观点。"), 1)
            self.assertLess(report.index("## 📌 综合研判"), report.index("- 资金情绪：测试观点。"))

    def test_render_report_merges_quality_status_into_source_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            data_dir = tmp_path / "data"
            out_path = tmp_path / "report.md"
            data_dir.mkdir()
            config_path.write_text(
                yaml.safe_dump({"primary_stock": {"name": "贵州茅台", "symbol": "600519"}, "peer_stocks": []}, allow_unicode=True),
                encoding="utf-8",
            )
            (data_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-12 17:30:00",
                        "quotes": {"sources": ["行情源"], "quotes": {"600519": {"收盘价": 1500.0, "涨跌幅": 1.2}}, "errors": []},
                        "news": {"sources": ["新闻源"], "items": [], "sections": [], "quality": {"summary": "新闻可用"}},
                        "research": {"sources": ["研报源"], "items": [], "quality": {"summary": "研报可用"}},
                        "macro": {"sources": ["宏观源"], "quality": {"summary": "宏观可用"}},
                        "margin_financing": {"sources": ["融资源"], "quality": {"summary": "融资可用"}},
                        "corporate_actions": {"sources": ["公告源"], "quality": {"summary": "公告可用"}},
                        "sentiment": {"sources": ["舆论源"], "quality": {"summary": "舆论可用"}},
                        "fund_flow": {
                            "sources": ["资金源"],
                            "quality": {"summary": "资金可用", "level": "complete", "source_mode": "test_mode", "target_date": "2026-06-12"},
                            "inflow_top5": [],
                            "outflow_top5": [],
                            "divergence_net_inflow_price_down": [],
                            "divergence_net_outflow_price_up": [],
                            "divergence_super_in_large_out": [],
                            "divergence_super_out_large_in": [],
                            "baijiu": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                ["render_report.py", "--config", str(config_path), "--data-dir", str(data_dir), "--date", "2026-06-12", "--out", str(out_path)],
            ):
                render_report.main()

            report = out_path.read_text(encoding="utf-8")
            self.assertNotIn("## ✅ 数据质量状态", report)
            self.assertIn("## 🧾 数据来源与抓取说明", report)
            source_section = report[report.index("## 🧾 数据来源与抓取说明") :]
            self.assertIn("### 数据质量", source_section)
            self.assertIn("行情数据：可用", source_section)
            self.assertIn("板块资金：资金可用", source_section)
            self.assertIn("板块资金质量等级：complete / test_mode", source_section)
            self.assertIn("新闻数据：新闻可用", source_section)
            self.assertIn("### 来源与异常", source_section)
            self.assertIn("- 行情数据：行情源", source_section)

    def test_render_report_shows_empty_grouped_news_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            data_dir = tmp_path / "data"
            out_path = tmp_path / "report.md"
            data_dir.mkdir()
            config_path.write_text(
                yaml.safe_dump({"primary_stock": {"name": "贵州茅台", "symbol": "600519"}, "peer_stocks": []}, allow_unicode=True),
                encoding="utf-8",
            )
            (data_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-12 17:30:00",
                        "quotes": {"sources": ["test"], "quotes": {"600519": {"收盘价": 1500.0, "涨跌幅": 1.2}}},
                        "news": {
                            "sources": ["test"],
                            "lookback_days": 30,
                            "brief": {},
                            "sections": [
                                {"title": "主标的新闻", "empty": "近一个月未见贵州茅台主标的有效新闻。", "items": []},
                                {"title": "行业新闻", "empty": "近一个月未见白酒/消费行业有效新闻。", "items": []},
                                {"title": "宏观与风险事件", "empty": "近一个月未见流动性或风险偏好有效新闻。", "items": []},
                            ],
                            "items": [],
                        },
                        "research": {"sources": [], "items": []},
                        "fund_flow": {
                            "sources": ["test"],
                            "inflow_top5": [],
                            "outflow_top5": [],
                            "divergence_net_inflow_price_down": [],
                            "divergence_net_outflow_price_up": [],
                            "divergence_super_in_large_out": [],
                            "divergence_super_out_large_in": [],
                            "baijiu": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                ["render_report.py", "--config", str(config_path), "--data-dir", str(data_dir), "--date", "2026-06-12", "--out", str(out_path)],
            ):
                render_report.main()

            report = out_path.read_text(encoding="utf-8")
            self.assertIn("#### 主标的新闻", report)
            self.assertIn("#### 行业新闻", report)
            self.assertIn("#### 宏观与风险事件", report)

    def test_render_report_places_earnings_analysis_after_comprehensive_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            data_dir = tmp_path / "data"
            out_path = tmp_path / "report.md"
            data_dir.mkdir()
            config_path.write_text(
                yaml.safe_dump({"primary_stock": {"name": "贵州茅台", "symbol": "600519"}, "peer_stocks": []}, allow_unicode=True),
                encoding="utf-8",
            )
            (data_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-25 17:30:00",
                        "quotes": {"sources": ["test"], "quotes": {"600519": {"收盘价": 1500.0, "涨跌幅": 1.2}}},
                        "news": {"sources": [], "items": [], "sections": []},
                        "research": {"sources": [], "items": []},
                        "summary": {},
                        "core_views": ["财报节奏：最新定期报告为2026-04-25披露。"],
                        "earnings_analysis": {
                            "title": "贵州茅台2026年第一季度报告",
                            "date": "2026-04-25",
                            "url": "https://example.com/q1.pdf",
                            "lines": ["财报事实：营业收入539.09亿元。", "结合资金情绪：白酒Ⅱ净流入。"],
                        },
                        "fund_flow": {
                            "sources": ["test"],
                            "inflow_top5": [],
                            "outflow_top5": [],
                            "divergence_net_inflow_price_down": [],
                            "divergence_net_outflow_price_up": [],
                            "divergence_super_in_large_out": [],
                            "divergence_super_out_large_in": [],
                            "baijiu": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                ["render_report.py", "--config", str(config_path), "--data-dir", str(data_dir), "--date", "2026-04-25", "--out", str(out_path)],
            ):
                render_report.main()

            report = out_path.read_text(encoding="utf-8")
            self.assertIn("## 📑 财报深度解读", report)
            self.assertLess(report.index("## 📌 综合研判"), report.index("## 📑 财报深度解读"))
            self.assertIn("[贵州茅台2026年第一季度报告](https://example.com/q1.pdf)", report)

    def test_fund_table_includes_small_order_column(self) -> None:
        table = render_report.fund_table(
            [
                {
                    "板块": "半导体",
                    "净流入（亿）": -33.38,
                    "超大单（亿）": -10.0,
                    "大单（亿）": -23.38,
                    "小单（亿）": 12.3,
                    "涨跌幅 %": -1.6,
                    "成交额（亿）": 1200.0,
                    "净流入率 %": -2.78,
                }
            ]
        )

        self.assertIn("| 板块 | 净流入（亿） | 超大单（亿） | 大单（亿） | 小单（亿） | 涨跌幅 % | 成交额（亿） | 净流入率 % |", table)
        self.assertIn("| 半导体 | -33.38 | -10.00 | -23.38 | +12.30 | -1.60% | 1200.00 | -2.78% |", table)


if __name__ == "__main__":
    unittest.main()
