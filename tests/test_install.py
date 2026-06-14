from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install  # noqa: E402


class InstallTest(unittest.TestCase):
    def test_check_required_tokens_requires_tushare(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            missing = install.missing_required_tokens(enable_feishu=False)

        self.assertIn("TUSHARE_TOKEN", missing)
        self.assertNotIn("FEISHU_APP_ID", missing)

    def test_check_required_tokens_requires_feishu_only_when_enabled(self) -> None:
        with patch.dict(os.environ, {"TUSHARE_TOKEN": "token"}, clear=True):
            missing = install.missing_required_tokens(enable_feishu=True)

        self.assertIn("FEISHU_APP_ID", missing)
        self.assertIn("FEISHU_APP_SECRET", missing)
        self.assertIn("FEISHU_RECEIVE_ID", missing)

    def test_install_wizard_writes_config_with_feishu_choice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            example = tmp_path / "config.example.yaml"
            config = tmp_path / "config.yaml"
            example.write_text(
                yaml.safe_dump({"feishu": {"dry_run": True}, "primary_stock": {"symbol": "600519"}}, allow_unicode=True),
                encoding="utf-8",
            )

            install.write_config(example, config, enable_feishu=True)

            payload = yaml.safe_load(config.read_text(encoding="utf-8"))
            self.assertFalse(payload["feishu"]["dry_run"])


if __name__ == "__main__":
    unittest.main()
