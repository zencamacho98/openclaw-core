# tests/test_belfort_paper_exec.py
#
# BELFORT-PAPER-EXEC-01 — Paper execution path tests.
#
# Covers:
#   A. execute_paper_signal — gate logic
#      - hold signal gated
#      - sell signal gated (not yet supported)
#      - non-paper mode gated
#      - non-regular session gated
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
        assert "sell" in result["gate_block_reason"].lower()
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

    def test_non_regular_session_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(session_type="pre_market")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "pre_market" in result["gate_block_reason"]

    def test_risk_blocked_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(risk_can_proceed=False, risk_block_reason="daily loss cap")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False
        assert "daily loss cap" in result["gate_block_reason"]

    def test_zero_qty_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(signal_qty=0)
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False

    def test_zero_price_gated(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal(signal_limit_price=0.0)
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"):
            result = execute_paper_signal(sig)
        assert result["gate_passed"] is False

    def test_gated_record_always_logged(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        log = tmp_path / "exec.jsonl"
        sig = _make_signal(signal_action="hold")
        with patch("app.belfort_paper_exec._PAPER_EXEC_LOG", log):
            execute_paper_signal(sig)
        assert log.exists()
        records = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
        assert len(records) == 1


# ── B. Eligible buy signal ────────────────────────────────────────────────────

class TestPaperExecEligibleBuy:
    def test_calls_broker_with_correct_args(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True)
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", tmp_path / "exec.jsonl"),
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result) as mock_submit,
        ):
            execute_paper_signal(sig)
        mock_submit.assert_called_once_with(symbol="SPY", qty=1, limit_price=510.10)

    def test_submitted_record_logged(self, tmp_path):
        from app.belfort_paper_exec import execute_paper_signal
        log = tmp_path / "exec.jsonl"
        sig = _make_signal()
        mock_result = _make_broker_result(submitted=True, order_id="ord-abc")
        with (
            patch("app.belfort_paper_exec._PAPER_EXEC_LOG", log),
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
            patch("app.belfort_broker.submit_paper_order", return_value=mock_result),
        ):
            result = execute_paper_signal(sig)
        for k in required_keys:
            assert k in result, f"Missing key: {k}"


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
