from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_html  # noqa: E402


class RenderHtmlTest(unittest.TestCase):
    def test_fallback_renderer_outputs_tables_and_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.md"
            out_path = tmp_path / "report.html"
            report_path.write_text(
                "\n".join(
                    [
                        "# 测试晚报",
                        "",
                        "| 板块 | 净流入（亿） |",
                        "|---|---:|",
                        "| 工业金属 | +83.69 |",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch("shutil.which", return_value=None),
                patch.object(
                    sys,
                    "argv",
                    [
                        "render_html.py",
                        "--report",
                        str(report_path),
                        "--out",
                        str(out_path),
                        "--title",
                        "A股收盘晚报",
                    ],
                ),
            ):
                render_html.main()

            html = out_path.read_text(encoding="utf-8")
            self.assertIn("<title>A股收盘晚报</title>", html)
            self.assertIn("<table>", html)
            self.assertIn("<td>工业金属</td>", html)
            self.assertIn("white-space: nowrap", html)
            self.assertIn("a { color: #2563eb", html)
            self.assertIn('class="pdf-export"', html)
            self.assertIn('href="report.pdf"', html)

    def test_fallback_renderer_outputs_clickable_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.md"
            out_path = tmp_path / "report.html"
            report_path.write_text(
                "\n".join(
                    [
                        "# 测试晚报",
                        "",
                        "**[贵州茅台调价新闻](https://example.com/news)**",
                    ]
                ),
                encoding="utf-8",
            )

            render_html.write_fallback_html(report_path, out_path, "A股收盘晚报")

            html = out_path.read_text(encoding="utf-8")
            self.assertIn('<a href="https://example.com/news">贵州茅台调价新闻</a>', html)
            self.assertNotIn("[贵州茅台调价新闻]", html)
            self.assertIn("导出PDF", html)

    def test_pandoc_renderer_injects_report_css(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.md"
            out_path = tmp_path / "report.html"
            report_path.write_text("# 测试晚报\n", encoding="utf-8")
            calls = []

            def fake_run(cmd, check):
                calls.append(cmd)
                Path(cmd[cmd.index("-o") + 1]).write_text("<html><head></head><body><h1>测试晚报</h1></body></html>", encoding="utf-8")

            with patch("subprocess.run", side_effect=fake_run):
                render_html.render_with_pandoc(report_path, out_path, "A股收盘晚报")

            cmd = calls[0]
            self.assertIn("--include-in-header", cmd)
            header_path = Path(cmd[cmd.index("--include-in-header") + 1])
            self.assertTrue(header_path.exists())
            self.assertIn("white-space: nowrap", header_path.read_text(encoding="utf-8"))
            self.assertIn("a { color: #2563eb", header_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
