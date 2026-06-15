from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from common import REQUIRED_FUND_COLUMNS, load_yaml, now_iso, read_json, to_float, write_json
from fetch_news import build_news_brief, deduplicate_and_rank_news, enrich_news_item, group_news_sections
from fetch_research import compact_text, extract_rating_and_target


RESEARCH_KEY_EVENT_KEYWORDS = [
    "调价",
    "提价",
    "动态调价",
    "市场化改革",
    "i茅台",
    "I茅台",
    "飞天",
    "批价",
    "分红",
    "权益分派",
    "股东大会",
    "回购",
    "增持",
    "减持",
    "财报",
    "业绩",
    "渠道",
    "动销",
    "库存",
    "年轻人",
    "年轻消费者",
    "年轻一代",
    "不喝白酒",
    "低度酒",
    "消费趋势",
    "消费代际",
    "宴席消费",
    "商务消费",
    "礼赠消费",
    "人事",
    "董事长",
    "高管",
]

HIGH_VALUE_RESEARCH_KEYWORDS = [
    "调价",
    "提价",
    "动态调价",
    "分红",
    "权益分派",
    "财报",
    "业绩",
    "董事长",
    "高管",
    "人事",
]

PUBLIC_OPINION_KEYWORDS = [
    "年轻人",
    "年轻消费者",
    "年轻一代",
    "不喝白酒",
    "低度酒",
    "消费趋势",
    "消费代际",
    "宴席消费",
    "商务消费",
    "礼赠消费",
    "高端消费",
    "动销",
    "库存",
    "批价",
]


def fmt_signed(value: Any, suffix: str = "") -> str:
    n = to_float(value)
    if n is None:
        return "暂缺"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.2f}{suffix}"


def sort_rows(rows: List[Dict[str, Any]], key: str, reverse: bool = True, n: int = 5) -> List[Dict[str, Any]]:
    valid = [r for r in rows if to_float(r.get(key)) is not None]
    return sorted(valid, key=lambda r: to_float(r.get(key)) or 0, reverse=reverse)[:n]


def filter_rows(rows: List[Dict[str, Any]], condition) -> List[Dict[str, Any]]:
    return [r for r in rows if condition(r)]


def baijiu_rows(rows: List[Dict[str, Any]], keywords: List[str]) -> List[Dict[str, Any]]:
    hits = []
    for r in rows:
        name = str(r.get("板块", ""))
        if any(k in name for k in keywords):
            hits.append(r)
    return hits


def parse_date_prefix(value: Any) -> datetime | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    if not match:
        return None
    return datetime.strptime(match.group(0), "%Y-%m-%d")


def is_within_target_lookback(value: Any, target_date: str | None, lookback_days: int) -> bool:
    if not target_date:
        return True
    item_dt = parse_date_prefix(value)
    if item_dt is None:
        return True
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    start_dt = target_dt - timedelta(days=max(lookback_days - 1, 0))
    return start_dt <= item_dt <= target_dt


def research_item_to_key_event(item: Dict[str, Any], target_date: str | None, lookback_days: int) -> Dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    combined = f"{title} {summary}"
    if not title or not any(keyword in combined for keyword in RESEARCH_KEY_EVENT_KEYWORDS):
        return None
    if not is_within_target_lookback(item.get("date"), target_date, lookback_days):
        return None

    institution = str(item.get("institution") or "机构暂缺").strip()
    importance = "高" if any(keyword in combined for keyword in HIGH_VALUE_RESEARCH_KEYWORDS) else "中"
    impact_direction = "利好" if any(keyword in combined for keyword in ["提价", "分红", "增持", "市场化改革"]) else "待观察"
    category = "行业新闻" if any(keyword in combined for keyword in PUBLIC_OPINION_KEYWORDS) else "主标的新闻"
    event = enrich_news_item(
        {
            "title": title,
            "source": f"券商观点：{institution}",
            "time": item.get("date") or "暂缺",
            "url": item.get("url") or "暂缺",
            "category": category,
            "summary": summary or f"券商研报标题指向：{title}",
            "impact_direction": impact_direction,
            "impact_targets": ["贵州茅台", "白酒行业"],
            "impact_period": "长期（1年以上）" if any(keyword in combined for keyword in ["市场化改革", "分红", "人事", "董事长", "高管"]) else "中期（1-3个月）",
            "importance": importance,
            "importance_reason": "券商研报触及调价、人事、分红、业绩或渠道等关键事件，需纳入长期投资底座。",
        }
    )
    event["impact_analysis"] = (
        "券商关键事件底座：重点验证事件是否改变茅台定价权、渠道利润、动销韧性或治理稳定性；"
        f"当前方向为{event.get('impact_direction')}，需与公告、批价和资金流交叉验证。"
    )
    event["impact"] = event["impact_analysis"]
    return event


def merge_research_key_events_into_news(
    news: Dict[str, Any],
    research: Dict[str, Any],
    sector: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    news_config = config.get("news", {})
    max_items = int(news_config.get("max_items", 18))
    per_section = int(news_config.get("per_section", 6))
    lookback_days = int(news.get("lookback_days") or news_config.get("lookback_days", 30))
    target_date = ((sector.get("quality") or {}).get("target_date") or None)

    key_events = [
        event
        for item in (research.get("items") or [])
        if (event := research_item_to_key_event(item, target_date, lookback_days)) is not None
    ]
    if not key_events:
        return news

    merged_items = deduplicate_and_rank_news([*(news.get("items") or []), *key_events], max_items=max_items, per_section=per_section)
    merged = dict(news)
    merged["items"] = merged_items
    merged["sections"] = group_news_sections(merged_items, per_section=per_section)
    merged["brief"] = build_news_brief(merged_items)
    merged["lookback_days"] = lookback_days
    sources = list(dict.fromkeys([*(news.get("sources") or []), "券商关键事件（新浪财经研究报告）"]))
    merged["sources"] = sources
    quality = dict(news.get("quality") or {})
    quality["item_count"] = len(merged_items)
    quality["summary"] = f"新闻数据可用，已合并 {len(key_events)} 条券商关键事件底座，并保留 {len(merged_items)} 条近一个月相关公开信息。"
    if quality.get("level") in {None, "empty"}:
        quality["level"] = "ok"
    merged["quality"] = quality
    return merged


def merge_macro_events_into_news(news: Dict[str, Any], macro: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    macro_items = macro.get("items") or []
    if not macro_items:
        return news

    news_config = config.get("news", {})
    max_items = int(news_config.get("max_items", 18))
    per_section = int(news_config.get("per_section", 6))
    merged_items = deduplicate_and_rank_news([*(news.get("items") or []), *macro_items], max_items=max_items, per_section=per_section)
    merged = dict(news)
    merged["items"] = merged_items
    merged["sections"] = group_news_sections(merged_items, per_section=per_section)
    merged["brief"] = build_news_brief(merged_items)
    sources = list(dict.fromkeys([*(news.get("sources") or []), *(macro.get("sources") or [])]))
    merged["sources"] = sources
    quality = dict(news.get("quality") or {})
    quality["item_count"] = len(merged_items)
    quality["summary"] = f"新闻数据可用，已合并 {len(macro_items)} 条美联储/美债宏观事件，并保留 {len(merged_items)} 条近一个月相关公开信息。"
    if quality.get("level") in {None, "empty"}:
        quality["level"] = "ok"
    errors = [*(news.get("errors") or []), *(macro.get("errors") or [])]
    merged["errors"] = errors
    merged["quality"] = quality
    return merged


def is_institution_view_news(item: Dict[str, Any]) -> bool:
    if item.get("institution_view"):
        return True
    source = str(item.get("source") or "")
    category = str(item.get("category") or "")
    title = str(item.get("title") or "")
    combined = f"{source} {category} {title}"
    institution_markers = ["券商观点", "机构观点", "机构评级", "研究报告", "研报"]
    return any(marker in combined for marker in institution_markers)


def remove_institution_views_from_news(news: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    news_config = config.get("news", {})
    max_items = int(news_config.get("max_items", 18))
    per_section = int(news_config.get("per_section", 6))
    raw_items = news.get("items") or []
    items = [item for item in raw_items if not is_institution_view_news(item)]
    removed_count = len(raw_items) - len(items)
    if not removed_count:
        return news

    items = deduplicate_and_rank_news(items, max_items=max_items, per_section=per_section)
    cleaned = dict(news)
    cleaned["items"] = items
    cleaned["sections"] = group_news_sections(items, per_section=per_section)
    cleaned["brief"] = build_news_brief(items)
    quality = dict(news.get("quality") or {})
    quality["item_count"] = len(items)
    previous = str(quality.get("summary") or "新闻数据可用").rstrip("。")
    quality["summary"] = f"{previous}；已将 {removed_count} 条券商/机构研报或评级新闻移至机构观点模块。"
    if quality.get("level") in {None, "empty"} and items:
        quality["level"] = "ok"
    cleaned["quality"] = quality
    return cleaned


def normalize_research_signal_fields(research: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(research)
    items = []
    for item in research.get("items") or []:
        clean = dict(item)
        signals = extract_rating_and_target(f"{clean.get('title') or ''} {clean.get('summary') or ''}")
        if signals.get("target_price") and clean.get("target_price") in {None, "", "目标价暂缺"}:
            clean["target_price"] = signals["target_price"]
        if signals.get("rating") and clean.get("rating") in {None, "", "评级暂缺"}:
            clean["rating"] = signals["rating"]
        items.append(clean)
    normalized["items"] = items
    return normalized


def merge_news_institution_views_into_research(research: Dict[str, Any], news: Dict[str, Any]) -> Dict[str, Any]:
    additions = []
    for item in news.get("items") or []:
        view = item.get("institution_view") or {}
        if not view:
            continue
        additions.append(
            {
                "title": item.get("title") or "机构评级新闻",
                "institution": view.get("institution") or "机构暂缺",
                "analyst": "研究员暂缺",
                "rating": view.get("rating") or "评级暂缺",
                "target_price": view.get("target_price") or "目标价暂缺",
                "date": str(item.get("time") or "暂缺")[:10],
                "url": item.get("url") or "",
                "summary": item.get("summary") or "",
                "source": item.get("source") or "机构评级新闻",
            }
        )
    if not additions:
        return research

    existing_keys = {
        (item.get("institution"), item.get("date"), item.get("target_price"), item.get("title"))
        for item in research.get("items") or []
    }
    merged_items = list(research.get("items") or [])
    for item in additions:
        key = (item.get("institution"), item.get("date"), item.get("target_price"), item.get("title"))
        if key not in existing_keys:
            merged_items.append(item)
            existing_keys.add(key)
    merged_items.sort(key=lambda item: item.get("date") or "", reverse=True)

    merged = dict(research)
    merged["items"] = merged_items
    merged["sources"] = list(dict.fromkeys([*(research.get("sources") or []), "机构评级新闻"]))
    quality = dict(research.get("quality") or {})
    quality["item_count"] = len(merged_items)
    quality["summary"] = f"机构观点数据可用，已合并 {len(additions)} 条评级新闻，并保留 {len(merged_items)} 条机构观点。"
    if quality.get("level") in {None, "empty"}:
        quality["level"] = "ok"
    merged["quality"] = quality
    return merged


def is_actionable_research_item(item: Dict[str, Any]) -> bool:
    rating = str(item.get("rating") or "").strip()
    target_price = str(item.get("target_price") or "").strip()
    has_rating = rating not in {"", "评级暂缺", "暂无评级", "未评级"}
    has_target = target_price not in {"", "目标价暂缺", "暂无目标价", "未给出目标价"}
    return has_rating and has_target


def filter_actionable_research_items(research: Dict[str, Any]) -> Dict[str, Any]:
    items = []
    for item in research.get("items") or []:
        if not is_actionable_research_item(item):
            continue
        clean = dict(item)
        clean["summary"] = compact_text(str(clean.get("summary") or ""), 90)
        items.append(clean)
    filtered = dict(research)
    filtered["items"] = items
    quality = dict(research.get("quality") or {})
    quality["item_count"] = len(items)
    if items:
        quality["level"] = "ok"
        quality["summary"] = f"机构观点数据可用，保留 {len(items)} 条同时具备评级和目标价的机构观点。"
    else:
        quality["level"] = "empty"
        quality["summary"] = "机构观点暂缺；缺评级或缺目标价的研报已过滤。"
    filtered["quality"] = quality
    return filtered


def build_public_opinion_items(news: Dict[str, Any], max_items: int = 6) -> List[Dict[str, Any]]:
    hits = []
    for item in news.get("items") or []:
        text = f"{item.get('title') or ''} {item.get('summary') or ''} {item.get('impact_analysis') or ''}"
        if any(keyword in text for keyword in PUBLIC_OPINION_KEYWORDS):
            hits.append(item)
    return hits[:max_items]


def iter_block_trade_items(block_trades: Any) -> List[Dict[str, Any]]:
    if isinstance(block_trades, dict):
        return list(block_trades.get("items") or [])
    if isinstance(block_trades, list):
        return block_trades
    return []


def build_block_trade_summary(block_trades: Any) -> Dict[str, Any]:
    items = iter_block_trade_items(block_trades)
    combined = " ".join(f"{item.get('title') or ''} {item.get('summary') or ''}" for item in items)
    if not combined.strip():
        return {"line": "暂缺。", "has_data": False}

    count_match = re.search(r"现?(\d+)笔大宗交易", combined)
    amount_match = re.search(r"(?:总成交金额|成交额)\s*([\d.]+)\s*亿元", combined)
    net_sell_match = re.search(r"机构净卖出\s*([\d.]+)\s*万元", combined)
    net_buy_match = re.search(r"机构净买入\s*([\d.]+)\s*万元", combined)
    premium_match = re.search(r"溢价率(?:为)?\s*(-?[\d.]+%)", combined)

    parts = []
    if count_match:
        parts.append(f"贵州茅台现{count_match.group(1)}笔大宗交易")
    else:
        parts.append("贵州茅台现大宗交易")
    if amount_match:
        parts.append(f"总成交金额{amount_match.group(1)}亿元")
    if net_sell_match:
        parts.append(f"机构净卖出{net_sell_match.group(1)}万元")
    elif net_buy_match:
        parts.append(f"机构净买入{net_buy_match.group(1)}万元")
    if premium_match:
        premium = premium_match.group(1)
        label = "折价率" if premium.startswith("-") else "溢价率"
        parts.append(f"{label}{premium}")
    return {
        "line": "，".join(parts) + "。",
        "has_data": True,
        "count": int(count_match.group(1)) if count_match else None,
        "amount_yi": to_float(amount_match.group(1)) if amount_match else None,
        "institution_net_sell_wan": to_float(net_sell_match.group(1)) if net_sell_match else None,
        "institution_net_buy_wan": to_float(net_buy_match.group(1)) if net_buy_match else None,
        "premium_pct": to_float(premium_match.group(1)) if premium_match else None,
        "items": items,
    }


def first_row_named(rows: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    return next((row for row in rows if str(row.get("板块") or "") == name), {})


def build_margin_financing_summary(margin_financing: Dict[str, Any] | None) -> Dict[str, Any]:
    item = (margin_financing or {}).get("item") or {}
    if not item:
        return {"line": "暂缺，本轮未取到融资融券数据，不参与判断。", "has_data": False}

    financing_balance = to_float(item.get("financing_balance_yi"))
    financing_buy = to_float(item.get("financing_buy_yi"))
    financing_repay = to_float(item.get("financing_repay_yi"))
    financing_net_buy = to_float(item.get("financing_net_buy_yi"))
    balance_change = to_float(item.get("financing_balance_change_yi"))
    short_balance = to_float(item.get("short_balance_shares"))
    short_change = to_float(item.get("short_balance_change_shares"))

    parts = []
    if financing_balance is not None:
        if balance_change is not None:
            parts.append(f"融资余额{financing_balance:.2f}亿元，较前一交易日{fmt_signed(balance_change, '亿元')}")
        else:
            parts.append(f"融资余额{financing_balance:.2f}亿元")
    if financing_buy is not None and financing_repay is not None and financing_net_buy is not None:
        parts.append(f"当日融资买入{financing_buy:.2f}亿元、偿还{financing_repay:.2f}亿元，融资净买入{fmt_signed(financing_net_buy, '亿元')}")
    if short_balance is not None:
        short_line = f"融券余量{short_balance / 10000:.2f}万股"
        if short_change is not None:
            short_line += f"，较前一交易日{fmt_signed(short_change / 10000, '万股')}"
        parts.append(short_line)

    return {
        "line": "；".join(parts) + "。" if parts else "融资融券字段不足，暂不参与判断。",
        "has_data": bool(parts),
        "financing_net_buy_yi": financing_net_buy,
        "financing_balance_change_yi": balance_change,
        "short_balance_change_shares": short_change,
    }


def build_fund_sentiment_line(
    quotes: Dict[str, Any],
    fund_flow: Dict[str, Any],
    block_trade: Dict[str, Any],
    margin_financing: Dict[str, Any] | None = None,
) -> str:
    primary = (quotes.get("quotes") or {}).get("600519", {})
    baijiu_rows_ = fund_flow.get("baijiu") or []
    baijiu = first_row_named(baijiu_rows_, "白酒Ⅱ") or (baijiu_rows_[0] if baijiu_rows_ else {})
    moutai_row = first_row_named(baijiu_rows_, "贵州茅台")

    positives: List[str] = []
    negatives: List[str] = []
    neutral: List[str] = []

    moutai_pct = to_float(primary.get("涨跌幅"))
    moutai_net = to_float(moutai_row.get("净流入（亿）"))
    moutai_super = to_float(moutai_row.get("超大单（亿）"))
    baijiu_net = to_float(baijiu.get("净流入（亿）"))
    baijiu_pct = to_float(baijiu.get("涨跌幅 %"))

    if baijiu_net is not None and baijiu_pct is not None:
        if baijiu_net > 0 and baijiu_pct > 0:
            positives.append("白酒Ⅱ净流入且上涨")
        elif baijiu_net < 0 and baijiu_pct < 0:
            negatives.append("白酒Ⅱ净流出且下跌")
        else:
            neutral.append("白酒Ⅱ资金与涨跌不同步")
    if moutai_pct is not None and moutai_net is not None:
        if moutai_pct > 0 and moutai_net < 0:
            negatives.append("茅台主力净流出但股价上涨")
        elif moutai_pct > 0 and moutai_net > 0:
            positives.append("茅台上涨且主力净流入")
        elif moutai_pct < 0 and moutai_net < 0:
            negatives.append("茅台下跌且主力净流出")
        else:
            neutral.append("茅台资金与涨跌不同步")
    if moutai_super is not None:
        if moutai_super < 0:
            negatives.append("茅台超大单净流出")
        elif moutai_super > 0:
            positives.append("茅台超大单净流入")
    if block_trade.get("institution_net_sell_wan") is not None and (block_trade.get("premium_pct") or 0) < 0:
        negatives.append("大宗交易机构净卖出且折价")
    elif block_trade.get("institution_net_buy_wan") is not None and (block_trade.get("premium_pct") or 0) >= 0:
        positives.append("大宗交易机构净买入")
    margin = build_margin_financing_summary(margin_financing)
    if margin.get("has_data"):
        net_buy = to_float(margin.get("financing_net_buy_yi"))
        balance_change = to_float(margin.get("financing_balance_change_yi"))
        short_change = to_float(margin.get("short_balance_change_shares"))
        if net_buy is not None and balance_change is not None:
            if net_buy > 0 and balance_change > 0:
                positives.append("融资端杠杆资金小幅加仓")
            elif net_buy < 0 and balance_change < 0:
                negatives.append("融资端杠杆资金减仓")
            else:
                neutral.append("融资买入与余额变化不同步")
        if short_change is not None:
            if short_change > 0:
                negatives.append("融券余量增加")
            elif short_change < 0:
                positives.append("融券余量下降")

    if negatives and positives:
        tone = "分歧偏弱" if len(negatives) > len(positives) else "分歧偏强"
    elif len(positives) >= len(negatives) + 2:
        tone = "偏强"
    elif len(negatives) >= len(positives) + 2:
        tone = "偏弱"
    elif negatives:
        tone = "偏弱"
    elif positives:
        tone = "偏强"
    else:
        tone = "中性"

    facts = [*positives, *negatives, *neutral]
    if not facts:
        return "样本不足，无法判断。"
    return f"{tone}：{'；'.join(facts[:5])}。"


def fund_flow_sanity_issues(rows: List[Dict[str, Any]], baijiu: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    if not baijiu:
        issues.append({"type": "baijiu_table_empty", "message": "白酒板块资金表为空"})
    for row in rows:
        name = row.get("板块", "未知板块")
        net = to_float(row.get("净流入（亿）"))
        amount = to_float(row.get("成交额（亿）"))
        rate = to_float(row.get("净流入率 %"))
        if net is not None and amount is not None and amount > 0 and abs(net) > amount:
            issues.append(
                {
                    "type": "fund_flow_net_exceeds_amount",
                    "board": name,
                    "net": net,
                    "amount": amount,
                    "message": "净流入绝对值大于成交额，疑似单位或源数据异常",
                }
            )
        if net is not None and amount not in (None, 0) and rate is not None:
            expected_rate = round(net / amount * 100, 2)
            if abs(expected_rate - rate) > 0.5:
                issues.append(
                    {
                        "type": "fund_flow_rate_mismatch",
                        "board": name,
                        "expected_rate": expected_rate,
                        "actual_rate": rate,
                        "message": "净流入率与净流入/成交额计算结果偏离过大",
                    }
                )
    return issues


def normalize_fund_flow_quality(sector: Dict[str, Any]) -> Dict[str, Any]:
    quality = dict(sector.get("quality") or {})
    if quality.get("source_mode") != "tushare_sw2_stock_moneyflow_aggregate":
        return sector
    summary = str(quality.get("summary") or "")
    if "小单<5万元" not in summary:
        quality["summary"] = (
            "申万二级行业资金流由 Tushare moneyflow 个股资金流按申万二级成分股聚合；"
            "Tushare 金额分档为小单<5万元、中单5-20万元、大单20-100万元、特大单/超大单>=100万元，"
            "基于主动买卖单统计；行业表按成分股档位净额加总，不按板块成交或一手金额重新分档。"
        )
    normalized = dict(sector)
    normalized["quality"] = quality
    return normalized


def build_market_summary(
    quotes: Dict[str, Any],
    fund_flow: Dict[str, Any],
    block_trades: Any | None = None,
    margin_financing: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    primary = (quotes.get("quotes") or {}).get("600519", {})
    inflow = (fund_flow.get("inflow_top5") or [{}])[0]
    outflow = (fund_flow.get("outflow_top5") or [{}])[0]
    baijiu = (fund_flow.get("baijiu") or [{}])[0]
    block_trade = build_block_trade_summary(block_trades)
    margin = build_margin_financing_summary(margin_financing)
    return {
        "moutai_line": "贵州茅台收于 {price} 元，涨跌幅 {pct}。".format(
            price=f"{to_float(primary.get('收盘价')):.2f}" if to_float(primary.get("收盘价")) is not None else "暂缺",
            pct=fmt_signed(primary.get("涨跌幅"), "%"),
        ),
        "main_inflow_line": "主力净流入居前的是 {name}（{net} 亿）。".format(
            name=inflow.get("板块", "暂缺"),
            net=fmt_signed(inflow.get("净流入（亿）")),
        ),
        "main_outflow_line": "净流出居前的是 {name}（{net} 亿）。".format(
            name=outflow.get("板块", "暂缺"),
            net=fmt_signed(outflow.get("净流入（亿）")),
        ),
        "baijiu_line": "{name}净流入 {net} 亿，板块涨跌幅 {pct}。".format(
            name=baijiu.get("板块", "白酒板块"),
            net=fmt_signed(baijiu.get("净流入（亿）")),
            pct=fmt_signed(baijiu.get("涨跌幅 %"), "%"),
        ),
        "block_trade_line": block_trade["line"],
        "margin_financing_line": margin["line"],
        "fund_sentiment_line": build_fund_sentiment_line(quotes, fund_flow, block_trade, margin_financing=margin_financing),
    }


def build_corporate_action_core_line(corporate_actions: Dict[str, Any]) -> str | None:
    dividend = corporate_actions.get("dividend") or {}
    buyback = corporate_actions.get("buyback") or {}
    parts = []
    if dividend:
        per_share = to_float(dividend.get("cash_dividend_per_share"))
        per_10 = to_float(dividend.get("cash_dividend_per_10_shares"))
        approved = dividend.get("approved_date")
        record_date = dividend.get("record_date") or "待确认"
        ex_date = dividend.get("ex_dividend_date") or "待确认"
        pay_date = dividend.get("cash_payment_date") or "待确认"
        if per_share is not None:
            amount = f"2025年度分红每股{per_share:.5f}元"
            if per_10 is not None:
                amount += f"（每10股{per_10:.2f}元）"
        else:
            amount = "2025年度分红金额待确认"
        approved_text = f"，{approved}股东会通过" if approved else ""
        parts.append(f"{amount}{approved_text}；登记日{record_date}、除息日{ex_date}、发放日{pay_date}；动作：等待权益分派实施公告确认日期")
    if buyback:
        shares = to_float(buyback.get("actual_shares_wan"))
        amount = to_float(buyback.get("actual_amount_yi"))
        low = to_float(buyback.get("price_low"))
        high = to_float(buyback.get("price_high"))
        completion = buyback.get("completion_date") or buyback.get("date") or "时间待确认"
        cancel = buyback.get("cancel_date")
        buyback_line = f"回购{completion}完成"
        if shares is not None and amount is not None:
            buyback_line += f"，{shares:.2f}万股/{amount:.2f}亿元"
        if low is not None and high is not None:
            buyback_line += f"，价格{low:.2f}-{high:.2f}元/股"
        if cancel:
            buyback_line += f"，{cancel}注销"
        buyback_line += "；动作：已完成，不作为未来增量回购买盘"
        parts.append(buyback_line)
    if not parts:
        return None
    return "公司行动：" + "；".join(parts)


def build_core_views(analysis: Dict[str, Any]) -> List[str]:
    summary = analysis.get("summary") or {}
    views = []
    corporate_line = build_corporate_action_core_line(analysis.get("corporate_actions") or {})
    if corporate_line:
        views.append(corporate_line)
    earnings_line = ((analysis.get("corporate_actions") or {}).get("earnings") or {}).get("line")
    if earnings_line:
        views.append(earnings_line)
    fund_line = summary.get("fund_sentiment_line")
    if fund_line and "样本不足" not in fund_line:
        views.append(f"资金情绪：{fund_line}")
    block_line = summary.get("block_trade_line")
    if block_line and block_line != "暂缺。":
        views.append(f"大宗交易：{block_line}")
    sentiment = analysis.get("sentiment") or {}
    sentiment_summary = sentiment.get("summary") or {}
    if sentiment_summary.get("sample_count"):
        views.append(f"散户舆论：{sentiment_summary.get('line')}")
    research_items = (analysis.get("research") or {}).get("items") or []
    if research_items:
        parts = [
            "{institution} {rating} {target}".format(
                institution=item.get("institution") or "机构暂缺",
                rating=item.get("rating") or "评级暂缺",
                target=item.get("target_price") or "目标价暂缺",
            )
            for item in research_items[:3]
        ]
        views.append(
            "机构观点：" + "；".join(parts) + "。"
        )
    macro_items = (analysis.get("macro") or {}).get("items") or []
    treasury = next((item for item in macro_items if "10年期国债" in str(item.get("title") or item.get("summary") or "")), None)
    if treasury:
        views.append(f"宏观利率：{treasury.get('summary') or treasury.get('title')}")
    return views[:7]


def build_daily_review(analysis: Dict[str, Any]) -> Dict[str, Any]:
    quotes = analysis.get("quotes") or {}
    fund_flow = analysis.get("fund_flow") or {}
    macro = analysis.get("macro") or {}
    summary = analysis.get("summary") or {}
    primary = (quotes.get("quotes") or {}).get("600519", {})
    baijiu_rows_ = fund_flow.get("baijiu") or []
    baijiu = first_row_named(baijiu_rows_, "白酒Ⅱ") or (baijiu_rows_[0] if baijiu_rows_ else {})
    moutai_row = first_row_named(baijiu_rows_, "贵州茅台")
    inflow_top = (fund_flow.get("inflow_top5") or [])[:3]

    lines: List[str] = []
    pct = to_float(primary.get("涨跌幅"))
    close = to_float(primary.get("收盘价"))
    open_price = to_float(primary.get("开盘价"))
    high = to_float(primary.get("最高价"))
    low = to_float(primary.get("最低价"))
    amount = to_float(primary.get("成交额（亿）"))
    if pct is not None and close is not None:
        direction = "下跌" if pct < 0 else "上涨" if pct > 0 else "平盘"
        lines.append(
            f"结论：今日贵州茅台{direction}{fmt_signed(pct, '%')}，收于{close:.2f}元；"
            "核心不是单一新闻冲击，而是技术承压、白酒资金分歧和成长板块吸金共同作用。"
        )
    tech_parts = []
    if open_price is not None and high is not None and low is not None and close is not None:
        tech_parts.append(f"日内开盘{open_price:.2f}、最高{high:.2f}、最低{low:.2f}、收盘{close:.2f}")
        if close < open_price:
            tech_parts.append("收盘低于开盘，说明盘中承接不足")
        if high == open_price:
            tech_parts.append("最高价贴近开盘价，反弹弹性偏弱")
    if amount is not None:
        tech_parts.append(f"成交额{amount:.2f}亿元")
    if tech_parts:
        lines.append("技术面：" + "；".join(tech_parts) + "。")

    fund_parts = []
    if moutai_row:
        fund_parts.append(
            "贵州茅台净流入{net}，超大单{super_large}，大单{large}，小单{small}".format(
                net=fmt_signed(moutai_row.get("净流入（亿）"), "亿"),
                super_large=fmt_signed(moutai_row.get("超大单（亿）"), "亿"),
                large=fmt_signed(moutai_row.get("大单（亿）"), "亿"),
                small=fmt_signed(moutai_row.get("小单（亿）"), "亿"),
            )
        )
    if baijiu:
        fund_parts.append(
            "{name}净流入{net}、涨跌幅{pct}".format(
                name=baijiu.get("板块", "白酒Ⅱ"),
                net=fmt_signed(baijiu.get("净流入（亿）"), "亿"),
                pct=fmt_signed(baijiu.get("涨跌幅 %"), "%"),
            )
        )
    if inflow_top:
        leader_text = "、".join(f"{row.get('板块')} {fmt_signed(row.get('净流入（亿）'), '亿')}" for row in inflow_top)
        fund_parts.append(f"资金主攻方向集中在{leader_text}")
    if fund_parts:
        lines.append("资金流动面：" + "；".join(fund_parts) + "。")

    macro_items = macro.get("items") or []
    macro_parts = []
    for item in macro_items:
        title = str(item.get("title") or "")
        summary_text = str(item.get("summary") or "")
        if any(key in title + summary_text for key in ["FOMC", "10年期国债", "PCE", "非农", "CPI", "PPI"]):
            macro_parts.append(summary_text or title)
        if len(macro_parts) >= 2:
            break
    if not macro_parts:
        macro_parts.append("宏观事件窗口暂以已抓取的利率、汇率与风险事件为准，缺数据时不强行编造。")
    lines.append("宏观消息面：" + "；".join(macro_parts) + "。")

    fund_sentiment = summary.get("fund_sentiment_line")
    if fund_sentiment:
        lines.append(f"大作手式判断：先看资金，再看叙事。今日资金情绪为“{fund_sentiment}”，短线应等待资金背离收敛或白酒Ⅱ重新获得净流入确认。")

    return {"title": "今日复盘：今日下跌的核心原因", "lines": lines}


def build_earnings_deep_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    earnings = ((analysis.get("corporate_actions") or {}).get("earnings") or {})
    report = earnings.get("latest_report") or {}
    if not report.get("deep_analysis_ready"):
        return {}

    metrics = report.get("metrics") or {}
    lines: List[str] = []
    revenue = to_float(metrics.get("revenue_yi"))
    revenue_yoy = to_float(metrics.get("revenue_yoy_pct"))
    profit = to_float(metrics.get("net_profit_yi"))
    profit_yoy = to_float(metrics.get("net_profit_yoy_pct"))
    cash_flow = to_float(metrics.get("operating_cash_flow_yi"))
    cash_flow_yoy = to_float(metrics.get("operating_cash_flow_yoy_pct"))
    i_moutai = to_float(metrics.get("i_moutai_revenue_yi"))

    facts = []
    if revenue is not None:
        facts.append(f"营业收入{revenue:.2f}亿元" + (f"（同比{fmt_signed(revenue_yoy, '%')}）" if revenue_yoy is not None else ""))
    if profit is not None:
        facts.append(f"净利润{profit:.2f}亿元" + (f"（同比{fmt_signed(profit_yoy, '%')}）" if profit_yoy is not None else ""))
    if cash_flow is not None:
        facts.append(f"经营现金流{cash_flow:.2f}亿元" + (f"（同比{fmt_signed(cash_flow_yoy, '%')}）" if cash_flow_yoy is not None else ""))
    if i_moutai is not None:
        facts.append(f"i茅台{i_moutai:.2f}亿元")
    if facts:
        lines.append("财报事实：" + "，".join(facts) + "。")

    news_sections = (analysis.get("news") or {}).get("sections") or []
    news_title = None
    for section in news_sections:
        section_items = section.get("items") or []
        if section_items:
            news_title = section_items[0].get("title")
            break
    if news_title:
        lines.append(f"要闻联动：最新高优先级事件为“{news_title}”，需与财报中的收入增速、渠道收入和现金流质量交叉验证。")

    summary = analysis.get("summary") or {}
    if summary.get("fund_sentiment_line") or summary.get("baijiu_line"):
        lines.append(f"资金与板块：资金情绪为“{summary.get('fund_sentiment_line') or '暂缺'}”；{summary.get('baijiu_line') or ''}")

    sentiment_line = ((analysis.get("sentiment") or {}).get("summary") or {}).get("line")
    if sentiment_line:
        lines.append(f"市场情绪：散户舆论为“{sentiment_line}”，用于观察财报公布后的短期预期差。")

    research_items = (analysis.get("research") or {}).get("items") or []
    if research_items:
        parts = [
            f"{item.get('institution') or '机构暂缺'} {item.get('rating') or '评级暂缺'} {item.get('target_price') or '目标价暂缺'}"
            for item in research_items[:3]
        ]
        lines.append("机构校验：" + "；".join(parts) + "。")

    if revenue_yoy is not None and profit_yoy is not None:
        if profit_yoy < revenue_yoy:
            lines.append("解读结论：收入仍增长但利润增速低于收入增速，需重点追踪价格体系、产品结构、费用和渠道政策是否压制盈利弹性。")
        else:
            lines.append("解读结论：利润弹性不弱于收入增速，需继续验证这种质量能否被批价、动销和现金流延续。")

    return {
        "title": report.get("title") or "定期报告",
        "date": report.get("date") or "日期暂缺",
        "url": report.get("url") or "",
        "lines": lines,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    config = load_yaml(args.config)
    data_dir = Path(args.data_dir)
    sector = read_json(data_dir / "sector_fund_flow.json", default={}) or {}
    sector = normalize_fund_flow_quality(sector)
    rows: List[Dict[str, Any]] = sector.get("rows", [])
    stock_rows: List[Dict[str, Any]] = sector.get("stock_rows", [])
    fund_config = config.get("fund_flow", {})
    legacy_top_n = int(fund_config.get("top_n", 5))
    inflow_outflow_top_n = int(fund_config.get("inflow_outflow_top_n", legacy_top_n))
    divergence_top_n = int(fund_config.get("divergence_top_n", legacy_top_n))
    baijiu_top_n = int(fund_config.get("baijiu_top_n", divergence_top_n))

    inflow_top = sort_rows(rows, "净流入（亿）", reverse=True, n=inflow_outflow_top_n)
    outflow_top = sort_rows(rows, "净流入（亿）", reverse=False, n=inflow_outflow_top_n)

    div_1 = sort_rows(
        filter_rows(rows, lambda r: (to_float(r.get("净流入（亿）")) or 0) > 0 and (to_float(r.get("涨跌幅 %")) or 0) < 0),
        "净流入（亿）",
        reverse=True,
        n=divergence_top_n,
    )
    div_2 = sort_rows(
        filter_rows(rows, lambda r: (to_float(r.get("净流入（亿）")) or 0) < 0 and (to_float(r.get("涨跌幅 %")) or 0) > 0),
        "净流入（亿）",
        reverse=False,
        n=divergence_top_n,
    )
    div_3 = sort_rows(
        filter_rows(rows, lambda r: (to_float(r.get("超大单（亿）")) or 0) > 0 and (to_float(r.get("大单（亿）")) or 0) < 0),
        "超大单（亿）",
        reverse=True,
        n=divergence_top_n,
    )
    div_4 = sort_rows(
        filter_rows(rows, lambda r: (to_float(r.get("超大单（亿）")) or 0) < 0 and (to_float(r.get("大单（亿）")) or 0) > 0),
        "超大单（亿）",
        reverse=False,
        n=divergence_top_n,
    )

    baijiu = baijiu_rows(rows, fund_config.get("baijiu_keywords", ["白酒", "酿酒"]))[:baijiu_top_n]
    baijiu = [*baijiu, *stock_rows]

    issues = []
    for table_name, table_rows in {
        f"净流入 TOP {inflow_outflow_top_n}": inflow_top,
        f"净流出 TOP {inflow_outflow_top_n}": outflow_top,
        "背离一": div_1,
        "背离二": div_2,
        "背离三": div_3,
        "背离四": div_4,
        "白酒板块": baijiu,
    }.items():
        for idx, row in enumerate(table_rows, 1):
            missing_cols = [col for col in REQUIRED_FUND_COLUMNS if col not in row]
            if missing_cols:
                issues.append({"table": table_name, "row": idx, "missing_columns": missing_cols})
    issues.extend(fund_flow_sanity_issues(rows, baijiu))

    quotes = read_json(data_dir / "quotes.json", default={}) or {}
    news = read_json(data_dir / "news.json", default={}) or {}
    research = read_json(data_dir / "research.json", default={}) or {}
    macro = read_json(data_dir / "macro.json", default={}) or {}
    sentiment = read_json(data_dir / "sentiment.json", default={}) or {}
    margin_financing = read_json(data_dir / "margin_financing.json", default={}) or {}
    corporate_actions = read_json(data_dir / "corporate_actions.json", default={}) or {}
    research = normalize_research_signal_fields(research)
    research = merge_news_institution_views_into_research(research, news)
    news = merge_macro_events_into_news(news, macro, config)
    news = remove_institution_views_from_news(news, config)
    news["public_opinion"] = build_public_opinion_items(news)
    research = filter_actionable_research_items(research)

    analysis = {
        "generated_at": now_iso(),
        "required_fund_columns": REQUIRED_FUND_COLUMNS,
        "quality_issues": issues,
        "table_limits": {
            "inflow_outflow_top_n": inflow_outflow_top_n,
            "divergence_top_n": divergence_top_n,
            "baijiu_top_n": baijiu_top_n,
        },
        "quotes": quotes,
        "news": news,
        "research": research,
        "macro": macro,
        "sentiment": sentiment,
        "margin_financing": margin_financing,
        "corporate_actions": corporate_actions,
        "summary": build_market_summary(
            quotes,
            {
                "inflow_top5": inflow_top,
                "outflow_top5": outflow_top,
                "baijiu": baijiu,
            },
            block_trades={"items": news.get("block_trades") or []},
            margin_financing=margin_financing,
        ),
        "fund_flow": {
            "sources": sector.get("sources", []),
            "stock_sources": sector.get("stock_sources", []),
            "errors": sector.get("errors", []),
            "warnings": sector.get("warnings", []),
            "supplements": sector.get("supplements", {}),
            "quality": sector.get("quality", {}),
            "inflow_top5": inflow_top,
            "outflow_top5": outflow_top,
            "divergence_net_inflow_price_down": div_1,
            "divergence_net_outflow_price_up": div_2,
            "divergence_super_in_large_out": div_3,
            "divergence_super_out_large_in": div_4,
            "baijiu": baijiu,
        },
    }
    analysis["earnings_analysis"] = build_earnings_deep_analysis(analysis)
    analysis["core_views"] = build_core_views(analysis)
    analysis["daily_review"] = build_daily_review(analysis)
    write_json(args.out, analysis)


if __name__ == "__main__":
    main()
