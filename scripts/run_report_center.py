from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import List

from report_calendar import TradeCalendar, date_str, ensure_trade_calendar, parse_date


@dataclass
class RunPlan:
    root: Path
    daily_dates: List[str] = field(default_factory=list)
    weekly_dates: List[str] = field(default_factory=list)
    morning_date: str | None = None
    morning_window_start: str | None = None
    morning_window_end: str | None = None
    render_index: bool = True


def read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def after_or_equal(value: str, expected: str) -> bool:
    return datetime.strptime(value, "%H:%M").time() >= datetime.strptime(expected, "%H:%M").time()


def next_day(day: str) -> str:
    return date_str(parse_date(day) + timedelta(days=1))


def previous_completed_week_anchor(today: str, now_time: str) -> str:
    dt = parse_date(today)
    if dt.weekday() == 5 and after_or_equal(now_time, "09:00"):
        return today
    if dt.weekday() == 6:
        return date_str(dt - timedelta(days=1))
    if dt.weekday() == 5:
        return date_str(dt - timedelta(days=8))
    return date_str(dt - timedelta(days=dt.weekday() + 3))


def completed_daily_target(today: str, now_time: str, calendar: TradeCalendar) -> str | None:
    if calendar.is_trading_day(today) and after_or_equal(now_time, "16:00"):
        return today
    return calendar.previous_trading_day(today)


def missing_daily_dates(today: str, now_time: str, calendar: TradeCalendar, state: dict) -> List[str]:
    target = completed_daily_target(today, now_time, calendar)
    if not target:
        return []
    last = state.get("last_daily_date") or state.get("last_successful_report_date")
    if not last:
        return [target] if calendar.is_trading_day(target) else []
    start = next_day(str(last))
    return calendar.trading_days_between(start, target)


def build_run_plan(today: str, now_time: str, root: Path, calendar: TradeCalendar, state_file: Path) -> RunPlan:
    state = read_state(state_file)
    run_state = read_state(root / "data" / "run_state.json")
    if "last_daily_date" not in state and "last_successful_report_date" not in state:
        last_daily = run_state.get("last_successful_report_date")
        if last_daily:
            state["last_successful_report_date"] = last_daily
    plan = RunPlan(root=root)
    dt = parse_date(today)
    plan.daily_dates = missing_daily_dates(today, now_time, calendar, state)
    anchor = previous_completed_week_anchor(today, now_time)
    if anchor:
        week_dates = calendar.week_trading_days(anchor)
        weekly_out = root / "output" / f"a_share_weekly_report_{week_dates[0]}_{week_dates[-1]}.html" if week_dates else None
        if week_dates and (not weekly_out or not weekly_out.exists()):
            plan.weekly_dates = week_dates
    if dt.weekday() == 0 and after_or_equal(now_time, "08:30"):
        out = root / "output" / f"a_share_morning_report_{today}.html"
        if not out.exists():
            previous = calendar.previous_trading_day(today)
            plan.morning_date = today
            plan.morning_window_start = f"{previous or today} 15:00"
            plan.morning_window_end = f"{today} 08:30"
    return plan


def run(cmd: List[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def execute_plan(plan: RunPlan, config: str, py: str = sys.executable, state_file: Path | None = None) -> None:
    for day in plan.daily_dates:
        run([py, "scripts/run_daily.py", "--config", config, "--date", day])
    if plan.daily_dates:
        run([py, "scripts/audit_report_history.py", "--root", str(plan.root), "--dates", *plan.daily_dates])
    if plan.weekly_dates:
        run([py, "scripts/run_weekly.py", "--root", str(plan.root), "--dates", *plan.weekly_dates, "--output-dir", str(plan.root / "output")])
    if plan.morning_date and plan.morning_window_start and plan.morning_window_end:
        run(
            [
                py,
                "scripts/run_morning.py",
                "--config",
                config,
                "--date",
                plan.morning_date,
                "--window-start",
                plan.morning_window_start,
                "--window-end",
                plan.morning_window_end,
            ]
        )
        run(
            [
                py,
                "scripts/audit_morning_history.py",
                "--root",
                str(plan.root),
                "--window",
                plan.morning_date,
                plan.morning_window_start,
                plan.morning_window_end,
            ]
        )
    if plan.render_index:
        run([py, "scripts/render_index.py", "--output-dir", str(plan.root / "output")])
    if state_file:
        state = read_state(state_file)
        if plan.daily_dates:
            state["last_daily_date"] = plan.daily_dates[-1]
        if plan.weekly_dates:
            state["last_weekly_end_date"] = plan.weekly_dates[-1]
        if plan.morning_date:
            state["last_morning_date"] = plan.morning_date
        state["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_state(state_file, state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--root", default=".")
    parser.add_argument("--date")
    parser.add_argument("--time")
    parser.add_argument("--state-file", default="data/report_center_state.json")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    now = datetime.now()
    today = args.date or now.strftime("%Y-%m-%d")
    now_time = args.time or now.strftime("%H:%M")
    calendar = ensure_trade_calendar(root / "data", int(today[:4]))
    state_file = root / args.state_file
    plan = build_run_plan(today, now_time, root, calendar, state_file)
    execute_plan(plan, config=args.config, py=sys.executable, state_file=state_file)


if __name__ == "__main__":
    main()
