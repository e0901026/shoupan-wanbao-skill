from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_sentiment  # noqa: E402


class FetchSentimentTest(unittest.TestCase):
    def test_parse_eastmoney_guba_posts_filters_by_target_date(self) -> None:
        html = """
        <table>
          <tr class="listitem">
            <td><div class="read">183</div></td>
            <td><div class="reply">4</div></td>
            <td><div class="title"><a href="//caifuhao.eastmoney.com/news/1">茅台已经在历史高位了，这个股价可以看到800</a></div></td>
            <td><div class="author"><a>怼穿肠</a></div></td>
            <td><div class="update">06-12 11:12</div></td>
          </tr>
          <tr class="listitem">
            <td><div class="read">80</div></td>
            <td><div class="reply">1</div></td>
            <td><div class="title"><a href="//caifuhao.eastmoney.com/news/2">今天希望收红，让咱过个愉快的周末。</a></div></td>
            <td><div class="author"><a>散户A</a></div></td>
            <td><div class="update">06-12 05:55</div></td>
          </tr>
          <tr class="listitem">
            <td><div class="read">75</div></td>
            <td><div class="reply">0</div></td>
            <td><div class="title"><a href="//caifuhao.eastmoney.com/news/3">6月14日的新帖子不能混入6月12日晚报</a></div></td>
            <td><div class="author"><a>散户B</a></div></td>
            <td><div class="update">06-14 04:18</div></td>
          </tr>
        </table>
        """

        items = fetch_sentiment.parse_eastmoney_guba_posts(html, symbol="600519", target_date="2026-06-12", lookback_days=30)

        self.assertEqual([item["title"] for item in items], ["茅台已经在历史高位了，这个股价可以看到800", "今天希望收红，让咱过个愉快的周末。"])
        self.assertEqual(items[0]["sentiment"], "负向")
        self.assertEqual(items[1]["sentiment"], "正向")
        self.assertEqual(items[0]["time"], "2026-06-12 11:12")
        self.assertEqual(items[0]["platform"], "东方财富股吧")

    def test_build_retail_sentiment_summary_uses_only_retail_posts(self) -> None:
        items = [
            {
                "title": "茅台已经在历史高位了，这个股价可以看到800",
                "sentiment": "负向",
                "read_count": 183,
                "reply_count": 4,
                "platform": "东方财富股吧",
            },
            {
                "title": "白酒即将起飞",
                "sentiment": "正向",
                "read_count": 90,
                "reply_count": 1,
                "platform": "东方财富股吧",
            },
            {
                "title": "中金维持贵州茅台跑赢行业评级",
                "sentiment": "中性",
                "read_count": 1000,
                "reply_count": 10,
                "platform": "券商观点",
            },
        ]

        summary = fetch_sentiment.build_retail_sentiment_summary(items)

        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["counts"]["负向"], 1)
        self.assertEqual(summary["counts"]["正向"], 1)
        self.assertNotIn("中金", summary["evidence_text"])

    def test_build_retail_sentiment_summary_includes_social_posts(self) -> None:
        items = [
            {
                "title": "贵州茅台扛不住了",
                "sentiment": "负向",
                "platform": "今日头条",
                "source_type": "retail_social_post",
            },
            {
                "title": "贵州茅台支撑很稳",
                "sentiment": "正向",
                "platform": "东方财富股吧",
                "source_type": "retail_forum_post",
            },
        ]

        summary = fetch_sentiment.build_retail_sentiment_summary(items)

        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["platform_counts"], {"今日头条": 1, "东方财富股吧": 1})

    def test_parse_toutiao_posts_pairs_content_with_relative_time(self) -> None:
        html = """
        <a href="/search/jump?url=https%3A%2F%2Ftoutiao.com%2Fgroup%2F1">全文 过去信白酒价值能穿越周期，现在周期早已转向科技，贵州茅台只会越扛越亏。</a>
        <a href="/search/jump?url=https%3A%2F%2Ftoutiao.com%2Fgroup%2F1_time">7小时前</a>
        <a href="/search/jump?url=https%3A%2F%2Ftoutiao.com%2Fgroup%2F2">全文 贵州茅台回购股票意味着公司觉得股票被低估。</a>
        <a href="/search/jump?url=https%3A%2F%2Ftoutiao.com%2Fgroup%2F2_time">5小时前</a>
        <a href="/search/jump?url=https%3A%2F%2Ftoutiao.com%2Fgroup%2F3">贵州茅台 (600519) 上证</a>
        <a>今天</a>
        """

        with patch("fetch_sentiment.datetime") as fake_datetime:
            fake_datetime.now.return_value = real_datetime(2026, 6, 15, 18, 0)
            fake_datetime.strptime.side_effect = real_datetime.strptime
            items = fetch_sentiment.parse_toutiao_posts(html, keyword="贵州茅台", target_date="2026-06-15", lookback_days=1)

        self.assertEqual([item["platform"] for item in items], ["今日头条", "今日头条"])
        self.assertEqual(items[0]["time"], "2026-06-15 13:00")
        self.assertEqual(items[0]["sentiment"], "正向")
        self.assertEqual(items[1]["sentiment"], "负向")
        self.assertTrue(items[0]["url"].startswith("https://toutiao.com/") or items[0]["url"].startswith("https://weitoutiao.zjurl.cn/"))
        self.assertNotIn("600519", [item["title"] for item in items])

    def test_main_writes_sentiment_payload_from_eastmoney(self) -> None:
        html = """
        <tr class="listitem">
          <td><div class="read">183</div></td>
          <td><div class="reply">4</div></td>
          <td><div class="title"><a href="//caifuhao.eastmoney.com/news/1">茅台已经在历史高位了，这个股价可以看到800</a></div></td>
          <td><div class="author"><a>怼穿肠</a></div></td>
          <td><div class="update">06-12 11:12</div></td>
        </tr>
        """
        response = Mock()
        response.text = html
        response.status_code = 200
        response.raise_for_status.return_value = None

        with tempfile.TemporaryDirectory() as tmp, patch("fetch_sentiment.requests.get", return_value=response):
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "sentiment.json"
            config_path.write_text("primary_stock:\n  symbol: '600519'\nsentiment:\n  lookback_days: 30\n  max_pages: 1\n", encoding="utf-8")
            with patch.object(sys, "argv", ["fetch_sentiment.py", "--config", str(config_path), "--date", "2026-06-12", "--out", str(out_path)]):
                fetch_sentiment.main()

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["quality"]["level"], "ok")
            self.assertEqual(payload["summary"]["sample_count"], 1)
            self.assertEqual(payload["items"][0]["title"], "茅台已经在历史高位了，这个股价可以看到800")


if __name__ == "__main__":
    unittest.main()
