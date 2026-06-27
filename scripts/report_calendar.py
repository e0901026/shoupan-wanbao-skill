from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

import requests


def date_str(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


@dataclass
class TradeCalendar:
    cache_path: Path

    def __post_init__(self) -> None:
        self.days: Dict[str, bool] = {}
        if self.cache_path.exists():
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.days = {item["date"]: bool(item["is_open"]) for item in payload.get("days", [])}

    def is_trading_day(self, day: str) -> bool:
        if day in self.days:
            return self.days[day]
        dt = parse_date(day)
        return dt.weekday() < 5

    def trading_days_between(self, start: str, end: str) -> List[str]:
        start_dt = parse_date(start)
        end_dt = parse_date(end)
        out: List[str] = []
        cur = start_dt
        while cur <= end_dt:
            value = date_str(cur)
            if self.is_trading_day(value):
                out.append(value)
            cur += timedelta(days=1)
        return out

    def previous_trading_day(self, day: str) -> str | None:
        cur = parse_date(day) - timedelta(days=1)
        for _ in range(20):
            value = date_str(cur)
            if self.is_trading_day(value):
                return value
            cur -= timedelta(days=1)
        return None

    def week_trading_days(self, day: str) -> List[str]:
        dt = parse_date(day)
        monday = dt - timedelta(days=dt.weekday())
        friday = monday + timedelta(days=4)
        return self.trading_days_between(date_str(monday), date_str(friday))


def cache_path_for_year(data_dir: str | Path, year: int) -> Path:
    return Path(data_dir) / f"trade_calendar_{year}.json"


def ensure_trade_calendar(data_dir: str | Path, year: int, token: str | None = None) -> TradeCalendar:
    path = cache_path_for_year(data_dir, year)
    if not path.exists() and token:
        fetch_tushare_calendar(path, year, token)
    return TradeCalendar(path)


def fetch_tushare_calendar(path: Path, year: int, token: str | None = None) -> None:
    token = token or os.getenv("TUSHARE_TOKEN")
    if not token:
        return
    body = {
        "api_name": "trade_cal",
        "token": token,
        "params": {"exchange": "SSE", "start_date": f"{year}0101", "end_date": f"{year}1231"},
        "fields": "cal_date,is_open",
    }
    resp = requests.post("https://api.tushare.pro", json=body, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"tushare trade_cal error: {data.get('msg') or data}")
    fields = (data.get("data") or {}).get("fields") or []
    rows = (data.get("data") or {}).get("items") or []
    days = []
    for item in rows:
        row = dict(zip(fields, item))
        raw = str(row.get("cal_date") or "")
        if len(raw) == 8:
            days.append({"date": f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}", "is_open": str(row.get("is_open")) == "1"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"days": days}, ensure_ascii=False, indent=2), encoding="utf-8")
