from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import load_yaml, now_iso, to_float, write_json
from cdp_utils import open_cdp_page
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
    "亏",
    "扛不住",
    "风险",
    "高估",
    "看空",
]

INSTITUTION_WORDS = ["券商", "研报", "评级", "目标价", "高盛", "中金", "华创证券", "国海证券", "研究报告"]
TOUTIAO_TIME_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>分钟|小时)前$|^(?P<day>昨天|今天)$|^(?P<date>\d{2}-\d{2})(\s+\d{2}:\d{2})?$")


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


def parse_relative_time(time_text: str, target_date: str | None) -> str | None:
    text = " ".join(time_text.split())
    match = TOUTIAO_TIME_PATTERN.match(text)
    if not match:
        return None
    base = datetime.now()
    if target_date:
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            if base.date() != target_dt.date():
                base = target_dt.replace(hour=18, minute=0)
        except ValueError:
            pass
    if match.group("unit"):
        amount = int(match.group("value"))
        delta = timedelta(minutes=amount) if match.group("unit") == "分钟" else timedelta(hours=amount)
        return (base - delta).strftime("%Y-%m-%d %H:%M")
    if match.group("day") == "昨天":
        return (base - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    if match.group("day") == "今天":
        return base.strftime("%Y-%m-%d %H:%M")
    if match.group("date"):
        year = int((target_date or base.strftime("%Y-%m-%d"))[:4])
        raw = f"{year}-{match.group('date')}"
        if " " in text:
            return f"{raw} {text.split()[-1]}"
        return f"{raw} 00:00"
    return None


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


def clean_toutiao_title(text: str) -> str:
    title = " ".join(text.split())
    title = re.sub(r"^全文\s*", "", title)
    return compact_text(title, 120)


def normalize_toutiao_url(href: str) -> str:
    absolute = urljoin("https://so.toutiao.com/", href)
    parsed = urlparse(absolute)
    qs = parse_qs(parsed.query)
    for value in qs.get("url", []):
        decoded = unquote(value)
        nested = parse_qs(urlparse(decoded).query)
        for h5_url in nested.get("h5_url", []):
            return unquote(h5_url)
        if "toutiao.com" in decoded or "weitoutiao.zjurl.cn" in decoded:
            return decoded
    return absolute


def parse_toutiao_posts(html_text: str, keyword: str, target_date: str | None, lookback_days: int) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    anchors = soup.select("a")
    items: List[Dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        title = clean_toutiao_title(anchor.get_text(" ", strip=True))
        if len(title) < 12:
            continue
        if keyword not in title and "茅台" not in title and "白酒" not in title:
            continue
        if any(word in title for word in INSTITUTION_WORDS):
            continue
        if title in {"贵州茅台 (600519) 上证", "贵州茅台 -头条号"}:
            continue
        nearby_time = None
        for next_anchor in anchors[index + 1 : index + 5]:
            candidate = " ".join(next_anchor.get_text(" ", strip=True).split())
            if TOUTIAO_TIME_PATTERN.match(candidate):
                nearby_time = candidate
                break
        if not nearby_time:
            continue
        time_text = parse_relative_time(nearby_time, target_date)
        if not time_text or not is_within_lookback(time_text, target_date, lookback_days):
            continue
        href = anchor.get("href") or ""
        items.append(
            {
                "platform": "今日头条",
                "source_type": "retail_social_post",
                "symbol": keyword,
                "title": title,
                "author": "今日头条用户",
                "time": time_text,
                "url": normalize_toutiao_url(href),
                "read_count": 0,
                "reply_count": 0,
                "sentiment": classify_retail_sentiment(title),
            }
        )
    by_url: Dict[str, Dict[str, Any]] = {}
    for item in items:
        by_url[item["url"]] = item
    return sorted(by_url.values(), key=lambda item: item.get("time") or "", reverse=True)


def fetch_toutiao_posts(keyword: str, target_date: str | None, lookback_days: int) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Referer": "https://so.toutiao.com/",
    }
    url = f"https://so.toutiao.com/search/?pd=weitoutiao&keyword={quote(keyword)}"
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return parse_toutiao_posts(resp.text, keyword=keyword, target_date=target_date, lookback_days=lookback_days)


def strip_html_text(value: Any) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def parse_xueqiu_time(value: Any, target_date: str | None) -> str | None:
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%a %b %d %H:%M:%S %z %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    if re.fullmatch(r"\d{2}-\d{2}\s+\d{2}:\d{2}", text):
        return item_date_from_update(text, target_date)
    return parse_relative_time(text, target_date)


def extract_xueqiu_status_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("list", "statuses", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return extract_xueqiu_status_list(data)
    return []


def parse_xueqiu_status_payload(payload: Any, symbol: str, target_date: str | None, lookback_days: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for raw in extract_xueqiu_status_list(payload):
        title = strip_html_text(raw.get("title") or raw.get("text") or raw.get("description"))
        if len(title) < 6 or any(word in title for word in INSTITUTION_WORDS):
            continue
        time_text = parse_xueqiu_time(raw.get("created_at") or raw.get("timeBefore") or raw.get("time"), target_date)
        if not time_text or not is_within_lookback(time_text, target_date, lookback_days):
            continue
        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        status_id = raw.get("id") or raw.get("status_id")
        url = raw.get("target") or raw.get("url") or (f"https://xueqiu.com/{user.get('id')}/{status_id}" if status_id and user.get("id") else "https://xueqiu.com/")
        items.append(
            {
                "platform": "雪球",
                "source_type": "retail_social_post",
                "symbol": symbol,
                "title": compact_text(title, 120),
                "author": user.get("screen_name") or raw.get("screen_name") or "雪球用户",
                "time": time_text,
                "url": urljoin("https://xueqiu.com/", str(url)),
                "read_count": parse_count(str(raw.get("view_count") or raw.get("viewCount") or 0)),
                "reply_count": parse_count(str(raw.get("reply_count") or raw.get("replyCount") or raw.get("comments_count") or 0)),
                "sentiment": classify_retail_sentiment(title),
            }
        )
    by_url: Dict[str, Dict[str, Any]] = {}
    for item in items:
        by_url[item["url"]] = item
    return sorted(by_url.values(), key=lambda item: item.get("time") or "", reverse=True)


def extract_opencli_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "rows", "items", "results", "comments"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            rows = extract_opencli_rows(value)
            if rows:
                return rows
    return []


def parse_xueqiu_opencli_payload(payload: Any, symbol: str, target_date: str | None, lookback_days: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in extract_opencli_rows(payload):
        title = strip_html_text(row.get("text") or row.get("title") or row.get("content"))
        if len(title) < 6 or any(word in title for word in INSTITUTION_WORDS):
            continue
        time_text = parse_xueqiu_time(row.get("created_at") or row.get("time") or row.get("date"), target_date)
        if not time_text or not is_within_lookback(time_text, target_date, lookback_days):
            continue
        items.append(
            {
                "platform": "雪球",
                "source_type": "retail_social_post",
                "symbol": symbol,
                "title": compact_text(title, 120),
                "author": str(row.get("author") or row.get("user") or "雪球用户"),
                "time": time_text,
                "url": urljoin("https://xueqiu.com/", str(row.get("url") or "")),
                "read_count": 0,
                "reply_count": parse_count(str(row.get("replies") or row.get("reply_count") or 0)),
                "like_count": parse_count(str(row.get("likes") or row.get("like_count") or 0)),
                "retweet_count": parse_count(str(row.get("retweets") or row.get("retweet_count") or 0)),
                "sentiment": classify_retail_sentiment(title),
            }
        )
    return sorted({item["url"] or item["title"]: item for item in items}.values(), key=lambda item: item.get("time") or "", reverse=True)


def xueqiu_symbol_for(symbol: str) -> str:
    if symbol.startswith(("5", "6", "9")):
        return f"SH{symbol}"
    if symbol.startswith(("0", "1", "2", "3")):
        return f"SZ{symbol}"
    return symbol


def fetch_xueqiu_posts_via_opencli(
    symbol: str,
    target_date: str | None,
    lookback_days: int,
    limit: int = 20,
    timeout: int = 25,
) -> List[Dict[str, Any]]:
    if not shutil.which("opencli"):
        raise RuntimeError("opencli not found in PATH")
    xueqiu_symbol = xueqiu_symbol_for(symbol)
    cmd = [
        "opencli",
        "xueqiu",
        "comments",
        xueqiu_symbol,
        "--limit",
        str(limit),
        "--site-session",
        "persistent",
        "--window",
        "background",
        "-f",
        "json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"opencli xueqiu comments timeout after {timeout}s") from exc
    if result.returncode != 0:
        detail = (result.stdout or result.stderr or "").strip()
        raise RuntimeError(f"opencli xueqiu comments failed: exit {result.returncode}; {compact_text(detail, 220)}")
    text = result.stdout.strip()
    if not text:
        return []
    payload = json.loads(text)
    return parse_xueqiu_opencli_payload(payload, symbol=symbol, target_date=target_date, lookback_days=lookback_days)


def fetch_xueqiu_posts_via_cdp(
    keyword: str,
    symbol: str,
    target_date: str | None,
    lookback_days: int,
    cdp_url: str,
    max_pages: int = 2,
) -> List[Dict[str, Any]]:
    search_url = f"https://xueqiu.com/k?q={quote(keyword)}"
    xueqiu_symbol = xueqiu_symbol_for(symbol)
    session = open_cdp_page(cdp_url, search_url)
    try:
        time.sleep(2)
        all_items: List[Dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            api_path = (
                "/statuses/search.json?"
                f"count=20&comment=0&symbol={xueqiu_symbol}&hl=0&source=all&sort=time&page={page}&q={quote(keyword)}"
            )
            result_text = session.evaluate(
                f"""
fetch({json.dumps(api_path)}, {{
  credentials: 'include',
  headers: {{'Accept': 'application/json, text/plain, */*'}}
}}).then(async (r) => {{
  const text = await r.text();
  return JSON.stringify({{status: r.status, contentType: r.headers.get('content-type'), text}});
}})
""",
                await_promise=True,
            )
            result = json.loads(result_text or "{}")
            if int(result.get("status") or 0) >= 400:
                raise RuntimeError(f"xueqiu api status {result.get('status')}")
            text = result.get("text") or ""
            if not text.strip():
                continue
            payload = json.loads(text)
            all_items.extend(parse_xueqiu_status_payload(payload, symbol=symbol, target_date=target_date, lookback_days=lookback_days))
        return sorted({item["url"]: item for item in all_items}.values(), key=lambda item: item.get("time") or "", reverse=True)
    finally:
        session.close()


def retail_weight(item: Dict[str, Any]) -> float:
    reads = max(int(item.get("read_count") or 0), 0)
    replies = max(int(item.get("reply_count") or 0), 0)
    return 1.0 + math.log1p(reads) / 5.0 + min(replies, 50) / 20.0


def build_retail_sentiment_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    retail_items = [
        item
        for item in items
        if item.get("source_type", "retail_forum_post") in {"retail_forum_post", "retail_social_post", "comment"}
        and item.get("platform") != "券商观点"
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
    platform_counts: Dict[str, int] = {}
    for item in retail_items:
        platform = item.get("platform") or "未知来源"
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
    platform_text = "、".join(f"{name} {count}" for name, count in platform_counts.items())
    return {
        "tone": tone,
        "sample_count": len(retail_items),
        "counts": counts,
        "platform_counts": platform_counts,
        "weighted_scores": {key: round(value, 2) for key, value in scores.items()},
        "evidence_text": evidence_text,
        "line": (
            f"散户舆论近窗有效样本 {len(retail_items)} 条（{platform_text}），"
            f"正向 {counts['正向']} / 负向 {counts['负向']} / 中性 {counts['中性']}，散户情绪{tone}。"
            if retail_items
            else "散户评论样本暂缺，不能给出舆论情绪判断。"
        ),
    }


def build_source_status(
    items: List[Dict[str, Any]],
    errors: List[str],
    opencli_attempted: bool = False,
    cdp_attempted: bool = False,
    agentreach_available: bool = False,
) -> List[Dict[str, str]]:
    platform_counts: Dict[str, int] = {}
    for item in items:
        platform = item.get("platform") or "未知来源"
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
    status = [
        {
            "source": "东方财富股吧",
            "status": "可用" if platform_counts.get("东方财富股吧") else "无有效样本",
            "detail": f"静态页面抓取到 {platform_counts.get('东方财富股吧', 0)} 条散户帖子。" if platform_counts.get("东方财富股吧") else "公开静态页未返回目标日期窗口内帖子。",
        },
        {
            "source": "今日头条",
            "status": "可用" if platform_counts.get("今日头条") else "无有效样本",
            "detail": f"微头条搜索页抓取到 {platform_counts.get('今日头条', 0)} 条散户表达。" if platform_counts.get("今日头条") else "微头条搜索页未返回目标日期窗口内样本。",
        },
        {
            "source": "雪球",
            "status": "可用" if platform_counts.get("雪球") else ("OpenCli/CDP未取到有效样本" if (opencli_attempted or cdp_attempted) else "受 WAF/登录态限制"),
            "detail": (
                f"OpenCli/CDP 抓取到 {platform_counts.get('雪球', 0)} 条雪球讨论。"
                if platform_counts.get("雪球")
                else (
                    "已按 OpenCli -> CDP 优先级尝试雪球，但未返回目标日期窗口内讨论；OpenCli 需要 Browser Bridge extension，CDP 需要远程调试 Chrome 登录态。"
                    if (opencli_attempted or cdp_attempted)
                    else "静态搜索页仅返回应用壳，搜索 API 触发 WAF；优先用 OpenCli xueqiu adapter，其次用 XUEQIU_CDP_URL/CHROME_REMOTE_DEBUGGING_URL 登录态 Chrome/CDP。"
                )
            ),
        },
        {
            "source": "Agent Reach",
            "status": "可用待接入" if agentreach_available else "当前环境未发现",
            "detail": "OpenCli 和 CDP 都失败时作为第三层兜底；本机未发现 agentreach CLI，当前工具列表也未暴露 Agent Reach connector。" if not agentreach_available else "可作为 OpenCli/CDP 失败后的第三层动态抓取兜底。",
        },
        {"source": "微博", "status": "受访客系统/登录态限制", "detail": "公开搜索跳转 Sina Visitor System；需登录态搜索或评论接口后再接入。"},
        {"source": "同花顺圈子", "status": "需动态渲染", "detail": "公开 HTML 可访问，但帖子列表未静态渲染。"},
        {"source": "新浪财经评论", "status": "接口可访问", "detail": "可按新闻 newsid 抓评论；本轮样本源优先股吧帖子。"},
    ]
    if errors:
        status.append({"source": "抓取异常", "status": "部分失败", "detail": "；".join(errors)})
    return status


def build_quality(items: List[Dict[str, Any]], errors: List[str]) -> Dict[str, Any]:
    if items:
        platforms = sorted({item.get("platform") for item in items if item.get("platform")})
        has_login_cdp = any(item.get("platform") == "雪球" for item in items)
        return {
            "level": "ok",
            "source_mode": "retail_public_static_plus_login_cdp" if has_login_cdp else "retail_public_static_multi_source",
            "summary": f"散户舆论样本可用，已抓取 {len(items)} 条样本，来源：{'、'.join(platforms)}。",
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
    stock_name = str(config.get("primary_stock", {}).get("name", "贵州茅台"))
    sentiment_config = config.get("sentiment", {})
    lookback_days = int(sentiment_config.get("lookback_days", 30))
    max_pages = int(sentiment_config.get("max_pages", 3))
    max_items = int(sentiment_config.get("max_items", 40))
    xueqiu_opencli_enabled = bool(sentiment_config.get("xueqiu_opencli_enabled", True))
    xueqiu_opencli_timeout = int(sentiment_config.get("xueqiu_opencli_timeout", 12))
    xueqiu_cdp_url = (
        str(sentiment_config.get("xueqiu_cdp_url") or "")
        or os.getenv("XUEQIU_CDP_URL")
        or os.getenv("CHROME_REMOTE_DEBUGGING_URL")
    )

    errors: List[str] = []
    items: List[Dict[str, Any]] = []
    opencli_attempted = xueqiu_opencli_enabled
    cdp_attempted = bool(xueqiu_cdp_url)
    agentreach_available = bool(shutil.which("agentreach") or shutil.which("agent-reach"))
    try:
        items.extend(fetch_eastmoney_guba_posts(symbol, target_date=args.date, lookback_days=lookback_days, max_pages=max_pages))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"eastmoney guba failed for {symbol}: {exc}")
    try:
        items.extend(fetch_toutiao_posts(stock_name, target_date=args.date, lookback_days=lookback_days))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"toutiao search failed for {stock_name}: {exc}")
    if xueqiu_opencli_enabled:
        try:
            items.extend(fetch_xueqiu_posts_via_opencli(symbol=symbol, target_date=args.date, lookback_days=lookback_days, limit=max_items, timeout=xueqiu_opencli_timeout))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"xueqiu opencli failed for {stock_name}: {exc}")
    has_xueqiu_items = any(item.get("platform") == "雪球" for item in items)
    if xueqiu_cdp_url and not has_xueqiu_items:
        try:
            items.extend(fetch_xueqiu_posts_via_cdp(stock_name, symbol=symbol, target_date=args.date, lookback_days=lookback_days, cdp_url=xueqiu_cdp_url))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"xueqiu cdp failed for {stock_name}: {exc}")
    items = sorted({item["url"]: item for item in items}.values(), key=lambda item: item.get("time") or "", reverse=True)
    items = items[:max_items]
    summary = build_retail_sentiment_summary(items)

    write_json(
        args.out,
        {
            "generated_at": now_iso(),
            "sources": sorted({item.get("platform") for item in items if item.get("platform")}),
            "errors": errors,
            "quality": build_quality(items, errors),
            "lookback_days": lookback_days,
            "summary": summary,
            "source_status": build_source_status(items, errors, opencli_attempted=opencli_attempted, cdp_attempted=cdp_attempted, agentreach_available=agentreach_available),
            "items": items,
        },
    )


if __name__ == "__main__":
    main()
