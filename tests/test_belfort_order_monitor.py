from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch


def test_belfort_state_exposes_working_order_timing():
    from app.routes.neighborhood import _belfort_state

    open_order = {
        "order_id": "ord-1",
        "symbol": "NVDA",
        "side": "buy",
        "qty": 3,
        "event_type": "ack",
        "timestamp_utc": "2026-04-14T00:00:00+00:00",
        "session_type": "regular",
    }
    replay_rows = [
        {
            "order_id": "ord-1",
            "symbol": "NVDA",
            "side": "buy",
            "qty": 3,
            "event_type": "placed",
            "timestamp_utc": "2026-04-14T00:00:00+00:00",
            "session_type": "regular",
        },
        {
            "order_id": "ord-1",
            "symbol": "NVDA",
            "side": "buy",
            "qty": 3,
            "event_type": "ack",
            "timestamp_utc": "2026-04-14T00:02:00+00:00",
            "session_type": "regular",
        },
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("observability.agent_state.load_state", side_effect=Exception("skip")))
        stack.enter_context(patch("app.portfolio.get_snapshot", return_value={}))
        stack.enter_context(patch("app.portfolio.get_trades", return_value=[]))
        stack.enter_context(patch("app.portfolio.positions", {}, create=True))
        stack.enter_context(patch("app.trading_loop.get_status", return_value={"running": False, "stop_requested": False}))
        stack.enter_context(patch("app.order_ledger.get_today_summary", return_value={"orders_placed": 1, "fills": 0, "rejects": 0}))
        stack.enter_context(patch("app.order_ledger.get_open_orders", return_value=[open_order]))
        stack.enter_context(patch("app.order_ledger.replay", return_value=replay_rows))
        stack.enter_context(patch("app.routes.neighborhood._working_order_stale_threshold_seconds", return_value=1))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_preflight", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_freshness_state", return_value={"session_type": "regular", "freshness": "fresh", "freshness_label": "Fresh"}))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_mode", return_value="paper"))
        stack.enter_context(patch("observability.belfort_summary.read_latest_signal_decision", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_paper_execution", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_paper_fill", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_sim_trade", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_sim_record", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_signal_stats_today", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_paper_exec_stats_today", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_sim_stats_today", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_sim_main_reason", return_value=""))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_activity_feed", return_value=[]))
        stack.enter_context(patch("observability.belfort_summary.read_reconciliation_status", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_learn_strip", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_regime_metrics", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_strategy_profile", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_setup_scorecard", return_value={}))
        state = _belfort_state()

    monitor = state["belfort_order_monitor"]
    assert monitor["open_orders"] == 1
    assert monitor["stale_open_orders"] == 1
    assert "stale" in monitor["stale_warning"].lower()
    assert monitor["working_orders"][0]["symbol"] == "NVDA"
    assert monitor["working_orders"][0]["status_label"] == "ack"
    assert monitor["working_orders"][0]["is_stale"] is True
    assert monitor["working_orders"][0]["age_label"]
    assert monitor["working_orders"][0]["updated_label"]
    assert monitor["oldest_open_age_label"]
    assert monitor["latest_update_age_label"]


def test_belfort_state_prefers_alpaca_paper_truth_for_account_and_positions():
    from app.routes.neighborhood import _belfort_state
    from app.belfort_broker import PaperAccountSnapshot, PaperPosition, PaperPositionsSnapshot

    with ExitStack() as stack:
        stack.enter_context(patch("observability.agent_state.load_state", side_effect=Exception("skip")))
        stack.enter_context(patch("app.portfolio.get_snapshot", return_value={"cash": 100000.0, "realized_pnl": 500.0, "unrealized_pnl": 0.0}))
        stack.enter_context(patch("app.portfolio.get_trades", return_value=[]))
        stack.enter_context(patch("app.portfolio.positions", {"LOCAL": {"qty": 1}}, create=True))
        stack.enter_context(patch("app.trading_loop.get_status", return_value={"running": False, "stop_requested": False}))
        stack.enter_context(patch("app.order_ledger.get_today_summary", return_value={"orders_placed": 0, "fills": 0, "rejects": 0}))
        stack.enter_context(patch("app.order_ledger.get_open_orders", return_value=[]))
        stack.enter_context(patch("app.order_ledger.replay", return_value=[]))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_preflight", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_freshness_state", return_value={"session_type": "closed", "freshness": "fresh", "freshness_label": "Fresh"}))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_mode", return_value="paper"))
        stack.enter_context(patch("observability.belfort_summary.read_latest_signal_decision", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_paper_execution", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_paper_fill", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_sim_trade", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_latest_sim_record", return_value=None))
        stack.enter_context(patch("observability.belfort_summary.read_signal_stats_today", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_paper_exec_stats_today", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_sim_stats_today", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_sim_main_reason", return_value=""))
        stack.enter_context(patch("observability.belfort_summary.read_belfort_activity_feed", return_value=[]))
        stack.enter_context(patch("observability.belfort_summary.read_reconciliation_status", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_learn_strip", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_regime_metrics", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_strategy_profile", return_value={}))
        stack.enter_context(patch("observability.belfort_summary.read_setup_scorecard", return_value={}))
        stack.enter_context(
            patch(
                "app.belfort_broker.fetch_paper_account_snapshot",
                return_value=PaperAccountSnapshot(available=True, cash=1750.0, buying_power=2400.0, equity=1895.0),
            )
        )
        stack.enter_context(
            patch(
                "app.belfort_broker.fetch_paper_positions",
                return_value=PaperPositionsSnapshot(
                    available=True,
                    positions=[PaperPosition(symbol="QQQ", qty=2, avg_cost=620.0, market_value=1260.0, unrealized_pnl=20.0)],
                ),
            )
        )
        state = _belfort_state()

    assert state["paper_truth_source"] == "alpaca_broker"
    assert state["cash"] == 1750.0
    assert state["paper_equity"] == 1895.0
    assert state["buying_power"] == 2400.0
    assert state["open_positions"] == ["QQQ"]
    assert state["broker_unrealized_pnl"] == 20.0
    assert "Alpaca" in state["broker_position_warning"] or state["broker_position_warning"]
