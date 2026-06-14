from __future__ import annotations

import argparse
import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import load_yaml, now_iso, to_float, write_json
from fetch_research import compact_text


POSITIVE_WORDS = [
    "低估",
    "起飞",
    "收红",
    "回血",
    "建仓",
    "支撑",
    "触底",
    "拐点",
    "价值回归",
    "向好",
    "稳",
    "长期",
    "成长",
    "买入",
    "看多",
    "修复",
]

NEGATIVE_WORDS = [
    "利空",
    "高位",
    "看到800",
    "800",
    "下跌",
    "暴跌",
    "断崖",
    "临终",
    "接刀",
    "失血",
    "喝茶",
    "不喝",
    "有害健康",
    "风险",
    "高估",
    "看空",
]

INSTITUTION_WORDS = ["券商", "研报", "评级", "目标价", "高盛", "中金", "华创证券", "国海证券", "研究报告"]


def classify_retail_sentiment(text: str) -> str:
    positive = sum(1 for word in POSITIVE_WORDS if word in text)
    negative = sum(1 for word in NEGATIVE_WORDS if word in text)
    if negative > positive:
        return "负向"
    if positive > negative:
        return "正向"
    return "中性"


def parse_count(text: str) -> int:
    value = to_float(text)
    return int(value or 0)


def item_date_from_update(update: str, target_date: str | None) -> str | None:
    match = re.search(r"(?P<month>\d{2})-(?P<day>\d{2})\s+(?P<hour>\d{2}):(?P<minute>\d{2})", update)
    if not match:
        return None
    year = int((target_date or datetime.now().strftime("%Y-%m-%d"))[:4])
    dt = datetime(year, int(match.group("month")), int(match.group("day")), int(match.group("hour")), int(match.group("minute")))
    if target_date:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        if dt.date() > target_dt.date() and dt.month == 12 and target_dt.month == 1:
            dt = dt.replace(year=year - 1)
    return dt.strftime("%Y-%m-%d %H:%M")


def is_within_lookback(time_text: str, target_date: str | None, lookback_days: int) -> bool:
    if not target_date:
        return True
    try:
        item_dt = datetime.strptime(time_text[:10], "%Y-%m-%d")
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        return False
    start_dt = target_dt - timedelta(days=max(lookback_days - 1, 0))
    return start_dt <= item_dt <= target_dt


def parse_eastmoney_guba_posts(
    html_text: str,
    symbol: str,
    target_date: str | None,
    lookback_days: int,
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: List[Dict[str, Any]] = []
    for row in soup.select(".listitem"):
        title_el = row.select_one(".title a")
        update_el = row.select_one(".update")
        if not title_el or not update_el:
            continue
        title = " ".join(title_el.get_text(" ", strip=True).split())
        if not title or any(word in title for word in INSTITUTION_WORDS):
            continue
        time_text = item_date_from_update(update_el.get_text(" ", strip=True), target_date)
        if not time_text or not is_within_lookback(time_text, target_date, lookback_days):
            continue
        author_el = row.select_one(".author a")
        href = title_el.get("href") or ""
        item = {
            "platform": "东方财富股吧",
            "source_type": "retail_forum_post",
            "symbol": symbol,
            "title": compact_text(title, 80),
            "author": author_el.get_text(" ", strip=True) if author_el else "匿名股民",
            "time": time_text,
            "url": urljoin("https://guba.eastmoney.com/", href),
            "read_count": parse_count(row.select_one(".read").get_text(" ", strip=True) if row.select_one(".read") else ""),
            "reply_count": parse_count(row.select_one(".reply").get_text(" ", strip=True) if row.select_one(".reply") else ""),
            "sentiment": classify_retail_sentiment(title),
        }
        items.append(item)
    return items


def fetch_eastmoney_guba_posts(symbol: str, target_date: str | None, lookback_days: int, max_pages: int) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Referer": "https://guba.eastmoney.com/",
    }
    items: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        url = f"https://guba.eastmoney.com/list,{symbol},99_{page}.html"
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        items.extend(parse_eastmoney_guba_posts(resp.text, symbol=symbol, target_date=target_date, lookback_days=lookback_days))
    by_url: Dict[str, Dict[str, Any]] = {}
    for item in items:
        by_url[item["url"]] = item
    return sorted(by_url.values(), key=lambda item: (item.get("time") or "", item.get("read_count") or 0), reverse=True)


def retail_weight(item: Dict[str, Any]) -> float:
    reads = max(int(item.get("read_count") or 0), 0)
    replies = max(int(item.get("reply_count") or 0), 0)
    return 1.0 + math.log1p(reads) / 5.0 + min(replies, 50) / 20.0


def build_retail_sentiment_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    retail_items = [
        item
        for item in items
        if item.get("source_type", "retail_forum_post") == "retail_forum_post" and item.get("platform") != "券商观点"
    ]
    counts = {"正向": 0, "负向": 0, "中性": 0}
    scores = {"正向": 0.0, "负向": 0.0, "中性": 0.0}
    for item in retail_items:
        sentiment = item.get("sentiment") or "中性"
        if sentiment not in counts:
            sentiment = "中性"
        counts[sentiment] += 1
        scores[sentiment] += retail_weight(item)

    directional = scores["正向"] - scores["负向"]
    total_directional = scores["正向"] + scores["负向"]
    if not retail_items:
        tone = "样本不足"
    elif total_directional == 0:
        tone = "中性"
    elif directional / total_directional >= 0.25:
        tone = "偏乐观"
    elif directional / total_directional <= -0.25:
        tone = "偏谨慎"
    else:
        tone = "分歧"

    evidence = sorted(retail_items, key=lambda item: (retail_weight(item), item.get("time") or ""), reverse=True)[:6]
    evidence_text = "；".join(f"{item.get('sentiment')}：{item.get('title')}" for item in evidence)
    return {
        "tone": tone,
        "sample_count": len(retail_items),
        "counts": counts,
        "weighted_scores": {key: round(value, 2) for key, value in scores.items()},
        "evidence_text": evidence_text,
        "line": (
            f"东方财富股吧近窗有效样本 {len(retail_items)} 条，"
            f"正向 {counts['正向']} / 负向 {counts['负向']} / 中性 {counts['中性']}，散户情绪{tone}。"
            if retail_items
            else "散户评论样本暂缺，不能给出舆论情绪判断。"
        ),
    }


def build_source_status(items: List[Dict[str, Any]], errors: List[str]) -> List[Dict[str, str]]:
    status = [
        {
            "source": "东方财富股吧",
            "status": "可用" if items else "无有效样本",
            "detail": f"静态页面抓取到 {len(items)} 条散户帖子。" if items else "公开静态页未返回目标日期窗口内帖子。",
        },
        {"source": "雪球", "status": "需要登录态/浏览器态", "detail": "公开请求触发 WAF，后续可用 Chrome/CDP 读取已登录会话。"},
        {"source": "微博", "status": "需要登录态/搜索态", "detail": "未接入登录搜索；适合作为后续 Agent Reach/CDP 增强源。"},
        {"source": "今日头条", "status": "需要动态渲染/登录态", "detail": "未接入登录搜索与评论 API。"},
        {"source": "同花顺圈子", "status": "需动态渲染", "detail": "公开 HTML 可访问，但帖子列表未静态渲染。"},
        {"source": "新浪财经评论", "status": "接口可访问", "detail": "可按新闻 newsid 抓评论；本轮样本源优先股吧帖子。"},
    ]
    if errors:
        status.append({"source": "抓取异常", "status": "部分失败", "detail": "；".join(errors)})
    return status


def build_quality(items: List[Dict[str, Any]], errors: List[str]) -> Dict[str, Any]:
    if items:
        return {
            "level": "ok",
            "source_mode": "retail_forum_public_static",
            "summary": f"散户舆论样本可用，已抓取 {len(items)} 条东方财富股吧帖子；雪球/微博/头条等登录源暂列待增强。",
            "item_count": len(items),
        }
    return {
        "level": "empty",
        "source_mode": "none",
        "summary": "散户舆论样本暂缺；公开页面未返回有效帖子。",
        "item_count": 0,
        "error_count": len(errors),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format.")
    args = parser.parse_args()

    config = load_yaml(args.config)
    symbol = str(config.get("primary_stock", {}).get("symbol", "600519"))
    sentiment_config = config.get("sentiment", {})
    lookback_days = int(sentiment_config.get("lookback_days", 30))
    max_pages = int(sentiment_config.get("max_pages", 3))
    max_items = int(sentiment_config.get("max_items", 40))

    errors: List[str] = []
    items: List[Dict[str, Any]] = []
    try:
        items.extend(fetch_eastmoney_guba_posts(symbol, target_date=args.date, lookback_days=lookback_days, max_pages=max_pages))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"eastmoney guba failed for {symbol}: {exc}")
    items = items[:max_items]
    summary = build_retail_sentiment_summary(items)

    write_json(
        args.out,
        {
            "generated_at": now_iso(),
            "sources": ["东方财富股吧"] if items else [],
            "errors": errors,
            "quality": build_quality(items, errors),
            "lookback_days": lookback_days,
            "summary": summary,
            "source_status": build_source_status(items, errors),
            "items": items,
        },
    )


if __name__ == "__main__":
    main()
