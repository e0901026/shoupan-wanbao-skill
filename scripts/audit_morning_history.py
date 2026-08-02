from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup


WINDOWS = {
    "2026-06-15": ("2026-06-12 15:00", "2026-06-15 08:30"),
    "2026-06-22": ("2026-06-18 15:00", "2026-06-22 08:30"),
    "2026-06-29": ("2026-06-26 15:00", "2026-06-29 08:30"),
    "2026-07-06": ("2026-07-03 15:00", "2026-07-06 08:30"),
    "2026-07-13": ("2026-07-10 15:00", "2026-07-13 08:30"),
    "2026-07-20": ("2026-07-17 15:00", "2026-07-20 08:30"),
    "2026-07-27": ("2026-07-24 15:00", "2026-07-27 08:30"),
}

DISPLAY_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s+·")
FORBIDDEN_MARKET_SECTIONS = ("板块资金流向", "净流入 TOP", "净流出 TOP", "四大背离", "五日量化快照")


def audit_report(path: Path, report_date: str, window_start: str, window_end: str) -> list[str]:
    issues: list[str] = []
    if not path.exists():
        return ["HTML missing"]
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    text = soup.get_text(" ", strip=True)
    expected_window = f"资讯窗口：{window_start} 至 {window_end}"
    if expected_window not in text:
        issues.append("window label mismatch")
    for heading in FORBIDDEN_MARKET_SECTIONS:
        if heading in text:
            issues.append(f"forbidden unopened-market section: {heading}")

    start = datetime.strptime(window_start, "%Y-%m-%d %H:%M")
    end = datetime.strptime(window_end, "%Y-%m-%d %H:%M")
    audited_meta = []
    for section_title in ("主标的新闻", "行业新闻", "机构观点"):
        heading = next((node for node in soup.find_all("h2") if node.get_text(" ", strip=True) == section_title), None)
        if heading is None:
            issues.append(f"missing section: {section_title}")
            continue
        for node in heading.find_all_next():
            if node is not heading and node.name == "h2":
                break
            if node.name == "span" and "meta" in (node.get("class") or []):
                audited_meta.append(node)

    # 宏观与风险事件既包括休市窗口新闻，也包括窗口前最新官方观测值和
    # 窗口后的待发生日历；它们不能按普通新闻窗口规则误判。
    for meta in audited_meta:
        match = DISPLAY_TIME_RE.match(" ".join(meta.get_text(" ", strip=True).split()))
        if not match:
            continue
        raw = match.group(1)
        published = None
        date_only = len(raw) == 10
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                published = datetime.strptime(raw, pattern)
                break
            except ValueError:
                continue
        if published is None:
            issues.append(f"unparseable displayed time: {raw}")
        elif date_only:
            if not (start.date() < published.date() < end.date()):
                issues.append(f"unverifiable boundary date displayed: {raw}")
        elif not (start <= published <= end):
            issues.append(f"displayed item outside window: {raw}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit historical Monday morning reports.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dates", nargs="*", default=None)
    parser.add_argument(
        "--window",
        nargs=3,
        metavar=("REPORT_DATE", "WINDOW_START", "WINDOW_END"),
        help="Audit one report with an explicit rest-period window; used by scheduled runs.",
    )
    args = parser.parse_args()
    root = Path(args.root)
    windows = {args.window[0]: (args.window[1], args.window[2])} if args.window else WINDOWS
    dates = args.dates if args.dates is not None else list(windows)
    failed = False
    for report_date in dates:
        window = windows.get(report_date)
        if not window:
            print(f"FAIL {report_date}: missing configured window")
            failed = True
            continue
        path = root / "output" / f"a_share_morning_report_{report_date}.html"
        issues = audit_report(path, report_date, *window)
        if issues:
            print(f"FAIL {report_date}: {'; '.join(issues)}")
            failed = True
        else:
            print(f"PASS {report_date}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
