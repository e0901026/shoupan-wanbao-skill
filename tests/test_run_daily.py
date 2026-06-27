from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_daily  # noqa: E402


class RunDailyTest(unittest.TestCase):
    def test_compute_news_lookback_uses_initial_window_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"

            lookback = run_daily.compute_news_lookback_days("2026-06-12", state_file, initial_days=30)

            self.assertEqual(lookback, 30)

    def test_compute_news_lookback_includes_market_closure_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            state_file.write_text(json.dumps({"last_successful_report_date": "2026-06-12"}), encoding="utf-8")

            lookback = run_daily.compute_news_lookback_days("2026-06-15", state_file, initial_days=30)

            self.assertEqual(lookback, 3)

    def test_run_daily_uses_strict_validation_and_renders_dated_html(self) -> None:
        calls = []

        def fake_run(cmd, check):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            with (
                patch.object(
                    sys,
                    "argv",
                    ["run_daily.py", "--config", "config.yaml", "--date", "2026-06-12", "--state-file", str(state_file)],
                ),
                patch("subprocess.run", side_effect=fake_run),
            ):
                run_daily.main()

        validate_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/validate_report.py")
        html_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/render_html.py")
        news_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/fetch_news.py")
        fund_flow_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/fetch_sector_fund_flow.py")
        sentiment_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/fetch_sentiment.py")
        margin_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/fetch_margin_financing.py")
        corporate_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/fetch_corporate_actions.py")
        macro_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/fetch_macro.py")
        command_names = [cmd[1] for cmd in calls]

        self.assertIn("--strict-fund-flow", validate_cmd)
        self.assertIn("output/a_share_evening_report_2026-06-12.html", html_cmd)
        self.assertNotIn("scripts/feishu_writer.py", command_names)
        self.assertIn("--lookback-days", news_cmd)
        self.assertIn("30", news_cmd)
        self.assertIn("--date", fund_flow_cmd)
        self.assertIn("2026-06-12", fund_flow_cmd)
        self.assertIn("--date", sentiment_cmd)
        self.assertIn("2026-06-12", sentiment_cmd)
        self.assertIn("--date", margin_cmd)
        self.assertIn("2026-06-12", margin_cmd)
        self.assertIn("--date", corporate_cmd)
        self.assertIn("2026-06-12", corporate_cmd)
        self.assertIn("--date", macro_cmd)
        self.assertIn("2026-06-12", macro_cmd)

    def test_run_daily_passes_incremental_news_window_and_updates_state_after_success(self) -> None:
        calls = []

        def fake_run(cmd, check):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_file = tmp_path / "state.json"
            state_file.write_text(json.dumps({"last_successful_report_date": "2026-06-12"}), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "run_daily.py",
                        "--config",
                        "config.yaml",
                        "--date",
                        "2026-06-15",
                        "--state-file",
                        str(state_file),
                    ],
                ),
                patch("subprocess.run", side_effect=fake_run),
            ):
                run_daily.main()

            news_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/fetch_news.py")
            self.assertIn("--lookback-days", news_cmd)
            self.assertIn("3", news_cmd)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["last_successful_report_date"], "2026-06-15")
            self.assertEqual(state["last_news_lookback_days"], 3)

    def test_run_daily_can_publish_to_feishu_when_requested(self) -> None:
        calls = []

        def fake_run(cmd, check):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            with (
                patch.object(
                    sys,
                    "argv",
                    ["run_daily.py", "--config", "config.yaml", "--date", "2026-06-12", "--publish-feishu", "--state-file", str(state_file)],
                ),
                patch("subprocess.run", side_effect=fake_run),
            ):
                run_daily.main()

        command_names = [cmd[1] for cmd in calls]
        self.assertIn("scripts/publish_feishu_html.py", command_names)
        publish_cmd = next(cmd for cmd in calls if cmd[1] == "scripts/publish_feishu_html.py")
        self.assertIn("--html", publish_cmd)
        self.assertIn("output/a_share_evening_report_2026-06-12.html", publish_cmd)

    def test_archive_daily_artifacts_copies_analysis_by_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "analysis.json").write_text(json.dumps({"summary": "ok"}, ensure_ascii=False), encoding="utf-8")

            run_daily.archive_daily_artifacts("2026-06-12", data_dir=data_dir)

            archived = data_dir / "archive" / "analysis_2026-06-12.json"
            self.assertTrue(archived.exists())
            self.assertEqual(json.loads(archived.read_text(encoding="utf-8"))["summary"], "ok")


if __name__ == "__main__":
    unittest.main()
