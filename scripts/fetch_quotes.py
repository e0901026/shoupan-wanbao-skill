from __future__ import annotations

import argparse
import os
import re
from typing import Any, Dict, List

import pandas as pd
import requests

from common import load_yaml, market_session, now_iso, to_float, write_json


def ts_code_for_stock(stock: Dict[str, Any]) -> str:
    suffix = "SH" if stock.get("market") == "SH" else "SZ"
    return f"{stock['symbol']}.{suffix}"


def build_quote_from_tushare_rows(symbol: str, name: str, daily: Dict[str, Any], basic: Dict[str, Any] | None = None) -> Dict[str, Any]:
    basic = basic or {}
    trade_date = str(daily.get("trade_date") or "")
    trade_date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}" if len(trade_date) == 8 else None
    amount_qian_yuan = to_float(daily.get("amount"))
    total_mv_wan = to_float(basic.get("total_mv"))
    return {
        "股票名称": name,
        "股票代码": symbol,
        "交易日期": trade_date_fmt,
        "收盘价": to_float(daily.get("close")),
        "涨跌幅": round(to_float(daily.get("pct_chg")) or 0, 2) if daily.get("pct_chg") is not None else None,
        "成交额（亿）": round(amount_qian_yuan / 100000, 2) if amount_qian_yuan is not None else None,
        "PE": to_float(basic.get("pe")),
        "总市值（亿）": round(total_mv_wan / 10000, 2) if total_mv_wan is not None else None,
        "开盘价": to_float(daily.get("open")),
        "最高价": to_float(daily.get("high")),
        "最低价": to_float(daily.get("low")),
        "振幅": None,
        "换手率": to_float(basic.get("turnover_rate")),
        "source": "tushare.daily+daily_basic",
    }


def fetch_quotes_by_tushare(stocks: List[Dict[str, Any]], trade_date: str, token: str) -> Dict[str, Dict[str, Any]]:
    url = "https://api.tushare.pro"
    trade_date_compact = trade_date.replace("-", "")
    ts_codes = ",".join(ts_code_for_stock(stock) for stock in stocks)
    session = market_session()

    def post(api_name: str, fields: str) -> list[Dict[str, Any]]:
        body = {
            "api_name": api_name,
            "token": token,
            "params": {"trade_date": trade_date_compact, "ts_code": ts_codes},
            "fields": fields,
        }
        resp = session.post(url, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"tushare {api_name} error: {data.get('msg') or data}")
        fields_out = (data.get("data") or {}).get("fields") or []
        items = (data.get("data") or {}).get("items") or []
        return [dict(zip(fields_out, item)) for item in items]

    daily_rows = post("daily", "ts_code,trade_date,open,high,low,close,pct_chg,amount")
    basic_rows = post("daily_basic", "ts_code,trade_date,turnover_rate,pe,total_mv")
    daily_by_code = {row["ts_code"]: row for row in daily_rows}
    basic_by_code = {row["ts_code"]: row for row in basic_rows}
    quotes: Dict[str, Dict[str, Any]] = {}
    for stock in stocks:
        ts_code = ts_code_for_stock(stock)
        daily = daily_by_code.get(ts_code)
        if daily:
            quotes[stock["symbol"]] = build_quote_from_tushare_rows(stock["symbol"], stock["name"], daily, basic_by_code.get(ts_code))
    return quotes


def fetch_quotes_by_akshare(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    result: Dict[str, Dict[str, Any]] = {}
    for symbol in symbols:
        hit = df[df["代码"] == symbol]
        if hit.empty:
            continue
        r = hit.iloc[0].to_dict()
        result[symbol] = {
            "股票名称": r.get("名称"),
            "股票代码": symbol,
            "收盘价": to_float(r.get("最新价")),
            "涨跌幅": to_float(r.get("涨跌幅")),
            "成交额（亿）": (to_float(r.get("成交额")) or 0) / 100000000 if r.get("成交额") is not None else None,
            "PE": to_float(r.get("市盈率-动态")),
            "总市值（亿）": (to_float(r.get("总市值")) or 0) / 100000000 if r.get("总市值") is not None else None,
            "开盘价": to_float(r.get("今开")),
            "最高价": to_float(r.get("最高")),
            "最低价": to_float(r.get("最低")),
            "振幅": to_float(r.get("振幅")),
            "换手率": to_float(r.get("换手率")),
            "source": "akshare.stock_zh_a_spot_em",
        }
    return result


def fetch_quote_by_eastmoney(secid: str, symbol: str, name: str) -> Dict[str, Any]:
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f162,f168,f170,f171",
        "fltt": "2",
        "invt": "2",
    }
    resp = market_session().get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    data = (resp.json().get("data") or {})
    return {
        "股票名称": data.get("f58") or name,
        "股票代码": data.get("f57") or symbol,
        "收盘价": to_float(data.get("f43")),
        "涨跌幅": to_float(data.get("f170")),
        "成交额（亿）": (to_float(data.get("f48")) or 0) / 100000000 if data.get("f48") is not None else None,
        "PE": to_float(data.get("f162")),
        "总市值（亿）": (to_float(data.get("f116")) or 0) / 100000000 if data.get("f116") is not None else None,
        "开盘价": to_float(data.get("f46")),
        "最高价": to_float(data.get("f44")),
        "最低价": to_float(data.get("f45")),
        "振幅": to_float(data.get("f171")),
        "换手率": to_float(data.get("f168")),
        "source": "eastmoney.push2.stock.get",
    }


def parse_sohu_historical_quote(payload: Any, symbol: str, name: str) -> Dict[str, Any]:
    if not isinstance(payload, list) or not payload or payload[0].get("status") != 0:
        raise ValueError(f"unexpected Sohu quote response for {symbol}")
    hq = payload[0].get("hq") or []
    if not hq:
        raise ValueError(f"empty Sohu quote response for {symbol}")
    row = hq[0]
    if len(row) < 10:
        raise ValueError(f"incomplete Sohu quote response for {symbol}")
    amount_wan = to_float(row[8])
    return {
        "股票名称": name,
        "股票代码": symbol,
        "交易日期": row[0],
        "收盘价": to_float(row[2]),
        "涨跌幅": to_float(row[4]),
        "成交额（亿）": round(amount_wan / 10000, 2) if amount_wan is not None else None,
        "PE": None,
        "总市值（亿）": None,
        "开盘价": to_float(row[1]),
        "最高价": to_float(row[6]),
        "最低价": to_float(row[5]),
        "振幅": None,
        "换手率": to_float(row[9]),
        "source": "sohu.hisHq",
    }


def fetch_quote_by_sohu(symbol: str, name: str, trade_date: str) -> Dict[str, Any]:
    url = "https://q.stock.sohu.com/hisHq"
    date_compact = trade_date.replace("-", "")
    params = {
        "code": f"cn_{symbol}",
        "start": date_compact,
        "end": date_compact,
        "stat": 1,
        "order": "D",
        "period": "d",
        "rt": "json",
    }
    resp = market_session().get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    quote = parse_sohu_historical_quote(resp.json(), symbol, name)
    if quote.get("交易日期") != trade_date:
        raise ValueError(f"Sohu quote date mismatch for {symbol}: {quote.get('交易日期')} != {trade_date}")
    return quote


def parse_tencent_quote_line(text: str, symbol: str, name: str) -> Dict[str, Any]:
    match = re.search(r'"(.*)"', text, flags=re.S)
    if not match:
        raise ValueError(f"unexpected Tencent quote response for {symbol}")
    parts = match.group(1).split("~")
    if len(parts) < 46:
        raise ValueError(f"incomplete Tencent quote response for {symbol}")
    trade_time = parts[30]
    trade_date = f"{trade_time[:4]}-{trade_time[4:6]}-{trade_time[6:8]}" if len(trade_time) >= 8 else None
    amount_wan = to_float(parts[37])
    return {
        "股票名称": parts[1] or name,
        "股票代码": parts[2] or symbol,
        "交易日期": trade_date,
        "收盘价": to_float(parts[3]),
        "涨跌幅": to_float(parts[32]),
        "成交额（亿）": round(amount_wan / 10000, 2) if amount_wan is not None else None,
        "PE": to_float(parts[39]),
        "总市值（亿）": to_float(parts[44]),
        "开盘价": to_float(parts[5]),
        "最高价": to_float(parts[33]),
        "最低价": to_float(parts[34]),
        "振幅": to_float(parts[43]),
        "换手率": to_float(parts[38]),
        "source": "tencent.qt.gtimg.quote",
    }


def fetch_quote_by_tencent(symbol: str, name: str, expected_date: str | None = None) -> Dict[str, Any]:
    prefix = "sh" if symbol.startswith("6") else "sz"
    url = "https://qt.gtimg.cn/q={prefix}{symbol}".format(prefix=prefix, symbol=symbol)
    resp = market_session().get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    quote = parse_tencent_quote_line(resp.text, symbol, name)
    if expected_date and quote.get("交易日期") != expected_date:
        raise ValueError(f"Tencent quote date mismatch for {symbol}: {quote.get('交易日期')} != {expected_date}")
    return quote


def enrich_quote_missing_fields(quote: Dict[str, Any], fallback: Dict[str, Any], source_suffix: str) -> None:
    fields = ["PE", "总市值（亿）", "振幅", "换手率"]
    changed = False
    for field in fields:
        if quote.get(field) is None and fallback.get(field) is not None:
            quote[field] = fallback[field]
            changed = True
    if changed and source_suffix not in str(quote.get("source", "")):
        quote["source"] = f"{quote.get('source', 'unknown')}+{source_suffix}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--date", help="Expected trading date in YYYY-MM-DD format.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    config = load_yaml(args.config)
    stocks = [config["primary_stock"], *config.get("peer_stocks", [])]
    symbols = [s["symbol"] for s in stocks]

    errors = []
    quotes: Dict[str, Dict[str, Any]] = {}
    tushare_token = os.getenv("TUSHARE_TOKEN")

    if args.date and tushare_token:
        try:
            quotes.update(fetch_quotes_by_tushare(stocks, args.date, tushare_token))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"tushare quote failed: {exc}")
    elif args.date:
        errors.append("tushare quote skipped: TUSHARE_TOKEN not set")

    if not args.date:
        try:
            quotes.update(fetch_quotes_by_akshare(symbols))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"akshare quote failed: {exc}")

    for stock in stocks:
        symbol = stock["symbol"]
        if symbol in quotes and quotes[symbol].get("收盘价") is not None:
            if args.date and any(quotes[symbol].get(field) is None for field in ["PE", "总市值（亿）", "振幅", "换手率"]):
                try:
                    fallback = fetch_quote_by_tencent(symbol, stock["name"], expected_date=args.date)
                    enrich_quote_missing_fields(quotes[symbol], fallback, "tencent.enrich")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"tencent quote enrich failed for {symbol}: {exc}")
            continue
        if args.date:
            try:
                quotes[symbol] = fetch_quote_by_sohu(symbol, stock["name"], args.date)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"sohu quote failed for {symbol}: {exc}")
        else:
            try:
                quotes[symbol] = fetch_quote_by_eastmoney(stock["secid"], symbol, stock["name"])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"eastmoney quote failed for {symbol}: {exc}")
        if symbol in quotes and quotes[symbol].get("收盘价") is not None:
            continue
        try:
            quotes[symbol] = fetch_quote_by_tencent(symbol, stock["name"], expected_date=args.date)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"tencent quote failed for {symbol}: {exc}")

    payload = {
        "generated_at": now_iso(),
        "sources": sorted({q.get("source", "unknown") for q in quotes.values()}),
        "errors": errors,
        "quotes": quotes,
    }
    write_json(args.out, payload)


if __name__ == "__main__":
    main()
