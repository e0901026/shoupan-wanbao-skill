from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import REQUIRED_FUND_COLUMNS, read_json


FUND_TABLE_TITLES = [
    "### 🔥 净流入 TOP 10",
    "### 💧 净流出 TOP 10",
    "### 🔴 背离一：净流入 ↗ 但股价跌",
    "### 🟢 背离二：净流出 ↘ 但股价涨",
    "### 🔶 背离三：超大单 ↑ + 大单 ↓",
    "### 🔶 背离四：超大单 ↓ + 大单 ↑",
    "## 🍶 白酒板块",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--strict-fund-flow", action="store_true", help="Fail unless fund flow data quality is complete.")
    args = parser.parse_args()

    report = Path(args.report).read_text(encoding="utf-8")
    analysis = read_json(args.analysis, default={}) or {}

    errors = []
    for title in FUND_TABLE_TITLES:
        if title not in report:
            errors.append(f"缺少表格模块：{title}")

    header = "| " + " | ".join(REQUIRED_FUND_COLUMNS) + " |"
    header_count = report.count(header)
    if header_count < len(FUND_TABLE_TITLES):
        errors.append(f"完整 {len(REQUIRED_FUND_COLUMNS)} 列资金表数量不足：发现 {header_count} 张，至少需要 {len(FUND_TABLE_TITLES)} 张")

    if "## ⚠️ 风险提示" not in report:
        errors.append("缺少风险提示")
    if "## 🧾 数据来源与抓取说明" not in report:
        errors.append("缺少数据来源与抓取说明")
    quotes = (analysis.get("quotes") or {}).get("quotes") or {}
    required_quote_symbols = ["600519", "000858", "600809", "000568", "002304"]
    missing_quotes = [symbol for symbol in required_quote_symbols if not (quotes.get(symbol) or {}).get("收盘价")]
    if missing_quotes:
        errors.append(f"关键行情数据缺失：{', '.join(missing_quotes)}")
    fund_flow = analysis.get("fund_flow") or {}
    if not fund_flow.get("inflow_top5"):
        errors.append("板块资金流入 TOP5 为空")
    if not fund_flow.get("outflow_top5"):
        errors.append("板块资金流出 TOP5 为空")
    fund_quality = fund_flow.get("quality") or {}
    if args.strict_fund_flow and fund_quality.get("level") != "complete":
        errors.append(f"严格资金流门禁失败：quality={fund_quality}")
    if analysis.get("quality_issues"):
        errors.append(f"analysis 中存在质量问题：{analysis['quality_issues']}")

    if errors:
        print("报告校验失败：")
        for err in errors:
            print(f"- {err}")
        sys.exit(1)

    print("报告校验通过。")
    if fund_quality.get("level") and fund_quality.get("level") != "complete":
        print(f"资金流为降级/非完整数据：{fund_quality}")


if __name__ == "__main__":
    main()
