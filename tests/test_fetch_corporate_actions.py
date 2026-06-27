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

import fetch_corporate_actions  # noqa: E402


DIVIDEND_MEETING_TEXT = """
2025年度股东会决议公告
股东会召开的时间：2026 年 6 月 11 日
议案名称：《关于 2025 年年度利润分配方案及 2026 年中期利润分配安排的议案》
审议结果：通过
会议决定，公司以实施权益分派股权登记日登记的总股本扣除回购专用账户内的股份为基数，
向全体股东每股派发 现金红利 28.02423 元（含税）。
以此计算合计拟派发现金红利 35,032,574,305.19 元（含税）。
股东会授权董事会制定 2026 年中期利润分配方案并组织实施。
"""

DIVIDEND_IMPLEMENTATION_TEXT = """
贵州茅台酒股份有限公司 2025年年度权益分派实施公告
重要内容提示：
每股分配比例 A 股每股现金红利28.02423元
相关日期 股份类别 股权登记日 最后交易日 除权（息） 日 现金红利发放日
Ａ股 2026/6/25 － 2026/6/26 2026/6/26
本次利润分配以方案实施前的公司总股本扣除回购专用账户内的股份1,250,081,601股为基数，
每股派发现金红利28.02423元（含税），共计派发现金红利35,032,574,305.19元。
"""

BUYBACK_TEXT = """
关于股份回购实施结果暨股份变动的公告
回购方案首次披露日 2025/11/6
预计回购金额 人民币 15亿元（含）～人民币 30亿元（含）
回购价格上限 1,863.67元/股
实际回购股数 2,188,614股
实际回购金额 2,999,933,749.57元
实际回购价格区间 1,252.63元/股～1,499.74元/股
2026 年 5 月 27 日，公司回购股份实施完成，实际回购公司股份 2,188,614 股，
回购最高价格 1,499.74 元/股，回购最低价格 1,252.63 元/股，回购均价 1,370.70 元/股。
预计公司将于 2026 年 5 月 28 日在中国证券登记结算有限责任公司上海分公司注销本次所回购的股份。
根据回购股份方案，公司本次回购股份 2,188,614 股将全部用于注销并减少公司注册资本。
"""

Q1_TEXT = """
贵州茅台酒股份有限公司2026 年第一季度报告
营业收入 53,909,252,220.51 50,600,957,885.78 6.54
归属于上市公司股东的净利润 27,242,512,886.45 26,847,474,238.76 1.47
经营活动产生的现金流量净额 26,909,891,269.13 8,809,195,646.38 205.48
基本每股收益（元/股） 21.76 21.38 1.78
茅台酒 系列酒 直销 批发代理 国内 国外
年初至报告期末的 主营业务收入 4,600,486.86 788,087.83 2,950,403.39 2,438,171.30 5,373,378.73 15,195.96
公司通过“i 茅台”数字营销平台实现酒类不含税收入 2,155,304.59 万元。
"""


class FetchCorporateActionsTest(unittest.TestCase):
    def test_compute_sse_acw_cookie_matches_observed_pdf_gate(self) -> None:
        cookie = fetch_corporate_actions.compute_sse_acw_cookie("D3B52C9334402553B7B6108E7E6F237C8FA3C670")

        self.assertEqual(cookie, "6a2e94b64332660e74d1763061cd5a95953fff76")

    def test_parse_dividend_and_buyback_records_build_action_lines(self) -> None:
        dividend = fetch_corporate_actions.parse_dividend_record(
            {
                "title": "贵州茅台2025年度股东会决议公告",
                "time": "2026-06-12",
                "url": "https://example.com/meeting.pdf",
            },
            DIVIDEND_MEETING_TEXT,
        )
        buyback = fetch_corporate_actions.parse_buyback_record(
            {
                "title": "贵州茅台关于回购股份实施结果暨股份变动的公告",
                "time": "2026-05-28",
                "url": "https://example.com/buyback.pdf",
            },
            BUYBACK_TEXT,
        )

        self.assertEqual(dividend["cash_dividend_per_share"], 28.02423)
        self.assertEqual(dividend["cash_dividend_per_10_shares"], 280.2423)
        self.assertEqual(dividend["approved_date"], "2026-06-11")
        self.assertIn("股权登记日", dividend["line"])
        self.assertIn("待权益分派实施公告确认", dividend["line"])
        self.assertEqual(buyback["actual_amount_yi"], 30.0)
        self.assertEqual(buyback["price_low"], 1252.63)
        self.assertEqual(buyback["price_high"], 1499.74)
        self.assertEqual(buyback["average_price"], 1370.7)
        self.assertEqual(buyback["completion_date"], "2026-05-27")
        self.assertEqual(buyback["cancel_date"], "2026-05-28")
        self.assertIn("注销并减少注册资本", buyback["line"])

    def test_parse_dividend_implementation_table_dates(self) -> None:
        dividend = fetch_corporate_actions.parse_dividend_record(
            {
                "title": "贵州茅台2025年年度权益分派实施公告",
                "time": "2026-06-22",
                "url": "https://example.com/dividend.pdf",
            },
            DIVIDEND_IMPLEMENTATION_TEXT,
        )

        self.assertEqual(dividend["record_date"], "2026-06-25")
        self.assertEqual(dividend["ex_dividend_date"], "2026-06-26")
        self.assertEqual(dividend["cash_payment_date"], "2026-06-26")
        self.assertIn("持股至股权登记日可享有本次现金分红", dividend["action"])

    def test_parse_earnings_report_triggers_deep_analysis_only_near_report_date(self) -> None:
        item = {
            "title": "贵州茅台2026年第一季度报告",
            "time": "2026-04-25",
            "url": "https://example.com/q1.pdf",
        }

        triggered = fetch_corporate_actions.parse_earnings_report(item, Q1_TEXT, target_date="2026-04-25", trigger_window_days=2)
        stale = fetch_corporate_actions.parse_earnings_report(item, Q1_TEXT, target_date="2026-06-12", trigger_window_days=2)

        self.assertTrue(triggered["deep_analysis_ready"])
        self.assertFalse(stale["deep_analysis_ready"])
        self.assertEqual(triggered["metrics"]["revenue_yi"], 539.09)
        self.assertEqual(triggered["metrics"]["net_profit_yi"], 272.43)
        self.assertEqual(triggered["metrics"]["operating_cash_flow_yi"], 269.1)
        self.assertEqual(triggered["metrics"]["i_moutai_revenue_yi"], 215.53)

    def test_select_relevant_announcements_limits_pdf_download_candidates(self) -> None:
        announcements = [
            {"title": "贵州茅台关于回购股份实施进展的公告", "time": "2026-02-04", "url": "https://example.com/buyback-2.pdf"},
            {"title": "贵州茅台关于回购股份实施进展的公告", "time": "2026-05-08", "url": "https://example.com/buyback-5.pdf"},
            {"title": "贵州茅台关于回购股份实施结果暨股份变动的公告", "time": "2026-05-28", "url": "https://example.com/buyback-result.pdf"},
            {"title": "贵州茅台2025年年度报告", "time": "2026-04-17", "url": "https://example.com/annual.pdf"},
            {"title": "贵州茅台2026年第一季度报告", "time": "2026-04-25", "url": "https://example.com/q1.pdf"},
            {"title": "贵州茅台2025年度股东会会议资料", "time": "2026-06-03", "url": "https://example.com/material.pdf"},
            {"title": "贵州茅台2025年度股东会决议公告", "time": "2026-06-12", "url": "https://example.com/meeting.pdf"},
        ]

        selected = fetch_corporate_actions.select_relevant_announcements(announcements)
        titles = [item["title"] for item in selected]

        self.assertIn("贵州茅台关于回购股份实施结果暨股份变动的公告", titles)
        self.assertIn("贵州茅台2026年第一季度报告", titles)
        self.assertIn("贵州茅台2025年度股东会决议公告", titles)
        self.assertNotIn("贵州茅台2025年度股东会会议资料", titles)
        self.assertNotIn("贵州茅台关于回购股份实施进展的公告", titles)
        self.assertNotIn("贵州茅台2025年年度报告", titles)

    def test_main_writes_corporate_actions_payload_from_official_announcements(self) -> None:
        announcements = [
            {
                "title": "贵州茅台2025年度股东会决议公告",
                "time": "2026-06-12",
                "url": "https://example.com/meeting.pdf",
            },
            {
                "title": "贵州茅台关于回购股份实施结果暨股份变动的公告",
                "time": "2026-05-28",
                "url": "https://example.com/buyback.pdf",
            },
            {
                "title": "贵州茅台2026年第一季度报告",
                "time": "2026-04-25",
                "url": "https://example.com/q1.pdf",
            },
        ]
        text_by_url = {
            "https://example.com/meeting.pdf": DIVIDEND_MEETING_TEXT,
            "https://example.com/buyback.pdf": BUYBACK_TEXT,
            "https://example.com/q1.pdf": Q1_TEXT,
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "corporate_actions.json"
            config_path.write_text(
                yaml.safe_dump({"primary_stock": {"symbol": "600519", "name": "贵州茅台"}}, allow_unicode=True),
                encoding="utf-8",
            )
            with (
                patch("fetch_corporate_actions.fetch_sse_announcements", return_value=announcements),
                patch("fetch_corporate_actions.fetch_pdf_text", side_effect=lambda url: text_by_url[url]),
                patch.object(
                    sys,
                    "argv",
                    [
                        "fetch_corporate_actions.py",
                        "--config",
                        str(config_path),
                        "--date",
                        "2026-06-12",
                        "--out",
                        str(out_path),
                    ],
                ),
            ):
                fetch_corporate_actions.main()

            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("每股现金红利28.02423元", data["dividend"]["line"])
            self.assertIn("实际回购218.86万股", data["buyback"]["line"])
            self.assertEqual(data["earnings"]["latest_report"]["title"], "贵州茅台2026年第一季度报告")
            self.assertFalse(data["earnings"]["latest_report"]["deep_analysis_ready"])


if __name__ == "__main__":
    unittest.main()
