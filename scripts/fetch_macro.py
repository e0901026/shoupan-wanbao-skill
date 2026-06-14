from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from common import now_iso, write_json
from fetch_news import enrich_news_item


FED_H15_URL = "https://www.federalreserve.gov/releases/h15/"
FED_FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_RELEASE_SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/current_year.asp"
BLS_EMPLOYMENT_SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/empsit.htm"
BLS_CPI_URL = "https://www.bls.gov/news.release/cpi.nr0.htm"
BEA_PCE_URL = "https://www.bea.gov/data/personal-consumption-expenditures-price-index"

FOMC_2026_MEETINGS = [
    ("2026-01-27", "2026-01-28"),
    ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"),
    ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"),
    ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"),
    ("2026-12-08", "2026-12-09"),
]

MACRO_EVENT_CALENDAR_2026 = [
    {
        "date": "2026-06-25",
        "name": "美国5月PCE / 个人收入与支出",
        "source": "U.S. Bureau of Economic Analysis",
        "url": BEA_PCE_URL,
        "why": "PCE 是美联储最关注的通胀指标之一，会影响降息、加息或维持高利率预期。",
    },
    {
        "date": "2026-07-02",
        "name": "美国6月非农就业",
        "source": "Bureau of Labor Statistics",
        "url": BLS_EMPLOYMENT_SCHEDULE_URL,
        "why": "非农会改变市场对就业韧性、工资通胀和联储利率路径的判断。",
    },
    {
        "date": "2026-07-14",
        "name": "美国6月CPI",
        "source": "Bureau of Labor Statistics",
        "url": BLS_CPI_URL,
        "why": "CPI 会直接影响通胀预期、美债收益率和权益资产估值折现率。",
    },
    {
        "date": "2026-07-15",
        "name": "美国6月PPI",
        "source": "Bureau of Labor Statistics",
        "url": BLS_RELEASE_SCHEDULE_URL,
        "why": "PPI 影响成本通胀预期，并可能通过美债利率传导到全球风险偏好。",
    },
]


def parse_float(value: str) -> float | None:
    value = value.strip()
    if not value or value == "n.a.":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_h15_html(html_text: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError("H.15 table not found")

    rows = [
        [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        for tr in table.find_all("tr")
    ]
    header = rows[0]
    dates = header[1:]
    latest_date = dates[-1] if dates else "暂缺"
    data: Dict[str, Any] = {
        "latest_date": latest_date,
        "source_url": FED_H15_URL,
    }
    in_treasury_nominal = False
    for cells in rows[1:]:
        if not cells:
            continue
        name = cells[0]
        values = [parse_float(value) for value in cells[1:]]
        latest = values[-1] if values else None
        previous = next((value for value in reversed(values[:-1]) if value is not None), None)
        if name.startswith("Federal funds"):
            data["effective_federal_funds_rate"] = latest
        elif name == "Treasury constant maturities":
            in_treasury_nominal = True
        elif in_treasury_nominal and name.startswith("Inflation indexed"):
            in_treasury_nominal = False
        elif in_treasury_nominal and name in {"2-year", "10-year", "30-year"}:
            key = name.replace("-", "y_").replace("year", "year")
            data[f"treasury_{key}"] = latest
            if previous is not None and latest is not None:
                data[f"treasury_{key}_change_bp"] = round((latest - previous) * 100, 1)
    return data


def next_fomc_meeting(target_date: str | None) -> Dict[str, str] | None:
    if not target_date:
        return None
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    for start, end in FOMC_2026_MEETINGS:
        start_dt = datetime.strptime(start, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end, "%Y-%m-%d").date()
        if target <= end_dt:
            return {"start": start, "end": end}
    return None


def upcoming_macro_events(target_date: str | None, horizon_days: int = 45) -> List[Dict[str, str]]:
    if not target_date:
        return []
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    out = []
    for event in MACRO_EVENT_CALENDAR_2026:
        event_dt = datetime.strptime(event["date"], "%Y-%m-%d").date()
        delta = (event_dt - target).days
        if 0 < delta <= horizon_days:
            out.append(event)
    return out


def fmt_percent(value: Any) -> str:
    if value is None:
        return "暂缺"
    return f"{float(value):.2f}%"


def fmt_bp(value: Any) -> str:
    if value is None:
        return "暂缺"
    sign = "+" if float(value) > 0 else ""
    return f"{sign}{float(value):.1f}bp"


def build_macro_items(h15: Dict[str, Any], target_date: str | None) -> List[Dict[str, Any]]:
    meeting = next_fomc_meeting(target_date)
    latest_date = h15.get("latest_date") or "暂缺"
    event_date = target_date or latest_date
    meeting_text = (
        f"下一次 FOMC 为 {meeting['start']} 至 {meeting['end']}。"
        if meeting
        else "下一次 FOMC 日期暂缺。"
    )
    effr = fmt_percent(h15.get("effective_federal_funds_rate"))
    ten_year = fmt_percent(h15.get("treasury_10y_year"))
    ten_year_change = fmt_bp(h15.get("treasury_10y_year_change_bp"))
    two_year = fmt_percent(h15.get("treasury_2y_year"))
    thirty_year = fmt_percent(h15.get("treasury_30y_year"))

    rate_path_summary = (
        f"截至 {event_date} 可见的官方 H.15 最新日度数据为 {latest_date}："
        f"有效联邦基金利率 {effr}，{meeting_text}"
        "6 月会议前应跟踪加息/维持高利率预期，而不是把它写成已加息。"
    )
    treasury_summary = (
        f"美国 10 年期国债收益率 {ten_year}，较上一观察日 {ten_year_change}；"
        f"2 年期 {two_year}，30 年期 {thirty_year}。"
        "10 年美债仍是消费龙头估值折现率和全球风险偏好的核心监控项。"
    )

    items = [
        enrich_news_item(
            {
                "title": "美联储利率路径观察：6月FOMC前关注加息/高利率预期",
                "source": "Federal Reserve H.15 / FOMC Calendar",
                "time": event_date,
                "url": FED_FOMC_CALENDAR_URL,
                "category": "宏观与风险事件",
                "summary": rate_path_summary,
                "impact_direction": "待观察",
                "impact_targets": ["A股市场", "全球市场"],
                "impact_period": "短期（1-5天）",
                "importance": "高",
            }
        )
    ]

    if h15.get("treasury_10y_year") is not None:
        items.append(
            enrich_news_item(
                {
                    "title": "美国10年期国债收益率处于高位，估值折现率压力需跟踪",
                    "source": "Federal Reserve H.15",
                    "time": event_date,
                    "url": FED_H15_URL,
                    "category": "宏观与风险事件",
                    "summary": treasury_summary,
                    "impact_direction": "利空",
                    "impact_targets": ["A股市场", "全球市场"],
                    "impact_period": "中期（1-3个月）",
                    "importance": "高",
                }
            )
        )

    future_events = upcoming_macro_events(target_date)
    if future_events:
        event_text = "；".join(f"{event['date']} {event['name']}（{event['why']}）" for event in future_events)
        items.append(
            enrich_news_item(
                {
                    "title": "未来宏观数据窗口：PCE、非农、CPI/PPI将影响资金流向",
                    "source": "Federal Reserve / BLS / BEA",
                    "time": event_date,
                    "url": BLS_RELEASE_SCHEDULE_URL,
                    "category": "宏观与风险事件",
                    "summary": f"未来 45 天需前瞻跟踪：{event_text}。这些事件即使尚未发生，也会提前影响美债收益率、美元、风险偏好和A股资金流向。",
                    "impact_direction": "待观察",
                    "impact_targets": ["A股市场", "全球市场"],
                    "impact_period": "中期（1-3个月）",
                    "importance": "高",
                }
            )
        )

    return items


def fetch_h15() -> Dict[str, Any]:
    resp = requests.get(FED_H15_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    return parse_h15_html(resp.text)


def build_quality(items: List[Dict[str, Any]], errors: List[str]) -> Dict[str, Any]:
    if items:
        return {
            "level": "ok",
            "source_mode": "federal_reserve_h15",
            "summary": f"宏观利率与未来事件数据可用，已生成 {len(items)} 条美联储/美债/数据窗口事件。",
            "item_count": len(items),
        }
    return {
        "level": "empty",
        "source_mode": "none",
        "summary": "宏观利率数据暂缺；官方源未返回可解析数据。",
        "item_count": 0,
        "error_count": len(errors),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format.")
    args = parser.parse_args()

    errors: List[str] = []
    h15: Dict[str, Any] = {}
    items: List[Dict[str, Any]] = []
    sources: List[str] = []
    try:
        h15 = fetch_h15()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"federal reserve h15 failed: {exc}")
    items = build_macro_items(h15, args.date)
    if h15:
        sources.extend(["Federal Reserve H.15"])
    if any("FOMC" in item.get("title", "") for item in items):
        sources.append("Federal Reserve FOMC Calendar")
    if any("未来宏观数据窗口" in item.get("title", "") for item in items):
        sources.extend(["Bureau of Labor Statistics", "U.S. Bureau of Economic Analysis"])
    sources = list(dict.fromkeys(sources))

    write_json(
        args.out,
        {
            "generated_at": now_iso(),
            "sources": sources,
            "errors": errors,
            "quality": build_quality(items, errors),
            "h15": h15,
            "items": items,
        },
    )


if __name__ == "__main__":
    main()
