from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from common import ensure_required_fund_columns, load_yaml, market_session, now_iso, to_float, write_json

DEGRADED_THS_MISSING_FIELDS = ["超大单（亿）", "大单（亿）", "小单（亿）", "成交额（亿）", "净流入率 %"]
EASTMONEY_SECTOR_FS = {
    "industry": "m:90 s:4",
    "concept": "m:90 t:3",
}
EASTMONEY_CLIST_HOSTS = ["push2.eastmoney.com", "push2delay.eastmoney.com"]
EASTMONEY_PAGE_SIZE = 100


def eastmoney_yuan_to_yi(value: Any) -> float | None:
    n = to_float(value)
    if n is None:
        return None
    return round(n / 100000000, 2)


def eastmoney_timestamp(value: Any) -> tuple[str | None, str | None]:
    n = to_float(value)
    if n is None:
        return None, None
    try:
        dt = datetime.fromtimestamp(int(n))
    except (OSError, OverflowError, ValueError):
        return None, None
    return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%d")


def eastmoney_item_to_row(item: Dict[str, Any], label: str) -> Dict[str, Any]:
    data_time, data_date = eastmoney_timestamp(item.get("f124"))
    return {
        "板块": item.get("f14"),
        "净流入（亿）": eastmoney_yuan_to_yi(item.get("f62")),
        "超大单（亿）": eastmoney_yuan_to_yi(item.get("f66")),
        "大单（亿）": eastmoney_yuan_to_yi(item.get("f72")),
        "中单（亿）": eastmoney_yuan_to_yi(item.get("f78")),
        "小单（亿）": eastmoney_yuan_to_yi(item.get("f84")),
        "涨跌幅 %": item.get("f3"),
        "成交额（亿）": eastmoney_yuan_to_yi(item.get("f6")),
        "净流入率 %": item.get("f184"),
        "板块代码": item.get("f12"),
        "数据时间": data_time,
        "数据日期": data_date,
        "sector_type": label,
        "source": "eastmoney.push2.clist.sw2_fund_flow" if label == "industry" else "eastmoney.push2.clist.fund_flow",
    }


def collect_eastmoney_pages(fetch_page) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 1
    total: int | None = None
    while True:
        page_rows, page_total = fetch_page(page)
        if total is None and page_total:
            total = int(page_total)
        if not page_rows:
            break
        rows.extend(page_rows)
        if total is not None and len(rows) >= total:
            break
        page += 1
    return rows


def fetch_eastmoney_sector_page_once(fs: str, page: int) -> tuple[List[Dict[str, Any]], int | None]:
    params = {
        "pn": page,
        "pz": EASTMONEY_PAGE_SIZE,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f62",
        "fs": fs,
        "stat": "1",
        "fields": "f12,f14,f2,f3,f6,f62,f66,f72,f78,f84,f184,f124",
        "ut": "8dec03ba335b81bf4ebdf7b29ec27d15",
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/bkzj/"}
    last_exc: Exception | None = None
    for host in EASTMONEY_CLIST_HOSTS:
        url = f"https://{host}/api/qt/clist/get"
        try:
            resp = eastmoney_get(url, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    else:
        if last_exc:
            raise last_exc
        return [], None
    payload = data.get("data") or {}
    return payload.get("diff") or [], payload.get("total")


def eastmoney_get(url: str, **kwargs):
    return market_session().get(url, **kwargs)


def fetch_eastmoney_sector_page(fs: str, page: int, retries: int = 3) -> tuple[List[Dict[str, Any]], int | None]:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fetch_eastmoney_sector_page_once(fs, page)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
    if last_exc:
        raise last_exc
    return [], None


def fetch_eastmoney_sector(fs: str, label: str) -> List[Dict[str, Any]]:
    """抓东方财富板块资金流。

    常用 fs：
    - 申万二级行业板块：m:90 s:4
    - 概念板块：m:90+t:3

    该接口属于公开页面使用的数据接口，字段可能变化，生产前需实测。
    """
    diff = collect_eastmoney_pages(lambda page: fetch_eastmoney_sector_page(fs, page))
    return [eastmoney_item_to_row(item, label) for item in diff]


def configured_sector_types(config: Dict[str, Any]) -> List[str]:
    raw_types = config.get("fund_flow", {}).get("sector_types") or ["industry"]
    valid = []
    for sector_type in raw_types:
        if sector_type in {"industry", "concept"} and sector_type not in valid:
            valid.append(sector_type)
    return valid or ["industry"]


def fetch_akshare_sector(sector_types: List[str]) -> List[Dict[str, Any]]:
    import akshare as ak

    rows: List[Dict[str, Any]] = []
    akshare_types = []
    if "industry" in sector_types:
        akshare_types.append("行业资金流")
    if "concept" in sector_types:
        akshare_types.append("概念资金流")
    for sector_type in akshare_types:
        try:
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type=sector_type)
        except Exception:
            continue
        for r in df.to_dict(orient="records"):
            r["source"] = f"akshare.stock_sector_fund_flow_rank.{sector_type}"
            rows.append(r)
    return rows


def fetch_akshare_ths_sector(sector_types: List[str]) -> List[Dict[str, Any]]:
    import akshare as ak

    rows: List[Dict[str, Any]] = []
    fetchers = [
        ("industry", "akshare.stock_fund_flow_industry", lambda: ak.stock_fund_flow_industry(symbol="即时")),
        ("concept", "akshare.stock_fund_flow_concept", lambda: ak.stock_fund_flow_concept(symbol="即时")),
    ]
    for label, source, fetcher in [item for item in fetchers if item[0] in sector_types]:
        df = fetcher()
        for r in df.to_dict(orient="records"):
            rows.append(
            {
                "板块": r.get("行业"),
                "净流入（亿）": r.get("净额"),
                "超大单（亿）": None,
                "大单（亿）": None,
                "小单（亿）": None,
                "涨跌幅 %": r.get("行业-涨跌幅"),
                "成交额（亿）": None,
                    "净流入率 %": None,
                    "sector_type": label,
                    "source": source,
                }
            )
    return rows


def parse_ths_sector_rows(html: str, label: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.J-ajax-table")
    if table is None:
        return []
    source = "10jqka.funds.hyzjl" if label == "industry" else "10jqka.funds.gnzjl"
    rows: List[Dict[str, Any]] = []
    for tr in table.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(cells) < 7:
            continue
        rows.append(
            {
                "板块": cells[1],
                "净流入（亿）": to_float(cells[6]),
                "超大单（亿）": None,
                "大单（亿）": None,
                "小单（亿）": None,
                "涨跌幅 %": to_float(cells[3]),
                "成交额（亿）": None,
                "净流入率 %": None,
                "sector_type": label,
                "source": source,
            }
        )
    return rows


def compact_date(date_text: str) -> str:
    return date_text.replace("-", "")


def display_date(date_text: str) -> str:
    if len(date_text) == 8 and date_text.isdigit():
        return f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
    return date_text


def wan_to_yi(value: Any) -> float | None:
    n = to_float(value)
    if n is None:
        return None
    return round(n / 10000, 2)


def qian_yuan_to_yi(value: Any) -> float | None:
    n = to_float(value)
    if n is None:
        return None
    return round(n / 100000, 2)


def active_sw_member_rows(member_rows: List[Dict[str, Any]], trade_date: str) -> List[Dict[str, Any]]:
    target = compact_date(trade_date)
    active = []
    for row in member_rows:
        ts_code = row.get("ts_code")
        l2_code = row.get("l2_code")
        l2_name = row.get("l2_name")
        if not ts_code or not l2_code or not l2_name:
            continue
        in_date = str(row.get("in_date") or "00000000")
        out_date = str(row.get("out_date") or "99999999")
        if in_date <= target <= out_date:
            active.append(row)
    return active


def aggregate_tushare_sw2_moneyflow(
    moneyflow_rows: List[Dict[str, Any]],
    member_rows: List[Dict[str, Any]],
    daily_rows: List[Dict[str, Any]],
    trade_date: str,
) -> List[Dict[str, Any]]:
    import pandas as pd

    if not moneyflow_rows or not member_rows:
        return []
    moneyflow = pd.DataFrame(moneyflow_rows)
    members = pd.DataFrame(active_sw_member_rows(member_rows, trade_date))
    if moneyflow.empty or members.empty:
        return []
    daily = pd.DataFrame(daily_rows or [])

    members = members.drop_duplicates(subset=["ts_code"], keep="first")
    merged = moneyflow.merge(members[["ts_code", "l2_code", "l2_name"]], on="ts_code", how="inner")
    if daily.empty:
        merged["pct_chg"] = None
        merged["amount"] = None
    else:
        merged = merged.merge(daily[["ts_code", "pct_chg", "amount"]], on="ts_code", how="left")

    amount_cols = [
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "net_mf_amount",
        "amount",
        "pct_chg",
    ]
    for col in amount_cols:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)

    merged["小单净额_万元"] = merged["buy_sm_amount"] - merged["sell_sm_amount"]
    merged["中单净额_万元"] = merged["buy_md_amount"] - merged["sell_md_amount"]
    merged["大单净额_万元"] = merged["buy_lg_amount"] - merged["sell_lg_amount"]
    merged["超大单净额_万元"] = merged["buy_elg_amount"] - merged["sell_elg_amount"]
    merged["成交额_千元"] = merged["amount"]
    merged["涨跌幅加权分子"] = merged["pct_chg"] * merged["成交额_千元"]

    grouped = (
        merged.groupby(["l2_code", "l2_name"], as_index=False)
        .agg(
            净流入_万元=("net_mf_amount", "sum"),
            超大单_万元=("超大单净额_万元", "sum"),
            大单_万元=("大单净额_万元", "sum"),
            中单_万元=("中单净额_万元", "sum"),
            小单_万元=("小单净额_万元", "sum"),
            成交额_千元=("成交额_千元", "sum"),
            涨跌幅加权分子=("涨跌幅加权分子", "sum"),
            成分股数量=("ts_code", "nunique"),
        )
        .sort_values("净流入_万元", ascending=False)
    )

    rows: List[Dict[str, Any]] = []
    for item in grouped.to_dict(orient="records"):
        net_yi = wan_to_yi(item.get("净流入_万元"))
        amount_yi = qian_yuan_to_yi(item.get("成交额_千元"))
        pct = None
        amount_raw = to_float(item.get("成交额_千元"))
        pct_num = to_float(item.get("涨跌幅加权分子"))
        if amount_raw not in (None, 0) and pct_num is not None:
            pct = round(pct_num / amount_raw, 2)
        rate = None
        if net_yi is not None and amount_yi not in (None, 0):
            rate = round(net_yi / amount_yi * 100, 2)
        rows.append(
            {
                "板块": item.get("l2_name"),
                "净流入（亿）": net_yi,
                "超大单（亿）": wan_to_yi(item.get("超大单_万元")),
                "大单（亿）": wan_to_yi(item.get("大单_万元")),
                "中单（亿）": wan_to_yi(item.get("中单_万元")),
                "小单（亿）": wan_to_yi(item.get("小单_万元")),
                "涨跌幅 %": pct,
                "成交额（亿）": amount_yi,
                "净流入率 %": rate,
                "板块代码": item.get("l2_code"),
                "成分股数量": int(item.get("成分股数量") or 0),
                "数据日期": display_date(trade_date),
                "sector_type": "industry",
                "source": "tushare.moneyflow.sw2_aggregate",
            }
        )
    return rows


def ts_code_for_stock(stock: Dict[str, Any]) -> str:
    suffix = "SH" if stock.get("market") == "SH" else "SZ"
    return f"{stock['symbol']}.{suffix}"


def build_tushare_stock_moneyflow_row(
    stock: Dict[str, Any],
    moneyflow_row: Dict[str, Any],
    daily_row: Dict[str, Any] | None,
    trade_date: str,
) -> Dict[str, Any]:
    daily_row = daily_row or {}
    net_yi = wan_to_yi(moneyflow_row.get("net_mf_amount"))
    amount_yi = qian_yuan_to_yi(daily_row.get("amount"))
    rate = None
    if net_yi is not None and amount_yi not in (None, 0):
        rate = round(net_yi / amount_yi * 100, 2)
    return {
        "板块": stock.get("name") or stock.get("symbol"),
        "净流入（亿）": net_yi,
        "超大单（亿）": wan_to_yi((to_float(moneyflow_row.get("buy_elg_amount")) or 0) - (to_float(moneyflow_row.get("sell_elg_amount")) or 0)),
        "大单（亿）": wan_to_yi((to_float(moneyflow_row.get("buy_lg_amount")) or 0) - (to_float(moneyflow_row.get("sell_lg_amount")) or 0)),
        "中单（亿）": wan_to_yi((to_float(moneyflow_row.get("buy_md_amount")) or 0) - (to_float(moneyflow_row.get("sell_md_amount")) or 0)),
        "小单（亿）": wan_to_yi((to_float(moneyflow_row.get("buy_sm_amount")) or 0) - (to_float(moneyflow_row.get("sell_sm_amount")) or 0)),
        "涨跌幅 %": round(to_float(daily_row.get("pct_chg")) or 0, 2) if daily_row.get("pct_chg") is not None else None,
        "成交额（亿）": amount_yi,
        "净流入率 %": rate,
        "板块代码": ts_code_for_stock(stock),
        "数据日期": display_date(trade_date),
        "sector_type": "stock_as_sector",
        "source": "tushare.moneyflow.stock",
    }


def fetch_tushare_stock_moneyflow(trade_date: str, token: str, stock: Dict[str, Any]) -> List[Dict[str, Any]]:
    import tushare as ts

    compact = compact_date(trade_date)
    ts_code = ts_code_for_stock(stock)
    pro = ts.pro_api(token)
    moneyflow = pro.moneyflow(
        ts_code=ts_code,
        trade_date=compact,
        fields=(
            "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,"
            "buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount"
        ),
    )
    if moneyflow.empty:
        return []
    daily = pro.daily(ts_code=ts_code, trade_date=compact, fields="ts_code,trade_date,pct_chg,amount")
    daily_row = daily.to_dict(orient="records")[0] if not daily.empty else {}
    return [build_tushare_stock_moneyflow_row(stock, moneyflow.to_dict(orient="records")[0], daily_row, trade_date)]


def fetch_tushare_sw2_aggregate(trade_date: str, token: str) -> List[Dict[str, Any]]:
    import tushare as ts

    compact = compact_date(trade_date)
    pro = ts.pro_api(token)
    moneyflow = pro.moneyflow(
        trade_date=compact,
        fields=(
            "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,"
            "buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount"
        ),
    )
    daily = pro.daily(trade_date=compact, fields="ts_code,trade_date,pct_chg,amount")
    members = pro.index_member_all(fields="l2_code,l2_name,ts_code,in_date,out_date,is_new")
    return aggregate_tushare_sw2_moneyflow(
        moneyflow.to_dict(orient="records"),
        members.to_dict(orient="records"),
        daily.to_dict(orient="records"),
        trade_date,
    )


def fetch_ths_sector(sector_types: List[str]) -> List[Dict[str, Any]]:
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.10jqka.com.cn/"}
    rows: List[Dict[str, Any]] = []
    urls = [
        ("industry", "https://data.10jqka.com.cn/funds/hyzjl/"),
        ("concept", "https://data.10jqka.com.cn/funds/gnzjl/"),
    ]
    for label, url in [item for item in urls if item[0] in sector_types]:
        resp = market_session().get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        resp.encoding = "gbk"
        rows.extend(parse_ths_sector_rows(resp.text, label))
    return rows


def compact_supplement_items(rows: List[Dict[str, Any]], max_items: int = 20) -> List[Dict[str, Any]]:
    items = []
    for row in rows[:max_items]:
        items.append(
            {
                "板块": row.get("板块"),
                "净流入（亿）": row.get("净流入（亿）"),
                "涨跌幅 %": row.get("涨跌幅 %"),
                "source": row.get("source"),
            }
        )
    return items


def build_supplements(sector_types: List[str]) -> tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    coverage = []
    try:
        rows = fetch_akshare_ths_sector(sector_types)
        if rows:
            coverage.append(
                {
                    "source": sorted({row.get("source", "unknown") for row in rows})[0],
                    "row_count": len(rows),
                    "items": compact_supplement_items(rows),
                    "note": "同花顺/AkShare 行业资金作为覆盖补充，不参与完整字段资金表排序。",
                }
            )
            return {"coverage": coverage}, errors
    except Exception as exc:  # noqa: BLE001
        errors.append(f"akshare ths supplement failed: {exc}")
    try:
        rows = fetch_ths_sector(sector_types)
        if rows:
            coverage.append(
                {
                    "source": sorted({row.get("source", "unknown") for row in rows})[0],
                    "row_count": len(rows),
                    "items": compact_supplement_items(rows),
                    "note": "同花顺行业资金作为覆盖补充，不参与完整字段资金表排序。",
                }
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"10jqka supplement failed: {exc}")
    return {"coverage": coverage}, errors


def assess_fund_flow_quality(
    rows: List[Dict[str, Any]],
    sources: List[str],
    target_date: str | None = None,
    data_dates: List[str] | None = None,
) -> Dict[str, Any]:
    if not rows:
        return {
            "level": "empty",
            "source_mode": "none",
            "missing_fields": [],
            "summary": "板块资金流向未抓取到可用数据。",
            "target_date": target_date,
            "data_dates": data_dates or [],
        }

    clean_dates = sorted({date for date in (data_dates or []) if date})
    if target_date and not clean_dates:
        return {
            "level": "date_unknown",
            "source_mode": "missing_data_date",
            "missing_fields": [],
            "summary": "板块资金流数据未提供可校验的数据日期，不能用于指定日期正式发布。",
            "target_date": target_date,
            "data_dates": clean_dates,
        }
    if target_date and clean_dates != [target_date]:
        return {
            "level": "date_mismatch",
            "source_mode": "date_mismatch",
            "missing_fields": [],
            "summary": f"板块资金流数据日期与目标日期不一致：target={target_date}, data_dates={clean_dates}",
            "target_date": target_date,
            "data_dates": clean_dates,
        }

    missing_fields = [
        field
        for field in DEGRADED_THS_MISSING_FIELDS
        if any(row.get(field) is None for row in rows)
    ]
    degraded_sources = ("10jqka.", "akshare.stock_fund_flow_industry", "akshare.stock_fund_flow_concept")
    if any(source.startswith(degraded_sources) for source in sources):
        return {
            "level": "degraded",
            "source_mode": "ths_degraded",
            "missing_fields": missing_fields or DEGRADED_THS_MISSING_FIELDS,
            "summary": "同花顺降级源可提供板块净流入/净流出和涨跌幅，但不提供超大单、大单、小单、成交额、净流入率。",
            "target_date": target_date,
            "data_dates": clean_dates,
        }
    if missing_fields:
        return {
            "level": "partial",
            "source_mode": "partial_required_fields",
            "missing_fields": missing_fields,
            "summary": "板块资金流数据可用，但部分强制字段缺值。",
            "target_date": target_date,
            "data_dates": clean_dates,
        }
    if any("tushare.moneyflow.sw2_aggregate" in source for source in sources):
        return {
            "level": "complete",
            "source_mode": "tushare_sw2_stock_moneyflow_aggregate",
            "missing_fields": [],
            "summary": "申万二级行业资金流由 Tushare moneyflow 个股资金流按申万二级成分股聚合；Tushare 金额分档为小单<5万元、中单5-20万元、大单20-100万元、特大单/超大单>=100万元，基于主动买卖单统计；行业表按成分股档位净额加总。",
            "target_date": target_date,
            "data_dates": clean_dates,
        }
    return {
        "level": "complete",
        "source_mode": "eastmoney_sw2_full"
        if any("eastmoney.push2.clist.sw2_fund_flow" in source for source in sources)
        else ("eastmoney_full" if any("eastmoney" in source for source in sources) else "complete"),
        "missing_fields": [],
        "summary": "申万二级行业资金流数据包含净流入、超大单、大单、小单、涨跌幅、成交额、净流入率。",
        "target_date": target_date,
        "data_dates": clean_dates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", help="Expected fund-flow trading date in YYYY-MM-DD format.")
    args = parser.parse_args()

    config = load_yaml(args.config)
    sector_types = configured_sector_types(config)
    errors = []
    warnings = []
    raw_rows: List[Dict[str, Any]] = []
    raw_stock_rows: List[Dict[str, Any]] = []
    supplements: Dict[str, Any] = {"coverage": []}

    for label in sector_types:
        fs = EASTMONEY_SECTOR_FS[label]
        try:
            raw_rows.extend(fetch_eastmoney_sector(fs, label))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"eastmoney sector {label} failed: {exc}")

    if raw_rows and args.date:
        eastmoney_dates = sorted({r.get("数据日期") for r in raw_rows if r.get("数据日期")})
        if eastmoney_dates != [args.date]:
            warnings.append(f"eastmoney returned non-target-date data: target={args.date}, data_dates={eastmoney_dates or ['unknown']}")
            raw_rows = []

    if not raw_rows:
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if args.date and tushare_token and "industry" in sector_types:
            try:
                raw_rows.extend(fetch_tushare_sw2_aggregate(args.date, tushare_token))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"tushare sw2 aggregate failed: {exc}")
        elif args.date and "industry" in sector_types:
            errors.append("tushare sw2 aggregate skipped: TUSHARE_TOKEN not set")

    tushare_token = os.getenv("TUSHARE_TOKEN")
    primary_stock = config.get("primary_stock")
    if args.date and tushare_token and primary_stock:
        try:
            raw_stock_rows.extend(fetch_tushare_stock_moneyflow(args.date, tushare_token, primary_stock))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"tushare primary stock moneyflow failed: {exc}")
    elif args.date and primary_stock:
        warnings.append("tushare primary stock moneyflow skipped: TUSHARE_TOKEN not set")

    if not raw_rows:
        try:
            raw_rows.extend(fetch_akshare_sector(sector_types))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"akshare sector fund flow failed: {exc}")
        if not raw_rows:
            errors.append("akshare sector fund flow returned no rows")
            try:
                raw_rows.extend(fetch_akshare_ths_sector(sector_types))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"akshare ths sector fund flow failed: {exc}")
            try:
                if not raw_rows:
                    raw_rows.extend(fetch_ths_sector(sector_types))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"10jqka sector fund flow failed: {exc}")
            if raw_rows:
                warnings.append("10jqka fallback lacks 超大单（亿）, 大单（亿）, 成交额（亿）, 净流入率 %")

    supplement_errors: List[str] = []
    if raw_rows:
        supplements, supplement_errors = build_supplements(sector_types)
        if supplement_errors:
            warnings.extend(supplement_errors)

    normalized = ensure_required_fund_columns(raw_rows)
    normalized_stock_rows = ensure_required_fund_columns(raw_stock_rows)
    data_dates = sorted({r.get("数据日期") for r in raw_rows if r.get("数据日期")})
    sources = sorted({r.get("source", "unknown") for r in raw_rows})
    stock_sources = sorted({r.get("source", "unknown") for r in raw_stock_rows})
    payload = {
        "generated_at": now_iso(),
        "sources": sources,
        "stock_sources": stock_sources,
        "errors": errors,
        "warnings": warnings,
        "supplements": supplements,
        "target_date": args.date,
        "data_dates": data_dates,
        "quality": assess_fund_flow_quality(normalized, sources, target_date=args.date, data_dates=data_dates),
        "rows": normalized,
        "stock_rows": normalized_stock_rows,
    }
    write_json(args.out, payload)


if __name__ == "__main__":
    main()
