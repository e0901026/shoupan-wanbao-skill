from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_margin_financing  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


def margin_payload(date: str, balance: int, buy: int, repay: int, short_balance: int, short_sell: int, short_repay: int):
    return {
        "result": [
            {
                "opDate": date,
                "stockCode": "600519",
                "securityAbbr": "贵州茅台",
                "rzye": balance,
                "rzmre": buy,
                "rzche": repay,
                "rqyl": short_balance,
                "rqmcl": short_sell,
                "rqchl": short_repay,
            }
        ]
    }


class FetchMarginFinancingTest(unittest.TestCase):
    def test_build_payload_calculates_net_buy_and_balance_change(self) -> None:
        payloads = {
            "20260612": margin_payload("20260612", 19194173310, 453922053, 450412417, 138228, 6000, 1407),
            "20260611": margin_payload("20260611", 19190663674, 253567840, 322295705, 133635, 1200, 8000),
        }

        def fake_get(url, params, headers, timeout):
            return FakeResponse(payloads[params["detailsDate"]])

        with patch("fetch_margin_financing.requests.get", side_effect=fake_get):
            result = fetch_margin_financing.build_margin_financing_payload(
                symbol="600519",
                name="贵州茅台",
                target_date="2026-06-12",
                max_lookback_days=3,
            )

        item = result["item"]
        self.assertEqual(result["quality"]["level"], "ok")
        self.assertEqual(item["date"], "2026-06-12")
        self.assertEqual(item["financing_balance_yi"], 191.94)
        self.assertEqual(item["financing_buy_yi"], 4.54)
        self.assertEqual(item["financing_repay_yi"], 4.5)
        self.assertEqual(item["financing_net_buy_yi"], 0.04)
        self.assertEqual(item["financing_balance_change_yi"], 0.04)
        self.assertEqual(item["short_balance_change_shares"], 4593)
        self.assertIn("上交所融资融券明细", result["sources"])

    def test_main_writes_margin_financing_json(self) -> None:
        payloads = {
            "20260612": margin_payload("20260612", 19194173310, 453922053, 450412417, 138228, 6000, 1407),
            "20260611": margin_payload("20260611", 19190663674, 253567840, 322295705, 133635, 1200, 8000),
        }

        def fake_get(url, params, headers, timeout):
            return FakeResponse(payloads[params["detailsDate"]])

        with tempfile.TemporaryDirectory() as tmp, patch("fetch_margin_financing.requests.get", side_effect=fake_get):
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            out_path = tmp_path / "margin_financing.json"
            config_path.write_text(
                yaml.safe_dump({"primary_stock": {"symbol": "600519", "name": "贵州茅台"}}, allow_unicode=True),
                encoding="utf-8",
            )
            with patch.object(
                sys,
                "argv",
                [
                    "fetch_margin_financing.py",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-06-12",
                    "--out",
                    str(out_path),
                ],
            ):
                fetch_margin_financing.main()

            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(data["item"]["stock_code"], "600519")
            self.assertEqual(data["quality"]["actual_date"], "2026-06-12")


if __name__ == "__main__":
    unittest.main()
