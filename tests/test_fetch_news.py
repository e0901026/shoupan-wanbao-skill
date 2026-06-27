from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_news  # noqa: E402


class FetchNewsTest(unittest.TestCase):
    def test_parse_sina_stock_news_filters_target_date_and_keywords(self) -> None:
        html = """
        &nbsp;&nbsp;&nbsp;&nbsp;2026-06-13&nbsp;15:54&nbsp;&nbsp;
        <a target='_blank' href='https://example.com/new'>茅台股东会释放三大信号</a> <br>
        &nbsp;&nbsp;&nbsp;&nbsp;2026-06-12&nbsp;20:44&nbsp;&nbsp;
        <a target='_blank' href='https://example.com/old'>稳进茅台释放长期信号</a> <br>
        &nbsp;&nbsp;&nbsp;&nbsp;2026-05-20&nbsp;10:11&nbsp;&nbsp;
        <a target='_blank' href='https://example.com/month'>贵州茅台分红方案落地</a> <br>
        &nbsp;&nbsp;&nbsp;&nbsp;2026-05-01&nbsp;10:11&nbsp;&nbsp;
        <a target='_blank' href='https://example.com/stale'>贵州茅台很早以前的新闻</a> <br>
        """

        items = fetch_news.parse_sina_stock_news_html(
            html,
            keywords=["茅台"],
            target_date="2026-06-12",
            lookback_days=30,
            max_items=8,
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "稳进茅台释放长期信号")
        self.assertEqual(items[0]["time"], "2026-06-12 20:44")
        self.assertEqual(items[0]["source"], "新浪财经个股资讯")
        self.assertEqual(items[0]["impact_targets"], ["贵州茅台"])
        self.assertIn(items[0]["importance"], {"高", "中", "低"})
        self.assertEqual(items[1]["title"], "贵州茅台分红方案落地")

    def test_normalize_title_groups_similar_dividend_titles(self) -> None:
        self.assertEqual(
            fetch_news.normalize_title_for_event("贵州茅台发布2025年度分红方案"),
            fetch_news.normalize_title_for_event("贵州茅台公布年度分红方案"),
        )

    def test_deduplicate_and_rank_news_prefers_better_source_for_same_event(self) -> None:
        items = [
            fetch_news.enrich_news_item(
                {
                    "title": "贵州茅台发布年度分红方案",
                    "source": "新浪财经",
                    "time": "2026-06-12 10:00",
                    "url": "https://example.com/sina",
                    "summary": "重复报道。",
                }
            ),
            fetch_news.enrich_news_item(
                {
                    "title": "贵州茅台公布年度分红方案",
                    "source": "上交所公告",
                    "time": "2026-06-12 09:30",
                    "url": "https://example.com/sse",
                    "summary": "官方公告。",
                }
            ),
            fetch_news.enrich_news_item(
                {
                    "title": "贵州茅台公布年度分红方案",
                    "source": "东方财富",
                    "time": "2026-06-12 09:40",
                    "url": "https://example.com/sse",
                    "summary": "同链接重复。",
                }
            ),
        ]

        deduped = fetch_news.deduplicate_and_rank_news(items, max_items=8)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["source"], "上交所公告")
        self.assertEqual(deduped[0]["importance"], "高")

    def test_enrich_news_item_outputs_long_term_investment_fields(self) -> None:
        item = fetch_news.enrich_news_item(
            {
                "title": "央行宣布降准释放长期资金",
                "source": "中国人民银行",
                "time": "2026-06-12 17:00",
                "url": "https://example.com/pboc",
            }
        )

        self.assertEqual(item["category"], "宏观与风险事件")
        self.assertEqual(item["impact_direction"], "利好")
        self.assertIn("A股市场", item["impact_targets"])
        self.assertEqual(item["importance"], "高")
        self.assertIn("impact_analysis", item)
        self.assertIn("impact_period", item)

    def test_enrich_news_item_classifies_macro_risk_events_named_by_user(self) -> None:
        titles = [
            "美伊战争升级冲击全球风险偏好",
            "美联储换届引发利率路径讨论",
            "美国非农数据强劲推升美债收益率",
        ]

        items = [fetch_news.enrich_news_item({"title": title, "source": "财联社", "url": f"u{idx}"}) for idx, title in enumerate(titles)]

        self.assertTrue(all(item["category"] == "宏观与风险事件" for item in items))
        self.assertTrue(all("全球市场" in item["impact_targets"] for item in items))
        self.assertIn("A股市场", items[2]["impact_targets"])

    def test_enrich_news_item_classifies_moutai_personnel_adjustment_as_key_event(self) -> None:
        item = fetch_news.enrich_news_item(
            {
                "title": "贵州茅台人事调整 董事长变动",
                "source": "上交所公告",
                "url": "u1",
            }
        )

        self.assertEqual(item["category"], "主标的新闻")
        self.assertEqual(item["importance"], "高")
        self.assertEqual(item["impact_period"], "长期（1年以上）")

    def test_enrich_news_item_keeps_moutai_block_trade_as_investment_relevant(self) -> None:
        item = fetch_news.enrich_news_item(
            {
                "title": "6月12日贵州茅台现2笔大宗交易 机构净卖出3681.94万元",
                "source": "新浪财经个股资讯",
                "url": "u1",
            }
        )

        self.assertEqual(item["category"], "主标的新闻")
        self.assertEqual(item["importance"], "中")
        self.assertEqual(item["impact_direction"], "利空")
        self.assertIn("贵州茅台", item["impact_targets"])

    def test_enrich_news_item_classifies_young_consumer_baijiu_sentiment_as_industry(self) -> None:
        item = fetch_news.enrich_news_item(
            {
                "title": "年轻人不喝白酒 低度酒替代成为消费趋势",
                "source": "东方财富",
                "url": "u1",
            }
        )

        self.assertEqual(item["category"], "行业新闻")
        self.assertIn("白酒行业", item["impact_targets"])
        self.assertIn("消费板块", item["impact_targets"])
        self.assertEqual(item["importance"], "中")

    def test_enrich_news_item_marks_competitor_accounting_risk_as_high_industry_risk(self) -> None:
        item = fetch_news.enrich_news_item(
            {
                "title": "五粮液被质疑做假账 渠道暗账暴露白酒行业风险",
                "source": "证券时报",
                "url": "u1",
            }
        )

        self.assertEqual(item["category"], "行业新闻")
        self.assertEqual(item["importance"], "高")
        self.assertEqual(item["impact_direction"], "利空")
        self.assertIn("白酒行业", item["impact_targets"])

    def test_food_beverage_etf_news_is_not_macro_risk(self) -> None:
        item = fetch_news.enrich_news_item(
            {
                "title": "食品饮料ETF冲击三连涨 贵州茅台召开股东大会",
                "source": "新浪财经",
                "url": "u1",
            }
        )

        self.assertNotEqual(item["category"], "宏观与风险事件")

    def test_enrich_institution_news_detail_extracts_goldman_target_price(self) -> None:
        raw = {
            "title": "高盛：维持贵州茅台买入评级，目标价上调近30%",
            "source": "新浪财经个股资讯",
            "time": "2026-06-12 20:30",
            "url": "https://example.com/goldman",
            "summary": "公开新闻标题指向：高盛：维持贵州茅台买入评级，目标价上调近30%",
        }
        response = Mock()
        response.text = "<article>6月12日，高盛维持对贵州茅台的买入评级，目标价1616元。</article>"
        response.encoding = "utf-8"
        response.apparent_encoding = "utf-8"
        response.raise_for_status.return_value = None

        with patch("fetch_news.requests.get", return_value=response):
            item = fetch_news.enrich_institution_news_detail(raw)

        self.assertEqual(item["institution_view"]["institution"], "高盛")
        self.assertEqual(item["institution_view"]["rating"], "买入")
        self.assertEqual(item["institution_view"]["target_price"], "1616 元")
        self.assertIn("高盛：买入，1616 元", item["summary"])

    def test_build_news_brief_prioritizes_decision_questions(self) -> None:
        brief = fetch_news.build_news_brief(
            [
                fetch_news.enrich_news_item({"title": "飞天茅台批价大幅回落", "source": "酒业家", "url": "u1"}),
                fetch_news.enrich_news_item({"title": "美联储议息会议维持利率不变", "source": "财联社", "url": "u2"}),
            ]
        )

        self.assertIn("茅台长期价值", brief)
        self.assertIn("白酒行业景气度", brief)
        self.assertIn("市场流动性", brief)
        self.assertIn("风险偏好", brief)

    def test_group_news_by_required_sections_keeps_main_industry_and_risk_buckets(self) -> None:
        grouped = fetch_news.group_news_sections(
            [
                fetch_news.enrich_news_item({"title": "贵州茅台发布年度分红方案", "source": "上交所公告", "url": "u1", "time": "2026-06-10 09:30"}),
                fetch_news.enrich_news_item({"title": "贵州茅台召开股东大会", "source": "上交所公告", "url": "u4", "time": "2026-06-12 09:30"}),
                fetch_news.enrich_news_item({"title": "飞天茅台批价大幅回落", "source": "酒业家", "url": "u2"}),
                fetch_news.enrich_news_item({"title": "央行宣布降准释放长期资金", "source": "中国人民银行", "url": "u3"}),
            ],
            per_section=3,
        )

        self.assertEqual([section["key"] for section in grouped], ["main", "industry", "risk"])
        self.assertEqual(grouped[0]["title"], "主标的新闻")
        self.assertEqual(grouped[0]["items"][0]["title"], "贵州茅台召开股东大会")
        self.assertEqual(grouped[1]["items"][0]["category"], "行业新闻")
        self.assertEqual(grouped[2]["items"][0]["category"], "宏观与风险事件")

    def test_deduplicate_and_rank_news_keeps_per_section_quota(self) -> None:
        items = [
            fetch_news.enrich_news_item({"title": "贵州茅台发布年度分红方案", "source": "上交所公告", "url": "u1"}),
            fetch_news.enrich_news_item({"title": "飞天茅台批价大幅回落", "source": "酒业家", "url": "u2"}),
            fetch_news.enrich_news_item({"title": "央行宣布降准释放长期资金", "source": "中国人民银行", "url": "u3"}),
        ]

        ranked = fetch_news.deduplicate_and_rank_news(items, max_items=12, per_section=3)

        self.assertEqual([item["category"] for item in ranked], ["主标的新闻", "行业新闻", "宏观与风险事件"])

    def test_deduplicate_and_rank_news_keeps_low_importance_relevant_items(self) -> None:
        items = [
            fetch_news.enrich_news_item({"title": "贵州茅台普通经营动态", "source": "新浪财经", "url": "u1"}),
            fetch_news.enrich_news_item({"title": "白酒渠道普通反馈", "source": "东方财富", "url": "u2"}),
            fetch_news.enrich_news_item({"title": "美元指数普通波动", "source": "财联社", "url": "u3"}),
        ]

        ranked = fetch_news.deduplicate_and_rank_news(items, max_items=12, per_section=3)

        self.assertEqual(len(ranked), 3)
        self.assertTrue(all(item["importance"] == "低" for item in ranked))

    def test_group_news_selects_high_importance_older_events_before_timeline_display(self) -> None:
        items = [
            fetch_news.enrich_news_item(
                {
                    "title": f"贵州茅台普通经营动态{idx}",
                    "source": "新浪财经",
                    "time": f"2026-06-12 {idx:02d}:00",
                    "url": f"u{idx}",
                }
            )
            for idx in range(6)
        ]
        items.append(
            fetch_news.enrich_news_item(
                {
                    "title": "贵州茅台动态调价纵深推进",
                    "source": "券商观点：中金公司",
                    "time": "2026-05-16",
                    "url": "u-old-high",
                }
            )
        )

        grouped = fetch_news.group_news_sections(items, per_section=3)
        main_titles = [item["title"] for item in grouped[0]["items"]]

        self.assertIn("贵州茅台动态调价纵深推进", main_titles)

    def test_balanced_search_keywords_includes_each_news_class(self) -> None:
        keywords = ["贵州茅台", "茅台", "白酒", "飞天批价", "降准", "美联储", "其他"]

        selected = fetch_news.balanced_search_keywords(keywords, limit=6)

        self.assertIn("贵州茅台", selected)
        self.assertIn("白酒", selected)
        self.assertIn("降准", selected)

    def test_parse_sse_announcements_to_official_news_items(self) -> None:
        payload = {
            "pageHelp": {
                "data": [
                    {
                        "SSEDATE": "2026-06-12",
                        "TITLE": "贵州茅台2025年年度权益分派实施公告",
                        "URL": "/disclosure/listedinfo/announcement/c/new/2026-06-12/600519.pdf",
                    }
                ]
            }
        }

        items = fetch_news.parse_sse_announcements(payload)

        self.assertEqual(items[0]["source"], "上交所公告")
        self.assertEqual(items[0]["time"], "2026-06-12")
        self.assertEqual(items[0]["importance"], "高")
        self.assertTrue(items[0]["url"].startswith("https://www.sse.com.cn/"))

    def test_lookback_start_for_date_limits_daily_official_news_window(self) -> None:
        self.assertEqual(fetch_news.lookback_start_for_date("2026-06-16", 4), "2026-06-13")
        self.assertEqual(fetch_news.lookback_start_for_date("2026-06-16", 30), "2026-05-18")


if __name__ == "__main__":
    unittest.main()
