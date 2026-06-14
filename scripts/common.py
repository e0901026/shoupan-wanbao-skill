from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml

CST_TZ_NAME = "Asia/Shanghai"

REQUIRED_FUND_COLUMNS = [
    "板块",
    "净流入（亿）",
    "超大单（亿）",
    "大单（亿）",
    "小单（亿）",
    "涨跌幅 %",
    "成交额（亿）",
    "净流入率 %",
]


def load_yaml(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_iso() -> str:
    # Hermes 一般会以 Asia/Shanghai 调度；这里不强依赖 zoneinfo，避免轻量环境失败。
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def env_value(name: Optional[str], default: Optional[str] = None) -> Optional[str]:
    if not name:
        return default
    return os.getenv(name, default)


def market_session():
    import requests

    session = requests.Session()
    session.trust_env = False
    return session


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("%", "")
    if s in {"", "-", "--", "None", "nan", "暂缺"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def yuan_to_yi(value: Any) -> Optional[float]:
    n = to_float(value)
    if n is None:
        return None
    return n / 100000000.0


def round_or_none(value: Any, ndigits: int = 2) -> Optional[float]:
    n = to_float(value)
    if n is None:
        return None
    return round(n, ndigits)


def fmt_num(value: Any, suffix: str = "", signed: bool = True) -> str:
    n = to_float(value)
    if n is None:
        return "暂缺"
    sign = "+" if signed and n > 0 else ""
    return f"{sign}{n:.2f}{suffix}"


def normalize_fund_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """统一资金流字段，缺失字段保留为 None，渲染层再显示“暂缺”。"""
    name = row.get("板块") or row.get("名称") or row.get("name") or row.get("sector")
    net = row.get("净流入（亿）")
    super_large = row.get("超大单（亿）")
    large = row.get("大单（亿）")
    small = row.get("小单（亿）")
    pct = row.get("涨跌幅 %")
    amount = row.get("成交额（亿）")
    rate = row.get("净流入率 %")

    # 兼容 AkShare / 东方财富常见列名
    aliases = {
        "净流入（亿）": ["今日主力净流入-净额", "主力净流入-净额", "主力净流入", "f62"],
        "超大单（亿）": ["今日超大单净流入-净额", "超大单净流入-净额", "超大单净流入", "f66"],
        "大单（亿）": ["今日大单净流入-净额", "大单净流入-净额", "大单净流入", "f72"],
        "小单（亿）": ["今日小单净流入-净额", "小单净流入-净额", "小单净流入", "f84"],
        "涨跌幅 %": ["今日涨跌幅", "涨跌幅", "f3"],
        "成交额（亿）": ["今日成交额", "成交额", "f6"],
        "净流入率 %": ["今日主力净流入-净占比", "主力净流入-净占比", "净流入率", "f184"],
    }
    values = {
        "净流入（亿）": net,
        "超大单（亿）": super_large,
        "大单（亿）": large,
        "小单（亿）": small,
        "涨跌幅 %": pct,
        "成交额（亿）": amount,
        "净流入率 %": rate,
    }
    for standard, keys in aliases.items():
        if values[standard] is None:
            for key in keys:
                if key in row:
                    values[standard] = row.get(key)
                    break

    # f62/f66/f72/f6 是东方财富接口里的“元”，转换为亿元。
    for col in ["净流入（亿）", "超大单（亿）", "大单（亿）", "小单（亿）", "成交额（亿）"]:
        raw = values[col]
        if raw is None:
            continue
        n = to_float(raw)
        if n is None:
            values[col] = None
        elif abs(n) > 1000000:  # 认为是“元”口径
            values[col] = round(n / 100000000.0, 2)
        else:
            values[col] = round(n, 2)

    for col in ["涨跌幅 %", "净流入率 %"]:
        values[col] = round_or_none(values[col], 2)

    if values["净流入率 %"] is None:
        net_n = to_float(values["净流入（亿）"])
        amount_n = to_float(values["成交额（亿）"])
        if net_n is not None and amount_n not in (None, 0):
            values["净流入率 %"] = round(net_n / amount_n * 100, 2)

    return {
        "板块": name or "暂缺",
        "净流入（亿）": values["净流入（亿）"],
        "超大单（亿）": values["超大单（亿）"],
        "大单（亿）": values["大单（亿）"],
        "小单（亿）": values["小单（亿）"],
        "涨跌幅 %": values["涨跌幅 %"],
        "成交额（亿）": values["成交额（亿）"],
        "净流入率 %": values["净流入率 %"],
    }


def ensure_required_fund_columns(rows: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    normalized = []
    for row in rows:
        clean = normalize_fund_row(row)
        merged = {col: clean.get(col) for col in REQUIRED_FUND_COLUMNS}
        for key, value in row.items():
            if key not in merged:
                merged[key] = value
        normalized.append(merged)
    return normalized
