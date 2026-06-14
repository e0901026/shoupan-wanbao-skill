from __future__ import annotations

import argparse
import io
import re
from datetime import datetime
from typing import Any, Dict, List

import requests
from pypdf import PdfReader

from common import load_yaml, now_iso, round_or_none, to_float, write_json, yuan_to_yi
from fetch_news import fetch_sse_announcements


SOURCE_NAME = "上交所公告"
SSE_REFERER = "https://www.sse.com.cn/assortment/stock/list/info/announcement/index.shtml"
PDF_SESSION = requests.Session()
PDF_SESSION.trust_env = False
SSE_ACW_MASK = "3000176000856006061501533003690027800375"
SSE_ACW_POS = [
    0xF,
    0x23,
    0x1D,
    0x18,
    0x21,
    0x10,
    0x1,
    0x26,
    0xA,
    0x9,
    0x13,
    0x1F,
    0x28,
    0x1B,
    0x16,
    0x17,
    0x19,
    0xD,
    0x6,
    0xB,
    0x27,
    0x12,
    0x14,
    0x8,
    0xE,
    0x15,
    0x20,
    0x1A,
    0x2,
    0x1E,
    0x7,
    0x4,
    0x11,
    0x5,
    0x3,
    0x1C,
    0x22,
    0x25,
    0xC,
    0x24,
]


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_number(value: str | None) -> float | None:
    return to_float((value or "").replace(",", ""))


def parse_cn_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.replace(" ", "")
    slash = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
    if slash:
        return f"{slash.group(1)}-{int(slash.group(2)):02d}-{int(slash.group(3)):02d}"
    cn = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if cn:
        return f"{cn.group(1)}-{int(cn.group(2)):02d}-{int(cn.group(3)):02d}"
    iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso:
        return f"{iso.group(1)}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
    return None


def parse_item_date(item: Dict[str, Any]) -> str:
    return str(item.get("time") or item.get("date") or "")[:10]


def compute_sse_acw_cookie(arg1: str) -> str:
    output = [""] * len(SSE_ACW_POS)
    for idx, char in enumerate(arg1):
        for pos_idx, pos in enumerate(SSE_ACW_POS):
            if pos == idx + 1:
                output[pos_idx] = char
                break
    arg2 = "".join(output)
    cookie = ""
    for idx in range(0, min(len(arg2), len(SSE_ACW_MASK)), 2):
        xor_char = int(arg2[idx : idx + 2], 16) ^ int(SSE_ACW_MASK[idx : idx + 2], 16)
        cookie += f"{xor_char:02x}"
    return cookie


def extract_sse_acw_cookie(html_text: str) -> str | None:
    match = re.search(r"var arg1='([^']+)'", html_text or "")
    if not match:
        return None
    return compute_sse_acw_cookie(match.group(1))


def download_pdf_bytes(url: str, timeout: int = 12) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": SSE_REFERER,
        "Accept": "application/pdf,application/octet-stream,*/*",
    }
    resp = PDF_SESSION.get(url, headers=headers, timeout=(5, timeout), allow_redirects=True)
    resp.raise_for_status()
    if resp.content.startswith(b"%PDF"):
        return resp.content
    cookie = extract_sse_acw_cookie(resp.text if "text" in resp.headers.get("content-type", "") else resp.content.decode("utf-8", "ignore"))
    if cookie:
        headers["Cookie"] = f"acw_sc__v2={cookie}"
        resp = PDF_SESSION.get(resp.url, headers=headers, timeout=(5, timeout), allow_redirects=True)
        resp.raise_for_status()
        if resp.content.startswith(b"%PDF"):
            return resp.content
    raise ValueError("SSE PDF download did not return PDF bytes")


def fetch_pdf_text(url: str) -> str:
    content = download_pdf_bytes(url)
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return compact_text(text)


def regex_last_number(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, flags=re.S)
    if not matches:
        return None
    value = matches[-1]
    if isinstance(value, tuple):
        value = next((part for part in reversed(value) if part), "")
    return normalize_number(str(value))


def parse_dividend_record(item: Dict[str, Any], text: str) -> Dict[str, Any]:
    title = item.get("title") or ""
    clean = compact_text(text)
    per_share = regex_last_number(r"每股(?:拟)?派发\s*现金红利\s*([0-9,.]+)\s*元", clean)
    total_yuan = regex_last_number(r"(?:合计拟派发现金红利|共计派发现金红利)\s*([0-9,.]+)\s*元", clean)
    approved_date = parse_cn_date((re.search(r"股东会召开的时间[:：]?\s*([0-9 年月日/-]+)", clean) or [None, None])[1])
    if not approved_date and "股东会决议" in title:
        approved_date = parse_cn_date(parse_item_date(item))

    record_date = parse_cn_date((re.search(r"股权登记日[:：]?\s*([0-9 年月日/-]+)", clean) or [None, None])[1])
    ex_date = parse_cn_date((re.search(r"(?:除权（息）日|除权除息日)[:：]?\s*([0-9 年月日/-]+)", clean) or [None, None])[1])
    payment_date = parse_cn_date((re.search(r"现金红利发放日[:：]?\s*([0-9 年月日/-]+)", clean) or [None, None])[1])

    if "实施公告" in title or record_date or ex_date or payment_date:
        status = "实施公告已披露"
    elif "股东会决议" in title or "审议结果：通过" in clean or "审议结果:通过" in clean:
        status = "股东会已通过，待权益分派实施公告确认日期"
    elif "调整" in title:
        status = "每股分红金额已调整，待股东会/实施公告确认"
    else:
        status = "利润分配方案已披露，待后续审议或实施公告"

    per_10 = round(per_share * 10, 5) if per_share is not None else None
    total_yi = round_or_none(yuan_to_yi(total_yuan), 2)
    timing = (
        f"股权登记日{record_date or '待确认'}，除权除息日{ex_date or '待确认'}，现金红利发放日{payment_date or '待确认'}"
    )
    action = (
        "处理动作：持股至股权登记日可享有本次现金分红，除权除息日核对除权影响和税后现金到账。"
        if record_date and ex_date and payment_date
        else "处理动作：分红金额已明确，等待权益分派实施公告确认股权登记日、除权除息日和现金红利发放日。"
    )
    amount_line = (
        f"每股现金红利{per_share:.5f}元（含税，约每10股{per_10:.5f}元）"
        if per_share is not None and per_10 is not None
        else "每股现金红利待确认"
    )
    total_line = f"，合计约{total_yi:.2f}亿元" if total_yi is not None else ""
    approved_line = f"，股东会{approved_date}通过" if approved_date else ""

    return {
        "type": "dividend",
        "title": title,
        "date": parse_item_date(item),
        "url": item.get("url") or "",
        "cash_dividend_per_share": per_share,
        "cash_dividend_per_10_shares": per_10,
        "total_cash_dividend_yi": total_yi,
        "approved_date": approved_date,
        "record_date": record_date,
        "ex_dividend_date": ex_date,
        "cash_payment_date": payment_date,
        "status": status,
        "action": action,
        "line": f"2025年度分红：{amount_line}{total_line}{approved_line}；{timing}；{action}",
    }


def parse_buyback_record(item: Dict[str, Any], text: str) -> Dict[str, Any]:
    clean = compact_text(text)
    actual_shares = regex_last_number(r"实际回购股数\s*([0-9,]+)\s*股", clean) or regex_last_number(
        r"实际回购公司股份\s*([0-9,]+)\s*股", clean
    )
    actual_amount_yuan = regex_last_number(r"实际回购金额\s*([0-9,.]+)\s*元", clean) or regex_last_number(
        r"使用资金总额\s*([0-9,.]+)\s*元", clean
    )
    interval = re.search(r"实际回购价格区间\s*([0-9,.]+)\s*元/股\s*[～~-]\s*([0-9,.]+)\s*元/股", clean)
    high_low_avg = re.search(
        r"回购最高价格\s*([0-9,.]+)\s*元/股.*?回购最低价格\s*([0-9,.]+)\s*元/股.*?回购均价\s*([0-9,.]+)\s*元/股",
        clean,
        flags=re.S,
    )
    price_low = normalize_number(interval.group(1)) if interval else None
    price_high = normalize_number(interval.group(2)) if interval else None
    average_price = None
    if high_low_avg:
        price_high = normalize_number(high_low_avg.group(1)) or price_high
        price_low = normalize_number(high_low_avg.group(2)) or price_low
        average_price = normalize_number(high_low_avg.group(3))

    completion_date = parse_cn_date((re.search(r"([0-9 年月日/-]+)，公司回购股份实施完成", clean) or [None, None])[1])
    cancel_date = parse_cn_date((re.search(r"预计公司将于\s*([0-9 年月日/-]+).*?注销", clean) or [None, None])[1])
    price_cap = regex_last_number(r"回购价格上限\s*([0-9,.]+)\s*元/股", clean)
    actual_amount_yi = round_or_none(yuan_to_yi(actual_amount_yuan), 2)
    shares_wan = round_or_none((actual_shares or 0) / 10000, 2) if actual_shares is not None else None

    price_line = ""
    if price_low is not None and price_high is not None:
        price_line = f"，价格区间{price_low:.2f}-{price_high:.2f}元/股"
    if average_price is not None:
        price_line += f"，均价{average_price:.2f}元/股"
    cap_line = f"，回购价格上限{price_cap:.2f}元/股" if price_cap is not None else ""
    amount_line = (
        f"实际回购{shares_wan:.2f}万股/{actual_amount_yi:.2f}亿元" if shares_wan is not None and actual_amount_yi is not None else "实际回购情况待确认"
    )
    time_line = f"{completion_date or parse_item_date(item)}实施完成"
    cancel_line = f"，{cancel_date}注销并减少注册资本" if cancel_date else "，全部用于注销并减少注册资本"
    action = "处理动作：回购已完成，不再作为未来增量买盘；注销减少股本，需结合每股分红和每股收益摊薄/增厚影响跟踪。"

    return {
        "type": "buyback",
        "title": item.get("title") or "",
        "date": parse_item_date(item),
        "url": item.get("url") or "",
        "actual_shares": int(actual_shares) if actual_shares is not None else None,
        "actual_shares_wan": shares_wan,
        "actual_amount_yi": actual_amount_yi,
        "price_low": price_low,
        "price_high": price_high,
        "average_price": average_price,
        "price_cap": price_cap,
        "completion_date": completion_date,
        "cancel_date": cancel_date,
        "action": action,
        "line": f"回购：{time_line}，{amount_line}{price_line}{cap_line}{cancel_line}；{action}",
    }


def report_kind(title: str) -> str:
    if "第一季度" in title:
        return "一季报"
    if "半年度" in title:
        return "半年报"
    if "第三季度" in title:
        return "三季报"
    if "年度报告" in title:
        return "年报"
    return "定期报告"


def is_earnings_report(item: Dict[str, Any]) -> bool:
    title = item.get("title") or ""
    if any(skip in title for skip in ["摘要", "英文版"]):
        return False
    return any(keyword in title for keyword in ["年度报告", "第一季度报告", "半年度报告", "第三季度报告"])


def days_between(left: str, right: str) -> int | None:
    try:
        return (datetime.strptime(left, "%Y-%m-%d").date() - datetime.strptime(right, "%Y-%m-%d").date()).days
    except Exception:
        return None


def extract_financial_metrics(text: str) -> Dict[str, Any]:
    clean = compact_text(text)
    metrics: Dict[str, Any] = {}

    patterns = {
        "revenue": r"营业收入\s+([0-9,.]+)\s+[0-9,.]+\s+(-?[0-9.]+)",
        "net_profit": r"归属于上市公司股东的净利润\s+([0-9,.]+)\s+[0-9,.]+\s+(-?[0-9.]+)",
        "operating_cash_flow": r"经营活动产生的现金流量净额\s+([0-9,.]+)\s+[0-9,.]+\s+(-?[0-9.]+)",
        "eps": r"基本每股收益（元/股）\s+([0-9,.]+)\s+[0-9,.]+\s+(-?[0-9.]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, clean)
        if not match:
            continue
        value = normalize_number(match.group(1))
        yoy = normalize_number(match.group(2))
        if key == "eps":
            metrics[f"{key}"] = value
        else:
            metrics[f"{key}_yi"] = round_or_none(yuan_to_yi(value), 2)
        metrics[f"{key}_yoy_pct"] = yoy

    sales_match = re.search(
        r"主营业务收入\s+([0-9,.]+)\s+([0-9,.]+)\s+([0-9,.]+)\s+([0-9,.]+)\s+([0-9,.]+)\s+([0-9,.]+)",
        clean,
    )
    if sales_match:
        labels = ["moutai_liquor", "series_liquor", "direct_sales", "wholesale", "domestic", "overseas"]
        for idx, label in enumerate(labels, 1):
            # 报告口径为万元，换算为亿元。
            metrics[f"{label}_revenue_yi"] = round_or_none((normalize_number(sales_match.group(idx)) or 0) / 10000, 2)

    i_moutai = re.search(r"i\s*茅台.*?收入\s*([0-9,.]+)\s*万元", clean, flags=re.I)
    if i_moutai:
        metrics["i_moutai_revenue_yi"] = round_or_none((normalize_number(i_moutai.group(1)) or 0) / 10000, 2)

    return metrics


def parse_earnings_report(
    item: Dict[str, Any],
    text: str,
    target_date: str,
    trigger_window_days: int = 2,
) -> Dict[str, Any]:
    date = parse_item_date(item)
    delta = days_between(target_date, date)
    deep_ready = delta is not None and 0 <= delta <= trigger_window_days
    kind = report_kind(item.get("title") or "")
    return {
        "type": "earnings_report",
        "kind": kind,
        "title": item.get("title") or "",
        "date": date,
        "url": item.get("url") or "",
        "deep_analysis_ready": deep_ready,
        "metrics": extract_financial_metrics(text),
    }


def next_report_watch_line(latest_report: Dict[str, Any] | None, target_date: str) -> str:
    year = target_date[:4]
    if not latest_report:
        return f"财报节奏：尚未抓到{year}年定期报告，需继续跟踪上交所定期报告公告和预约披露页面。"
    kind = latest_report.get("kind")
    title = latest_report.get("title")
    date = latest_report.get("date")
    if kind == "一季报":
        next_hint = f"{year}年半年度报告"
        deadline = f"{year}-08-31前"
    elif kind == "半年报":
        next_hint = f"{year}年第三季度报告"
        deadline = f"{year}-10-31前"
    elif kind == "三季报":
        next_hint = f"{year}年年度报告"
        deadline = f"{int(year) + 1}-04-30前"
    else:
        next_hint = f"{year}年第一季度报告"
        deadline = f"{year}-04-30前"
    return (
        f"财报节奏：最新定期报告为{date}披露的《{title}》；下一重点关注{next_hint}"
        f"（法定披露期限通常为{deadline}，官方预约披露日待交易所页面确认）。"
    )


def relevant_announcement(item: Dict[str, Any]) -> bool:
    title = item.get("title") or ""
    return any(keyword in title for keyword in ["利润分配", "分红", "权益分派", "股东会决议", "回购股份", "年度报告", "季度报告", "半年度报告"])


def select_relevant_announcements(announcements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []

    for item in announcements:
        title = item.get("title") or ""
        if any(keyword in title for keyword in ["权益分派实施", "股东会决议", "调整2025年年度利润分配", "利润分配方案及"]):
            selected.append(item)

    buybacks = [item for item in announcements if "回购股份" in (item.get("title") or "")]
    buybacks.sort(
        key=lambda item: (
            1 if "实施结果" in (item.get("title") or "") else 0,
            item.get("time") or "",
        ),
        reverse=True,
    )
    if buybacks:
        selected.append(buybacks[0])

    reports = [item for item in announcements if is_earnings_report(item)]
    reports.sort(key=lambda item: item.get("time") or "", reverse=True)
    if reports:
        selected.append(reports[0])

    deduped = []
    seen = set()
    for item in selected:
        key = item.get("url") or item.get("title")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def choose_best_dividend(records: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    if not records:
        return None
    def score(record: Dict[str, Any]) -> tuple[int, str]:
        status = record.get("status") or ""
        if "实施公告" in status:
            rank = 3
        elif "股东会已通过" in status:
            rank = 2
        elif "调整" in status:
            rank = 1
        else:
            rank = 0
        return rank, record.get("date") or ""

    return sorted(records, key=score, reverse=True)[0]


def build_corporate_actions_payload(
    symbol: str,
    name: str,
    target_date: str,
    trigger_window_days: int = 2,
) -> Dict[str, Any]:
    start_date = f"{target_date[:4]}-01-01"
    errors: List[str] = []
    source_status: List[Dict[str, Any]] = []
    texts: Dict[str, str] = {}
    announcements: List[Dict[str, Any]] = []
    try:
        announcements = fetch_sse_announcements(symbol, start_date, target_date, max_items=200)
        source_status.append(
            {
                "source": SOURCE_NAME,
                "category": "official",
                "method": "official_json",
                "status": "ok",
                "detail": f"获取 {len(announcements)} 条 {symbol} 年内公告。",
            }
        )
    except Exception as exc:
        errors.append(f"{SOURCE_NAME} 公告列表: {type(exc).__name__}: {exc}")
        source_status.append(
            {
                "source": SOURCE_NAME,
                "category": "official",
                "method": "official_json",
                "status": "failed",
                "detail": f"公告列表请求失败：{type(exc).__name__}",
            }
        )

    dividend_records: List[Dict[str, Any]] = []
    buyback_records: List[Dict[str, Any]] = []
    earnings_reports: List[Dict[str, Any]] = []

    for item in select_relevant_announcements(announcements):
        url = item.get("url") or ""
        try:
            text = fetch_pdf_text(url)
            texts[url] = text
            source_status.append(
                {
                    "source": SOURCE_NAME,
                    "category": "official",
                    "method": "pdf_text",
                    "status": "ok",
                    "detail": f"解析公告 PDF：{item.get('title')}",
                }
            )
        except Exception as exc:
            errors.append(f"{item.get('title')}: {type(exc).__name__}: {exc}")
            source_status.append(
                {
                    "source": SOURCE_NAME,
                    "category": "official",
                    "method": "pdf_text",
                    "status": "failed",
                    "detail": f"公告 PDF 解析失败：{item.get('title')}",
                }
            )
            continue

        title = item.get("title") or ""
        if any(keyword in title for keyword in ["利润分配", "分红", "权益分派", "股东会决议"]):
            record = parse_dividend_record(item, text)
            if record.get("cash_dividend_per_share") is not None or "利润分配" in title:
                dividend_records.append(record)
        if "回购股份" in title:
            buyback_records.append(parse_buyback_record(item, text))
        if is_earnings_report(item):
            earnings_reports.append(parse_earnings_report(item, text, target_date, trigger_window_days=trigger_window_days))

    dividend = choose_best_dividend(dividend_records) or {}
    buyback = sorted(buyback_records, key=lambda item: item.get("date") or "", reverse=True)[0] if buyback_records else {}
    latest_report = sorted(earnings_reports, key=lambda item: item.get("date") or "", reverse=True)[0] if earnings_reports else None
    earnings = {
        "latest_report": latest_report or {},
        "reports": earnings_reports,
        "line": next_report_watch_line(latest_report, target_date),
    }

    item_count = len([item for item in [dividend, buyback, latest_report] if item])
    quality_level = "ok" if item_count else "empty"
    return {
        "generated_at": now_iso(),
        "target_date": target_date,
        "symbol": symbol,
        "name": name,
        "dividend": dividend,
        "buyback": buyback,
        "earnings": earnings,
        "sources": [SOURCE_NAME],
        "source_status": source_status,
        "errors": errors,
        "quality": {
            "level": quality_level,
            "source_mode": "sse_announcements_pdf",
            "summary": f"公司行动数据可用，提取分红/回购/财报记录 {item_count} 类。" if item_count else "公司行动数据暂缺。",
            "target_date": target_date,
            "item_count": item_count,
        },
        "papale_improvements": [
            {
                "type": "site_pattern",
                "detail": "上交所静态 PDF 可能先返回 acw_sc__v2 JavaScript 校验页；可从 arg1 按固定 posList/mask 计算 cookie 后重试 static.sse.com.cn PDF。",
                "reuse_scope": "sse.com.cn announcement PDF crawling",
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--trigger-window-days", type=int, default=2)
    args = parser.parse_args()

    config = load_yaml(args.config)
    primary = config.get("primary_stock") or {}
    payload = build_corporate_actions_payload(
        symbol=str(primary.get("symbol") or "600519"),
        name=str(primary.get("name") or "贵州茅台"),
        target_date=args.date,
        trigger_window_days=args.trigger_window_days,
    )
    write_json(args.out, payload)


if __name__ == "__main__":
    main()
