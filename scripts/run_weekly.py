from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from report_html_utils import ensure_pdf_export_link

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:  # pragma: no cover - only used in very small environments.
    BeautifulSoup = None  # type: ignore[assignment]
    Tag = Any  # type: ignore[misc,assignment]


FUND_FLOW_KEYS = [
    "inflow_top5",
    "outflow_top5",
    "divergence_net_inflow_price_down",
    "divergence_net_outflow_price_up",
    "divergence_super_in_large_out",
    "divergence_super_out_large_in",
]

FLOW_HEADERS = [
    "板块",
    "出现次数",
    "净流入（亿）",
    "超大单（亿）",
    "大单（亿）",
    "小单（亿）",
    "平均涨跌幅 %",
    "成交额（亿）",
    "平均净流入率 %",
]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace("+", "").replace("%", "").replace("亿", "").replace(",", "").strip()
    if not text or text == "暂缺":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt(value: Any, suffix: str = "", signed: bool = False) -> str:
    n = to_float(value)
    if n is None:
        return "暂缺"
    sign = "+" if signed and n > 0 else ""
    return f"{sign}{n:.2f}{suffix}"


def parse_daily_review_numbers(analysis: Dict[str, Any]) -> Dict[str, float]:
    joined = " ".join((analysis.get("daily_review") or {}).get("lines") or [])
    out: Dict[str, float] = {}
    match = re.search(r"贵州茅台净流入([+-]?[\d.]+)亿，超大单([+-]?[\d.]+)亿，大单([+-]?[\d.]+)亿，小单([+-]?[\d.]+)亿", joined)
    if match:
        out.update(
            {
                "moutai_net": float(match.group(1)),
                "moutai_super": float(match.group(2)),
                "moutai_large": float(match.group(3)),
                "moutai_small": float(match.group(4)),
            }
        )
    match = re.search(r"白酒Ⅱ净流入([+-]?[\d.]+)亿、涨跌幅([+-]?[\d.]+)%", joined)
    if match:
        out.update({"baijiu_net": float(match.group(1)), "baijiu_pct": float(match.group(2))})
    match = re.search(r"资金主攻方向集中在(.+?)(?:。|$)", joined)
    if match:
        out["leaders"] = match.group(1)  # type: ignore[assignment]
    return out


def archive_path(root: Path, date: str) -> Path:
    return root / "data" / "archive" / f"analysis_{date}.json"


def daily_html_path(root: Path, date: str) -> Path:
    return root / "output" / f"a_share_evening_report_{date}.html"


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_html_table(table_node: Tag | None) -> List[Dict[str, str]]:
    if not table_node:
        return []
    headers = [clean_text(th.get_text(" ", strip=True)) for th in table_node.find_all("th")]
    rows: List[Dict[str, str]] = []
    for tr in table_node.find_all("tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if not cells:
            continue
        if not headers:
            headers = [f"列{i + 1}" for i in range(len(cells))]
        rows.append({headers[i]: cells[i] for i in range(min(len(headers), len(cells)))})
    return rows


def find_heading(soup: Any, text: str, tags: tuple[str, ...] = ("h2", "h3")) -> Tag | None:
    if soup is None:
        return None
    for node in soup.find_all(tags):
        if text in clean_text(node.get_text(" ", strip=True)):
            return node
    return None


def siblings_until(start: Tag | None, stop_tags: tuple[str, ...]) -> List[Tag]:
    if start is None:
        return []
    nodes: List[Tag] = []
    for node in start.find_next_siblings():
        if getattr(node, "name", None) in stop_tags:
            break
        if getattr(node, "name", None):
            nodes.append(node)
    return nodes


def first_table_after_heading(soup: Any, heading_text: str) -> Tag | None:
    heading = find_heading(soup, heading_text, ("h3", "h2"))
    if not heading:
        return None
    return heading.find_next("table")


def first_liquor_compare_table(soup: Any) -> Tag | None:
    if soup is None:
        return None
    for node in soup.find_all(("h2", "h3")):
        text = clean_text(node.get_text(" ", strip=True))
        if "白酒板块" in text and "对比" not in text:
            return node.find_next("table")
    return None


def parse_news_from_html(soup: Any) -> Dict[str, Any]:
    news_heading = find_heading(soup, "要闻速览", ("h2",))
    items: List[Dict[str, str]] = []
    current_category = ""
    for node in siblings_until(news_heading, ("h2",)):
        if getattr(node, "name", None) == "h4":
            current_category = clean_text(node.get_text(" ", strip=True))
            continue
        if getattr(node, "name", None) != "p":
            continue
        link = node.find("a")
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        title = clean_text(link.get_text(" ", strip=True)) if link else text
        url = str(link.get("href", "")) if link else ""
        time_match = re.search(r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)", text)
        parts = [clean_text(p) for p in text.split("·")]
        source = parts[2] if len(parts) >= 3 and link else (parts[1] if len(parts) >= 2 else "")
        summary_match = re.search(r"摘要[:：]\s*(.+)$", text)
        items.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "time": time_match.group(1) if time_match else "",
                "summary": summary_match.group(1) if summary_match else "",
                "category": current_category,
            }
        )
    return {"items": items}


def parse_sentiment_from_html(soup: Any) -> Dict[str, Any]:
    heading = find_heading(soup, "市场情绪", ("h2",))
    p_texts = [clean_text(node.get_text(" ", strip=True)) for node in siblings_until(heading, ("h2",)) if getattr(node, "name", None) == "p"]
    fund_line = ""
    retail_line = ""
    sample_count = 0
    for text in p_texts:
        if "情绪判断" in text and not fund_line:
            fund_line = text
        if ("散户舆论" in text or "散户情绪" in text) and not retail_line:
            retail_line = text
            match = re.search(r"有效样本\s*(\d+)\s*条", text)
            if match:
                sample_count = int(match.group(1))
    return {"summary": {"line": retail_line or fund_line or (p_texts[0] if p_texts else ""), "fund_line": fund_line, "sample_count": sample_count}}


def parse_daily_review_from_html(soup: Any) -> Dict[str, Any]:
    heading = find_heading(soup, "今日复盘", ("h2",))
    lines: List[str] = []
    for node in siblings_until(heading, ("h2",)):
        if getattr(node, "name", None) == "li":
            lines.append(clean_text(node.get_text(" ", strip=True)))
        if getattr(node, "name", None) == "ul":
            lines.extend(clean_text(li.get_text(" ", strip=True)) for li in node.find_all("li"))
    return {"lines": [line for line in lines if line]}


def parse_quote_from_html(soup: Any) -> Dict[str, Any]:
    text = clean_text(soup.get_text(" ", strip=True))
    quote: Dict[str, Any] = {}
    close_match = re.search(r"收盘[:：]\s*([+-]?[\d.]+)\s*元[（(]([+-]?[\d.]+)%[）)]", text)
    amount_match = re.search(r"成交额[:：]\s*([+-]?[\d.]+)\s*亿", text)
    if close_match:
        quote["收盘价"] = close_match.group(1)
        quote["涨跌幅"] = close_match.group(2)
    if amount_match:
        quote["成交额（亿）"] = amount_match.group(1)
    return {"quotes": {"600519": quote}}


def parse_fund_flow_from_html(soup: Any) -> Dict[str, Any]:
    mapping = {
        "净流入 TOP": "inflow_top5",
        "净流出 TOP": "outflow_top5",
        "背离一": "divergence_net_inflow_price_down",
        "背离二": "divergence_net_outflow_price_up",
        "背离三": "divergence_super_in_large_out",
        "背离四": "divergence_super_out_large_in",
    }
    out: Dict[str, Any] = {key: [] for key in FUND_FLOW_KEYS}
    for heading_text, key in mapping.items():
        out[key] = parse_html_table(first_table_after_heading(soup, heading_text))
    out["liquor_compare"] = parse_html_table(first_liquor_compare_table(soup))
    return out


def parse_daily_html(path: Path) -> Dict[str, Any]:
    if BeautifulSoup is None:
        raise RuntimeError("当前 Python 环境缺少 bs4，无法从日报 HTML 回退解析周报数据。")
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    return {
        "quotes": parse_quote_from_html(soup),
        "daily_review": parse_daily_review_from_html(soup),
        "news": parse_news_from_html(soup),
        "sentiment": parse_sentiment_from_html(soup),
        "fund_flow": parse_fund_flow_from_html(soup),
        "summary": {},
    }


def load_daily_analyses(root: Path, dates: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for date in dates:
        path = archive_path(root, date)
        if path.exists():
            out[date] = read_json(path)
            continue
        html_path = daily_html_path(root, date)
        if html_path.exists():
            out[date] = parse_daily_html(html_path)
    return out


def load_institutional_evidence(root: Path, start: str, end: str) -> Dict[str, Any]:
    path = root / "data" / f"institutional_evidence_{start}_{end}.json"
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def load_corporate_actions(root: Path) -> Dict[str, Any]:
    path = root / "data" / "corporate_actions.json"
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def board_rows(analyses: Dict[str, Dict[str, Any]], key: str, limit: int = 10) -> List[List[str]]:
    counts: Counter[str] = Counter()
    sums: defaultdict[str, float] = defaultdict(float)
    for analysis in analyses.values():
        for row in (analysis.get("fund_flow") or {}).get(key) or []:
            name = row.get("板块")
            if not name:
                continue
            counts[str(name)] += 1
            sums[str(name)] += to_float(row.get("净流入（亿）")) or 0
    return [[name, f"{count}/{len(analyses)}", fmt(sums[name], "亿", signed=True)] for name, count in counts.most_common(limit)]


def average(values: List[float]) -> float | None:
    return sum(values) / len(values) if values else None


def cumulative_return_from_daily_pct(values: Iterable[Any]) -> float | None:
    product = 1.0
    count = 0
    for value in values:
        pct = to_float(value)
        if pct is None:
            continue
        product *= 1 + pct / 100
        count += 1
    return (product - 1) * 100 if count else None


def cash_dividends_in_window(corporate_actions: Dict[str, Any], start: str, end: str) -> List[Dict[str, Any]]:
    dividend = corporate_actions.get("dividend") or {}
    ex_date = clean_text(dividend.get("ex_dividend_date"))
    per_share = to_float(dividend.get("cash_dividend_per_share"))
    if not ex_date or per_share is None or not (start <= ex_date <= end):
        return []
    return [{"ex_date": ex_date, "cash_dividend_per_share": per_share, "title": dividend.get("title") or "现金分红"}]


def infer_previous_close(first_close: float | None, first_daily_pct: Any, first_day_dividend: float = 0.0) -> float | None:
    pct = to_float(first_daily_pct)
    if first_close is None or pct is None:
        return None
    adjusted_reference = first_close / (1 + pct / 100)
    return adjusted_reference + first_day_dividend


def total_return_with_cash_dividend(
    closes: List[float],
    daily_pct_values: List[Any],
    dividends: List[Dict[str, Any]],
    start: str,
) -> float | None:
    if not closes or not daily_pct_values:
        return None
    first_day_dividend = sum(to_float(item.get("cash_dividend_per_share")) or 0 for item in dividends if item.get("ex_date") == start)
    previous_close = infer_previous_close(closes[0], daily_pct_values[0], first_day_dividend)
    if previous_close is None or previous_close == 0:
        return None
    cash = sum(to_float(item.get("cash_dividend_per_share")) or 0 for item in dividends)
    return ((closes[-1] + cash) / previous_close - 1) * 100


def flow_change_rows(analyses: Dict[str, Dict[str, Any]], key: str, limit: int = 10) -> List[List[str]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for analysis in analyses.values():
        for row in (analysis.get("fund_flow") or {}).get(key) or []:
            name = clean_text(row.get("板块"))
            if not name:
                continue
            item = grouped.setdefault(
                name,
                {
                    "count": 0,
                    "net": 0.0,
                    "super": 0.0,
                    "large": 0.0,
                    "small": 0.0,
                    "amount": 0.0,
                    "pct": [],
                    "rate": [],
                },
            )
            item["count"] += 1
            item["net"] += to_float(row.get("净流入（亿）")) or 0
            item["super"] += to_float(row.get("超大单（亿）")) or 0
            item["large"] += to_float(row.get("大单（亿）")) or 0
            item["small"] += to_float(row.get("小单（亿）")) or 0
            item["amount"] += to_float(row.get("成交额（亿）")) or 0
            pct = to_float(row.get("涨跌幅 %"))
            rate = to_float(row.get("净流入率 %"))
            if pct is not None:
                item["pct"].append(pct)
            if rate is not None:
                item["rate"].append(rate)
    ordered = sorted(grouped.items(), key=lambda kv: (kv[1]["count"], abs(kv[1]["net"])), reverse=True)[:limit]
    return [
        [
            name,
            f"{item['count']}/{len(analyses)}",
            fmt(item["net"], signed=True),
            fmt(item["super"], signed=True),
            fmt(item["large"], signed=True),
            fmt(item["small"], signed=True),
            fmt(average(item["pct"]), signed=True),
            fmt(item["amount"]),
            fmt(average(item["rate"]), signed=True),
        ]
        for name, item in ordered
    ]


def weekly_net_flow_rows(analyses: Dict[str, Dict[str, Any]], direction: str, limit: int = 10) -> List[List[str]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    seen_by_date: set[tuple[str, str, str]] = set()
    for date, analysis in analyses.items():
        flow = analysis.get("fund_flow") or {}
        for key in ("inflow_top5", "outflow_top5"):
            for row in flow.get(key) or []:
                name = clean_text(row.get("板块"))
                if not name:
                    continue
                marker = (date, key, name)
                if marker in seen_by_date:
                    continue
                seen_by_date.add(marker)
                item = grouped.setdefault(
                    name,
                    {
                        "count": 0,
                        "net": 0.0,
                        "super": 0.0,
                        "large": 0.0,
                        "small": 0.0,
                        "amount": 0.0,
                        "pct": [],
                        "rate": [],
                    },
                )
                item["count"] += 1
                item["net"] += to_float(row.get("净流入（亿）")) or 0
                item["super"] += to_float(row.get("超大单（亿）")) or 0
                item["large"] += to_float(row.get("大单（亿）")) or 0
                item["small"] += to_float(row.get("小单（亿）")) or 0
                item["amount"] += to_float(row.get("成交额（亿）")) or 0
                pct = to_float(row.get("涨跌幅 %"))
                rate = to_float(row.get("净流入率 %"))
                if pct is not None:
                    item["pct"].append(pct)
                if rate is not None:
                    item["rate"].append(rate)
    if direction == "in":
        filtered = [(name, item) for name, item in grouped.items() if item["net"] > 0]
        ordered = sorted(filtered, key=lambda kv: kv[1]["net"], reverse=True)[:limit]
    else:
        filtered = [(name, item) for name, item in grouped.items() if item["net"] < 0]
        ordered = sorted(filtered, key=lambda kv: kv[1]["net"])[:limit]
    return [
        [
            name,
            f"{item['count']}/{len(analyses)}",
            fmt(item["net"], signed=True),
            fmt(item["super"], signed=True),
            fmt(item["large"], signed=True),
            fmt(item["small"], signed=True),
            fmt(average(item["pct"]), signed=True),
            fmt(item["amount"]),
            fmt(average(item["rate"]), signed=True),
        ]
        for name, item in ordered
    ]


def sort_time_key(value: str) -> str:
    return clean_text(value)


def format_weekly_title(start: str, end: str) -> str:
    start_parts = start.split("-")
    end_parts = end.split("-")
    if len(start_parts) == 3 and len(end_parts) == 3 and start_parts[0] == end_parts[0]:
        return f"{start_parts[0]}年{start_parts[1]}月{start_parts[2]}日-{end_parts[1]}月{end_parts[2]}日贵州茅台周报"
    return f"{start}至{end}贵州茅台周报"


def news_event_key(item: Dict[str, Any]) -> str:
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    if any(keyword in text for keyword in ("分红", "派息", "现金红利", "除权", "除息", "权益分派")):
        return "event:dividend"
    if "大宗交易" in text:
        return "event:block_trade"
    if any(keyword in text for keyword in ("白酒股下跌", "白酒股受挫", "高端囤货需求降温")):
        return "event:baijiu_pressure"
    if any(keyword in text for keyword in ("市值超越茅台", "超越贵州茅台", "多了1.4个贵州茅台", "新股王")):
        return "event:style_rotation"
    if any(keyword in text for keyword in ("目标价", "评级", "研报", "高盛", "华创证券", "中金")):
        return "event:research:" + re.sub(r"\W+", "", clean_text(item.get("title")).lower())[:18]
    return "event:title:" + re.sub(r"\W+", "", clean_text(item.get("title")).lower())[:28]


def build_news_event(group: List[Dict[str, str]]) -> Dict[str, str]:
    latest = max(group, key=lambda item: sort_time_key(item.get("time") or item.get("date") or ""))
    text = " ".join(f"{item.get('title', '')} {item.get('summary', '')}" for item in group)
    event_title = latest.get("title", "")
    impact = latest.get("summary", "")
    if any(keyword in text for keyword in ("分红", "派息", "现金红利", "除权", "除息", "权益分派")):
        payout = re.search(r"每\s*10\s*股派\s*([\d.]+)\s*元", text)
        total = re.search(r"(\d+(?:\.\d+)?)\s*亿元", text)
        detail = []
        if payout:
            detail.append(f"每10股派{payout.group(1)}元")
        if total:
            detail.append(f"合计约{total.group(1)}亿元")
        event_title = "贵州茅台现金分红落地" + (f"：{'，'.join(detail)}" if detail else "")
        impact = "长期现金回报为正，但本周股价和白酒Ⅱ资金未同步确认，不能单独视为趋势反转。"
    elif "大宗交易" in text:
        event_title = "贵州茅台出现大宗交易"
        impact = "观察是否只是平价成交的流动性换手，不能直接等同于方向性增减仓。"
    elif any(keyword in text for keyword in ("白酒股下跌", "白酒股受挫", "高端囤货需求降温")):
        event_title = "白酒板块承压：高端需求与板块卖压成为核心约束"
        impact = "该事件与本周白酒Ⅱ净流出相互印证，是压制茅台估值修复的主要背景。"
    elif any(keyword in text for keyword in ("市值超越茅台", "超越贵州茅台", "多了1.4个贵州茅台", "新股王")):
        event_title = "市场风格继续向科技和高弹性资产迁移"
        impact = "科技成长资产吸走市场注意力和流动性，消费龙头相对吸引力下降。"
    return {
        "date": latest.get("time") or latest.get("date") or "",
        "title": event_title,
        "url": latest.get("url", ""),
        "source": latest.get("source", ""),
        "category": latest.get("category", ""),
        "summary": impact,
    }


def dedupe_news(analyses: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    low_value_patterns = ("后市是否有机会", "附走势预测", "人气排名", "近一个月未见")
    for date, analysis in sorted(analyses.items()):
        for item in (analysis.get("news") or {}).get("items") or []:
            title = clean_text(item.get("title"))
            if not title:
                continue
            if any(pattern in title for pattern in low_value_patterns):
                continue
            normalized = (
                {
                    "date": date,
                    "time": clean_text(item.get("time")) or date,
                    "title": title,
                    "url": clean_text(item.get("url")),
                    "source": clean_text(item.get("source")),
                    "category": clean_text(item.get("category")),
                    "summary": clean_text(item.get("summary")),
                }
            )
            groups[news_event_key(normalized)].append(normalized)
    events = [build_news_event(group) for group in groups.values()]
    return sorted(events, key=lambda item: sort_time_key(item["date"]), reverse=True)


def sentiment_rows(analyses: Dict[str, Dict[str, Any]]) -> List[List[str]]:
    rows = []
    for date, analysis in sorted(analyses.items(), reverse=True):
        sentiment = (analysis.get("sentiment") or {}).get("summary") or {}
        fund_line = clean_text((analysis.get("summary") or {}).get("fund_sentiment_line")) or clean_text(sentiment.get("fund_line"))
        retail_line = clean_text(sentiment.get("line"))
        fund_label, evidence = summarize_fund_sentiment(fund_line)
        retail_label = summarize_retail_sentiment(retail_line)
        rows.append(
            [
                date[5:],
                fund_label,
                retail_label,
                evidence,
                str(sentiment.get("sample_count") or 0),
            ]
        )
    return rows


def summarize_fund_sentiment(fund_line: str) -> tuple[str, str]:
    text = clean_text(fund_line)
    if not text:
        return "暂缺", "暂缺"
    label = "资金分歧"
    if "分歧偏弱" in text or "白酒Ⅱ净流出" in text or "融资端杠杆资金减仓" in text or "主力净流出" in text:
        label = "资金偏弱"
    if "分歧偏强" in text or "白酒Ⅱ净流入且上涨" in text:
        label = "资金偏强"
    evidence: List[str] = []
    if "白酒Ⅱ净流出" in text or "白酒观察：非白酒净流入" in text:
        evidence.append("白酒净流出")
    elif "白酒Ⅱ净流入" in text:
        evidence.append("白酒净流入")
    if "融资端杠杆资金减仓" in text or "融资净买入-" in text or "较前一交易日-" in text:
        evidence.append("融资减仓")
    elif "融资端杠杆资金小幅加仓" in text or "融资净买入+" in text:
        evidence.append("融资加仓")
    if "茅台超大单净流入" in text:
        evidence.append("茅台超大单承接")
    if "茅台下跌" in text or "白酒Ⅱ净流出且下跌" in text:
        evidence.append("价格/板块偏弱")
    return label, "；".join(evidence[:3]) or "暂无关键证据"


def summarize_retail_sentiment(retail_line: str) -> str:
    text = clean_text(retail_line)
    if not text:
        return "暂缺"
    match = re.search(r"散户情绪(偏乐观|偏谨慎|分歧|谨慎|乐观)", text)
    if match:
        state = match.group(1)
        return f"散户{state}"
    return text[:28] + ("..." if len(text) > 28 else "")


def latest_fund_line(analyses: Dict[str, Dict[str, Any]]) -> str:
    for _, analysis in sorted(analyses.items(), reverse=True):
        sentiment = (analysis.get("sentiment") or {}).get("summary") or {}
        line = clean_text(sentiment.get("fund_line")) or clean_text((analysis.get("summary") or {}).get("fund_sentiment_line"))
        if line:
            return line
    return ""


def extract_sentiment_field(fund_line: str, label: str) -> str:
    if not fund_line or label not in fund_line:
        return "暂缺"
    tail = fund_line.split(label, 1)[1]
    cuts = [tail.index(marker) for marker in ("；", "。", "\n") if marker in tail]
    if cuts:
        tail = tail[: min(cuts)]
    return clean_text(label + tail)


def financing_weekly_summary(analyses: Dict[str, Dict[str, Any]]) -> str:
    points = []
    for date, analysis in sorted(analyses.items()):
        sentiment = (analysis.get("sentiment") or {}).get("summary") or {}
        line = clean_text(sentiment.get("fund_line")) or clean_text((analysis.get("summary") or {}).get("fund_sentiment_line"))
        balance_match = re.search(r"融资余额\s*([\d.]+)\s*亿元", line)
        short_match = re.search(r"融券余量\s*([\d.]+)\s*万股", line)
        if balance_match or short_match:
            points.append(
                {
                    "date": date,
                    "balance": float(balance_match.group(1)) if balance_match else None,
                    "short": float(short_match.group(1)) if short_match else None,
                }
            )
    if not points:
        return "暂缺"
    first = points[0]
    last = points[-1]
    parts = []
    if first["balance"] is not None and last["balance"] is not None:
        if len(points) >= 2:
            parts.append(
                f"融资余额 {first['balance']:.2f}亿 → {last['balance']:.2f}亿，周变化 {fmt(last['balance'] - first['balance'], '亿', signed=True)}"
            )
        else:
            parts.append(f"融资余额 {last['balance']:.2f}亿；仅1日数据，暂不能计算周变化")
    if first["short"] is not None and last["short"] is not None:
        if len(points) >= 2:
            parts.append(
                f"融券余量 {first['short']:.2f}万股 → {last['short']:.2f}万股，周变化 {fmt(last['short'] - first['short'], '万股', signed=True)}"
            )
        else:
            parts.append(f"融券余量 {last['short']:.2f}万股；仅1日数据，暂不能计算周变化")
    return "；".join(parts) or "暂缺"


def format_evidence_block_trade(evidence: Dict[str, Any], fallback: str) -> tuple[str, str]:
    block = evidence.get("block_trades") or {}
    items = block.get("items") or []
    if not items:
        return fallback, "已接入/本周为空" if fallback != "暂缺" else "已接入/结构化抓取为空"
    amount_yuan = to_float(block.get("total_amount_yuan")) or 0
    sellers = ", ".join(dict.fromkeys(clean_text(item.get("seller")) for item in items if item.get("seller")))
    buyers = ", ".join(dict.fromkeys(clean_text(item.get("buyer")) for item in items if item.get("buyer")))
    premiums = [to_float(item.get("premium_ratio")) for item in items if to_float(item.get("premium_ratio")) is not None]
    premium_text = f"平均溢价率 {sum(premiums) / len(premiums):.2f}%" if premiums else "溢价率暂缺"
    detail = f"{len(items)} 笔，合计 {amount_yuan / 1e8:.2f} 亿元，{premium_text}"
    if sellers:
        detail += f"；卖方：{sellers}"
    if buyers:
        detail += f"；买方：{buyers}"
    return detail, "已接入/东方财富结构化"


def format_evidence_lhb(evidence: Dict[str, Any]) -> tuple[str, str]:
    lhb = evidence.get("lhb") or {}
    items = lhb.get("items") or []
    if not items:
        return clean_text(lhb.get("summary")) or "本周未上龙虎榜，无席位级别异动披露。", "已接入/本周为空"
    return f"本周龙虎榜 {len(items)} 条，需进一步拆席位买卖。", "已接入"


def format_evidence_northbound(evidence: Dict[str, Any]) -> tuple[str, str]:
    north = evidence.get("northbound") or {}
    items = north.get("items") or []
    if not items:
        return clean_text(north.get("summary")) or "北向持股暂缺。", "源可访问但本周不可用/滞后"
    first = items[0]
    last = items[-1]
    start_shares = to_float(first.get("持股数量"))
    end_shares = to_float(last.get("持股数量"))
    if start_shares is not None and end_shares is not None:
        return f"持股数量 {start_shares / 10000:.2f} 万股 → {end_shares / 10000:.2f} 万股，变化 {(end_shares - start_shares) / 10000:+.2f} 万股。", "已接入"
    return f"获取 {len(items)} 条北向持股，但字段不足。", "已接入/字段不足"


def format_evidence_etf(evidence: Dict[str, Any], limit: int = 5) -> tuple[str, str]:
    etf = evidence.get("etf") or {}
    items = etf.get("items") or []
    if not items:
        return clean_text(etf.get("summary")) or "ETF份额变化暂缺。", "待补数据源"
    preferred = [item for item in items if any(keyword in clean_text(item.get("name")) for keyword in ("酒", "食品饮料", "食品"))]
    rows = preferred[:limit] if preferred else items[:limit]
    parts = []
    for item in rows:
        change = to_float(item.get("share_change"))
        pct = to_float(item.get("share_change_pct"))
        parts.append(
            f"{item.get('code')} {item.get('name')} 份额 {change / 1e8:+.2f} 亿份（{pct:+.2f}%）"
            if change is not None and pct is not None
            else f"{item.get('code')} {item.get('name')} 份额变化暂缺"
        )
    return "；".join(parts), "已接入/上交所 ETF 份额"


def format_evidence_fund_holdings(evidence: Dict[str, Any], limit: int = 6) -> tuple[str, str]:
    holdings = evidence.get("fund_holdings") or {}
    items = holdings.get("items") or []
    if not items:
        return clean_text(holdings.get("summary")) or "基金持仓暂缺。", "待补数据源"
    names = []
    for item in items[:limit]:
        shares = to_float(item.get("持仓数量"))
        ratio = to_float(item.get("占流通股比例"))
        names.append(
            f"{item.get('基金名称')} {shares / 10000:.2f} 万股，占流通 {ratio:.2f}%"
            if shares is not None and ratio is not None
            else clean_text(item.get("基金名称"))
        )
    summary = clean_text(holdings.get("summary"))
    return f"{summary} 前列：{'；'.join(names)}", "已接入/季报滞后口径"


def institutional_selloff_check_html(analyses: Dict[str, Dict[str, Any]], totals: Dict[str, float], evidence: Dict[str, Any] | None = None) -> str:
    fund_line = latest_fund_line(analyses)
    financing = financing_weekly_summary(analyses)
    evidence = evidence or {}
    block_trade, block_status = format_evidence_block_trade(evidence, extract_sentiment_field(fund_line, "大宗交易："))
    lhb_text, lhb_status = format_evidence_lhb(evidence)
    north_text, north_status = format_evidence_northbound(evidence)
    etf_text, etf_status = format_evidence_etf(evidence)
    fund_holdings_text, fund_holdings_status = format_evidence_fund_holdings(evidence)
    liquor = liquor_compare_totals(analyses)
    baijiu_evidence = format_liquor_compare_row("白酒Ⅱ", liquor) or fmt(totals["baijiu_net"], "亿", signed=True)
    moutai_evidence = format_liquor_compare_row("贵州茅台", liquor) or (
        f"贵州茅台：净流入 {fmt(totals['moutai_net'], '亿', signed=True)}；"
        f"超大单 {fmt(totals['moutai_super'], '亿', signed=True)}；大单 {fmt(totals['moutai_large'], '亿', signed=True)}；"
        f"小单 {fmt(totals['moutai_small'], '亿', signed=True)}"
    )
    conclusion = (
        "当前证据能说明白酒板块遭遇主力资金净流出，显示大资金对白酒方向配置意愿偏弱；"
        "但仅凭行业资金流、ETF份额变化和成交分档，不能直接判定机构主动抛售，更不能直接归因为板块基金调仓。"
        "下表按证据强弱使用：已接入且当周有效的数据可参与判断；季报滞后数据只能说明持仓暴露；源滞后或为空的数据只用于排除对应证据。"
    )
    rows = [
        [
            "白酒Ⅱ主力资金",
            baijiu_evidence,
            "已接入",
            "板块层面卖压" if totals["baijiu_net"] < 0 else "板块资金未显示明显卖压",
        ],
        [
            "贵州茅台资金层级",
            moutai_evidence,
            "已接入",
            "超大单承接、大单撤退" if totals["moutai_super"] > 0 and totals["moutai_large"] < 0 else "资金层级未显示典型承接分歧",
        ],
        ["融资融券", financing, "已接入/日报抽取", "用于观察杠杆资金是否同步撤退"],
        ["大宗交易", block_trade, block_status, "用于观察是否存在大额换手或折价成交；本周金额较小则不能解释主跌幅"],
        ["ETF份额变化", etf_text, etf_status, "份额下降是申赎/调仓线索，不等同于已经卖出茅台；需结合ETF持仓权重和成交验证"],
        ["基金持仓", fund_holdings_text, fund_holdings_status, "用于判断哪些基金暴露在茅台上；季报口径不能证明当周卖出"],
        ["北向/外资", north_text, north_status, "源滞后时不得参与本周买卖判断，只能记录数据缺口"],
        ["龙虎榜", lhb_text, lhb_status, "用于识别营业部或机构席位交易；未上榜则没有席位披露证据"],
    ]
    return f"<p class=\"note\">{html.escape(conclusion)}</p>{table(['验证项','本周证据','状态','怎么解读'], rows)}"


def liquor_compare_totals(analyses: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    totals: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for analysis in analyses.values():
        for row in (analysis.get("fund_flow") or {}).get("liquor_compare") or []:
            name = clean_text(row.get("板块"))
            if name not in {"白酒Ⅱ", "贵州茅台", "非白酒"}:
                continue
            for field in ("净流入（亿）", "超大单（亿）", "大单（亿）", "小单（亿）"):
                totals[name][field] += to_float(row.get(field)) or 0
    return totals


def liquor_compare_weekly_rows(analyses: Dict[str, Dict[str, Any]]) -> List[List[str]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for analysis in analyses.values():
        for row in (analysis.get("fund_flow") or {}).get("liquor_compare") or []:
            name = clean_text(row.get("板块"))
            if name not in {"白酒Ⅱ", "贵州茅台", "非白酒"}:
                continue
            item = grouped.setdefault(
                name,
                {
                    "count": 0,
                    "net": 0.0,
                    "super": 0.0,
                    "large": 0.0,
                    "small": 0.0,
                    "amount": 0.0,
                    "pct": [],
                    "rate": [],
                },
            )
            item["count"] += 1
            item["net"] += to_float(row.get("净流入（亿）")) or 0
            item["super"] += to_float(row.get("超大单（亿）")) or 0
            item["large"] += to_float(row.get("大单（亿）")) or 0
            item["small"] += to_float(row.get("小单（亿）")) or 0
            item["amount"] += to_float(row.get("成交额（亿）")) or 0
            pct = to_float(row.get("涨跌幅 %"))
            rate = to_float(row.get("净流入率 %"))
            if pct is not None:
                item["pct"].append(pct)
            if rate is not None:
                item["rate"].append(rate)
    order = ["白酒Ⅱ", "贵州茅台", "非白酒"]
    rows = []
    for name in order:
        item = grouped.get(name)
        if not item:
            continue
        rows.append(
            [
                name,
                f"{item['count']}/{len(analyses)}",
                fmt(item["net"], signed=True),
                fmt(item["super"], signed=True),
                fmt(item["large"], signed=True),
                fmt(item["small"], signed=True),
                fmt(average(item["pct"]), signed=True),
                fmt(item["amount"]),
                fmt(average(item["rate"]), signed=True),
            ]
        )
    return rows


def format_liquor_compare_row(name: str, totals: Dict[str, Dict[str, float]]) -> str:
    row = totals.get(name)
    if not row:
        return ""
    return (
        f"{name}：净流入 {fmt(row.get('净流入（亿）'), '亿', signed=True)}；"
        f"超大单 {fmt(row.get('超大单（亿）'), '亿', signed=True)}；"
        f"大单 {fmt(row.get('大单（亿）'), '亿', signed=True)}；"
        f"小单 {fmt(row.get('小单（亿）'), '亿', signed=True)}"
    )


def news_timeline_html(items: List[Dict[str, str]], limit: int = 12) -> str:
    if not items:
        return "<p>本周日报中暂未提取到要闻。</p>"
    rows = []
    for item in items[:limit]:
        title = html.escape(item["title"])
        if item.get("url"):
            title = f'<a href="{html.escape(item["url"], quote=True)}">{title}</a>'
        rows.append(
            "<tr>"
            f"<td>{html.escape((item.get('date') or '')[:16])}</td>"
            f"<td>{html.escape(item.get('category') or '')}</td>"
            f"<td>{title}</td>"
            f"<td>{html.escape(item.get('summary') or '')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>时间</th><th>类别</th><th>核心事件</th><th>投资含义</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )


def weekly_review_calibration_html(
    analyses: Dict[str, Dict[str, Any]], totals: Dict[str, float], week_return: float | None, closes: List[float]
) -> str:
    bullets = []
    if len(closes) >= 2 and (week_return or 0) < 0:
        bullets.append(
            f"本周复盘校正：收盘价从 {closes[0]:.2f} 元回落到 {closes[-1]:.2f} 元，含现金分红总回报 {fmt(week_return, '%', signed=True)}。"
            "首尾裸价格变化包含除息影响，不能直接当作实际亏损；此前承接信号也没有被总回报验证，后续日报不能把“超大单为正”直接写成进攻信号。"
        )
    if totals["moutai_super"] > 0 and totals["moutai_large"] < 0:
        bullets.append(
            f"资金校正：超大单 {fmt(totals['moutai_super'], '亿', signed=True)}，大单 {fmt(totals['moutai_large'], '亿', signed=True)}。"
            "这类结构应默认归类为承接型资金，除非次日价格、成交额和白酒Ⅱ同步确认。"
        )
    if totals["baijiu_net"] < 0:
        bullets.append(
            f"板块校正：白酒Ⅱ本周净流入 {fmt(totals['baijiu_net'], '亿', signed=True)}。"
            "行业贝塔没有修复时，茅台个股利好和低吸资金容易被板块卖压抵消。"
        )
    if not bullets:
        bullets.append("本周日报核心判断没有明显被后续走势证伪，下周继续按价格、资金、板块、新闻四条线交叉验证。")
    strategy = [
        "后续日报策略优化：把分红、回购、公告类利好放进“是否被价格和资金确认”的框架里，不单独当成上涨理由。",
        "后续日报策略优化：连续两日以上出现“超大单正、大单负、价格弱”时，直接标注为承接型分歧，而不是趋势反转。",
        "后续日报策略优化：板块资金要看连续性和净流入率，单日 TOP10 只作为线索，不能替代周度主线判断。",
    ]
    return "<ul>" + "".join(f"<li>{html.escape(line)}</li>" for line in bullets) + "</ul><h3>后续日报策略优化</h3><ul>" + "".join(
        f"<li>{html.escape(line)}</li>" for line in strategy
    ) + "</ul>"


def dividend_news_items(news_items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    keywords = ("分红", "派息", "现金红利", "除权", "除息", "权益分派")
    return [item for item in news_items if any(keyword in f"{item.get('title', '')} {item.get('summary', '')}" for keyword in keywords)]


def weekly_core_view(totals: Dict[str, float], week_return: float | None, news_items: List[Dict[str, str]] | None = None) -> str:
    parts = []
    if week_return is not None:
        parts.append(f"周内贵州茅台含现金分红总回报为 {fmt(week_return, '%', signed=True)}。")
    parts.append(
        f"茅台主力净流入合计 {fmt(totals['moutai_net'], '亿', signed=True)}，其中超大单 {fmt(totals['moutai_super'], '亿', signed=True)}、大单 {fmt(totals['moutai_large'], '亿', signed=True)}。"
    )
    parts.append(f"白酒Ⅱ净流入合计 {fmt(totals['baijiu_net'], '亿', signed=True)}。")
    dividends = dividend_news_items(news_items or [])
    if dividends:
        latest = dividends[-1]
        parts.append(
            f"本周出现分红事件（{latest.get('title', '分红事项')}），这是长期现金回报的正面信号；"
            "但当周股价和白酒Ⅱ资金没有同步转强，说明分红利好不能抵消行业贝塔走弱和资金结构分歧。"
        )
    if totals["moutai_super"] > 0 and totals["moutai_large"] < 0:
        parts.append("结构上更像超大单承接、大单撤退，不能简单理解为趋势性进攻。")
    if totals["baijiu_net"] < 0:
        parts.append("行业贝塔偏弱会压制茅台个股估值修复，需要等待白酒Ⅱ连续回流确认。")
    return "".join(parts)


def weekly_review_text(totals: Dict[str, float], week_return: float | None, closes: List[float]) -> str:
    if len(closes) >= 2:
        price_text = (
            f"收盘价从 {closes[0]:.2f} 元走到 {closes[-1]:.2f} 元，含现金分红总回报 {fmt(week_return, '%', signed=True)}；"
            "因本周发生除息，首尾裸价格变化不能直接当作实际收益；"
        )
    else:
        price_text = "价格数据不足，暂不能计算完整周收益；"
    fund_text = (
        f"资金上，茅台主力 {fmt(totals['moutai_net'], '亿', signed=True)}，"
        f"超大单 {fmt(totals['moutai_super'], '亿', signed=True)}，"
        f"大单 {fmt(totals['moutai_large'], '亿', signed=True)}，"
        f"白酒Ⅱ {fmt(totals['baijiu_net'], '亿', signed=True)}。"
    )
    return price_text + fund_text + "本周复盘重点不是单日涨跌，而是确认资金层级、行业贝塔、新闻叙事和散户情绪是否同向。"


def weekly_flow_comment(title: str, rows: List[List[str]]) -> str:
    if not rows:
        return "<p class=\"note\">本周该维度没有可聚合的板块记录。</p>"
    leader = rows[0]
    name = leader[0]
    count = leader[1]
    net = leader[2]
    super_order = leader[3]
    large = leader[4]
    amount = leader[7]
    rate = leader[8]
    return (
        f"<p class=\"note\">分析：{html.escape(title)} 中，{html.escape(name)} 出现 {html.escape(count)}，"
        f"净流入 {html.escape(net)}，超大单 {html.escape(super_order)}，大单 {html.escape(large)}，"
        f"成交额 {html.escape(amount)}，平均净流入率 {html.escape(rate)}。"
        "若净流入与涨跌幅、超大单与大单方向不一致，按资金分歧处理，不直接外推为趋势。</p>"
    )


def table(headers: List[str], rows: List[List[str]]) -> str:
    body = "\n".join("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows)
    return "<table><thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + f"</tr></thead><tbody>{body}</tbody></table>"


def build_weekly_html(
    analyses: Dict[str, Dict[str, Any]],
    start: str,
    end: str,
    institutional_evidence: Dict[str, Any] | None = None,
    corporate_actions: Dict[str, Any] | None = None,
) -> str:
    daily_rows = []
    totals = defaultdict(float)
    closes = []
    daily_pct_values = []
    for date, analysis in sorted(analyses.items()):
        quote = ((analysis.get("quotes") or {}).get("quotes") or {}).get("600519") or {}
        nums = parse_daily_review_numbers(analysis)
        for key in ["moutai_net", "moutai_super", "moutai_large", "moutai_small", "baijiu_net"]:
            totals[key] += to_float(nums.get(key)) or 0
        close = to_float(quote.get("收盘价"))
        if close is not None:
            closes.append(close)
        daily_pct_values.append(quote.get("涨跌幅"))
        daily_rows.append(
            [
                date[5:],
                fmt(close),
                fmt(quote.get("涨跌幅"), "%", signed=True),
                fmt(quote.get("成交额（亿）"), "亿"),
                fmt(nums.get("moutai_net"), "亿", signed=True),
                fmt(nums.get("moutai_super"), "亿", signed=True),
                fmt(nums.get("moutai_large"), "亿", signed=True),
                fmt(nums.get("baijiu_net"), "亿", signed=True),
                fmt(nums.get("baijiu_pct"), "%", signed=True),
                str(nums.get("leaders") or ""),
            ]
        )
    corporate_actions = corporate_actions or {}
    dividends = cash_dividends_in_window(corporate_actions, start, end)
    market_return = cumulative_return_from_daily_pct(daily_pct_values)
    week_return = total_return_with_cash_dividend(closes, daily_pct_values, dividends, start)
    if week_return is None:
        week_return = market_return
    raw_price_change = ((closes[-1] / closes[0] - 1) * 100) if len(closes) >= 2 and closes[0] else None
    dividend_text = "；".join(
        f"{item.get('ex_date')} 每股现金分红 {fmt(item.get('cash_dividend_per_share'), '元')}" for item in dividends
    ) or "本周未识别到官方现金分红"
    report_title = format_weekly_title(start, end)
    inflow_rows = weekly_net_flow_rows(analyses, "in")
    outflow_rows = weekly_net_flow_rows(analyses, "out")
    liquor_rows = liquor_compare_weekly_rows(analyses)
    divergence_sections = {
        "背离一：净流入但股价跌": flow_change_rows(analyses, "divergence_net_inflow_price_down"),
        "背离二：净流出但股价涨": flow_change_rows(analyses, "divergence_net_outflow_price_up"),
        "背离三：超大单流入 + 大单流出": flow_change_rows(analyses, "divergence_super_in_large_out"),
        "背离四：超大单流出 + 大单流入": flow_change_rows(analyses, "divergence_super_out_large_in"),
    }
    divergence_html = "\n".join(
        f"<h3>{html.escape(name)}</h3>{table(FLOW_HEADERS, rows)}{weekly_flow_comment(name, rows)}"
        for name, rows in divergence_sections.items()
    )
    news_items = dedupe_news(analyses)
    review_calibration = weekly_review_calibration_html(analyses, totals, week_return, closes)
    source_links = "\n".join(
        f'<a href="a_share_evening_report_{html.escape(date)}.html">{html.escape(date[5:])} 日报</a>' for date in sorted(analyses)
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(report_title)}</title>
<style>
:root {{ --ink:#172033; --muted:#657083; --line:#dce3ee; --bg:#f6f8fb; --card:#fff; --red:#b42318; --green:#067647; --blue:#175cd3; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.72 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",Arial,sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:28px 24px 56px; }}
h1 {{ font-size:30px; line-height:1.25; margin:0 0 8px; }}
h2 {{ font-size:22px; margin:30px 0 12px; border-bottom:1px solid var(--line); padding-bottom:8px; }}
h3 {{ font-size:17px; margin:20px 0 8px; }}
p {{ margin:8px 0; }}
.meta {{ color:var(--muted); }}
.grid {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin:18px 0; }}
.metric {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; }}
.metric b {{ display:block; font-size:22px; margin-top:4px; }}
.good {{ color:var(--green); }} .bad {{ color:var(--red); }} .blue {{ color:var(--blue); }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; margin:12px 0 20px; }}
th,td {{ border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }}
th {{ background:#eef3fa; font-weight:700; white-space:nowrap; }}
tr:last-child td {{ border-bottom:0; }}
ul {{ padding-left:20px; }}
.note {{ background:#fff7e6; border:1px solid #fedf89; border-radius:8px; padding:12px 14px; }}
.sources a, a {{ color:var(--blue); text-decoration:none; }}
.sources a {{ margin-right:12px; white-space:nowrap; }}
@media (max-width: 980px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} table {{ font-size:13px; }} }}
</style>
</head><body><main>
<h1>{html.escape(report_title)}</h1>
<p class="meta">区间：{html.escape(start)} 至 {html.escape(end)}。数据优先来自每日归档 JSON；缺失归档时从已有收盘晚报 HTML 回退提取。</p>
<div class="grid">
  <div class="metric">含分红总回报<b>{fmt(week_return, '%', signed=True)}</b></div>
  <div class="metric">茅台主力净流入<b>{fmt(totals['moutai_net'], '亿', signed=True)}</b></div>
  <div class="metric">超大单<b>{fmt(totals['moutai_super'], '亿', signed=True)}</b></div>
  <div class="metric">大单<b>{fmt(totals['moutai_large'], '亿', signed=True)}</b></div>
  <div class="metric">白酒Ⅱ净流入<b>{fmt(totals['baijiu_net'], '亿', signed=True)}</b></div>
</div>
<h2>核心判断</h2>
<p>{html.escape(weekly_core_view(totals, week_return, news_items))}</p>
<h2>本周复盘</h2>
<p>{html.escape(weekly_review_text(totals, week_return, closes))}</p>
<h2>五日量化快照</h2>
<p class="note">收益口径：顶部“含分红总回报”按上一个交易日基准价、期末收盘价和区间内现金分红计算；行情日涨跌累计为 {html.escape(fmt(market_return, '%', signed=True))}，首尾收盘价裸变化为 {html.escape(fmt(raw_price_change, '%', signed=True))}，裸价格变化受除息影响，不等同于实际收益。官方分红识别：{html.escape(dividend_text)}。</p>
{table(['日期','收盘','行情日涨跌幅','成交额','茅台主力','超大单','大单','白酒Ⅱ主力','白酒Ⅱ涨跌','当日资金主线'], daily_rows)}
<h2>本周复盘校正</h2>
{review_calibration}
<h2>要闻速览时间线</h2>
{news_timeline_html(news_items)}
<h2>板块基金/机构抛售验证</h2>
{institutional_selloff_check_html(analyses, totals, institutional_evidence)}
<h2>板块资金流向变化</h2>
<p class="note">周度流入/流出按“同一板块先合并本周所有可见日榜记录，再按周度净额分组”计算；因此同一板块不会同时出现在周度净流入和周度净流出。若某板块某日未进入日报 TOP10，则该日不纳入本表。</p>
<h3>周度净流入 TOP10</h3>
{table(FLOW_HEADERS, inflow_rows)}
{weekly_flow_comment('周度净流入 TOP10', inflow_rows)}
<h3>周度净流出 TOP10</h3>
{table(FLOW_HEADERS, outflow_rows)}
{weekly_flow_comment('周度净流出 TOP10', outflow_rows)}
<h3>白酒与茅台固定观察</h3>
{table(FLOW_HEADERS, liquor_rows)}
<p class="note">这张表不按 TOP10 筛选，固定保留白酒Ⅱ、贵州茅台和非白酒，用来判断茅台自身资金、白酒行业资金和全市场非白酒资金是否同向。</p>
<h2>四大背离周度分析</h2>
{divergence_html}
<h2>背后根因链</h2>
<ol><li>先看白酒Ⅱ资金是否连续回流，再看茅台大单能否由负转正。</li><li>净流入率要和成交额一起看：高净流入率但成交额偏小，代表局部弹性；高成交额叠加大额净流出，代表主战场撤退。</li><li>四大背离不是结论本身，而是风险提示：价格、净流入、超大单、大单方向不一致时，优先按资金分歧处理。</li></ol>
<h2>数据来源</h2>
<p class="sources">{source_links}</p>
</main></body></html>"""


def write_weekly_report(root: str | Path, dates: List[str], output_dir: str | Path = "output") -> Path:
    root_path = Path(root)
    analyses = load_daily_analyses(root_path, dates)
    if not analyses:
        raise RuntimeError("没有找到可用于周报的日报归档 JSON。")
    start = min(analyses)
    end = max(analyses)
    institutional_evidence = load_institutional_evidence(root_path, start, end)
    corporate_actions = load_corporate_actions(root_path)
    out = Path(output_dir) / f"a_share_weekly_report_{start}_{end}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_weekly_html(analyses, start, end, institutional_evidence, corporate_actions), encoding="utf-8")
    ensure_pdf_export_link(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()
    print(write_weekly_report(args.root, args.dates, args.output_dir))


if __name__ == "__main__":
    main()
