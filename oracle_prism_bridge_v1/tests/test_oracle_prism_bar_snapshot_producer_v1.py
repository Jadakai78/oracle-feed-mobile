"""Tests for oracle_prism_bar_snapshot_producer_v1.py.

All tests use dependency-injected/mocked fetch data only. No live Kraken
calls are made anywhere in this file.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import oracle_prism_bar_snapshot_producer_v1 as bridge  # noqa: E402


FIXED_CLOCK = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
START_EPOCH = 1_700_000_000  # arbitrary fixed base epoch, interval-start


def make_row(index: int, price: float = 100.0) -> list:
    """One synthetic Kraken OHLC row: [time, open, high, low, close, vwap, volume, count]."""
    start = START_EPOCH + index * bridge.BAR_INTERVAL_SECONDS
    return [start, price, price + 1.0, price - 1.0, price, price, 10.0, 5]


def make_kraken_payload(symbol: str, count: int, price: float = 100.0, include_inprogress: bool = True) -> dict:
    rows = [make_row(i, price) for i in range(count)]
    if include_inprogress:
        # Final in-progress row -- must always be dropped, regardless of shape.
        rows.append([START_EPOCH + count * bridge.BAR_INTERVAL_SECONDS, price, price, price, price, price, 1.0, 1])
    return {"error": [], "result": {symbol: rows, "last": rows[-1][0]}}


def fetcher_from_payloads(payloads: dict):
    def _fetch(pair: str):
        if pair not in payloads:
            raise AssertionError(f"unexpected pair requested: {pair}")
        return payloads[pair]
    return _fetch


class TestCompletedRowExclusion(unittest.TestCase):
    def test_final_in_progress_row_excluded(self):
        payload = make_kraken_payload("SOLUSD", 390, include_inprogress=True)
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        # 390 completed + 1 in-progress were provided; exactly 390 completed remain.
        self.assertEqual(len(record["bars"]), 390)


class TestTimestampConversion(unittest.TestCase):
    def test_known_epoch_converts_to_exact_close_plus_900(self):
        payload = make_kraken_payload("SOLUSD", 390)
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        first_bar = record["bars"][0]
        expected_start = START_EPOCH  # exactly 390 rows supplied, so all are retained starting at index 0
        expected_close = datetime.fromtimestamp(expected_start + bridge.BAR_INTERVAL_SECONDS, timezone.utc)
        expected_text = expected_close.isoformat().replace("+00:00", "Z")
        self.assertEqual(first_bar["timestamp"], expected_text)

    def test_exact_formula_on_single_known_row(self):
        bar = bridge._row_to_bar([1_000_000_000, 1.0, 2.0, 0.5, 1.5, 1.0, 10.0, 3])
        expected = datetime.fromtimestamp(1_000_000_000 + 900, timezone.utc).isoformat().replace("+00:00", "Z")
        self.assertEqual(bar["timestamp"], expected)
        self.assertTrue(bar["timestamp"].endswith("Z"))


class TestBarKeys(unittest.TestCase):
    def test_all_six_bar_keys_and_only_those(self):
        payload = make_kraken_payload("SOLUSD", 390)
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        for bar in record["bars"]:
            self.assertEqual(set(bar.keys()), bridge.BAR_KEYS)


class TestRetentionCount(unittest.TestCase):
    def test_390_plus_retains_exactly_newest_390(self):
        payload = make_kraken_payload("SOLUSD", 500)
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(len(record["bars"]), 390)
        # Newest retained bar must correspond to the last completed row (index 499).
        expected_last_start = START_EPOCH + 499 * bridge.BAR_INTERVAL_SECONDS
        expected_close = datetime.fromtimestamp(expected_last_start + bridge.BAR_INTERVAL_SECONDS, timezone.utc)
        expected_text = expected_close.isoformat().replace("+00:00", "Z")
        self.assertEqual(record["bars"][-1]["timestamp"], expected_text)

    def test_fewer_than_390_yields_empty_bars(self):
        payload = make_kraken_payload("SOLUSD", 389)
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})


class TestFailureIsolation(unittest.TestCase):
    def test_fetch_exception_yields_empty_bars_for_only_that_pair(self):
        def fetch(pair):
            if pair == "SOL/USD":
                raise RuntimeError("network down")
            return make_kraken_payload(bridge.kraken_symbol(pair), 390)

        snapshot = bridge.build_snapshot(["SOL/USD", "ETH/USD"], fetch=fetch, generated_at=FIXED_CLOCK)
        pairs_by_name = {entry["pair"]: entry for entry in snapshot["pairs"]}
        self.assertEqual(pairs_by_name["SOL/USD"]["bars"], [])
        self.assertEqual(len(pairs_by_name["ETH/USD"]["bars"]), 390)

    def test_malformed_kraken_response_yields_empty_bars(self):
        fetch = fetcher_from_payloads({"SOL/USD": {"error": ["EQuery:Unknown asset pair"], "result": {}}})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})

    def test_malformed_response_missing_result_key(self):
        fetch = fetcher_from_payloads({"SOL/USD": {"error": []}})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})

    def test_non_dict_response_yields_empty_bars(self):
        fetch = fetcher_from_payloads({"SOL/USD": "not json"})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})


class TestOhlcvValidation(unittest.TestCase):
    def test_non_finite_zero_or_negative_ohlcv_yields_empty_bars(self):
        rows = [make_row(i) for i in range(390)]
        rows[10][4] = 0.0  # close = 0, not strictly positive
        payload = {"error": [], "result": {"SOLUSD": rows + [rows[-1]], "last": rows[-1][0]}}
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})

    def test_negative_volume_yields_empty_bars(self):
        rows = [make_row(i) for i in range(390)]
        rows[5][6] = -1.0
        payload = {"error": [], "result": {"SOLUSD": rows + [rows[-1]], "last": rows[-1][0]}}
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})

    def test_invalid_ohlc_ordering_yields_empty_bars(self):
        rows = [make_row(i) for i in range(390)]
        # Break ordering: low above open/close.
        rows[20] = [rows[20][0], 100.0, 101.0, 105.0, 100.0, 100.0, 10.0, 5]
        payload = {"error": [], "result": {"SOLUSD": rows + [rows[-1]], "last": rows[-1][0]}}
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})


class TestTimestampDiscontinuity(unittest.TestCase):
    def test_timestamp_gap_yields_empty_bars(self):
        rows = [make_row(i) for i in range(390)]
        # Introduce a gap by skipping ahead for one row's start epoch.
        rows[50][0] = rows[50][0] + bridge.BAR_INTERVAL_SECONDS
        payload = {"error": [], "result": {"SOLUSD": rows + [rows[-1]], "last": rows[-1][0]}}
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        record = bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(record, {"pair": "SOL/USD", "bars": []})


class TestAliasMapping(unittest.TestCase):
    def test_btc_and_doge_aliases(self):
        self.assertEqual(bridge.kraken_symbol("BTC/USD"), "XBTUSD")
        self.assertEqual(bridge.kraken_symbol("DOGE/USD"), "XDGUSD")

    def test_unmapped_pair_uses_plain_concatenation(self):
        self.assertEqual(bridge.kraken_symbol("SOL/USD"), "SOLUSD")
        self.assertEqual(bridge.kraken_symbol("MATIC/USD"), "MATICUSD")
        self.assertEqual(bridge.kraken_symbol("RNDR/USD"), "RNDRUSD")


class TestMultiplePairsOrderingAndIsolation(unittest.TestCase):
    def test_order_preserved_and_failures_isolated(self):
        def fetch(pair):
            if pair == "ETH/USD":
                raise RuntimeError("boom")
            return make_kraken_payload(bridge.kraken_symbol(pair), 390)

        pairs = ["SOL/USD", "ETH/USD", "BTC/USD"]
        snapshot = bridge.build_snapshot(pairs, fetch=fetch, generated_at=FIXED_CLOCK)
        result_order = [entry["pair"] for entry in snapshot["pairs"]]
        self.assertEqual(result_order, pairs)
        pairs_by_name = {entry["pair"]: entry for entry in snapshot["pairs"]}
        self.assertEqual(pairs_by_name["ETH/USD"]["bars"], [])
        self.assertEqual(len(pairs_by_name["SOL/USD"]["bars"]), 390)
        self.assertEqual(len(pairs_by_name["BTC/USD"]["bars"]), 390)


class TestAtomicOutput(unittest.TestCase):
    def test_atomic_output_valid_json_no_temp_residue(self):
        payload = bridge.build_snapshot(
            ["SOL/USD"],
            fetch=fetcher_from_payloads({"SOL/USD": make_kraken_payload("SOLUSD", 390)}),
            generated_at=FIXED_CLOCK,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "snapshot.json"
            bridge.write_snapshot_atomic(payload, output_path)
            self.assertTrue(output_path.exists())
            with open(output_path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            self.assertEqual(loaded["recordtype"], bridge.OUTPUT_RECORDTYPE)
            leftover = [name for name in os.listdir(tmpdir) if name != "snapshot.json"]
            self.assertEqual(leftover, [])


class TestExactKeySets(unittest.TestCase):
    def test_snapshot_exact_key_sets_hold_at_all_levels(self):
        payload = bridge.build_snapshot(
            ["SOL/USD", "ETH/USD"],
            fetch=fetcher_from_payloads({
                "SOL/USD": make_kraken_payload("SOLUSD", 390),
                "ETH/USD": {"error": ["bad"], "result": {}},
            }),
            generated_at=FIXED_CLOCK,
        )
        self.assertEqual(set(payload.keys()), bridge.TOP_LEVEL_KEYS)
        for entry in payload["pairs"]:
            self.assertEqual(set(entry.keys()), bridge.PAIR_ENTRY_KEYS)
            for bar in entry["bars"]:
                self.assertEqual(set(bar.keys()), bridge.BAR_KEYS)


class TestImmutability(unittest.TestCase):
    def test_input_mock_response_not_mutated(self):
        payload = make_kraken_payload("SOLUSD", 390)
        payload_before = copy.deepcopy(payload)
        fetch = fetcher_from_payloads({"SOL/USD": payload})
        bridge.build_pair_snapshot("SOL/USD", fetch)
        self.assertEqual(payload, payload_before)


class TestCliBehavior(unittest.TestCase):
    def test_cli_success_writes_snapshot_with_injected_fetcher(self):
        import tempfile

        payload_source = fetcher_from_payloads({
            pair: make_kraken_payload(bridge.kraken_symbol(pair), 390) for pair in ["SOL/USD", "BTC/USD"]
        })

        original_default_fetch = bridge.default_fetch
        bridge.default_fetch = payload_source
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = str(Path(tmpdir) / "out.json")
                exit_code = bridge.main(["--output", output_path, "--pairs", "SOL/USD", "BTC/USD"])
                self.assertEqual(exit_code, 0)
                with open(output_path, encoding="utf-8") as handle:
                    loaded = json.load(handle)
                self.assertEqual(len(loaded["pairs"]), 2)
        finally:
            bridge.default_fetch = original_default_fetch

    def test_cli_configuration_failure_exits_nonzero_and_writes_nothing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "out.json")
            exit_code = bridge.main(["--output", output_path, "--pairs", " SOL/USD "])
            self.assertNotEqual(exit_code, 0)
            self.assertFalse(Path(output_path).exists())


if __name__ == "__main__":
    unittest.main()
