# tests/test_belfort_paper_exec.py
#
# BELFORT-PAPER-EXEC-01 — Paper execution path tests.
#
# Covers:
#   A. execute_paper_signal — gate logic
#      - hold signal gated
#      - sell signal gated when no tracked paper position exists
#      - non-paper mode gated
#      - closed session gated
#      - extended-hours paper allowed
#      - risk-blocked signal gated
#      - zero qty gated
#   B. execute_paper_signal — eligible buy signal
#      - calls submit_paper_order with correct args
#      - logs execution record
#      - was_submitted_to_broker = True on success
#      - broker_error logged on failure
#      - paper_only = True always
#   C. submit_paper_order gates
#      - non-paper URL blocked
#      - missing credentials blocked
#      - bad qty blocked
#   D. Observability bridge
#      - read_latest_paper_execution returns most recent record
#      - read_paper_exec_stats_today aggregates correctly
#   E. Peter status includes paper exec summary in paper mode
#   F. _run_paper_execution only fires for paper mode
#   G. No regression

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_signal(
    mode:             str   = "paper",
    session_type:     str   = "regular",
    signal_action:    str   = "buy",
    risk_can_proceed: bool  = True,
    risk_block_reason: str  = None,
    signal_qty:       int   = 1,
    signal_limit_price: float = 510.10,
    symbol:           str   = "SPY",
) -> dict:
    return {
        "written_at":          "2026-04-12T10:00:00Z",
        "symbol":              symbol,
        "mode":                mode,
        "session_type":        session_type,
        "data_lane":           "IEX_ONLY",
        "signal_action":       signal_action,
        "signal_qty":          signal_qty,
        "signal_order_type":   "marketable_limit",
        "signal_limit_price":  signal_limit_price,
        "signal_rationale":    "test rationale",
        "risk_can_proceed":    risk_can_proceed,
        "risk_block_reason":   risk_block_reason,
        "risk_checks_run":     "all_passed" if risk_can_proceed else "daily_loss_cap",
        "was_executed":        False,
        "execution_mode":      "none",
        "setup_tag":           "trend continuation",
        "relative_volume":     2.0,
        "gap_pct":             0.02,
        "relative_strength_vs_spy_pct": 0.01,
    }


def _make_broker_result(submitted=True, order_id="ord-123", status="pending_new", error=""):
    from app.belfort_broker import BrokerResult
    return BrokerResult(
        submitted              = submitted,
        broker_order_id        = order_id if submitted else "",
        broker_client_order_id = "belfort-paper-test",
        broker_status          = status if submitted else "",
        broker_error           = error if not submitted else "",
        submission_error       = "",
    )


def _paper_candidate(symbol: str = "SPY", *, eligible: bool = True, label: str = "eligible", reason: str | None = None):
    return {
        "symbol": symbol,
        "paper_eligible": eligible,
        "tradeability_label": label,
        "tradeability_reason": reason or (
            "Eligible for paper trading in Belfort's liquid Phase 1 universe."
            if eligible else
            "Watch only for now — not in Belfort's Phase 1 paper universe."
        ),
    }


def _clean_snapshot() -> dict:
    return {"cash": 100_000.0, "unrealized_pnl": 0.0, "positions": {}}


# ── A. Gate logic ─────────────────────────────────────────────────────────────

class TestPaperExecGates:
    def test_hold_signal_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(signal_action="hold")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert result["execution_status"] == "gated"
        assert result["was_submitted_to_broker"] is False
        assert result["paper_only"] is True

    def test_sell_signal_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(signal_action="sell")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "no tracked paper position exists" in result["gate_block_reason"].lower()
        assert result["was_submitted_to_broker"] is False

    def test_shadow_mode_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(mode="shadow")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "shadow" in result["gate_block_reason"].lower()

    def test_observation_mode_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(mode="observation")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False

    def test_closed_session_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(session_type="closed")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "closed" in result["gate_block_reason"]

    def test_pre_market_allowed_and_flagged_extended(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(session_type="pre_market")
        mock_result = _make_broker_result(submitted=True)
        cfg = {"BELFORT_COST_EDGE_RATIO_LIMIT": 10.0}
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.strategy.config.get_config", return_value=cfg),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result) as mock_submit,
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is True
        mock_submit.assert_called_once_with(symbol="SPY", qty=1, limit_price=510.10, side="buy", extended_hours=True)

    def test_risk_blocked_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(risk_can_proceed=False, risk_block_reason="daily loss cap")
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "daily loss cap" in result["gate_block_reason"]

    def test_zero_qty_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(signal_qty=0)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False

    def test_zero_price_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(signal_limit_price=0.0)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False

    def test_watch_only_symbol_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(symbol="SOFI")
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate("SOFI", eligible=False, label="watch_only")),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "phase 1 paper universe" in result["gate_block_reason"].lower()

    def test_gated_record_always_logged(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        log = tmp_path / "exec.jsonl"
        sig = _make_signal(signal_action="hold")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", log):
            execute_paper_signal(sig)
        assert log.exists()
        records = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
        assert len(records) == 1

    def test_symbol_concentration_blocks_new_buy(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(symbol="QQQ", signal_qty=10, signal_limit_price=500.0)
        mock_snapshot = {
            "cash": 20_000.0,
            "unrealized_pnl": 0.0,
            "positions": {"QQQ": {"qty": 40.0, "avg_cost": 500.0}},
        }
        cfg = {
            "BELFORT_MAX_ORDERS_PER_DAY": 100,
            "BELFORT_GLOBAL_COOLDOWN_SECONDS": 0,
            "BELFORT_SYMBOL_COOLDOWN_SECONDS": 0,
            "BELFORT_TURNOVER_BUDGET_PCT": 2.0,
            "BELFORT_MAX_SYMBOL_EXPOSURE_PCT": 0.2,
            "BELFORT_MAX_TOTAL_EXPOSURE_PCT": 0.65,
            "BELFORT_MAX_ACTIVE_POSITIONS": 4,
            "BELFORT_COST_EDGE_RATIO_LIMIT": 0.25,
        }
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate("QQQ")),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=mock_snapshot),
            patch("app.strategy.config.get_config", return_value=cfg),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "too much of the book" in result["gate_block_reason"].lower()

    def test_recent_symbol_cooldown_blocks_churn(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(symbol="QQQ", signal_qty=1, signal_limit_price=510.10)
        exec_log = tmp_path / "exec.jsonl"
        exec_log.write_text(json.dumps({
            "written_at": datetime.now(timezone.utc).isoformat(),
            "symbol": "QQQ",
            "execution_status": "gated",
        }) + "\n", encoding="utf-8")
        cfg = {
            "BELFORT_MAX_ORDERS_PER_DAY": 100,
            "BELFORT_GLOBAL_COOLDOWN_SECONDS": 0,
            "BELFORT_SYMBOL_COOLDOWN_SECONDS": 600,
            "BELFORT_TURNOVER_BUDGET_PCT": 2.0,
            "BELFORT_MAX_SYMBOL_EXPOSURE_PCT": 0.2,
            "BELFORT_MAX_TOTAL_EXPOSURE_PCT": 0.65,
            "BELFORT_MAX_ACTIVE_POSITIONS": 4,
            "BELFORT_COST_EDGE_RATIO_LIMIT": 0.25,
        }
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", exec_log),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate("QQQ")),
            patch("app.portfolio.get_snapshot", return_value={"cash": 100_000.0, "unrealized_pnl": 0.0, "positions": {}}),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.strategy.config.get_config", return_value=cfg),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "too recently" in result["gate_block_reason"].lower()

    def test_hourly_capacity_blocks_fee_heavy_churn(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(symbol="QQQ", signal_qty=1, signal_limit_price=510.10)
        cfg = {
            "BELFORT_MAX_ORDERS_PER_DAY": 100,
            "BELFORT_MAX_ORDERS_PER_HOUR": 2,
            "BELFORT_GLOBAL_COOLDOWN_SECONDS": 0,
            "BELFORT_SYMBOL_COOLDOWN_SECONDS": 0,
            "BELFORT_TURNOVER_BUDGET_PCT": 2.0,
            "BELFORT_MAX_SYMBOL_EXPOSURE_PCT": 0.2,
            "BELFORT_MAX_TOTAL_EXPOSURE_PCT": 0.65,
            "BELFORT_MAX_ACTIVE_POSITIONS": 4,
            "BELFORT_COST_EDGE_RATIO_LIMIT": 0.25,
        }
        recent_orders = [
            {
                "event_type": "placed",
                "environment": "paper",
                "symbol": "QQQ",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
            {
                "event_type": "placed",
                "environment": "paper",
                "symbol": "SPY",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
        ]
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate("QQQ")),
            patch("app.order_ledger.get_today_count", return_value=2),
            patch("app.order_ledger.replay", return_value=recent_orders),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.strategy.config.get_config", return_value=cfg),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "last hour" in result["gate_block_reason"].lower()

    def test_net_edge_floor_blocks_fee_dominated_setup(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(symbol="QQQ", signal_qty=1, signal_limit_price=50.0)
        candidate = _paper_candidate("QQQ")
        candidate["tradeability_reason"] = "Eligible for paper trading in Belfort's expanded liquid-volatility universe."
        cfg = {
            "BELFORT_MAX_ORDERS_PER_DAY": 100,
            "BELFORT_MAX_ORDERS_PER_HOUR": 16,
            "BELFORT_GLOBAL_COOLDOWN_SECONDS": 0,
            "BELFORT_SYMBOL_COOLDOWN_SECONDS": 0,
            "BELFORT_TURNOVER_BUDGET_PCT": 2.0,
            "BELFORT_MAX_SYMBOL_EXPOSURE_PCT": 0.2,
            "BELFORT_MAX_TOTAL_EXPOSURE_PCT": 0.65,
            "BELFORT_MAX_ACTIVE_POSITIONS": 4,
            "BELFORT_COST_EDGE_RATIO_LIMIT": 10.0,
            "BELFORT_TRAINING_COMMISSION_PER_ORDER": 2.0,
            "BELFORT_MIN_NET_EDGE_PCT": 0.01,
        }
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=candidate),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.strategy.config.get_config", return_value=cfg),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "fees" in result["gate_block_reason"].lower() or "profit after likely fees" in result["gate_block_reason"].lower()


# ── B. Eligible buy signal ────────────────────────────────────────────────────

class TestPaperExecEligibleBuy:
    def test_calls_broker_with_correct_args(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result) as mock_submit,
        ):
            execute_paper_signal(sig)
        mock_submit.assert_called_once_with(symbol="SPY", qty=1, limit_price=510.10, side="buy", extended_hours=False)

    def test_sell_calls_broker_when_position_is_tracked(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(signal_action="sell")
        mock_result = _make_broker_result(submitted=True)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.portfolio.get_snapshot", return_value={"positions": {"SPY": {"qty": 1, "avg_cost": 500.0}}}),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result) as mock_submit,
        ):
            execute_paper_signal(sig)
        mock_submit.assert_called_once_with(symbol="SPY", qty=1, limit_price=510.10, side="sell", extended_hours=False)

    def test_submitted_record_logged(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        log = tmp_path / "exec.jsonl"
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True, order_id="ord-abc")
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", log),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result),
        ):
            execute_paper_signal(sig)
        records = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
        assert len(records) == 1
        assert records[0]["was_submitted_to_broker"] is True
        assert records[0]["broker_order_id"] == "ord-abc"
        assert records[0]["execution_status"] == "submitted"

    def test_paper_only_invariant(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result),
        ):
            result = execute_paper_signal(sig)
        assert result["paper_only"] is True

    def test_gate_passed_true_on_submit(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result),
        ):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is True

    def test_broker_error_logged(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        log = tmp_path / "exec.jsonl"
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=False, error="insufficient buying power")
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", log),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result),
        ):
            result = execute_paper_signal(sig)
        assert result["was_submitted_to_broker"] is False
        assert result["execution_status"] == "broker_error"
        assert "insufficient buying power" in result["broker_error"]

    def test_exec_summary_no_real_money_language(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result),
        ):
            result = execute_paper_signal(sig)
        assert "No real money" in result["exec_summary"]
        assert "PAPER" in result["exec_summary"]

    def test_record_shape_complete(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True)
        required_keys = [
            "written_at", "paper_only", "signal_written_at", "symbol", "mode",
            "session_type", "data_lane", "action", "qty", "order_type", "limit_price",
            "signal_rationale", "risk_checks_run", "gate_passed", "gate_block_reason",
            "was_submitted_to_broker", "broker_order_id", "broker_client_order_id",
            "broker_status", "broker_error", "submission_error", "execution_status",
            "exec_summary",
        ]
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_scanner.lookup_candidate", return_value=_paper_candidate()),
            patch("app.order_ledger.get_today_count", return_value=0),
            patch("app.order_ledger.replay", return_value=[]),
            patch("app.portfolio.get_snapshot", return_value=_clean_snapshot()),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result),
        ):
            result = execute_paper_signal(sig)
        for k in required_keys:
            assert k in result, f"Missing key: {k}"


class TestPaperFlatten:
    def test_flatten_returns_already_flat_when_no_positions(self):
        from app.belfort_paper_exec import flatten_paper_positions
        from app.belfort_broker import PaperPositionsSnapshot
        with (
            patch("app.belfort_broker.fetch_paper_positions", return_value=PaperPositionsSnapshot(available=True, positions=[])),
            patch("app.portfolio.get_snapshot", return_value={"positions": {}}),
        ):
            result = flatten_paper_positions()
        assert result["status"] == "already_flat"
        assert result["submitted"] == 0

    def test_flatten_uses_sell_signals_for_each_open_name(self):
        from app.belfort_paper_exec import flatten_paper_positions
        from app.belfort_broker import PaperPosition, PaperPositionsSnapshot

        class _Quote:
            bid = 100.0
            midpoint = 100.2
            last = 100.1
            spread_pct = 0.002
            data_lane = "IEX_ONLY"

        calls = []

        def _fake_exec(signal_record):
            calls.append(signal_record)
            return {
                "symbol": signal_record["symbol"],
                "was_submitted_to_broker": True,
                "execution_status": "submitted",
            }

        snapshot = {
            "positions": {
                "SPY": {"qty": 2, "avg_cost": 99.0},
                "QQQ": {"qty": 1, "avg_cost": 98.0},
            }
        }
        with (
            patch(
                "app.belfort_broker.fetch_paper_positions",
                return_value=PaperPositionsSnapshot(
                    available=True,
                    positions=[
                        PaperPosition(symbol="SPY", qty=2, avg_cost=99.0),
                        PaperPosition(symbol="QQQ", qty=1, avg_cost=98.0),
                    ],
                ),
            ),
            patch("app.portfolio.get_snapshot", return_value=snapshot),
            patch("app.market_time.session_type", return_value="regular"),
            patch("app.market_data_feed.get_quote", return_value=_Quote()),
            patch("app.belfort_paper_exec.execute_paper_signal", side_effect=_fake_exec),
        ):
            result = flatten_paper_positions("Operator close all")

        assert result["status"] == "flatten_submitted"
        assert result["submitted"] == 2
        assert [row["symbol"] for row in calls] == ["SPY", "QQQ"]
        assert all(row["signal_action"] == "sell" for row in calls)

    def test_flatten_prefers_broker_positions_over_local_snapshot(self):
        from app.belfort_paper_exec import flatten_paper_positions
        from app.belfort_broker import PaperPosition, PaperPositionsSnapshot

        class _Quote:
            bid = 50.0
            midpoint = 50.1
            last = 50.05
            spread_pct = 0.002
            data_lane = "IEX_ONLY"

        calls = []

        def _fake_exec(signal_record):
            calls.append(signal_record)
            return {
                "symbol": signal_record["symbol"],
                "was_submitted_to_broker": True,
                "execution_status": "submitted",
            }

        with (
            patch(
                "app.belfort_broker.fetch_paper_positions",
                return_value=PaperPositionsSnapshot(
                    available=True,
                    positions=[PaperPosition(symbol="NVDA", qty=3, avg_cost=48.0)],
                ),
            ),
            patch("app.portfolio.get_snapshot", return_value={"positions": {}}),
            patch("app.market_time.session_type", return_value="regular"),
            patch("app.market_data_feed.get_quote", return_value=_Quote()),
            patch("app.belfort_paper_exec.execute_paper_signal", side_effect=_fake_exec),
        ):
            result = flatten_paper_positions("Broker truth close all")

        assert result["status"] == "flatten_submitted"
        assert result["positions_source"] == "alpaca_broker"
        assert [row["symbol"] for row in calls] == ["NVDA"]


# ── C. Broker safety gates ────────────────────────────────────────────────────

class TestBrokerSafetyGates:
    def test_non_paper_url_blocked(self):
        from app.belfort_broker import submit_paper_order
        with patch("app.belfort_broker._is_paper_url", False):
            result = submit_paper_order("SPY", qty=1, limit_price=510.0)
        assert result.submitted is False
        assert "paper" in result.submission_error.lower()

    def test_missing_credentials_blocked(self):
        from app.belfort_broker import submit_paper_order
        with (
            patch("app.belfort_broker._is_paper_url", True),
            patch("app.belfort_broker._API_KEY",    ""),
            patch("app.belfort_broker._API_SECRET", ""),
        ):
            result = submit_paper_order("SPY", qty=1, limit_price=510.0)
        assert result.submitted is False
        assert "credentials" in result.submission_error.lower()

    def test_zero_qty_blocked(self):
        from app.belfort_broker import submit_paper_order
        with (
            patch("app.belfort_broker._is_paper_url", True),
            patch("app.belfort_broker._API_KEY",    "test-key"),
            patch("app.belfort_broker._API_SECRET", "test-secret"),
        ):
            result = submit_paper_order("SPY", qty=0, limit_price=510.0)
        assert result.submitted is False

    def test_paper_only_invariant_on_result(self):
        from app.belfort_broker import submit_paper_order
        with patch("app.belfort_broker._is_paper_url", False):
            result = submit_paper_order("SPY", qty=1, limit_price=510.0)
        assert result.paper_only is True

    def test_successful_submission_returns_order_id(self):
        from app.belfort_broker import submit_paper_order
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "broker-order-xyz", "client_order_id": "belfort-test", "status": "pending_new",
        }
        with (
            patch("app.belfort_broker._is_paper_url", True),
            patch("app.belfort_broker._API_KEY",    "key"),
            patch("app.belfort_broker._API_SECRET", "secret"),
            patch("app.belfort_broker._BASE_URL",   "https://paper-api.alpaca.markets/v2"),
            patch("requests.post", return_value=mock_resp),
        ):
            result = submit_paper_order("SPY", qty=1, limit_price=510.10)
        assert result.submitted is True
        assert result.broker_order_id == "broker-order-xyz"
        assert result.broker_status == "pending_new"

    def test_broker_http_error_not_submitted(self):
        from app.belfort_broker import submit_paper_order
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"message": "insufficient buying power"}
        with (
            patch("app.belfort_broker._is_paper_url", True),
            patch("app.belfort_broker._API_KEY",    "key"),
            patch("app.belfort_broker._API_SECRET", "secret"),
            patch("app.belfort_broker._BASE_URL",   "https://paper-api.alpaca.markets/v2"),
            patch("requests.post", return_value=mock_resp),
        ):
            result = submit_paper_order("SPY", qty=1, limit_price=510.10)
        assert result.submitted is False
        assert "insufficient buying power" in result.broker_error

    def test_network_timeout_not_submitted(self):
        import requests
        from app.belfort_broker import submit_paper_order
        with (
            patch("app.belfort_broker._is_paper_url", True),
            patch("app.belfort_broker._API_KEY",    "key"),
            patch("app.belfort_broker._API_SECRET", "secret"),
            patch("requests.post", side_effect=requests.exceptions.Timeout()),
        ):
            result = submit_paper_order("SPY", qty=1, limit_price=510.10)
        assert result.submitted is False
        assert "timed out" in result.submission_error.lower()


# ── D. Observability bridge ───────────────────────────────────────────────────

class TestPaperExecObservability:
    def test_read_latest_returns_none_when_no_log(self, tmp_path):
        from observability.belfort_summary import read_latest_paper_execution
        with patch("observability.belfort_summary._PAPER_EXEC_LOG", tmp_path / "nope.jsonl"):
            assert read_latest_paper_execution() is None

    def test_read_latest_returns_most_recent(self, tmp_path):
        log = tmp_path / "exec.jsonl"
        records = [
            {"written_at": "2026-04-12T10:00:00Z", "execution_status": "gated"},
            {"written_at": "2026-04-12T10:00:05Z", "execution_status": "submitted"},
        ]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        from observability.belfort_summary import read_latest_paper_execution
        with patch("observability.belfort_summary._PAPER_EXEC_LOG", log):
            result = read_latest_paper_execution()
        assert result["execution_status"] == "submitted"

    def test_stats_empty_when_no_log(self, tmp_path):
        from observability.belfort_summary import read_paper_exec_stats_today
        with patch("observability.belfort_summary._PAPER_EXEC_LOG", tmp_path / "nope.jsonl"):
            stats = read_paper_exec_stats_today()
        assert stats["total"] == 0
        assert stats["submitted"] == 0

    def test_stats_counts_today_records(self, tmp_path):
        from datetime import date
        today = date.today().isoformat()
        log = tmp_path / "exec.jsonl"
        records = [
            {"written_at": f"{today}T10:00:00Z", "execution_status": "submitted", "symbol": "SPY"},
            {"written_at": f"{today}T10:00:05Z", "execution_status": "gated", "symbol": "SPY"},
            {"written_at": f"{today}T10:00:10Z", "execution_status": "broker_error", "symbol": "SPY"},
            {"written_at": "2026-01-01T10:00:00Z", "execution_status": "submitted", "symbol": "SPY"},  # old
        ]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        from observability.belfort_summary import read_paper_exec_stats_today
        with patch("observability.belfort_summary._PAPER_EXEC_LOG", log):
            stats = read_paper_exec_stats_today()
        assert stats["total"] == 3
        assert stats["submitted"] == 1
        assert stats["gated"] == 1
        assert stats["errored"] == 1
        assert "SPY" in stats["symbols"]


class TestPaperExecSync:
    def test_sync_filled_order_records_trade_and_fill_record(self, tmp_path):
        from app.belfort_broker import PaperOrderStatus
        from app.belfort_paper_exec import sync_paper_execution

        log = tmp_path / "exec.jsonl"
        open_order = {
            "order_id": "ord-1",
            "symbol": "SPY",
            "side": "buy",
            "qty": 1,
            "limit_price": 510.10,
            "data_lane": "IEX_ONLY",
            "session_type": "regular",
            "rationale": "test rationale",
        }
        status = PaperOrderStatus(
            order_id="ord-1",
            client_order_id="client-1",
            submitted=True,
            status="filled",
            symbol="SPY",
            side="buy",
            qty=1.0,
            filled_qty=1.0,
            limit_price=510.10,
            fill_price=510.05,
            updated_at="2026-04-14T10:01:00Z",
        )
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", log),
            patch("app.order_ledger.get_open_orders", return_value=[open_order]),
            patch("app.belfort_broker.fetch_paper_order", return_value=status),
            patch("app.portfolio.set_market_price") as mock_set_price,
            patch("app.portfolio.record_trade") as mock_record_trade,
            patch("app.order_ledger.append") as mock_append,
        ):
            records = sync_paper_execution()

        assert len(records) == 1
        assert records[0]["execution_status"] == "filled"
        assert records[0]["portfolio_sync_status"] == "recorded"
        mock_set_price.assert_called_once_with("SPY", 510.05)
        mock_record_trade.assert_called_once_with("SPY", "BUY", 1.0, 510.05)
        assert any(call.kwargs.get("event_type") == "fill" for call in mock_append.call_args_list)

    def test_submit_paper_order_accepts_sell_side(self):
        from app.belfort_broker import submit_paper_order

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "broker-order-sell", "client_order_id": "belfort-sell", "status": "pending_new",
        }
        with (
            patch("app.belfort_broker._is_paper_url", True),
            patch("app.belfort_broker._API_KEY", "key"),
            patch("app.belfort_broker._API_SECRET", "secret"),
            patch("app.belfort_broker._BASE_URL", "https://paper-api.alpaca.markets/v2"),
            patch("requests.post", return_value=mock_resp) as mock_post,
        ):
            result = submit_paper_order("SPY", qty=1, limit_price=510.10, side="sell")

        assert result.submitted is True
        assert mock_post.call_args.kwargs["json"]["side"] == "sell"


# ── E. Peter status in paper mode ─────────────────────────────────────────────

class TestPeterStatusPaperExec:
    def _make_preflight(self):
        return {
            "mode": "observation", "readiness_level": "OBSERVATION_ONLY",
            "data_lane": "IEX_ONLY", "session_type": "regular",
            "observation_ticks_today": 5, "last_tick_at": None,
            "can_advance_to": None, "advancement_blocked_by": None,
            "broker_environment": "paper", "paper_credentials": True, "written_at": None,
        }

    def test_paper_exec_summary_in_paper_mode(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        latest_exec = {
            "execution_status": "submitted",
            "exec_summary": "PAPER BUY 1 SPY @ limit $510.10 — submitted to broker (id: ord-xyz). No real money.",
            "broker_order_id": "ord-xyz",
        }
        with (
            patch("peter.handlers.read_belfort_preflight", return_value=self._make_preflight()),
            patch("peter.handlers.read_belfort_mode",      return_value="paper"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
            patch("peter.handlers.read_latest_paper_execution",  return_value=latest_exec),
            patch("peter.handlers.read_paper_exec_stats_today",  return_value={
                "total": 1, "submitted": 1, "gated": 0, "errored": 0, "symbols": ["SPY"],
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.ok
        assert "No real money" in resp.summary or "paper" in resp.summary.lower()
        assert "paper" in resp.metrics["mode"]

    def test_no_paper_exec_section_in_shadow_mode(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=self._make_preflight()),
            patch("peter.handlers.read_belfort_mode",      return_value="shadow"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
            patch("peter.handlers.read_latest_paper_execution",  return_value=None),
            patch("peter.handlers.read_paper_exec_stats_today",  return_value={
                "total": 0, "submitted": 0, "gated": 0, "errored": 0, "symbols": [],
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.ok
        # Paper exec section should not appear for shadow mode
        assert "Paper order submitted" not in resp.summary
        assert "paper orders today" not in resp.summary.lower()


# ── F. _run_paper_execution only fires for paper mode ─────────────────────────

class TestRunPaperExecutionMode:
    def test_shadow_mode_does_not_trigger_paper_exec(self):
        from app.trading_loop import _run_paper_execution
        sig = _make_signal(mode="shadow")
        with patch("app.belfort_paper_exec.execute_paper_signal") as mock_exec:
            _run_paper_execution(sig)
        mock_exec.assert_not_called()

    def test_none_signal_does_not_trigger_paper_exec(self):
        from app.trading_loop import _run_paper_execution
        with patch("app.belfort_paper_exec.execute_paper_signal") as mock_exec:
            _run_paper_execution(None)
        mock_exec.assert_not_called()

    def test_paper_mode_triggers_paper_exec(self):
        from app.trading_loop import _run_paper_execution
        sig = _make_signal(mode="paper")
        with patch("app.belfort_paper_exec.execute_paper_signal") as mock_exec:
            _run_paper_execution(sig)
        mock_exec.assert_called_once_with(sig)

    def test_observation_mode_does_not_trigger(self):
        from app.trading_loop import _run_paper_execution
        sig = _make_signal(mode="observation")
        with patch("app.belfort_paper_exec.execute_paper_signal") as mock_exec:
            _run_paper_execution(sig)
        mock_exec.assert_not_called()


# ── G. broker_status utility ──────────────────────────────────────────────────

class TestBrokerStatus:
    def test_broker_status_returns_paper_only_true(self):
        from app.belfort_broker import broker_status
        status = broker_status()
        assert status["paper_only"] is True

    def test_is_paper_url_reflects_config(self):
        from app.belfort_broker import broker_status, _PAPER_URL_MARKER, _BASE_URL
        status = broker_status()
        assert status["is_paper_url"] == (_PAPER_URL_MARKER in _BASE_URL)
