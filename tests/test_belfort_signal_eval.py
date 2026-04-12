# tests/test_belfort_signal_eval.py
#
# BELFORT-SIGNAL-EVAL-01: Signal evaluation path tests.
#
# Tests cover:
#   - SHADOW mode evaluates strategy on eligible ticks
#   - OBSERVATION mode skips evaluation (no log write)
#   - PAPER mode evaluates but doesn't execute
#   - Risk guardrail result is logged with signal
#   - Hold decisions logged with was_executed=False
#   - Blocked decisions logged with risk_block_reason
#   - was_executed is always False
#   - read_latest_signal_decision returns most recent non-skipped record
#   - read_signal_stats_today aggregates correctly
#   - Peter response includes signal summary without implying execution
#   - UI-facing _belfort_state includes belfort_latest_signal

from __future__ import annotations

import json
import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_quote(
    symbol:    str   = "SPY",
    bid:       float = 510.0,
    ask:       float = 510.10,
    data_lane: str   = "IEX_ONLY",
) -> MagicMock:
    q = MagicMock()
    q.symbol    = symbol
    q.bid       = bid
    q.ask       = ask
    q.last      = ask
    q.data_lane = data_lane
    return q


def _make_portfolio(
    cash:         float = 50000.0,
    realized_pnl: float = 0.0,
    trade_count:  int   = 0,
) -> dict:
    return {
        "cash":         cash,
        "realized_pnl": realized_pnl,
        "trade_count":  trade_count,
        "positions":    {},
    }


# ── evaluate_signal: mode gates ───────────────────────────────────────────────

class TestEvaluateSignalModeGate:
    def test_observation_mode_skips(self, tmp_path):
        from app.belfort_signal_eval import evaluate_signal
        q = _make_quote()
        with patch("app.belfort_signal_eval._SIGNAL_LOG", tmp_path / "signal_log.jsonl"):
            result = evaluate_signal(q, mode="observation")
        assert result["skipped"] is True
        assert result["was_executed"] is False
        # Nothing written to log
        assert not (tmp_path / "signal_log.jsonl").exists()

    def test_shadow_mode_evaluates(self, tmp_path):
        from app.belfort_signal_eval import evaluate_signal
        q = _make_quote()
        with (
            patch("app.belfort_signal_eval._SIGNAL_LOG", tmp_path / "signal_log.jsonl"),
            patch("app.belfort_signal_eval._strategy") as mock_strat,
            patch("app.belfort_signal_eval._guardrails") as mock_risk,
            patch("app.market_time.session_type", return_value="regular", create=True),
        ):
            from app.belfort_strategy import BelfortSignal
            from datetime import datetime, timezone
            mock_strat.evaluate.return_value = BelfortSignal(
                symbol="SPY", action="hold", qty=0, order_type="none",
                limit_price=0.0, rationale="no edge", data_lane="IEX_ONLY",
                session_type="regular", generated_at=datetime.now(timezone.utc).isoformat(),
            )
            from app.belfort_risk import RiskCheckResult
            mock_risk.check.return_value = RiskCheckResult(
                passed=True, block_reason=None, check_name="hold_passthrough",
                signal=mock_strat.evaluate.return_value,
            )
            result = evaluate_signal(q, mode="shadow")

        assert result.get("skipped") is not True
        assert result["mode"] == "shadow"
        assert result["was_executed"] is False
        assert result["execution_mode"] == "none"

    def test_paper_mode_evaluates(self, tmp_path):
        from app.belfort_signal_eval import evaluate_signal
        q = _make_quote()
        with (
            patch("app.belfort_signal_eval._SIGNAL_LOG", tmp_path / "signal_log.jsonl"),
            patch("app.belfort_signal_eval._strategy") as mock_strat,
            patch("app.belfort_signal_eval._guardrails") as mock_risk,
        ):
            from app.belfort_strategy import BelfortSignal
            from datetime import datetime, timezone
            mock_strat.evaluate.return_value = BelfortSignal(
                symbol="SPY", action="hold", qty=0, order_type="none",
                limit_price=0.0, rationale="no edge", data_lane="IEX_ONLY",
                session_type="regular", generated_at=datetime.now(timezone.utc).isoformat(),
            )
            from app.belfort_risk import RiskCheckResult
            mock_risk.check.return_value = RiskCheckResult(
                passed=True, block_reason=None, check_name="hold_passthrough",
                signal=mock_strat.evaluate.return_value,
            )
            result = evaluate_signal(q, mode="paper")

        assert result["mode"] == "paper"
        assert result["was_executed"] is False
        assert result["execution_mode"] == "none"

    def test_live_mode_skips(self, tmp_path):
        from app.belfort_signal_eval import evaluate_signal
        q = _make_quote()
        with patch("app.belfort_signal_eval._SIGNAL_LOG", tmp_path / "signal_log.jsonl"):
            result = evaluate_signal(q, mode="live")
        assert result["skipped"] is True
        assert result["was_executed"] is False


# ── Signal log write ──────────────────────────────────────────────────────────

class TestSignalLogWrite:
    def _eval_shadow(self, tmp_path, action="hold"):
        from app.belfort_signal_eval import evaluate_signal
        from app.belfort_strategy import BelfortSignal
        from app.belfort_risk import RiskCheckResult
        from datetime import datetime, timezone
        q = _make_quote()
        sig = BelfortSignal(
            symbol="SPY", action=action, qty=1 if action != "hold" else 0,
            order_type="marketable_limit" if action != "hold" else "none",
            limit_price=510.10 if action != "hold" else 0.0,
            rationale="test rationale", data_lane="IEX_ONLY",
            session_type="regular", generated_at=datetime.now(timezone.utc).isoformat(),
        )
        rr = RiskCheckResult(passed=True, block_reason=None, check_name="hold_passthrough", signal=sig)
        log_path = tmp_path / "signal_log.jsonl"
        with (
            patch("app.belfort_signal_eval._SIGNAL_LOG", log_path),
            patch("app.belfort_signal_eval._strategy") as mock_strat,
            patch("app.belfort_signal_eval._guardrails") as mock_risk,
        ):
            mock_strat.evaluate.return_value = sig
            mock_risk.check.return_value = rr
            result = evaluate_signal(q, mode="shadow", portfolio=_make_portfolio())
        return result, log_path

    def test_hold_logged_to_file(self, tmp_path):
        result, log_path = self._eval_shadow(tmp_path, action="hold")
        assert log_path.exists()
        records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(records) == 1
        assert records[0]["signal_action"] == "hold"

    def test_was_executed_always_false(self, tmp_path):
        result, log_path = self._eval_shadow(tmp_path, action="buy")
        assert result["was_executed"] is False
        records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert records[0]["was_executed"] is False

    def test_execution_mode_always_none(self, tmp_path):
        result, _ = self._eval_shadow(tmp_path, action="sell")
        assert result["execution_mode"] == "none"

    def test_record_shape(self, tmp_path):
        result, log_path = self._eval_shadow(tmp_path)
        required_keys = [
            "written_at", "symbol", "mode", "session_type", "data_lane",
            "strategy_name", "signal_action", "signal_qty", "signal_order_type",
            "signal_limit_price", "signal_rationale",
            "risk_can_proceed", "risk_block_reason", "risk_checks_run",
            "was_executed", "execution_mode", "decision_summary_plain_english",
        ]
        for k in required_keys:
            assert k in result, f"Missing key: {k}"


# ── Blocked signals ───────────────────────────────────────────────────────────

class TestBlockedSignals:
    def test_risk_blocked_logged(self, tmp_path):
        from app.belfort_signal_eval import evaluate_signal
        from app.belfort_strategy import BelfortSignal
        from app.belfort_risk import RiskCheckResult
        from datetime import datetime, timezone
        q = _make_quote()
        sig = BelfortSignal(
            symbol="SPY", action="buy", qty=1, order_type="marketable_limit",
            limit_price=510.10, rationale="reversion buy", data_lane="IEX_ONLY",
            session_type="regular", generated_at=datetime.now(timezone.utc).isoformat(),
        )
        rr = RiskCheckResult(
            passed=False, block_reason="Daily loss cap reached: $-600.00",
            check_name="daily_loss_cap", signal=sig,
        )
        log_path = tmp_path / "signal_log.jsonl"
        with (
            patch("app.belfort_signal_eval._SIGNAL_LOG", log_path),
            patch("app.belfort_signal_eval._strategy") as mock_strat,
            patch("app.belfort_signal_eval._guardrails") as mock_risk,
        ):
            mock_strat.evaluate.return_value = sig
            mock_risk.check.return_value = rr
            result = evaluate_signal(q, mode="shadow", portfolio=_make_portfolio())

        assert result["risk_can_proceed"] is False
        assert "Daily loss cap" in (result["risk_block_reason"] or "")
        assert result["was_executed"] is False
        assert result["risk_checks_run"] == "daily_loss_cap"

    def test_decision_summary_no_order_language(self, tmp_path):
        from app.belfort_signal_eval import evaluate_signal
        from app.belfort_strategy import BelfortSignal
        from app.belfort_risk import RiskCheckResult
        from datetime import datetime, timezone
        q = _make_quote()
        sig = BelfortSignal(
            symbol="SPY", action="hold", qty=0, order_type="none",
            limit_price=0.0, rationale="no edge", data_lane="IEX_ONLY",
            session_type="regular", generated_at=datetime.now(timezone.utc).isoformat(),
        )
        rr = RiskCheckResult(passed=True, block_reason=None, check_name="hold_passthrough", signal=sig)
        log_path = tmp_path / "signal_log.jsonl"
        with (
            patch("app.belfort_signal_eval._SIGNAL_LOG", log_path),
            patch("app.belfort_signal_eval._strategy") as mock_strat,
            patch("app.belfort_signal_eval._guardrails") as mock_risk,
        ):
            mock_strat.evaluate.return_value = sig
            mock_risk.check.return_value = rr
            result = evaluate_signal(q, mode="shadow")

        summary = result["decision_summary_plain_english"]
        assert "No order was placed" in summary
        assert "SHADOW" in summary or "shadow" in summary


# ── read_latest_signal_decision ───────────────────────────────────────────────

class TestReadLatestSignalDecision:
    def test_returns_none_when_no_log(self, tmp_path):
        from observability.belfort_summary import read_latest_signal_decision
        with patch("observability.belfort_summary._SIGNAL_LOG", tmp_path / "nope.jsonl"):
            assert read_latest_signal_decision() is None

    def test_returns_most_recent_non_skipped(self, tmp_path):
        log = tmp_path / "signal_log.jsonl"
        records = [
            {"written_at": "2026-04-12T10:00:00Z", "signal_action": "hold", "skipped": False},
            {"written_at": "2026-04-12T10:00:05Z", "signal_action": "buy",  "skipped": False},
        ]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        from observability.belfort_summary import read_latest_signal_decision
        with patch("observability.belfort_summary._SIGNAL_LOG", log):
            result = read_latest_signal_decision()
        assert result["signal_action"] == "buy"

    def test_skips_skipped_records(self, tmp_path):
        log = tmp_path / "signal_log.jsonl"
        records = [
            {"written_at": "2026-04-12T10:00:00Z", "signal_action": "sell", "skipped": False},
            {"written_at": "2026-04-12T10:00:05Z", "skipped": True, "skip_reason": "mode=observation"},
        ]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        from observability.belfort_summary import read_latest_signal_decision
        with patch("observability.belfort_summary._SIGNAL_LOG", log):
            result = read_latest_signal_decision()
        assert result["signal_action"] == "sell"


# ── read_signal_stats_today ───────────────────────────────────────────────────

class TestReadSignalStatsToday:
    def test_empty_when_no_log(self, tmp_path):
        from observability.belfort_summary import read_signal_stats_today
        with patch("observability.belfort_summary._SIGNAL_LOG", tmp_path / "nope.jsonl"):
            stats = read_signal_stats_today()
        assert stats["total"] == 0

    def test_counts_todays_records(self, tmp_path):
        from datetime import date
        today = date.today().isoformat()
        log = tmp_path / "signal_log.jsonl"
        records = [
            {"written_at": f"{today}T10:00:00Z", "signal_action": "hold", "risk_can_proceed": True,  "skipped": False},
            {"written_at": f"{today}T10:00:05Z", "signal_action": "buy",  "risk_can_proceed": True,  "skipped": False},
            {"written_at": f"{today}T10:00:10Z", "signal_action": "buy",  "risk_can_proceed": False, "skipped": False},
            {"written_at": "2026-01-01T10:00:00Z", "signal_action": "hold", "risk_can_proceed": True, "skipped": False},  # old
            {"written_at": f"{today}T10:00:15Z", "skipped": True},  # skipped
        ]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        from observability.belfort_summary import read_signal_stats_today
        with patch("observability.belfort_summary._SIGNAL_LOG", log):
            stats = read_signal_stats_today()
        assert stats["total"] == 3
        assert stats["actions"]["buy"] == 2
        assert stats["actions"]["hold"] == 1
        assert stats["holds"] == 1
        assert stats["allowed"] == 2
        assert stats["blocked"] == 1


# ── Peter handle_belfort_status signal integration ────────────────────────────

class TestPeterBelfortStatusSignalIntegration:
    def test_shadow_mode_includes_signal_summary(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        preflight = {
            "mode": "shadow", "readiness_level": "PAPER_READY", "data_lane": "IEX_ONLY",
            "session_type": "regular", "observation_ticks_today": 5, "last_tick_at": None,
            "can_advance_to": None, "advancement_blocked_by": None,
            "broker_environment": "paper", "paper_credentials": True, "written_at": None,
        }
        latest_signal = {
            "signal_action": "hold", "symbol": "SPY",
            "signal_rationale": "no edge", "risk_can_proceed": True,
            "was_executed": False,
        }
        with (
            patch("peter.handlers.read_belfort_preflight", return_value=preflight),
            patch("peter.handlers.read_latest_signal_decision", return_value=latest_signal),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 3, "actions": {"buy": 0, "sell": 0, "hold": 3}, "holds": 3, "blocked": 0, "allowed": 3,
            }),
        ):
            cmd  = parse_command("belfort status")
            resp = handle_belfort_status(cmd)

        assert resp.ok
        assert "No order was placed" in resp.summary
        assert "HOLD" in resp.summary or "hold" in resp.summary.lower()

    def test_observation_mode_no_signal_line(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        preflight = {
            "mode": "observation", "readiness_level": "OBSERVATION_ONLY", "data_lane": "IEX_ONLY",
            "session_type": "regular", "observation_ticks_today": 2, "last_tick_at": None,
            "can_advance_to": "shadow", "advancement_blocked_by": None,
            "broker_environment": "paper", "paper_credentials": True, "written_at": None,
        }
        with (
            patch("peter.handlers.read_belfort_preflight", return_value=preflight),
            patch("peter.handlers.read_belfort_mode", return_value="observation"),
        ):
            cmd  = parse_command("belfort status")
            resp = handle_belfort_status(cmd)

        assert resp.ok
        # No signal decision line in observation mode (signal eval doesn't run)
        assert "Latest" not in resp.summary or "decision:" not in resp.summary


# ── _QuoteProxy injects session_type and data_lane ───────────────────────────

class TestQuoteProxy:
    def test_proxy_injects_session_type(self):
        from app.belfort_signal_eval import _QuoteProxy
        raw = MagicMock()
        raw.symbol = "SPY"
        raw.bid    = 510.0
        raw.ask    = 510.1
        proxy = _QuoteProxy(raw, session_type="regular", data_lane="IEX_ONLY")
        assert proxy.session_type == "regular"
        assert proxy.data_lane == "IEX_ONLY"
        assert proxy.symbol == "SPY"

    def test_proxy_falls_through_to_raw(self):
        from app.belfort_signal_eval import _QuoteProxy
        raw = MagicMock()
        raw.bid = 42.5
        proxy = _QuoteProxy(raw, session_type="closed", data_lane="UNKNOWN")
        assert proxy.bid == 42.5


# ── read_signal_log ───────────────────────────────────────────────────────────

class TestReadSignalLog:
    def test_empty_when_no_file(self, tmp_path):
        from app.belfort_signal_eval import read_signal_log
        with patch("app.belfort_signal_eval._SIGNAL_LOG", tmp_path / "nope.jsonl"):
            assert read_signal_log() == []

    def test_reads_last_n_records(self, tmp_path):
        log = tmp_path / "signal_log.jsonl"
        records = [{"id": i} for i in range(10)]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        from app.belfort_signal_eval import read_signal_log
        with patch("app.belfort_signal_eval._SIGNAL_LOG", log):
            result = read_signal_log(3)
        assert len(result) == 3
        assert result[-1]["id"] == 9
