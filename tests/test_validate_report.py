from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidateReportTest(unittest.TestCase):
    def test_strict_fund_flow_fails_on_degraded_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = tmp_path / "report.md"
            analysis = tmp_path / "analysis.json"
            header = "| 板块 | 净流入（亿） | 超大单（亿） | 大单（亿） | 小单（亿） | 涨跌幅 % | 成交额（亿） | 净流入率 % |"
            report.write_text(
                "\n".join(
                    [
                        "# 📊 股市收盘晚报 | 2026年06月12日（周五）",
                        "### 🔥 净流入 TOP 10",
                        header,
                        "### 💧 净流出 TOP 10",
                        header,
                        "### 🔴 背离一：净流入 ↗ 但股价跌",
                        header,
                        "### 🟢 背离二：净流出 ↘ 但股价涨",
                        header,
                        "### 🔶 背离三：超大单 ↑ + 大单 ↓",
                        header,
                        "### 🔶 背离四：超大单 ↓ + 大单 ↑",
                        header,
                        "## 🍶 白酒板块",
                        header,
                        "## 🧾 数据来源与抓取说明",
                        "## ⚠️ 风险提示",
                    ]
                ),
                encoding="utf-8",
            )
            row = {"板块": "证券", "净流入（亿）": 69.68}
            analysis.write_text(
                json.dumps(
                    {
                        "quotes": {
                            "quotes": {
                                "600519": {"收盘价": 1291.91},
                                "000858": {"收盘价": 79.92},
                                "600809": {"收盘价": 118.54},
                                "000568": {"收盘价": 85.0},
                                "002304": {"收盘价": 43.0},
                            }
                        },
                        "fund_flow": {
                            "quality": {"level": "degraded", "source_mode": "10jqka_degraded"},
                            "inflow_top5": [row],
                            "outflow_top5": [row],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            default_result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/validate_report.py"), "--report", str(report), "--analysis", str(analysis)],
                text=True,
                capture_output=True,
                check=False,
            )
            strict_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/validate_report.py"),
                    "--report",
                    str(report),
                    "--analysis",
                    str(analysis),
                    "--strict-fund-flow",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(default_result.returncode, 0, default_result.stdout + default_result.stderr)
            self.assertNotEqual(strict_result.returncode, 0)
            self.assertIn("严格资金流门禁失败", strict_result.stdout)


if __name__ == "__main__":
    unittest.main()
