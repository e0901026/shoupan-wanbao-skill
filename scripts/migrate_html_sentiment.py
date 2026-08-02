from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from common import now_iso, write_json
from fetch_sentiment import build_retail_sentiment_summary, classify_retail_sentiment


TIME_RE = re.compile(r"(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})")
COUNTS_RE = re.compile(r"阅读\s*(?P<read>\d+)\s*/\s*回复\s*(?P<reply>\d+)")


def parse_sentiment_items(html_text: str, report_date: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    heading = soup.find(id="舆论情绪")
    if not isinstance(heading, Tag):
        return []

    items: list[dict[str, Any]] = []
    for node in heading.find_all_next():
        if node is not heading and node.name in {"h2", "h3"}:
            break
        if node.name != "p":
            continue
        text = " ".join(node.get_text(" ", strip=True).split())
        time_match = TIME_RE.search(text)
        link = node.find("a", href=True)
        if not time_match or not link or not time_match.group("time").startswith(report_date):
            continue
        title = " ".join(link.get_text(" ", strip=True).split())
        count_match = COUNTS_RE.search(text)
        platform = next(
            (name for name in ["雪球", "微博", "今日头条", "东方财富股吧", "同花顺圈子", "新浪财经评论"] if name in text),
            "历史报告留存样本",
        )
        items.append(
            {
                "platform": platform,
                "source_type": "retail_forum_post",
                "symbol": "600519",
                "title": title,
                "author": "历史报告未展示",
                "time": time_match.group("time"),
                "url": link.get("href"),
                "read_count": int(count_match.group("read")) if count_match else 0,
                "reply_count": int(count_match.group("reply")) if count_match else 0,
                "sentiment": classify_retail_sentiment(title),
                "evidence_provenance": "同日期旧版HTML可见条目迁移；保留原始链接，未补写正文。",
            }
        )
    return list({item["url"]: item for item in items}.values())


def build_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    platforms = sorted({item["platform"] for item in items})
    return {
        "generated_at": now_iso(),
        "sources": platforms,
        "errors": [],
        "quality": {
            "level": "ok" if items else "empty",
            "source_mode": "archived_html_visible_evidence",
            "summary": (
                f"从同日期旧版HTML迁移 {len(items)} 条可见散户舆论证据；仅统计可复核条目，不沿用无法逐条复核的旧聚合数。"
                if items
                else "同日期旧版HTML未找到可复核散户舆论条目。"
            ),
            "item_count": len(items),
        },
        "lookback_days": 1,
        "summary": build_retail_sentiment_summary(items),
        "source_status": [
            {
                "source": "历史HTML证据迁移",
                "status": "可复核" if items else "无有效样本",
                "detail": "仅迁移报告中可见的时间、标题、链接、平台及互动数；未恢复当时未展示的样本。",
            }
        ],
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate visible sentiment evidence from a dated HTML report.")
    parser.add_argument("--html", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    html_text = Path(args.html).read_text(encoding="utf-8")
    write_json(args.out, build_payload(parse_sentiment_items(html_text, args.date)))


if __name__ == "__main__":
    main()
