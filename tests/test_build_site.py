from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402


class BuildSiteTest(unittest.TestCase):
    def test_build_site_only_publishes_canonical_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            site = root / "site"
            output.mkdir()
            (output / "a_share_evening_report_2026-07-31.html").write_text(
                "<html><body><h1>A股收盘晚报 2026-07-31</h1></body></html>", encoding="utf-8"
            )
            (output / "a_share_evening_report_2026-07-31.pdf").write_bytes(b"pdf")
            (output / "a_share_evening_report_2026-07-31.pandoc-header.html").write_text("skip", encoding="utf-8")
            (site / "stale.html").parent.mkdir(parents=True)
            (site / "stale.html").write_text("stale", encoding="utf-8")

            manifest = build_site.build_site(output, site)

            self.assertEqual(manifest["report_total"], 1)
            self.assertEqual(manifest["pdf_total"], 1)
            self.assertTrue((site / "index.html").exists())
            self.assertTrue((site / "a_share_evening_report_2026-07-31.html").exists())
            self.assertTrue((site / "a_share_evening_report_2026-07-31.pdf").exists())
            self.assertFalse((site / "a_share_evening_report_2026-07-31.pandoc-header.html").exists())
            self.assertFalse((site / "stale.html").exists())
            saved = json.loads((site / "site-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["report_counts"]["daily"], 1)
            rebuilt = build_site.build_site(output, site)
            self.assertEqual(rebuilt["content_hash"], saved["content_hash"])
            self.assertEqual(rebuilt["generated_at"], saved["generated_at"])


if __name__ == "__main__":
    unittest.main()
