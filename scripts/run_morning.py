from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from report_html_utils import ensure_pdf_export_link


def item_line(item: Dict[str, Any]) -> str:
    title = html.escape(str(item.get("title") or "标题暂缺"))
    url = html.escape(str(item.get("url") or "#"))
    source = html.escape(str(item.get("source") or "来源暂缺"))
    time = html.escape(str(item.get("time") or item.get("date") or "时间暂缺"))
    summary = html.escape(str(item.get("summary") or item.get("brief") or "摘要暂缺"))
    return f'<li><b><a href="{url}">{title}</a></b><br><span class="meta">{time} · {source}</span><br>{summary}</li>'


def section(title: str, items: List[Dict[str, Any]], empty: str) -> str:
    if not items:
        return f"<h2>{html.escape(title)}</h2><p class=\"meta\">{html.escape(empty)}</p>"
    return f"<h2>{html.escape(title)}</h2><ul>" + "\n".join(item_line(item) for item in items) + "</ul>"


def build_morning_html(
    title_date: str,
    window_start: str,
    window_end: str,
    news: Dict[str, Any],
    research: Dict[str, Any],
    sentiment: Dict[str, Any],
    macro: Dict[str, Any],
    corporate_actions: Dict[str, Any],
) -> str:
    news_items = news.get("items") or []
    main_news = [item for item in news_items if item.get("category") == "主标的新闻"]
    industry_news = [item for item in news_items if item.get("category") == "行业新闻"]
    risk_news = [*([item for item in news_items if item.get("category") == "宏观与风险事件"]), *(macro.get("items") or [])]
    research_items = research.get("items") or []
    sentiment_line = ((sentiment.get("summary") or {}).get("line") or "休市期间舆论样本暂缺。")
    action_line = (corporate_actions.get("dividend") or {}).get("line") or (corporate_actions.get("earnings") or {}).get("line") or "休市期间未识别到新的分红/财报动作。"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>开盘早报 {html.escape(title_date)}</title>
<style>body{{font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;max-width:1040px;margin:0 auto;padding:28px 24px;color:#172033;background:#f6f8fb}}h1{{font-size:30px}}h2{{border-bottom:1px solid #dce3ee;padding-bottom:8px;margin-top:30px}}a{{color:#175cd3;text-decoration:none;font-weight:700}}li{{margin:10px 0}}.meta{{color:#667085}}.card{{background:#fff;border:1px solid #dce3ee;border-radius:8px;padding:12px 14px}}</style>
</head><body>
<h1>开盘早报 {html.escape(title_date)}</h1>
<p class="meta">资讯窗口：{html.escape(window_start)} 至 {html.escape(window_end)}。本报告只整理休市期间资讯与风险，不生成未开盘行情或板块资金结论。</p>
<div class="card"><b>盘前判断：</b>先检查公告/宏观/舆论是否改变长期价值、行业景气、流动性或风险偏好；开盘后再用实时价格和资金确认。</div>
<h2>公司行动</h2><p>{html.escape(action_line)}</p>
{section('主标的新闻', main_news, '窗口内未识别到主标的新闻。')}
{section('行业新闻', industry_news, '窗口内未识别到白酒/消费行业新闻。')}
{section('宏观与风险事件', risk_news, '窗口内未识别到宏观风险事件。')}
{section('机构观点', research_items, '窗口内未识别到同时具备评级和目标价的机构观点。')}
<h2>舆论情绪</h2><p>{html.escape(sentiment_line)}</p>
<h2>开盘观察</h2><ul><li>若休市资讯偏利空，开盘先看是否放量跌破上一交易日低点。</li><li>若资讯偏中性，重点观察白酒Ⅱ和贵州茅台是否同步获得资金回流。</li><li>盘中确认前，不用早报替代收盘晚报的资金结论。</li></ul>
</body></html>"""


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def run(cmd: List[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--out")
    parser.add_argument("--data-dir", default="data/morning")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    # The existing fetchers apply their own target-date and lookback filtering. For the morning report,
    # use a conservative 3-day window around the weekend/holiday gap.
    commands = [
        [py, "scripts/fetch_news.py", "--config", args.config, "--out", str(data_dir / "news.json"), "--lookback-days", "3", "--date", args.date],
        [py, "scripts/fetch_research.py", "--config", args.config, "--out", str(data_dir / "research.json"), "--date", args.date],
        [py, "scripts/fetch_sentiment.py", "--config", args.config, "--out", str(data_dir / "sentiment.json"), "--date", args.date],
        [py, "scripts/fetch_corporate_actions.py", "--config", args.config, "--out", str(data_dir / "corporate_actions.json"), "--date", args.date],
        [py, "scripts/fetch_macro.py", "--out", str(data_dir / "macro.json"), "--date", args.date],
    ]
    for cmd in commands:
        run(cmd)
    out = Path(args.out or f"output/a_share_morning_report_{args.date}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        build_morning_html(
            args.date,
            args.window_start,
            args.window_end,
            read_json(data_dir / "news.json"),
            read_json(data_dir / "research.json"),
            read_json(data_dir / "sentiment.json"),
            read_json(data_dir / "macro.json"),
            read_json(data_dir / "corporate_actions.json"),
        ),
        encoding="utf-8",
    )
    ensure_pdf_export_link(out)
    print(out)


if __name__ == "__main__":
    main()
