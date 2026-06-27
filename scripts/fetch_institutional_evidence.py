from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

try:
    import akshare as ak
except ImportError:  # pragma: no cover - dependency is optional at install time.
    ak = None  # type: ignore[assignment]

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:
    import tushare as ts
except ImportError:  # pragma: no cover
    ts = None  # type: ignore[assignment]


EASTMONEY_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
RELEVANT_ETF_PATTERN = re.compile(r"酒|食品|饮料|消费")


def ymd(value: str) -> str:
    return value.replace("-", "")


def iso(value: Any) -> str:
    text = str(value or "")
    return text[:10]


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def eastmoney_get(params: Dict[str, Any]) -> Dict[str, Any]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        }
    )
    response = session.get(EASTMONEY_API, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def source_status(source: str, category: str, method: str, status: str, detail: str) -> Dict[str, str]:
    return {"source": source, "category": category, "method": method, "status": status, "detail": detail}


def result_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ((payload.get("result") or {}).get("data") or []) if payload.get("success") else []


def fetch_block_trades(stock_code: str, start: str, end: str, statuses: List[Dict[str, str]]) -> Dict[str, Any]:
    params = {
        "reportName": "RPT_DATA_BLOCKTRADE",
        "columns": "ALL",
        "filter": f"(SECURITY_CODE=\"{stock_code}\")(TRADE_DATE>='{start}')(TRADE_DATE<='{end}')",
        "pageNumber": 1,
        "pageSize": 100,
        "sortColumns": "TRADE_DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        rows = result_rows(eastmoney_get(params))
    except Exception as exc:
        statuses.append(source_status("东方财富大宗交易", "structured_data", "datacenter api", "failed", str(exc)))
        return {"items": [], "summary": "大宗交易抓取失败。"}
    items = [
        {
            "trade_date": iso(row.get("TRADE_DATE")),
            "price": row.get("DEAL_PRICE"),
            "premium_ratio": row.get("PREMIUM_RATIO"),
            "volume": row.get("DEAL_VOLUME"),
            "amount_yuan": row.get("DEAL_AMT"),
            "buyer": row.get("BUYER_NAME"),
            "seller": row.get("SELLER_NAME"),
            "close_price": row.get("CLOSE_PRICE"),
        }
        for row in rows
    ]
    total_amount = sum(to_float(item.get("amount_yuan")) or 0 for item in items)
    statuses.append(source_status("东方财富大宗交易", "structured_data", "datacenter api", "ok" if items else "empty", f"{start} 至 {end} 获取 {len(items)} 笔。"))
    return {"items": items, "total_amount_yuan": total_amount, "summary": f"{len(items)} 笔，合计 {total_amount / 1e8:.2f} 亿元。"}


def fetch_lhb(stock_code: str, start: str, end: str, statuses: List[Dict[str, str]]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    token = os.environ.get("TUSHARE_TOKEN")
    if ts is not None and token:
        try:
            pro = ts.pro_api(token)
            for day in date_range_from_strings(start, end):
                df = pro.query("top_list", trade_date=ymd(day), ts_code=f"{stock_code}.SH")
                if df is not None and not df.empty:
                    items.extend(df.to_dict("records"))
            statuses.append(source_status("Tushare 龙虎榜", "structured_data", "tushare top_list", "ok" if items else "empty", f"{start} 至 {end} 获取 {len(items)} 条。"))
            return {"items": items, "summary": "本周龙虎榜有记录。" if items else "本周未上龙虎榜，无席位级别异动披露。"}
        except Exception as exc:
            statuses.append(source_status("Tushare 龙虎榜", "structured_data", "tushare top_list", "failed", str(exc)))
    try:
        rows = result_rows(
            eastmoney_get(
                {
                    "reportName": "RPT_LHB_BOARDDATE",
                    "columns": "SECURITY_CODE,TRADE_DATE,TR_DATE",
                    "filter": f"(SECURITY_CODE=\"{stock_code}\")",
                    "pageNumber": 1,
                    "pageSize": 1000,
                    "sortColumns": "TRADE_DATE",
                    "sortTypes": -1,
                    "source": "WEB",
                    "client": "WEB",
                }
            )
        )
        items = [row for row in rows if start <= iso(row.get("TRADE_DATE")) <= end]
        statuses.append(source_status("东方财富龙虎榜", "structured_data", "datacenter api", "ok" if items else "empty", f"{start} 至 {end} 获取 {len(items)} 条。"))
    except Exception as exc:
        statuses.append(source_status("东方财富龙虎榜", "structured_data", "datacenter api", "failed", str(exc)))
    return {"items": items, "summary": "本周龙虎榜有记录。" if items else "本周未上龙虎榜，无席位级别异动披露。"}


def date_range_from_strings(start: str, end: str) -> List[str]:
    if pd is None:
        return [start, end] if start != end else [start]
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start=start, end=end, freq="D")]


def fetch_northbound(stock_code: str, start: str, end: str, statuses: List[Dict[str, str]]) -> Dict[str, Any]:
    if ak is None or pd is None:
        statuses.append(source_status("AkShare 北向持股", "structured_data", "akshare", "failed", "akshare/pandas 不可用。"))
        return {"items": [], "summary": "北向持股暂缺。"}
    try:
        df = ak.stock_hsgt_individual_em(symbol=stock_code)
        df["持股日期"] = pd.to_datetime(df["持股日期"])
        latest = df["持股日期"].max().strftime("%Y-%m-%d") if not df.empty else ""
        sub = df[(df["持股日期"] >= pd.Timestamp(start)) & (df["持股日期"] <= pd.Timestamp(end))]
        if sub.empty:
            status = "failed" if latest and latest < end else "empty"
            detail = f"接口可访问，但 600519 最新可用日期为 {latest or '未知'}，无法验证 {start} 至 {end}。"
            statuses.append(source_status("东方财富/AkShare 北向持股", "structured_data", "akshare", status, detail))
            return {"items": [], "latest_available_date": latest, "summary": detail}
        items = sub.to_dict("records")
        statuses.append(source_status("东方财富/AkShare 北向持股", "structured_data", "akshare", "ok", f"{start} 至 {end} 获取 {len(items)} 条。"))
        return {"items": items, "latest_available_date": latest, "summary": f"获取 {len(items)} 日北向持股。"}
    except Exception as exc:
        statuses.append(source_status("东方财富/AkShare 北向持股", "structured_data", "akshare", "failed", str(exc)))
        return {"items": [], "summary": "北向持股抓取失败。"}


def fetch_sse_etf(start: str, end: str, statuses: List[Dict[str, str]]) -> Dict[str, Any]:
    if ak is None or pd is None:
        statuses.append(source_status("上交所 ETF 份额", "structured_data", "akshare", "failed", "akshare/pandas 不可用。"))
        return {"items": [], "summary": "ETF 份额暂缺。"}
    try:
        start_df = ak.fund_etf_scale_sse(date=ymd(start))
        end_df = ak.fund_etf_scale_sse(date=ymd(end))
        start_df["基金代码"] = start_df["基金代码"].astype(str)
        end_df["基金代码"] = end_df["基金代码"].astype(str)
        merged = start_df.merge(end_df, on="基金代码", suffixes=("_start", "_end"))
        mask = merged["基金简称_end"].astype(str).str.contains(RELEVANT_ETF_PATTERN, na=False)
        merged = merged[mask].copy()
        merged["share_change"] = merged["基金份额_end"].astype(float) - merged["基金份额_start"].astype(float)
        merged["share_change_pct"] = merged["share_change"] / merged["基金份额_start"].astype(float) * 100
        merged = merged.sort_values("share_change", ascending=True)
        items = [
            {
                "code": row["基金代码"],
                "name": row["基金简称_end"],
                "type": row.get("ETF类型_end"),
                "start_date": start,
                "end_date": end,
                "start_shares": row["基金份额_start"],
                "end_shares": row["基金份额_end"],
                "share_change": row["share_change"],
                "share_change_pct": row["share_change_pct"],
            }
            for _, row in merged.iterrows()
        ]
        statuses.append(source_status("上交所 ETF 份额", "structured_data", "akshare fund_etf_scale_sse", "ok" if items else "empty", f"{start} 至 {end} 获取 {len(items)} 只相关 ETF。"))
        return {"items": items, "summary": f"获取 {len(items)} 只消费/食品/酒相关上交所 ETF 份额变化。"}
    except Exception as exc:
        statuses.append(source_status("上交所 ETF 份额", "structured_data", "akshare fund_etf_scale_sse", "failed", str(exc)))
        return {"items": [], "summary": "ETF 份额抓取失败。"}


def fetch_fund_holdings(stock_code: str, statuses: List[Dict[str, str]]) -> Dict[str, Any]:
    if ak is None or pd is None:
        statuses.append(source_status("新浪财经基金持股", "structured_data", "akshare", "failed", "akshare/pandas 不可用。"))
        return {"items": [], "summary": "基金持仓暂缺。"}
    try:
        df = ak.stock_fund_stock_holder(symbol=stock_code)
        if df.empty:
            statuses.append(source_status("新浪财经基金持股", "structured_data", "akshare stock_fund_stock_holder", "empty", "返回空表。"))
            return {"items": [], "summary": "基金持仓暂缺。"}
        latest_date = str(df["截止日期"].max())
        latest = df[df["截止日期"].astype(str) == latest_date].copy()
        latest["持股市值"] = latest["持股市值"].astype(float)
        latest = latest.sort_values("持股市值", ascending=False)
        items = latest.head(20).to_dict("records")
        total_shares = float(latest["持仓数量"].astype(float).sum())
        statuses.append(source_status("新浪财经基金持股", "structured_data", "akshare stock_fund_stock_holder", "ok", f"最新截止 {latest_date}，共 {len(latest)} 条。"))
        return {
            "items": items,
            "latest_date": latest_date,
            "total_items": int(len(latest)),
            "total_shares": total_shares,
            "summary": f"最新截止 {latest_date}，{len(latest)} 只基金持有，合计 {total_shares / 10000:.2f} 万股；该数据为季报滞后口径。",
        }
    except Exception as exc:
        statuses.append(source_status("新浪财经基金持股", "structured_data", "akshare stock_fund_stock_holder", "failed", str(exc)))
        return {"items": [], "summary": "基金持仓抓取失败。"}


def fetch_evidence(stock_code: str, start: str, end: str) -> Dict[str, Any]:
    statuses: List[Dict[str, str]] = []
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target": {"stock_code": stock_code, "date_window": f"{start} 至 {end}"},
        "source_status": statuses,
        "block_trades": fetch_block_trades(stock_code, start, end, statuses),
        "lhb": fetch_lhb(stock_code, start, end, statuses),
        "northbound": fetch_northbound(stock_code, start, end, statuses),
        "etf": fetch_sse_etf(start, end, statuses),
        "fund_holdings": fetch_fund_holdings(stock_code, statuses),
    }
    ok_count = sum(1 for item in statuses if item["status"] in {"ok", "empty"})
    failed = [item for item in statuses if item["status"] == "failed"]
    payload["quality"] = {
        "level": "partial" if failed else "ok",
        "summary": f"机构/基金验证源 {ok_count}/{len(statuses)} 可用；失败或滞后 {len(failed)} 项。",
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-code", default="600519")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    payload = fetch_evidence(args.stock_code, args.start_date, args.end_date)
    out = Path(args.out or f"data/institutional_evidence_{args.start_date}_{args.end_date}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
