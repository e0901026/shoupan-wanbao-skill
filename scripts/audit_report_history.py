from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common import to_float


FLOW_GROUPS = [
    "inflow_top5",
    "outflow_top5",
    "divergence_net_inflow_price_down",
    "divergence_net_outflow_price_up",
    "divergence_super_in_large_out",
    "divergence_super_out_large_in",
    "baijiu",
]


def close_enough(left: Any, right: Any, tolerance: float = 0.001) -> bool:
    a = to_float(left)
    b = to_float(right)
    return a is not None and b is not None and abs(a - b) <= tolerance


def normalized_date(value: Any) -> str | None:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%Y %b %d"):
        try:
            return datetime.strptime(text[:11] if pattern == "%Y %b %d" else text[:10], pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def row_equation_issue(row: Dict[str, Any]) -> str | None:
    net = to_float(row.get("净流入（亿）"))
    super_large = to_float(row.get("超大单（亿）"))
    large = to_float(row.get("大单（亿）"))
    if None in (net, super_large, large):
        return f"{row.get('板块', '未知板块')}主力资金字段缺失"
    if abs(net - (super_large + large)) > 0.001:
        return f"{row.get('板块')}主力净流入不等于超大单+大单"
    return None


def divergence_issue(group: str, row: Dict[str, Any]) -> str | None:
    net = to_float(row.get("净流入（亿）"))
    pct = to_float(row.get("涨跌幅 %"))
    super_large = to_float(row.get("超大单（亿）"))
    large = to_float(row.get("大单（亿）"))
    conditions = {
        "divergence_net_inflow_price_down": net is not None and pct is not None and net > 0 and pct < 0,
        "divergence_net_outflow_price_up": net is not None and pct is not None and net < 0 and pct > 0,
        "divergence_super_in_large_out": super_large is not None and large is not None and super_large > 0 and large < 0,
        "divergence_super_out_large_in": super_large is not None and large is not None and super_large < 0 and large > 0,
    }
    if group in conditions and not conditions[group]:
        return f"{row.get('板块')}不满足{group}条件"
    return None


def audit_analysis(date: str, analysis: Dict[str, Any], html_path: Path | None = None) -> List[str]:
    issues = [str(item.get("message") or item) for item in analysis.get("quality_issues") or []]
    quotes_payload = analysis.get("quotes") or {}
    quote = (quotes_payload.get("quotes") or {}).get("600519") or {}
    if quote.get("交易日期") != date:
        issues.append(f"行情日期不符：{quote.get('交易日期')}")
    pre_close = to_float(quote.get("前收盘价"))
    close = to_float(quote.get("收盘价"))
    change = to_float(quote.get("涨跌额"))
    pct = to_float(quote.get("涨跌幅"))
    if None in (pre_close, close, change, pct):
        issues.append("贵州茅台行情公式字段缺失")
    else:
        if not close_enough(close, pre_close + change, 0.02):
            issues.append("收盘价不等于前收盘价+涨跌额")
        calculated_pct = change / pre_close * 100 if pre_close else 0.0
        if not close_enough(pct, calculated_pct, 0.03):
            issues.append("涨跌幅与前收盘价/涨跌额不一致")
    cross = (quotes_payload.get("cross_checks") or {}).get("600519") or {}
    if cross.get("status") != "matched":
        issues.append(f"贵州茅台行情交叉核验未通过：{cross.get('status') or '缺失'}")

    h15 = ((analysis.get("macro") or {}).get("h15") or {})
    macro_date_fields = ["latest_date", *[key for key in h15 if key.endswith("_observation_date")]]
    for field in macro_date_fields:
        raw_observed = h15.get(field)
        observed = normalized_date(raw_observed)
        if observed and observed > date:
            issues.append(f"宏观利率发生历史穿越：{field}={raw_observed}")

    fund = analysis.get("fund_flow") or {}
    quality = fund.get("quality") or {}
    if quality.get("source_mode") != "tushare_sw2_stock_moneyflow_aggregate" or quality.get("level") != "complete":
        issues.append("申万二级资金源或质量等级不合格")
    for group in FLOW_GROUPS:
        for row in fund.get(group) or []:
            equation = row_equation_issue(row)
            if equation:
                issues.append(equation)
            divergence = divergence_issue(group, row)
            if divergence:
                issues.append(divergence)
    inflow = fund.get("inflow_top5") or []
    outflow = fund.get("outflow_top5") or []
    if any((to_float(row.get("净流入（亿）")) or 0) <= 0 for row in inflow):
        issues.append("净流入TOP含非正值")
    if any((to_float(row.get("净流入（亿）")) or 0) >= 0 for row in outflow):
        issues.append("净流出TOP含非负值")
    inflow_names = {str(row.get("板块")) for row in inflow}
    outflow_names = {str(row.get("板块")) for row in outflow}
    if inflow_names & outflow_names:
        issues.append("同一板块同时出现在净流入与净流出TOP")
    liquor_names = {str(row.get("板块")) for row in fund.get("baijiu") or []}
    for required in ("白酒Ⅱ", "贵州茅台"):
        if required not in liquor_names:
            issues.append(f"白酒固定观察缺少{required}")
    if html_path and not html_path.exists():
        issues.append("HTML报告缺失")
    return issues


def audit_dates(root: Path, dates: Iterable[str]) -> Dict[str, List[str]]:
    results: Dict[str, List[str]] = {}
    for date in dates:
        archive = root / "data" / "archive" / f"analysis_{date}.json"
        if not archive.exists():
            results[date] = ["分析归档缺失"]
            continue
        analysis = json.loads(archive.read_text(encoding="utf-8"))
        results[date] = audit_analysis(
            date,
            analysis,
            root / "output" / f"a_share_evening_report_{date}.html",
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--dates", nargs="+", required=True)
    args = parser.parse_args()
    results = audit_dates(Path(args.root).resolve(), args.dates)
    failed = {date: issues for date, issues in results.items() if issues}
    print(json.dumps({"status": "failed" if failed else "passed", "results": results}, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
