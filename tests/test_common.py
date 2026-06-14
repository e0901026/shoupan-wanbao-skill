from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402


class CommonTest(unittest.TestCase):
    def test_market_session_ignores_environment_proxies(self) -> None:
        session = common.market_session()

        self.assertFalse(session.trust_env)


if __name__ == "__main__":
    unittest.main()
