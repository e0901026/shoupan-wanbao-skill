from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_feishu_html  # noqa: E402


class PublishFeishuHtmlTest(unittest.TestCase):
    def test_html_to_docx_blocks_preserves_headings_paragraphs_links_and_tables(self) -> None:
        html = """
        <html><body>
          <h1>股市收盘晚报</h1>
          <h2>机构观点</h2>
          <p><strong>高盛</strong> · 买入 · <a href="https://example.com">1616 元</a></p>
          <table>
            <tr><th>板块</th><th>净流入</th></tr>
            <tr><td>白酒Ⅱ</td><td>1.23</td></tr>
          </table>
        </body></html>
        """

        blocks = publish_feishu_html.html_to_docx_blocks(html)

        self.assertEqual(blocks[0]["block_type"], "heading1")
        self.assertEqual(blocks[0]["text"], "股市收盘晚报")
        self.assertEqual(blocks[1]["block_type"], "heading2")
        self.assertEqual(blocks[2]["block_type"], "paragraph")
        self.assertIn("高盛", blocks[2]["text"])
        self.assertIn("https://example.com", blocks[2]["links"])
        self.assertEqual(blocks[3]["block_type"], "table")
        self.assertEqual(blocks[3]["rows"][1], ["白酒Ⅱ", "1.23"])

    def test_dry_run_writes_preview_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            html_path = tmp_path / "report.html"
            analysis_path = tmp_path / "analysis.json"
            out_path = tmp_path / "preview.json"
            config_path.write_text(yaml.safe_dump({"feishu": {"dry_run": True}}, allow_unicode=True), encoding="utf-8")
            html_path.write_text("<html><body><h1>A股收盘晚报</h1><p>内容</p></body></html>", encoding="utf-8")
            analysis_path.write_text(json.dumps({"generated_at": "2026-06-12 17:30:00"}, ensure_ascii=False), encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "publish_feishu_html.py",
                    "--config",
                    str(config_path),
                    "--html",
                    str(html_path),
                    "--analysis",
                    str(analysis_path),
                    "--dry-run-out",
                    str(out_path),
                ],
            ):
                publish_feishu_html.main()

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["title"], "A股收盘晚报")
            self.assertEqual(payload["docx_blocks"][0]["block_type"], "heading1")
            self.assertIn("分享卡片", payload["card_preview"]["elements"][0]["text"]["content"])

    def test_validate_env_value_rejects_placeholders_and_truncated_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "FEISHU_APP_SECRET"):
            publish_feishu_html.validate_env_value("FEISHU_APP_SECRET", "abc...")

        with self.assertRaisesRegex(RuntimeError, "FEISHU_RECEIVE_ID"):
            publish_feishu_html.validate_env_value("FEISHU_RECEIVE_ID", "oc_xxx")

    def test_required_env_names_skip_receive_id_for_doc_only(self) -> None:
        self.assertEqual(
            publish_feishu_html.required_env_names(doc_only=True),
            ["FEISHU_APP_ID", "FEISHU_APP_SECRET"],
        )
        self.assertIn("FEISHU_RECEIVE_ID", publish_feishu_html.required_env_names(doc_only=False))

    def test_feishu_http_error_includes_response_body(self) -> None:
        response = requests.Response()
        response.status_code = 400
        response._content = b'{"code":999,"msg":"invalid receive_id"}'
        response.url = "https://open.feishu.cn/open-apis/im/v1/messages"

        with self.assertRaisesRegex(RuntimeError, "invalid receive_id"):
            publish_feishu_html.ensure_feishu_ok(response, "send card")


if __name__ == "__main__":
    unittest.main()
