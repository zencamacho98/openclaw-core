from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _quote(symbol: str, mid: float, *, spread_pct: float = 0.002, last: float | None = None):
    half_spread = mid * spread_pct / 2.0
    return SimpleNamespace(
        symbol=symbol,
        midpoint=mid,
        last=last if last is not None else mid,
        bid=mid - half_spread,
        ask=mid + half_spread,
        spread_pct=spread_pct,
        data_lane="IEX_ONLY",
        is_live=True,
        source="alpaca",
    )


def _profile(
    symbol: str,
    *,
    market_cap_usd: float | None = 5_000_000_000.0,
    float_shares: float | None = 500_000_000.0,
    avg_volume: float | None = 5_000_000.0,
):
    return {
        "symbol": symbol,
        "market_cap_usd": market_cap_usd,
        "market_cap_bucket": "mid-cap" if market_cap_usd and market_cap_usd < 10_000_000_000 else "large-cap",
        "float_shares": float_shares,
        "float_bucket": "medium float" if float_shares and float_shares < 200_000_000 else "high float",
        "avg_volume": avg_volume,
    }


def _bar_context(
    *,
    gap_pct: float | None = 0.02,
    recent_volume: float = 2_000_000.0,
    bar_count: int = 24,
    intraday_change_pct: float | None = 0.015,
):
    return {
        "gap_pct": gap_pct,
        "recent_volume": recent_volume,
        "bar_count": bar_count,
        "intraday_change_pct": intraday_change_pct,
    }


class TestBelfortScanner(unittest.TestCase):

    def test_refresh_snapshot_ranks_focus_symbol_and_writes_snapshot(self):
        import app.belfort_scanner as scanner

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = pathlib.Path(tmp) / "scanner_snapshot.json"
            snapshot_path.write_text(json.dumps({
                "written_at": "2026-04-14T11:59:00+00:00",
                "focus_symbol": "SPY",
                "focus_reason": "warmup",
                "leaders": [],
                "benchmarks": [],
                "lower_price_watch": [],
                "catalysts": [],
                "universe_size": 0,
                "limitations": [],
                "history": {
                    "SPY": [{"t": "a", "mid": 497.0}, {"t": "b", "mid": 498.5}, {"t": "c", "mid": 500.0}],
                    "ABCD": [{"t": "a", "mid": 8.4}, {"t": "b", "mid": 8.7}, {"t": "c", "mid": 9.0}],
                },
            }), encoding="utf-8")
            quotes = {
                "SPY": _quote("SPY", 500.0),
                "QQQ": _quote("QQQ", 420.0),
                "IWM": _quote("IWM", 210.0),
                "AAPL": _quote("AAPL", 210.0),
                "MSFT": _quote("MSFT", 425.0),
                "NVDA": _quote("NVDA", 110.0),
                "AMD": _quote("AMD", 155.0),
                "TSLA": _quote("TSLA", 180.0),
                "META": _quote("META", 510.0),
                "AMZN": _quote("AMZN", 195.0),
                "GOOGL": _quote("GOOGL", 165.0),
                "PLTR": _quote("PLTR", 28.0, spread_pct=0.0015),
                "SOFI": _quote("SOFI", 8.0),
                "RKLB": _quote("RKLB", 19.0),
                "IONQ": _quote("IONQ", 12.0),
                "SOUN": _quote("SOUN", 6.5),
                "ACHR": _quote("ACHR", 8.5),
                "QBTS": _quote("QBTS", 4.0),
                "LCID": _quote("LCID", 2.8),
                "HIMS": _quote("HIMS", 18.5),
                "ABCD": _quote("ABCD", 9.0, spread_pct=0.0008),
            }

            def fake_get_quote(symbol: str):
                q = quotes.get(symbol.upper())
                return q or _quote(symbol.upper(), 25.0, spread_pct=0.01)

            news = [
                {
                    "headline": "ABCD lands major contract and raises revenue outlook",
                    "summary": "Fresh catalyst for ABCD",
                    "symbols": ["ABCD"],
                    "url": "https://example.com/abcd",
                    "updated_at": "2026-04-14T12:00:00+00:00",
                    "sentiment_bias": 2,
                    "source": "wire",
                }
            ]
            profiles = {sym: _profile(sym) for sym in quotes.keys()}
            profiles["ABCD"] = _profile("ABCD", market_cap_usd=600_000_000.0, float_shares=14_000_000.0, avg_volume=12_000_000.0)
            bar_context = {sym: _bar_context() for sym in quotes.keys()}
            bar_context["ABCD"] = _bar_context(gap_pct=0.045, recent_volume=5_500_000.0)

            with patch.object(scanner, "_SCANNER_SNAPSHOT", snapshot_path), \
                 patch.object(scanner, "_CACHE", {"written_at": None, "snapshot": None}), \
                 patch.object(scanner, "fetch_latest_news", return_value=news), \
                 patch("app.company_profile_feed.get_company_profiles", return_value=profiles), \
                 patch("app.market_data_feed.get_multi_symbol_bar_context", return_value=bar_context), \
                 patch("app.market_data_feed.get_quote", side_effect=fake_get_quote):
                result = scanner.refresh_scanner_snapshot(max_age_seconds=0)

            self.assertTrue(snapshot_path.exists())
            board = result["leaders"] + result["lower_price_watch"] + result["benchmarks"]
            leader = next(item for item in board if item["symbol"] == "ABCD")
            self.assertIn("watch", leader["strategy_fit"])
            self.assertIn("clean", leader["tradeability"])
            self.assertTrue(
                "stronger" in leader["relative_strength_label"] or "leading" in leader["relative_strength_label"]
            )
            self.assertFalse(leader["paper_eligible"])
            self.assertEqual(leader["tradeability_label"], "watch_only")
            self.assertIn("float", leader["tradeability_reason"].lower())
            self.assertEqual(leader["price_bucket"], "lower-price momentum watch")
            self.assertIn(leader["catalyst_type"], {"business catalyst", "earnings / numbers"})
            self.assertEqual(leader["risk_flags"], [])
            self.assertTrue(leader["board_note"])
            self.assertGreaterEqual(result["universe_size"], 10)
            self.assertIn("range expansion", " ".join(result["selection_framework"]))
            self.assertIn("relative strength vs SPY", " ".join(result["selection_framework"]))
            self.assertIn("relative_volume_leaders", result)
            self.assertIn("gap_leaders", result)
            self.assertIn("preopen_leaders", result)
            self.assertIn("opportunity_score", leader)
            self.assertIn(
                result["paper_eligible_focus_symbol"],
                {"SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "PLTR", "SOFI", "HIMS", "RKLB"},
            )

    def test_read_snapshot_returns_cached_file_when_fresh(self):
        import app.belfort_scanner as scanner

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = pathlib.Path(tmp) / "scanner_snapshot.json"
            snapshot_path.write_text(
                '{"written_at":"2999-01-01T00:00:00+00:00","focus_symbol":"PLTR","focus_reason":"cached","leaders":[],"benchmarks":[],"lower_price_watch":[],"catalysts":[],"universe_size":1,"limitations":[],"history":{}}',
                encoding="utf-8",
            )
            with patch.object(scanner, "_SCANNER_SNAPSHOT", snapshot_path):
                result = scanner.read_scanner_snapshot(max_age_seconds=75)

            self.assertEqual(result["focus_symbol"], "PLTR")
            self.assertEqual(result["focus_reason"], "cached")

    def test_refresh_snapshot_marks_dilution_risk(self):
        import app.belfort_scanner as scanner

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = pathlib.Path(tmp) / "scanner_snapshot.json"
            snapshot_path.write_text(json.dumps({
                "written_at": "2026-04-14T11:59:00+00:00",
                "focus_symbol": "SPY",
                "focus_reason": "warmup",
                "leaders": [],
                "benchmarks": [],
                "lower_price_watch": [],
                "catalysts": [],
                "universe_size": 0,
                "limitations": [],
                "history": {
                    "SPY": [{"t": "a", "mid": 498.5}, {"t": "b", "mid": 499.3}, {"t": "c", "mid": 500.0}],
                    "SOUN": [{"t": "a", "mid": 6.4}, {"t": "b", "mid": 6.7}, {"t": "c", "mid": 7.0}],
                },
            }), encoding="utf-8")
            quotes = {
                "SPY": _quote("SPY", 500.0, last=501.0),
                "QQQ": _quote("QQQ", 420.0, last=420.5),
                "IWM": _quote("IWM", 210.0, last=210.2),
                "SOUN": _quote("SOUN", 7.0, spread_pct=0.001, last=7.25),
            }

            def fake_get_quote(symbol: str):
                return quotes.get(symbol.upper()) or _quote(symbol.upper(), 20.0)

            news = [
                {
                    "headline": "SOUN announces secondary offering after strong run",
                    "summary": "Potential dilution risk for SOUN",
                    "symbols": ["SOUN"],
                    "url": "https://example.com/soun",
                    "updated_at": "2026-04-14T12:00:00+00:00",
                    "sentiment_bias": -2,
                    "source": "wire",
                }
            ]
            profiles = {sym: _profile(sym) for sym in quotes.keys()}
            profiles["SOUN"] = _profile("SOUN", market_cap_usd=190_000_000.0, float_shares=8_000_000.0, avg_volume=400_000.0)
            bar_context = {sym: _bar_context() for sym in quotes.keys()}
            bar_context["SOUN"] = _bar_context(gap_pct=0.08, recent_volume=150_000.0)

            with patch.object(scanner, "_SCANNER_SNAPSHOT", snapshot_path), \
                 patch.object(scanner, "_CACHE", {"written_at": None, "snapshot": None}), \
                 patch.object(scanner, "fetch_latest_news", return_value=news), \
                 patch("app.company_profile_feed.get_company_profiles", return_value=profiles), \
                 patch("app.market_data_feed.get_multi_symbol_bar_context", return_value=bar_context), \
                 patch("app.market_data_feed.get_quote", side_effect=fake_get_quote):
                result = scanner.refresh_scanner_snapshot(max_age_seconds=0)

            board = result["leaders"] + result["lower_price_watch"] + result["benchmarks"]
            candidate = next(item for item in board if item["symbol"] == "SOUN")
            self.assertEqual(candidate["catalyst_type"], "financing / dilution risk")
            self.assertIn("dilution risk", candidate["risk_flags"])
            self.assertTrue(candidate["relative_strength_label"])
            self.assertFalse(candidate["paper_eligible"])
            self.assertIn(candidate["tradeability_label"], {"watch_only", "blocked"})
            self.assertTrue(candidate["tradeability_reason"])

    def test_phase1_midcap_allowlist_can_become_eligible(self):
        import app.belfort_scanner as scanner

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = pathlib.Path(tmp) / "scanner_snapshot.json"
            snapshot_path.write_text(json.dumps({
                "written_at": "2026-04-14T11:59:00+00:00",
                "focus_symbol": "SPY",
                "focus_reason": "warmup",
                "leaders": [],
                "benchmarks": [],
                "lower_price_watch": [],
                "catalysts": [],
                "universe_size": 0,
                "limitations": [],
                "history": {
                    "SPY": [{"t": "a", "mid": 500.0}, {"t": "b", "mid": 500.5}, {"t": "c", "mid": 501.0}],
                    "SOFI": [{"t": "a", "mid": 16.4}, {"t": "b", "mid": 16.7}, {"t": "c", "mid": 17.1}],
                },
            }), encoding="utf-8")
            quotes = {
                "SPY": _quote("SPY", 501.0, spread_pct=0.001),
                "QQQ": _quote("QQQ", 420.0, spread_pct=0.001),
                "IWM": _quote("IWM", 210.0, spread_pct=0.001),
                "SOFI": _quote("SOFI", 17.1, spread_pct=0.004, last=17.3),
            }

            def fake_get_quote(symbol: str):
                return quotes.get(symbol.upper()) or _quote(symbol.upper(), 25.0, spread_pct=0.006)

            profiles = {sym: _profile(sym, market_cap_usd=900_000_000.0, float_shares=180_000_000.0, avg_volume=12_000_000.0) for sym in quotes.keys()}
            bar_context = {sym: _bar_context(gap_pct=0.015, recent_volume=8_000_000.0) for sym in quotes.keys()}

            with patch.object(scanner, "_SCANNER_SNAPSHOT", snapshot_path), \
                 patch.object(scanner, "_CACHE", {"written_at": None, "snapshot": None}), \
                 patch.object(scanner, "fetch_latest_news", return_value=[]), \
                 patch("app.company_profile_feed.get_company_profiles", return_value=profiles), \
                 patch("app.market_data_feed.get_multi_symbol_bar_context", return_value=bar_context), \
                 patch("app.market_data_feed.get_quote", side_effect=fake_get_quote):
                result = scanner.refresh_scanner_snapshot(max_age_seconds=0)

            board = result["leaders"] + result["lower_price_watch"] + result["benchmarks"]
            sofi = next(item for item in board if item["symbol"] == "SOFI")
            self.assertTrue(sofi["paper_eligible"])
            self.assertEqual(sofi["tradeability_label"], "eligible")
            self.assertIn("expanded liquid-volatility universe", sofi["tradeability_reason"].lower())

    def test_dynamic_small_cap_can_become_paper_eligible_when_structure_is_clean(self):
        import app.belfort_scanner as scanner

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = pathlib.Path(tmp) / "scanner_snapshot.json"
            snapshot_path.write_text(json.dumps({
                "written_at": "2026-04-14T11:59:00+00:00",
                "focus_symbol": "SPY",
                "focus_reason": "warmup",
                "leaders": [],
                "benchmarks": [],
                "lower_price_watch": [],
                "catalysts": [],
                "universe_size": 0,
                "limitations": [],
                "history": {
                    "SPY": [{"t": "a", "mid": 500.0}, {"t": "b", "mid": 500.8}, {"t": "c", "mid": 501.2}],
                    "ASTS": [{"t": "a", "mid": 23.9}, {"t": "b", "mid": 24.3}, {"t": "c", "mid": 24.9}],
                },
            }), encoding="utf-8")
            quotes = {
                "SPY": _quote("SPY", 501.2, spread_pct=0.001),
                "QQQ": _quote("QQQ", 420.0, spread_pct=0.001),
                "IWM": _quote("IWM", 210.0, spread_pct=0.001),
                "ASTS": _quote("ASTS", 24.9, spread_pct=0.008, last=25.1),
            }

            def fake_get_quote(symbol: str):
                return quotes.get(symbol.upper()) or _quote(symbol.upper(), 25.0, spread_pct=0.006)

            profiles = {sym: _profile(sym) for sym in quotes.keys()}
            profiles["ASTS"] = _profile("ASTS", market_cap_usd=1_600_000_000.0, float_shares=46_000_000.0, avg_volume=9_500_000.0)
            bar_context = {sym: _bar_context(gap_pct=0.03, recent_volume=7_000_000.0) for sym in quotes.keys()}

            with patch.object(scanner, "_SCANNER_SNAPSHOT", snapshot_path), \
                 patch.object(scanner, "_CACHE", {"written_at": None, "snapshot": None}), \
                 patch.object(scanner, "fetch_latest_news", return_value=[]), \
                 patch("app.company_profile_feed.get_company_profiles", return_value=profiles), \
                 patch("app.market_data_feed.get_multi_symbol_bar_context", return_value=bar_context), \
                 patch("app.market_data_feed.get_quote", side_effect=fake_get_quote):
                result = scanner.refresh_scanner_snapshot(max_age_seconds=0)

            board = result["leaders"] + result["lower_price_watch"] + result["benchmarks"]
            asts = next(item for item in board if item["symbol"] == "ASTS")
            self.assertTrue(asts["paper_eligible"])
            self.assertEqual(asts["tradeability_label"], "eligible")
            self.assertIn("expanded liquid-volatility universe", asts["tradeability_reason"].lower())
            self.assertIn("mid-cap", asts["structure_label"])
            self.assertIsNotNone(asts["relative_volume"])
            self.assertGreater(asts["relative_volume"], 0.8)

    def test_low_relative_volume_keeps_name_watch_only(self):
        import app.belfort_scanner as scanner

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = pathlib.Path(tmp) / "scanner_snapshot.json"
            snapshot_path.write_text(json.dumps({
                "written_at": "2026-04-14T11:59:00+00:00",
                "focus_symbol": "SPY",
                "focus_reason": "warmup",
                "leaders": [],
                "benchmarks": [],
                "lower_price_watch": [],
                "catalysts": [],
                "universe_size": 0,
                "limitations": [],
                "history": {
                    "SPY": [{"t": "a", "mid": 500.0}, {"t": "b", "mid": 500.8}, {"t": "c", "mid": 501.2}],
                    "TEM": [{"t": "a", "mid": 56.0}, {"t": "b", "mid": 56.5}, {"t": "c", "mid": 57.0}],
                },
            }), encoding="utf-8")
            quotes = {
                "SPY": _quote("SPY", 501.2, spread_pct=0.001),
                "QQQ": _quote("QQQ", 420.0, spread_pct=0.001),
                "IWM": _quote("IWM", 210.0, spread_pct=0.001),
                "TEM": _quote("TEM", 57.0, spread_pct=0.006, last=57.2),
            }

            def fake_get_quote(symbol: str):
                return quotes.get(symbol.upper()) or _quote(symbol.upper(), 25.0, spread_pct=0.006)

            profiles = {sym: _profile(sym, market_cap_usd=2_500_000_000.0, float_shares=90_000_000.0, avg_volume=8_000_000.0) for sym in quotes.keys()}
            bar_context = {sym: _bar_context(gap_pct=0.01, recent_volume=250_000.0) for sym in quotes.keys()}

            with patch.object(scanner, "_SCANNER_SNAPSHOT", snapshot_path), \
                 patch.object(scanner, "_CACHE", {"written_at": None, "snapshot": None}), \
                 patch.object(scanner, "fetch_latest_news", return_value=[]), \
                 patch("app.company_profile_feed.get_company_profiles", return_value=profiles), \
                 patch("app.market_data_feed.get_multi_symbol_bar_context", return_value=bar_context), \
                 patch("app.market_data_feed.get_quote", side_effect=fake_get_quote):
                result = scanner.refresh_scanner_snapshot(max_age_seconds=0)

            board = result["leaders"] + result["lower_price_watch"] + result["benchmarks"]
            tem = next(item for item in board if item["symbol"] == "TEM")
            self.assertFalse(tem["paper_eligible"])
            self.assertEqual(tem["tradeability_label"], "watch_only")
            self.assertIn("relative volume", tem["tradeability_reason"].lower())

    def test_preopen_score_favors_gap_and_flow_names(self):
        import app.belfort_scanner as scanner

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = pathlib.Path(tmp) / "scanner_snapshot.json"
            snapshot_path.write_text(json.dumps({
                "written_at": "2026-04-14T11:59:00+00:00",
                "focus_symbol": "SPY",
                "focus_reason": "warmup",
                "leaders": [],
                "benchmarks": [],
                "lower_price_watch": [],
                "catalysts": [],
                "universe_size": 0,
                "limitations": [],
                "history": {
                    "SPY": [{"t": "a", "mid": 500.0}, {"t": "b", "mid": 500.5}, {"t": "c", "mid": 501.0}],
                    "ASTS": [{"t": "a", "mid": 23.8}, {"t": "b", "mid": 24.2}, {"t": "c", "mid": 24.9}],
                    "AAPL": [{"t": "a", "mid": 200.0}, {"t": "b", "mid": 200.2}, {"t": "c", "mid": 200.3}],
                },
            }), encoding="utf-8")
            quotes = {
                "SPY": _quote("SPY", 501.0, spread_pct=0.001),
                "QQQ": _quote("QQQ", 420.0, spread_pct=0.001),
                "IWM": _quote("IWM", 210.0, spread_pct=0.001),
                "ASTS": _quote("ASTS", 24.9, spread_pct=0.006, last=25.1),
                "AAPL": _quote("AAPL", 200.3, spread_pct=0.001, last=200.4),
            }

            def fake_get_quote(symbol: str):
                return quotes.get(symbol.upper()) or _quote(symbol.upper(), 25.0, spread_pct=0.006)

            profiles = {sym: _profile(sym) for sym in quotes.keys()}
            profiles["ASTS"] = _profile("ASTS", market_cap_usd=1_600_000_000.0, float_shares=46_000_000.0, avg_volume=9_500_000.0)
            bar_context = {sym: _bar_context(gap_pct=0.005, recent_volume=900_000.0) for sym in quotes.keys()}
            bar_context["ASTS"] = _bar_context(gap_pct=0.045, recent_volume=7_000_000.0)

            with patch.object(scanner, "_SCANNER_SNAPSHOT", snapshot_path), \
                 patch.object(scanner, "_CACHE", {"written_at": None, "snapshot": None}), \
                 patch.object(scanner, "fetch_latest_news", return_value=[]), \
                 patch("app.company_profile_feed.get_company_profiles", return_value=profiles), \
                 patch("app.market_data_feed.get_multi_symbol_bar_context", return_value=bar_context), \
                 patch("app.market_data_feed.get_quote", side_effect=fake_get_quote), \
                 patch("app.market_time.session_type", return_value="pre_market"):
                result = scanner.refresh_scanner_snapshot(max_age_seconds=0)

            preopen = result["preopen_leaders"]
            self.assertTrue(preopen)
            self.assertEqual(preopen[0]["symbol"], "ASTS")
            self.assertGreater(preopen[0]["opportunity_score"], 0)


if __name__ == "__main__":
    unittest.main()
