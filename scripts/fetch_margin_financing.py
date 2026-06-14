from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from typing import Any, Dict, List

import requests

from common import load_yaml, now_iso, round_or_none, to_float, write_json, yuan_to_yi


SSE_MARGIN_DETAIL_URL = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
SOURCE_NAME = "上交所融资融券明细"


def date_compact(date_text: str) -> str:
    return date_text.replace("-", "")


def date_display(date_text: str) -> str:
    if len(date_text) == 8 and date_text.isdigit():
        return f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
    return date_text


def previous_calendar_dates(target_date: str, max_lookback_days: int) -> List[str]:
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    return [(target - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(max_lookback_days)]


def fetch_sse_margin_detail(date: str, symbol: str = "", timeout: int = 12) -> Dict[str, Any]:
    params = {
        "isPagination": "true",
        "tabType": "mxtype",
        "detailsDate": date,
        "stockCode": symbol,
        "beginDate": "",
        "endDate": "",
        "pageHelp.pageSize": "50",
        "pageHelp.pageCount": "50",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
    }
    headers = {
        "Referer": "https://www.sse.com.cn/market/othersdata/margin/detail/",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
    }
    resp = requests.get(SSE_MARGIN_DETAIL_URL, params=params, headers=headers, timeout=(5, timeout))
    resp.raise_for_status()
    return resp.json()


def parse_sse_margin_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(payload.get("result") or [])


def row_for_symbol(rows: List[Dict[str, Any]], symbol: str) -> Dict[str, Any] | None:
    wanted = symbol.zfill(6)
    for row in rows:
        code = str(row.get("stockCode") or "").zfill(6)
        if code == wanted:
            return row
    return None


def margin_item_from_row(row: Dict[str, Any], previous: Dict[str, Any] | None = None) -> Dict[str, Any]:
    financing_balance = to_float(row.get("rzye"))
    financing_buy = to_float(row.get("rzmre"))
    financing_repay = to_float(row.get("rzche"))
    short_balance = to_float(row.get("rqyl"))
    short_sell = to_float(row.get("rqmcl"))
    short_repay = to_float(row.get("rqchl"))

    previous_balance = to_float((previous or {}).get("rzye"))
    previous_short_balance = to_float((previous or {}).get("rqyl"))

    balance_change = None
    if financing_balance is not None and previous_balance is not None:
        balance_change = financing_balance - previous_balance
    short_balance_change = None
    if short_balance is not None and previous_short_balance is not None:
        short_balance_change = short_balance - previous_short_balance

    return {
        "date": date_display(str(row.get("opDate") or "")),
        "stock_code": str(row.get("stockCode") or "").zfill(6),
        "stock_name": row.get("securityAbbr") or "暂缺",
        "financing_balance_yi": round_or_none(yuan_to_yi(financing_balance), 2),
        "financing_buy_yi": round_or_none(yuan_to_yi(financing_buy), 2),
        "financing_repay_yi": round_or_none(yuan_to_yi(financing_repay), 2),
        "financing_net_buy_yi": round_or_none(yuan_to_yi((financing_buy or 0) - (financing_repay or 0)), 2)
        if financing_buy is not None and financing_repay is not None
        else None,
        "financing_balance_change_yi": round_or_none(yuan_to_yi(balance_change), 2),
        "short_balance_shares": int(short_balance) if short_balance is not None else None,
        "short_sell_shares": int(short_sell) if short_sell is not None else None,
        "short_repay_shares": int(short_repay) if short_repay is not None else None,
        "short_balance_change_shares": int(short_balance_change) if short_balance_change is not None else None,
    }


def build_margin_financing_payload(
    symbol: str,
    name: str,
    target_date: str,
    max_lookback_days: int = 10,
) -> Dict[str, Any]:
    errors: List[str] = []
    source_status: List[Dict[str, Any]] = []
    hits: List[Dict[str, Any]] = []

    for compact_date in previous_calendar_dates(target_date, max_lookback_days):
        try:
            rows = parse_sse_margin_rows(fetch_sse_margin_detail(compact_date, symbol=symbol))
        except Exception as exc:
            errors.append(f"{SOURCE_NAME} {date_display(compact_date)}: {type(exc).__name__}: {exc}")
            source_status.append(
                {
                    "source": SOURCE_NAME,
                    "category": "structured_data",
                    "method": "official_json",
                    "status": "failed",
                    "detail": f"{date_display(compact_date)} 请求失败：{type(exc).__name__}",
                }
            )
            continue

        row = row_for_symbol(rows, symbol)
        if row:
            hits.append(row)
            source_status.append(
                {
                    "source": SOURCE_NAME,
                    "category": "structured_data",
                    "method": "official_json",
                    "status": "ok",
                    "detail": f"{date_display(compact_date)} 获取到 {symbol} 融资融券明细。",
                }
            )
            if len(hits) >= 2:
                break
        else:
            source_status.append(
                {
                    "source": SOURCE_NAME,
                    "category": "structured_data",
                    "method": "official_json",
                    "status": "empty",
                    "detail": f"{date_display(compact_date)} 未找到 {symbol} 明细。",
                }
            )

    if not hits:
        return {
            "generated_at": now_iso(),
            "target_date": target_date,
            "symbol": symbol,
            "name": name,
            "item": {},
            "previous_item": {},
            "sources": [SOURCE_NAME],
            "source_status": source_status,
            "errors": errors,
            "quality": {
                "level": "empty",
                "source_mode": "sse_margin_detail",
                "summary": f"融资融券数据暂缺，近 {max_lookback_days} 个自然日未取到 {symbol} 明细。",
                "target_date": target_date,
            },
        }

    current_row = hits[0]
    previous_row = hits[1] if len(hits) > 1 else None
    item = margin_item_from_row(current_row, previous_row)
    previous_item = margin_item_from_row(previous_row) if previous_row else {}
    actual_date = item.get("date")
    previous_date = previous_item.get("date")
    level = "ok" if previous_row else "partial"
    summary = (
        f"融资融券数据可用，实际取数日 {actual_date}，上一交易日 {previous_date}。"
        if previous_row
        else f"融资融券数据可用，实际取数日 {actual_date}；上一交易日对比暂缺。"
    )

    return {
        "generated_at": now_iso(),
        "target_date": target_date,
        "actual_date": actual_date,
        "previous_date": previous_date,
        "symbol": symbol,
        "name": name,
        "item": item,
        "previous_item": previous_item,
        "sources": [SOURCE_NAME],
        "source_status": source_status,
        "errors": errors,
        "quality": {
            "level": level,
            "source_mode": "sse_margin_detail",
            "summary": summary,
            "target_date": target_date,
            "actual_date": actual_date,
            "previous_date": previous_date,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--symbol")
    parser.add_argument("--name")
    parser.add_argument("--max-lookback-days", type=int, default=10)
    args = parser.parse_args()

    config = load_yaml(args.config)
    primary = config.get("primary_stock") or {}
    symbol = args.symbol or str(primary.get("symbol") or "600519")
    name = args.name or str(primary.get("name") or "贵州茅台")
    payload = build_margin_financing_payload(symbol, name, args.date, max_lookback_days=args.max_lookback_days)
    write_json(args.out, payload)


if __name__ == "__main__":
    main()
