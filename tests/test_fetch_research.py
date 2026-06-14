from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_research  # noqa: E402


class FetchResearchTest(unittest.TestCase):
    def test_parse_sina_research_list_keeps_reports_on_or_before_target_date(self) -> None:
        html = """
        <table>
          <tr><td>序号</td><td>标题</td><td>报告类型</td><td>发布日期</td><td>机构</td><td>研究员</td></tr>
          <tr>
            <td>1</td><td><a href='//stock.finance.sina.com.cn/report1'>贵州茅台：新报告</a></td>
            <td>公司</td><td>2026-06-13</td><td>甲证券</td><td>张三</td>
          </tr>
          <tr>
            <td>2</td><td><a href='//stock.finance.sina.com.cn/report2'>贵州茅台：不竭泽而渔</a></td>
            <td>公司</td><td>2026-06-12</td><td>国海证券股份有限公司</td><td>刘旭德</td>
          </tr>
        </table>
        """

        items = fetch_research.parse_sina_research_list_html(html, target_date="2026-06-12")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["institution"], "国海证券股份有限公司")
        self.assertEqual(items[0]["analyst"], "刘旭德")
        self.assertEqual(items[0]["date"], "2026-06-12")
        self.assertTrue(items[0]["url"].startswith("https://stock.finance.sina.com.cn/"))

    def test_extract_rating_and_target_from_research_text(self) -> None:
        signals = fetch_research.extract_rating_and_target(
            "维持一年目标价2030 元和“强推”评级。维持目标价1670.98 元，对应2026年25倍PE。"
        )

        self.assertEqual(signals["target_price"], "2030 元")
        self.assertEqual(signals["rating"], "强推")

    def test_parse_research_detail_outputs_structured_target_and_rating(self) -> None:
        html = """
        <div class="content">
          盈利预测与估值 我们基本维持2026/27年盈利预测不变，
          维持目标价1670.98 元，对应2026/27 年25.0x/24.0x P/E，有25.4%上行空间。
          维持跑赢行业评级。
        </div>
        """

        detail = fetch_research.parse_sina_research_detail(html, "贵州茅台")

        self.assertEqual(detail["target_price"], "1670.98 元")
        self.assertEqual(detail["rating"], "跑赢行业")
        self.assertIn("维持目标价1670.98 元", detail["summary"])


if __name__ == "__main__":
    unittest.main()
