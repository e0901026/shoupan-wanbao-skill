from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def read_state(path: str | Path) -> dict:
    state_path = Path(path)
    if not state_path.exists():
        return {}
    with state_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_state(path: str | Path, state: dict) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def archive_daily_artifacts(
    report_date: str,
    data_dir: str | Path = "data",
    archive_dir: str | Path | None = None,
) -> None:
    data_path = Path(data_dir)
    archive_path = Path(archive_dir) if archive_dir is not None else data_path / "archive"
    archive_path.mkdir(parents=True, exist_ok=True)
    analysis = data_path / "analysis.json"
    if analysis.exists():
        shutil.copy2(analysis, archive_path / f"analysis_{report_date}.json")


def compute_news_lookback_days(report_date: str, state_file: str | Path, initial_days: int = 30) -> int:
    state = read_state(state_file)
    last_date = state.get("last_successful_report_date")
    if not last_date:
        return initial_days
    current = datetime.strptime(report_date, "%Y-%m-%d").date()
    previous = datetime.strptime(str(last_date), "%Y-%m-%d").date()
    gap = (current - previous).days
    return max(gap, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--date", help="Report/trading date in YYYY-MM-DD format.")
    parser.add_argument("--state-file", default="data/run_state.json", help="State file used to decide first-run vs incremental news window.")
    parser.add_argument("--initial-news-lookback-days", type=int, default=30, help="News lookback window for the first successful run.")
    parser.add_argument("--news-lookback-days", type=int, help="Explicit news window override, useful for audited historical backfills.")
    parser.add_argument("--data-dir", default="data", help="Per-run data directory; use an isolated directory for parallel backfills.")
    parser.add_argument("--archive-dir", default="data/archive", help="Shared destination for successful dated analysis archives.")
    parser.add_argument("--report-md", help="Intermediate Markdown path. Defaults to output/report.md for normal runs.")
    parser.add_argument("--member-cache", default="data/sw2_members_cache.json", help="Shared complete SW2 membership cache.")
    parser.add_argument("--publish-feishu", action="store_true", help="Also run the optional Feishu publisher after HTML generation.")
    parser.add_argument(
        "--allow-degraded-fund-flow",
        action="store_true",
        help="Allow degraded fund-flow sources for internal drafts. Default is strict complete fund-flow validation.",
    )
    parser.add_argument("--no-html", action="store_true", help="Skip HTML export.")
    parser.add_argument("--no-index", action="store_true", help="Skip refreshing output/index.html after generation.")
    args = parser.parse_args()

    py = sys.executable
    report_date = args.date or datetime.now().strftime("%Y-%m-%d")
    html_out = f"output/a_share_evening_report_{report_date}.html"
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    report_md = Path(args.report_md or ("output/report.md" if data_dir == Path("data") else data_dir / "report.md"))
    report_md.parent.mkdir(parents=True, exist_ok=True)
    news_lookback_days = args.news_lookback_days or compute_news_lookback_days(
        report_date,
        args.state_file,
        initial_days=args.initial_news_lookback_days,
    )
    data_file = lambda name: str(data_dir / name)
    commands = [
        [py, "scripts/fetch_quotes.py", "--config", args.config, "--out", data_file("quotes.json")],
        [py, "scripts/fetch_sector_fund_flow.py", "--config", args.config, "--out", data_file("sector_fund_flow.json"), "--member-cache", args.member_cache],
        [py, "scripts/fetch_news.py", "--config", args.config, "--out", data_file("news.json"), "--lookback-days", str(news_lookback_days)],
        [py, "scripts/fetch_research.py", "--config", args.config, "--out", data_file("research.json")],
        [py, "scripts/fetch_sentiment.py", "--config", args.config, "--out", data_file("sentiment.json")],
        [py, "scripts/fetch_margin_financing.py", "--config", args.config, "--out", data_file("margin_financing.json")],
        [py, "scripts/fetch_corporate_actions.py", "--config", args.config, "--out", data_file("corporate_actions.json")],
        [py, "scripts/fetch_macro.py", "--out", data_file("macro.json")],
        [py, "scripts/analyze_report.py", "--config", args.config, "--data-dir", str(data_dir), "--out", data_file("analysis.json")],
        [py, "scripts/render_report.py", "--config", args.config, "--data-dir", str(data_dir), "--out", str(report_md)],
        [py, "scripts/validate_report.py", "--report", str(report_md), "--analysis", data_file("analysis.json")],
    ]
    if args.date:
        date_aware_scripts = {
            "scripts/fetch_quotes.py",
            "scripts/fetch_sector_fund_flow.py",
            "scripts/fetch_news.py",
            "scripts/fetch_research.py",
            "scripts/fetch_sentiment.py",
            "scripts/fetch_margin_financing.py",
            "scripts/fetch_corporate_actions.py",
            "scripts/fetch_macro.py",
            "scripts/render_report.py",
        }
        for cmd in commands:
            if cmd[1] in date_aware_scripts:
                cmd.extend(["--date", args.date])
    if not args.allow_degraded_fund_flow:
        validate_cmd = next(cmd for cmd in commands if cmd[1] == "scripts/validate_report.py")
        validate_cmd.append("--strict-fund-flow")
    if not args.no_html:
        commands.append(
            [
                py,
                "scripts/render_html.py",
                "--report",
                str(report_md),
                "--out",
                html_out,
                "--title",
                f"A股收盘晚报 {report_date}",
            ]
        )
    if args.publish_feishu:
        commands.append([py, "scripts/publish_feishu_html.py", "--config", args.config, "--html", html_out, "--analysis", data_file("analysis.json")])
    if not args.no_index:
        commands.append([py, "scripts/render_index.py", "--output-dir", "output"])
    for cmd in commands:
        run(cmd)
    archive_daily_artifacts(report_date, data_dir=data_dir, archive_dir=args.archive_dir)
    state = read_state(args.state_file)
    state.update(
        {
            "last_successful_report_date": report_date,
            "last_news_lookback_days": news_lookback_days,
            "last_html_output": html_out,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    write_state(args.state_file, state)


if __name__ == "__main__":
    main()
