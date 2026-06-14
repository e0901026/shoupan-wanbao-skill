from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from common import fmt_num, load_yaml, read_json


def cn_weekday(dt: datetime) -> str:
    return "一二三四五六日"[dt.weekday()]


def fund_table(rows: List[Dict[str, Any]]) -> str:
    header = (
        "| 板块 | 净流入（亿） | 超大单（亿） | 大单（亿） | 小单（亿） | 涨跌幅 % | 成交额（亿） | 净流入率 % |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|"
    )
    lines = [header]
    for r in rows:
        lines.append(
            "| {name} | {net} | {super_large} | {large} | {small} | {pct} | {amount} | {rate} |".format(
                name=r.get("板块", "暂缺"),
                net=fmt_num(r.get("净流入（亿）")),
                super_large=fmt_num(r.get("超大单（亿）")),
                large=fmt_num(r.get("大单（亿）")),
                small=fmt_num(r.get("小单（亿）")),
                pct=fmt_num(r.get("涨跌幅 %"), "%"),
                amount=fmt_num(r.get("成交额（亿）"), signed=False),
                rate=fmt_num(r.get("净流入率 %"), "%"),
            )
        )
    return "\n".join(lines)


def quote_line(q: Dict[str, Any], name: str) -> str:
    return f"├ {name}：{fmt_num(q.get('收盘价'), ' 元', signed=False)}（{fmt_num(q.get('涨跌幅'), '%')}）"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    config = load_yaml(args.config)
    data_dir = Path(args.data_dir)
    analysis = read_json(data_dir / "analysis.json")
    if analysis is None:
        raise FileNotFoundError("data/analysis.json not found. Run analyze_report.py first.")

    today = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.now()
    date_cn = today.strftime("%Y年%m月%d日")
    date_compact = today.strftime("%Y%m%d")
    weekday_cn = f"周{cn_weekday(today)}"

    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / "templates")),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["fmt_num"] = fmt_num
    env.filters["fund_table"] = fund_table
    env.filters["quote_line"] = quote_line

    tpl = env.get_template("report.md.j2")
    report = tpl.render(
        config=config,
        analysis=analysis,
        date_cn=date_cn,
        date_compact=date_compact,
        weekday_cn=weekday_cn,
        fund_table=fund_table,
        quote_line=quote_line,
        fmt_num=fmt_num,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
