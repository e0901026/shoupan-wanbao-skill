from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_morning_history  # noqa: E402
import migrate_html_sentiment  # noqa: E402


class HistoryEvidenceToolsTest(unittest.TestCase):
    def test_migrates_only_visible_same_day_sentiment_evidence(self) -> None:
        html = """
        <h3 id="舆论情绪">舆论情绪</h3>
        <p><strong>2026-06-17 12:50</strong> · <strong><a href="https://example.com/1">茅台下跌风险仍在</a></strong>
        · 东方财富股吧 · 阅读 1156 / 回复 20</p>
        <p><strong>2026-06-16 12:50</strong> · <strong><a href="https://example.com/2">旧样本</a></strong></p>
        <h3>飞天批价情绪</h3>
        """
        items = migrate_html_sentiment.parse_sentiment_items(html, "2026-06-17")
        payload = migrate_html_sentiment.build_payload(items)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["time"], "2026-06-17 12:50")
        self.assertEqual(items[0]["read_count"], 1156)
        self.assertEqual(payload["summary"]["sample_count"], 1)
        self.assertEqual(payload["quality"]["source_mode"], "archived_html_visible_evidence")

    def test_morning_audit_rejects_market_sections_and_window_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "morning.html"
            path.write_text(
                """
                <p>资讯窗口：2026-06-12 15:00 至 2026-06-15 08:30</p>
                <h2>主标的新闻</h2><ul><li><span class="meta">2026-06-15 09:00 · 新浪</span></li></ul>
                <h2>行业新闻</h2><p>无</p><h2>机构观点</h2><p>无</p>
                <h2>板块资金流向</h2>
                """,
                encoding="utf-8",
            )
            issues = audit_morning_history.audit_report(
                path,
                "2026-06-15",
                "2026-06-12 15:00",
                "2026-06-15 08:30",
            )

        self.assertTrue(any("outside window" in issue for issue in issues))
        self.assertTrue(any("forbidden unopened-market section" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
