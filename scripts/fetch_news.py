from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from html import unescape
from typing import Any, Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import load_yaml, now_iso, write_json
from fetch_research import compact_text, extract_rating_and_target


SOURCE_PRIORITY = {
    "贵州茅台官网": 0,
    "上交所公告": 1,
    "巨潮资讯": 2,
    "Federal Reserve": 2,
    "Bureau of Labor Statistics": 2,
    "U.S. Bureau of Economic Analysis": 2,
    "财联社": 3,
    "证券时报": 4,
    "中国证券报": 4,
    "上海证券报": 4,
    "券商观点": 4,
    "新浪财经研究报告": 4,
    "东方财富": 5,
    "东方财富搜索页": 5,
    "新浪财经": 6,
    "新浪财经个股资讯": 6,
}

IMPORTANCE_SCORE = {"高": 3, "中": 2, "低": 1}

MAIN_TARGET_KEYWORDS = [
    "贵州茅台",
    "600519",
    "茅台",
    "飞天茅台",
    "茅台1935",
    "i茅台",
    "I茅台",
    "茅台集团",
    "茅台人事",
    "董事长",
    "高管",
    "人事调整",
    "大宗交易",
    "机构净买入",
    "机构净卖出",
    "溢价率",
]
INDUSTRY_KEYWORDS = [
    "白酒",
    "食品饮料",
    "飞天批价",
    "批价",
    "调价",
    "提价",
    "动态调价",
    "市场化改革",
    "年轻人",
    "年轻消费者",
    "年轻一代",
    "不喝白酒",
    "低度酒",
    "消费代际",
    "消费趋势",
    "宴席消费",
    "商务消费",
    "礼赠消费",
    "做假账",
    "财务造假",
    "会计差错",
    "审计保留",
    "虚增收入",
    "暗账",
    "处罚",
    "监管",
    "经销商暴雷",
    "渠道乱象",
    "动销",
    "库存",
    "渠道",
    "五粮液",
    "山西汾酒",
    "泸州老窖",
    "洋河股份",
    "今世缘",
    "古井贡酒",
    "舍得酒业",
    "酒鬼酒",
]
MACRO_KEYWORDS = [
    "降准",
    "降息",
    "LPR",
    "MLF",
    "逆回购",
    "社融",
    "M2",
    "信贷",
    "央行",
    "中国人民银行",
    "财政部",
    "国务院",
    "证监会",
    "美联储",
    "美联储换届",
    "欧洲央行",
    "日本央行",
    "IMF",
    "世界银行",
    "CPI",
    "PPI",
    "PMI",
    "GDP",
    "社零",
    "出口",
    "房地产",
    "PCE",
    "非农",
    "美国非农",
    "ISM",
    "美债",
    "美债收益率",
    "美国10年期国债收益率",
    "美元指数",
    "人民币",
    "加息",
    "战争",
    "美伊",
    "美伊战争",
    "伊朗",
    "以色列",
    "中东",
    "冲突",
    "金融风险",
    "银行业",
    "主权债务",
    "IPO",
    "减持",
    "分红政策",
]

INSTITUTION_NAMES = [
    "高盛",
    "中金",
    "中国国际金融",
    "华创证券",
    "国海证券",
    "兴业证券",
    "中信证券",
    "华西证券",
    "天风证券",
    "华鑫证券",
    "摩根士丹利",
    "大摩",
    "瑞银",
]


def normalize_title_for_event(title: str) -> str:
    text = re.sub(r"\s+", "", title)
    text = re.sub(r"\d{4}年?度?", "", text)
    replacements = {
        "发布": "",
        "公布": "",
        "披露": "",
        "公告": "",
        "年度": "",
        "方案": "方案",
        "实施": "",
        "最新": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def source_rank(source: str) -> int:
    for key, rank in SOURCE_PRIORITY.items():
        if key in source:
            return rank
    return 9


def infer_category(title: str) -> str:
    if any(keyword in title for keyword in MACRO_KEYWORDS):
        return "宏观与风险事件"
    primary_company_keywords = ["贵州茅台", "600519", "茅台集团", "i茅台", "I茅台", "股东大会", "董事长", "高管", "人事调整"]
    if any(keyword in title for keyword in primary_company_keywords):
        return "主标的新闻"
    if any(keyword in title for keyword in INDUSTRY_KEYWORDS):
        return "行业新闻"
    if any(keyword in title for keyword in MAIN_TARGET_KEYWORDS):
        return "主标的新闻"
    return "其他"


def infer_impact_direction(title: str) -> str:
    positive = ["分红", "回购", "增持", "增长", "超预期", "提价", "批价上涨", "动销改善", "降准", "降息", "消费刺激", "长期资金", "机构净买入"]
    negative = ["减持", "下滑", "不及预期", "批价下跌", "批价大幅回落", "回落", "库存高", "动销不佳", "做假账", "财务造假", "会计差错", "审计保留", "虚增收入", "暗账", "处罚", "监管", "渠道乱象", "经销商暴雷", "战争升级", "金融风险", "加息", "机构净卖出", "折价"]
    neutral = ["维持", "会议", "讲话", "表态", "数据公布", "换届", "人事调整"]
    if any(word in title for word in positive):
        return "利好"
    if any(word in title for word in negative):
        return "利空"
    if any(word in title for word in neutral):
        return "中性"
    return "待观察"


def infer_impact_targets(title: str) -> List[str]:
    targets = []
    if any(keyword in title for keyword in MAIN_TARGET_KEYWORDS):
        targets.append("贵州茅台")
    if any(keyword in title for keyword in INDUSTRY_KEYWORDS):
        targets.append("白酒行业")
    if any(keyword in title for keyword in ["消费", "餐饮", "社零", "高端消费", "食品饮料", "年轻人", "年轻消费者", "低度酒"]):
        targets.append("消费板块")
    if any(keyword in title for keyword in ["降准", "降息", "LPR", "MLF", "社融", "M2", "信贷", "证监会", "IPO", "长期资金", "A股", "美债", "加息"]):
        targets.append("A股市场")
    if any(keyword in title for keyword in ["美联储", "美国", "PCE", "非农", "ISM", "美元", "战争", "冲突", "IMF", "世界银行", "全球", "美伊", "伊朗", "以色列", "中东"]):
        targets.append("全球市场")
    return targets or ["A股市场"]


def infer_impact_period(title: str, category: str) -> str:
    if any(word in title for word in ["财报", "分红", "股东大会", "董事长", "高管", "人事调整", "战略", "渠道改革", "组织架构", "市场化改革"]):
        return "长期（1年以上）"
    if any(word in title for word in ["动销", "库存", "批价", "调价", "提价", "年轻人", "年轻消费者", "低度酒", "消费趋势", "业绩预告", "宏观数据", "CPI", "PPI", "PMI", "社融", "M2", "LPR", "非农", "美债"]):
        return "中期（1-3个月）"
    if category == "宏观与风险事件":
        return "短期（1-5天）"
    return "中期（1-3个月）"


def infer_importance(title: str) -> tuple[str, str]:
    high = ["财报", "业绩快报", "业绩预告", "分红", "权益分派", "利润分配", "批价大幅", "提价", "调价", "动销重大", "做假账", "财务造假", "会计差错", "审计保留", "虚增收入", "暗账", "处罚", "重大监管", "渠道乱象", "经销商暴雷", "降准", "降息", "美联储议息", "战争升级", "美伊战争", "金融风险", "董事长变动", "人事调整"]
    medium = ["宏观数据", "CPI", "PPI", "PMI", "GDP", "社零", "非农", "美债", "加息", "美联储换届", "行业数据", "券商", "评级", "目标价", "讲话", "表态", "批价", "库存", "动销", "年轻人", "年轻消费者", "低度酒", "消费趋势", "大宗交易", "机构净买入", "机构净卖出", "溢价率"]
    if any(word in title for word in high):
        return "高", "涉及财报/分红/流动性/重大价格或风险事件，可能影响长期估值或风险偏好。"
    if any(word in title for word in medium):
        return "中", "涉及宏观、行业、价格、交易行为、机构观点或政策信号，需要纳入跟踪。"
    return "低", "普通资讯或投资影响暂不明确，仅作为背景信息。"


def build_investment_analysis(item: Dict[str, Any]) -> str:
    direction = item.get("impact_direction", "待观察")
    targets = "、".join(item.get("impact_targets") or [])
    period = item.get("impact_period", "中期（1-3个月）")
    category = item.get("category", "其他")
    if category == "主标的新闻":
        return f"重点看是否改变贵州茅台经营质量、渠道价格体系或股东回报预期；当前方向为{direction}，影响对象：{targets}，影响周期：{period}。"
    if category == "行业新闻":
        return f"重点看白酒动销、库存、批价和终端需求是否发生趋势变化；当前方向为{direction}，影响对象：{targets}，影响周期：{period}。"
    if category == "宏观与风险事件":
        return f"重点看市场流动性、估值折现率和风险偏好是否变化；当前方向为{direction}，影响对象：{targets}，影响周期：{period}。"
    return f"投资影响暂不明确；当前方向为{direction}，影响对象：{targets}，影响周期：{period}。"


def enrich_news_item(item: Dict[str, Any]) -> Dict[str, Any]:
    title = str(item.get("title") or "").strip()
    source = str(item.get("source") or "暂缺").strip()
    category = item.get("category") or infer_category(title)
    inferred_importance, inferred_importance_reason = infer_importance(title)
    importance = item.get("importance") or inferred_importance
    importance_reason = item.get("importance_reason") or inferred_importance_reason
    enriched = {
        "title": title,
        "url": item.get("url") or "暂缺",
        "source": source,
        "time": item.get("time") or "暂缺",
        "keyword": item.get("keyword") or "",
        "category": category,
        "summary": item.get("summary") or infer_news_summary(title),
        "impact_direction": item.get("impact_direction") or infer_impact_direction(title),
        "impact_targets": item.get("impact_targets") or infer_impact_targets(title),
        "impact_period": item.get("impact_period") or infer_impact_period(title, category),
        "importance": importance,
        "importance_reason": importance_reason,
    }
    if item.get("institution_view"):
        enriched["institution_view"] = item.get("institution_view")
    enriched["impact_analysis"] = item.get("impact_analysis") or build_investment_analysis(enriched)
    # 兼容旧模板字段。
    enriched["impact"] = item.get("impact") or enriched["impact_analysis"]
    return enriched


def is_investment_relevant(item: Dict[str, Any]) -> bool:
    title = item.get("title") or ""
    return item.get("importance") != "低" or any(
        keyword in title for keyword in [*MAIN_TARGET_KEYWORDS, *INDUSTRY_KEYWORDS, *MACRO_KEYWORDS]
    )


def better_news_item(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    left_tuple = (source_rank(left.get("source", "")), -IMPORTANCE_SCORE.get(left.get("importance", "低"), 1), left.get("time") or "")
    right_tuple = (source_rank(right.get("source", "")), -IMPORTANCE_SCORE.get(right.get("importance", "低"), 1), right.get("time") or "")
    return left if left_tuple <= right_tuple else right


def ranked_news_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            item.get("time") or "",
            -IMPORTANCE_SCORE.get(item.get("importance", "低"), 1),
            source_rank(item.get("source", "")),
        ),
        reverse=True,
    )


def select_section_items(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    selected = sorted(
        items,
        key=lambda item: (
            IMPORTANCE_SCORE.get(item.get("importance", "低"), 1),
            -source_rank(item.get("source", "")),
            item.get("time") or "",
        ),
        reverse=True,
    )[:limit]
    return ranked_news_items(selected)


def group_news_sections(items: List[Dict[str, Any]], per_section: int = 4) -> List[Dict[str, Any]]:
    sections = [
        {"key": "main", "title": "主标的新闻", "empty": "近一个月未见贵州茅台主标的有效新闻。", "items": []},
        {"key": "industry", "title": "行业新闻", "empty": "近一个月未见白酒/消费行业有效新闻。", "items": []},
        {"key": "risk", "title": "宏观与风险事件", "empty": "近一个月未见流动性或风险偏好有效新闻。", "items": []},
    ]
    mapping = {
        "主标的新闻": sections[0],
        "行业新闻": sections[1],
        "宏观与风险事件": sections[2],
    }
    buckets = {title: [] for title in mapping}
    for item in items:
        section = mapping.get(item.get("category"))
        if section is None:
            continue
        buckets[section["title"]].append(item)
    for section in sections:
        section["items"] = select_section_items(buckets.get(section["title"], []), per_section)
    return sections


def balanced_search_keywords(keywords: List[str], limit: int) -> List[str]:
    buckets = {
        "main": [],
        "industry": [],
        "risk": [],
        "other": [],
    }
    for keyword in keywords:
        if any(part in keyword for part in MACRO_KEYWORDS):
            buckets["risk"].append(keyword)
        elif any(part in keyword for part in INDUSTRY_KEYWORDS):
            buckets["industry"].append(keyword)
        elif any(part in keyword for part in MAIN_TARGET_KEYWORDS):
            buckets["main"].append(keyword)
        else:
            buckets["other"].append(keyword)

    selected: List[str] = []
    while len(selected) < limit:
        changed = False
        for key in ["main", "industry", "risk", "other"]:
            if buckets[key]:
                candidate = buckets[key].pop(0)
                if candidate not in selected:
                    selected.append(candidate)
                    changed = True
                    if len(selected) >= limit:
                        break
        if not changed:
            break
    return selected


def deduplicate_and_rank_news(items: List[Dict[str, Any]], max_items: int, per_section: int = 4) -> List[Dict[str, Any]]:
    by_url: Dict[str, Dict[str, Any]] = {}
    for raw in items:
        item = enrich_news_item(raw)
        url = item.get("url") or ""
        if url and url != "暂缺":
            by_url[url] = better_news_item(by_url[url], item) if url in by_url else item
        else:
            key = f"missing-url:{item.get('title')}"
            by_url[key] = item

    by_event: Dict[str, Dict[str, Any]] = {}
    for item in by_url.values():
        key = normalize_title_for_event(item.get("title", ""))
        by_event[key] = better_news_item(by_event[key], item) if key in by_event else item

    relevant = [item for item in by_event.values() if is_investment_relevant(item)]
    grouped = group_news_sections(relevant, per_section=per_section)
    ranked: List[Dict[str, Any]] = []
    for section in grouped:
        ranked.extend(section["items"])
    return ranked[:max_items]


def build_news_brief(items: List[Dict[str, Any]]) -> Dict[str, str]:
    main = [item for item in items if "贵州茅台" in (item.get("impact_targets") or [])]
    industry = [item for item in items if "白酒行业" in (item.get("impact_targets") or [])]
    liquidity = [item for item in items if "A股市场" in (item.get("impact_targets") or []) and item.get("category") == "宏观与风险事件"]
    global_risk = [item for item in items if "全球市场" in (item.get("impact_targets") or [])]

    def line(label: str, hits: List[Dict[str, Any]], stable_text: str) -> str:
        if not hits:
            return f"{label}：未见需要改变判断的高价值新闻。{stable_text}"
        top = hits[0]
        return f"{label}：{top.get('impact_direction')}，关注“{top.get('title')}”。{top.get('impact_analysis')}"

    return {
        "茅台长期价值": line("茅台长期价值", main, "继续以经营质量、渠道价格和股东回报为核心跟踪。"),
        "白酒行业景气度": line("白酒行业景气度", industry, "继续重点跟踪批价、库存和动销。"),
        "市场流动性": line("市场流动性", liquidity, "暂未看到流动性环境发生方向性变化。"),
        "风险偏好": line("风险偏好", global_risk, "暂未看到全球风险事件明显冲击 A 股风险偏好。"),
    }


def is_within_lookback(item_date: str, target_date: str | None, lookback_days: int) -> bool:
    if not target_date:
        return True
    item_dt = datetime.strptime(item_date, "%Y-%m-%d").date()
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    start_dt = target_dt - timedelta(days=max(lookback_days - 1, 0))
    return start_dt <= item_dt <= target_dt


def year_start_for_date(target_date: str | None) -> str:
    if target_date:
        return f"{target_date[:4]}-01-01"
    return f"{datetime.now().year}-01-01"


def parse_sse_announcements(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = ((payload.get("pageHelp") or {}).get("data") or [])
    items: List[Dict[str, Any]] = []
    for row in data:
        title = row.get("TITLE")
        if not title:
            continue
        url = urljoin("https://www.sse.com.cn/", row.get("URL") or "")
        items.append(
            enrich_news_item(
                {
                    "title": title,
                    "source": "上交所公告",
                    "time": row.get("SSEDATE") or row.get("ADDDATE") or "暂缺",
                    "url": url,
                    "summary": f"贵州茅台官方公告：{title}",
                }
            )
        )
    return items


def fetch_sse_announcements(symbol: str, start_date: str, end_date: str, max_items: int = 80) -> List[Dict[str, Any]]:
    url = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
    params = {
        "jsonCallBack": "",
        "isPagination": "true",
        "productId": symbol,
        "securityType": "0101,120100,020100,020200,120200",
        "reportType": "ALL",
        "beginDate": start_date,
        "endDate": end_date,
        "pageHelp.pageSize": str(max_items),
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "5",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.sse.com.cn/assortment/stock/list/info/announcement/",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return parse_sse_announcements(resp.json())


def fetch_public_search_stub(keyword: str, max_items: int = 3) -> List[Dict[str, Any]]:
    """轻量新闻抓取骨架。

    生产建议：
    1. 优先使用 Hermes 的浏览器/搜索工具抓新闻，因为它更适合处理搜索结果页。
    2. 或者接入你有权限的新闻 API。
    3. 不要绕过登录、付费墙、验证码或反爬限制。

    这里给一个简单 HTML 解析示例：抓取公开搜索结果页的 title 文本。
    具体新闻源页面结构经常变化，因此结果仅作为脚手架。
    """
    url = "https://so.eastmoney.com/news/s"
    params = {"keyword": keyword}
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items: List[Dict[str, Any]] = []
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        href = a.get("href")
        if not title or len(title) < 8:
            continue
        if keyword not in title and "茅台" not in title and "白酒" not in title:
            continue
        items.append(
            enrich_news_item(
                {
                "title": title,
                "source": "东方财富搜索页",
                "time": "暂缺",
                "url": href,
                "keyword": keyword,
                "summary": "待 Hermes 浏览器或新闻 API 补充摘要。",
                }
            )
        )
        if len(items) >= max_items:
            break
    return items


def infer_news_impact(title: str) -> str:
    if any(word in title for word in ["股东会", "市场化改革", "股东回报", "i茅台", "韧性"]):
        return "偏公司经营与治理信号，需结合股价和白酒板块资金验证。"
    if any(word in title for word in ["批价", "酒价", "领跌", "回落", "价格"]):
        return "偏终端价格情绪，可能影响白酒板块估值预期。"
    if any(word in title for word in ["致歉", "侵权", "处罚", "风险"]):
        return "偏事件扰动，短期影响需看是否扩散到品牌或渠道层面。"
    if any(word in title for word in ["股王", "大跌", "估值"]):
        return "偏市场比较与交易情绪，参考价值低于公司基本面信息。"
    return "公开新闻线索，需结合资金流、行情与权威公告交叉验证。"


def infer_news_summary(title: str) -> str:
    return f"公开新闻标题指向：{title}"


def detect_institution(text: str) -> str | None:
    for name in INSTITUTION_NAMES:
        if name in text:
            return "中国国际金融股份有限公司" if name in {"中金", "中国国际金融"} else name
    return None


def article_text_from_html(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    body = (
        soup.select_one("#artibody")
        or soup.select_one(".article")
        or soup.select_one(".article-content")
        or soup.select_one(".content")
        or soup.find("article")
        or soup.body
    )
    return body.get_text(" ", strip=True) if body else ""


def enrich_institution_news_detail(item: Dict[str, Any]) -> Dict[str, Any]:
    title = item.get("title") or ""
    if not any(keyword in title for keyword in ["目标价", "评级", *INSTITUTION_NAMES]):
        return item
    url = item.get("url") or ""
    if not url.startswith("http"):
        return item
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        text = article_text_from_html(resp.text)
    except Exception as exc:  # noqa: BLE001
        item["detail_error"] = f"institution news detail failed: {exc}"
        return item

    combined = f"{title} {text}"
    institution = detect_institution(combined)
    signals = extract_rating_and_target(combined)
    if not institution or not signals:
        return item
    item["institution_view"] = {
        "institution": institution,
        "rating": signals.get("rating") or "评级暂缺",
        "target_price": signals.get("target_price") or "目标价暂缺",
    }
    signal_line = "，".join(part for part in [item["institution_view"]["rating"], item["institution_view"]["target_price"]] if part and "暂缺" not in part)
    if signal_line:
        item["summary"] = compact_text(f"{institution}：{signal_line}。{text}", 140)
    return item


def parse_sina_stock_news_html(
    html_text: str,
    keywords: List[str],
    target_date: str | None = None,
    lookback_days: int = 30,
    max_items: int = 8,
) -> List[Dict[str, Any]]:
    """Parse Sina stock news list rows from the legacy gbk HTML page."""
    pattern = re.compile(
        r"(?P<date>\d{4}-\d{2}-\d{2})&nbsp;(?P<time>\d{2}:\d{2})&nbsp;&nbsp;"
        r"\s*<a[^>]+href=['\"](?P<href>[^'\"]+)['\"][^>]*>(?P<title>.*?)</a>",
        re.S,
    )
    items: List[Dict[str, Any]] = []
    for match in pattern.finditer(html_text):
        item_date = match.group("date")
        if not is_within_lookback(item_date, target_date, lookback_days):
            continue
        title = BeautifulSoup(unescape(match.group("title")), "html.parser").get_text(" ", strip=True)
        title = " ".join(title.split())
        if not title:
            continue
        if keywords and not any(keyword in title for keyword in keywords):
            continue
        href = urljoin("https://vip.stock.finance.sina.com.cn/", unescape(match.group("href")))
        raw = {
            "title": title,
            "source": "新浪财经个股资讯",
            "time": f"{item_date} {match.group('time')}",
            "url": href,
            "keyword": next((keyword for keyword in keywords if keyword in title), ""),
            "summary": infer_news_summary(title),
        }
        items.append(enrich_news_item(raw))
        if len(items) >= max_items:
            break
    return items


def fetch_sina_stock_news(symbol: str, keywords: List[str], target_date: str | None, max_items: int, lookback_days: int = 30) -> List[Dict[str, Any]]:
    market_symbol = f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{market_symbol}.phtml"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    resp.encoding = "gbk"
    items = parse_sina_stock_news_html(resp.text, keywords, target_date=target_date, lookback_days=lookback_days, max_items=max_items)
    enriched = []
    for item in items:
        enriched.append(enrich_news_item(enrich_institution_news_detail(item)))
    return enriched


def build_quality(items: List[Dict[str, Any]], errors: List[str]) -> Dict[str, Any]:
    if items:
        return {
            "level": "ok",
            "source_mode": "long_term_investor_news_filter",
            "summary": f"新闻数据可用，已保留 {len(items)} 条近一个月相关公开新闻，并按主标的、行业、宏观风险分组。",
            "item_count": len(items),
        }
    return {
        "level": "empty",
        "source_mode": "none",
        "summary": "新闻数据暂缺；公开源未返回匹配条目。",
        "item_count": 0,
        "error_count": len(errors),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", help="News date in YYYY-MM-DD format. Defaults to latest available.")
    parser.add_argument("--lookback-days", type=int, help="Override news lookback window in calendar days.")
    args = parser.parse_args()

    config = load_yaml(args.config)
    keywords = config.get("news", {}).get("keywords", [])
    max_items = int(config.get("news", {}).get("max_items", 8))
    per_section = int(config.get("news", {}).get("per_section", 4))
    lookback_days = int(args.lookback_days or config.get("news", {}).get("lookback_days", 30))
    max_search_keywords = int(config.get("news", {}).get("max_search_keywords", min(len(keywords), 12)))
    primary_symbol = str(config.get("primary_stock", {}).get("symbol", "600519"))

    errors = []
    news: List[Dict[str, Any]] = []
    sources = []
    if args.date:
        try:
            official = fetch_sse_announcements(primary_symbol, year_start_for_date(args.date), args.date)
            news.extend(official)
            if official:
                sources.append("上交所公告")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"sse announcements failed for {primary_symbol}: {exc}")

    try:
        news.extend(fetch_sina_stock_news(primary_symbol, keywords, target_date=args.date, max_items=max_items, lookback_days=lookback_days))
        if news:
            sources.append("新浪财经个股资讯")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"sina stock news failed for {primary_symbol}: {exc}")

    block_trades: List[Dict[str, Any]] = []
    try:
        block_trades = fetch_sina_stock_news(primary_symbol, ["大宗交易"], target_date=args.date, max_items=8, lookback_days=lookback_days)
        news.extend(block_trades)
        if block_trades:
            sources.append("新浪财经个股资讯-大宗交易")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"sina block trade news failed for {primary_symbol}: {exc}")

    for keyword in balanced_search_keywords(keywords, max_search_keywords):
        try:
            news.extend(fetch_public_search_stub(keyword, max_items=2))
            sources.append("东方财富搜索页")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"news search failed for {keyword}: {exc}")

    dedup = deduplicate_and_rank_news(news, max_items=max_items, per_section=per_section)
    sections = group_news_sections(dedup, per_section=per_section)

    write_json(
        args.out,
        {
            "generated_at": now_iso(),
            "sources": sources or ["新浪财经个股资讯 / 东方财富搜索页"],
            "errors": errors,
            "quality": build_quality(dedup, errors),
            "brief": build_news_brief(dedup),
            "lookback_days": lookback_days,
            "sections": sections,
            "items": dedup,
            "block_trades": deduplicate_and_rank_news(block_trades, max_items=8, per_section=8),
        },
    )


if __name__ == "__main__":
    main()
