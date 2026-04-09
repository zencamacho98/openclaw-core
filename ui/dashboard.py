"""
ui/dashboard.py  —  OpenClaw operator console.

Tabs: Overview · Trading · Insights · Controls
Advanced content (config, logs, experiments, raw loop) lives in expanders inside Controls.
"""
import json
import pathlib
import time
from datetime import datetime, timezone

import requests
import streamlit as st

API_BASE         = "http://127.0.0.1:8000"
REFRESH_INTERVAL = 5
VALIDATION_DIR   = pathlib.Path("data/validation_runs")

SIGNAL_COLOR   = {"BUY": "green", "SELL": "red", "HOLD": "gray"}
DECISION_COLOR = {"flag_for_tuning": "red", "collect_more_data": "orange", "monitor": "green"}

st.set_page_config(page_title="OpenClaw", layout="wide", initial_sidebar_state="collapsed")

# ── HTTP ───────────────────────────────────────────────────────────────────────
def fetch(path):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def post_req(path, params=None):
    try:
        r = requests.post(f"{API_BASE}{path}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def post_json(path, body: dict):
    try:
        r = requests.post(f"{API_BASE}{path}", json=body, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def _time_ago(iso_str):
    if not iso_str:
        return ""
    try:
        d = int((datetime.now(timezone.utc) -
                 datetime.fromisoformat(iso_str.replace("Z", "+00:00"))).total_seconds())
        if d < 60:   return f"{d}s ago"
        if d < 3600: return f"{d // 60}m ago"
        return f"{d // 3600}h {(d % 3600) // 60}m ago"
    except Exception:
        return ""

def _val_records():
    if not VALIDATION_DIR.exists():
        return []
    out = []
    for f in sorted(VALIDATION_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append((f, json.loads(f.read_text())))
        except Exception:
            pass
    return out

# ── Session state ──────────────────────────────────────────────────────────────
for _k in ("analysis_result", "decision_result"):
    if _k not in st.session_state:
        st.session_state[_k] = None

# ── Fetch ──────────────────────────────────────────────────────────────────────
portfolio   = fetch("/monitor/portfolio")
report      = fetch("/monitor/report")
agents      = fetch("/monitor/agents")
strategy    = fetch("/monitor/strategy?symbol=SPY")
logs        = fetch("/logs")
recs        = fetch("/monitor/recommendations?n=5")
patterns    = fetch("/monitor/patterns?n=20")
prop_data   = fetch("/monitor/proposal")
trading     = fetch("/monitor/trading/status")
config_data = fetch("/monitor/config")
changelog   = fetch("/monitor/tuning/changelog?n=10")
regime_data = fetch("/monitor/regime?symbol=SPY")

is_trading = (trading or {}).get("running", False)


# ══════════════════════════════════════════════════════════════════════════════
# HEADER — title + status badge + key metrics
# ══════════════════════════════════════════════════════════════════════════════
hdr, badge = st.columns([5, 1])
with hdr:
    st.title("OpenClaw")
with badge:
    if is_trading:
        ticks = (trading or {}).get("ticks", 0)
        st.success(f"LIVE · {ticks} ticks · {_time_ago((trading or {}).get('started_at'))}")
    else:
        st.error("STOPPED")

if portfolio and report:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cash",            f"${portfolio['cash']:,.2f}",
              help="Available buying power")
    m2.metric("Portfolio Value", f"${report['portfolio_value']:,.2f}",
              help="Cash + value of open positions at last price")
    m3.metric("Realized P&L",   f"${portfolio['realized_pnl']:,.2f}",
              help="Profit/loss locked in by completed sell trades")
    m4.metric("Total Trades",   portfolio["trade_count"],
              help="Total number of individual buy + sell executions")
else:
    st.caption("Connecting to backend…")

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_overview, tab_trading, tab_insights, tab_controls = st.tabs(
    ["Overview", "Trading", "Insights", "Controls"]
)


# ══════════════════════════════════════════════════════════════════════════════
# OVERVIEW — agent state · signal · recent activity
# ══════════════════════════════════════════════════════════════════════════════
with tab_overview:
    left, right = st.columns([2, 3])

    with left:
        # Agent card
        trader = (agents or {}).get("trader", {})
        status = trader.get("status", "unknown") if trader else "unknown"
        color  = "green" if status == "idle" else "orange"
        with st.container(border=True):
            st.caption("AGENT")
            st.markdown(f"### :{color}[{status.upper()}]")
            task = trader.get("current_task") if trader else None
            st.markdown(f"`{task or '—'}`")
            if trader and trader.get("queue"):
                st.caption(f"Queued: {trader['queue']}")

        st.write("")

        # Signal card
        with st.container(border=True):
            st.caption("SIGNAL  —  SPY")
            if strategy:
                sig   = strategy.get("signal", "HOLD")
                color = SIGNAL_COLOR.get(sig, "gray")
                st.markdown(f"### :{color}[{sig}]")

                sw = strategy.get("short_window",   (config_data or {}).get("SHORT_WINDOW", 3))
                lw = strategy.get("long_window",    (config_data or {}).get("LONG_WINDOW", 7))
                s1, s2 = st.columns(2)
                s1.metric(f"MA {sw}",  f"${strategy['short_ma']:,.2f}" if strategy.get("short_ma") else "—",
                          help=f"Short moving average (window={sw})")
                s2.metric(f"MA {lw}", f"${strategy['long_ma']:,.2f}"  if strategy.get("long_ma")  else "—",
                          help=f"Long moving average (window={lw})")

                if not strategy.get("warmed_up"):
                    remaining = max(0, lw - strategy.get("price_count", 0))
                    st.caption(f"Warming up — {remaining} tick(s) needed")
                elif regime_data and not regime_data.get("error"):
                    reg    = regime_data.get("regime", "—")
                    er     = regime_data.get("efficiency_ratio")
                    active = regime_data.get("active_strategy", "—").replace("_", " ")
                    st.caption(
                        f"Regime: **{reg}** · ER {f'{er:.3f}' if er is not None else '—'} · {active}",
                    )
            else:
                st.caption("No signal data. Start mock trading.")

    with right:
        st.caption("RECENT ACTIVITY")
        if logs:
            rows = [
                {"Time": e["time"][11:19], "Task": e["task"], "Status": e["status"]}
                for e in reversed(logs[-15:])
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True, height=420)
        else:
            st.caption("No activity yet. Start mock trading to see executions.")


# ══════════════════════════════════════════════════════════════════════════════
# TRADING — stats · history · positions
# ══════════════════════════════════════════════════════════════════════════════
with tab_trading:
    if report:
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Win Rate",    f"{report['win_rate'] * 100:.1f}%",
                  help="Percentage of sell trades that closed with a profit")
        t2.metric("Avg P&L",    f"${report['avg_pnl_per_sell']:,.2f}",
                  help="Average realized P&L per completed sell")
        t3.metric("Best Trade", f"${report['best_trade_pnl']:,.2f}",
                  help="Highest single-trade profit")
        t4.metric("Worst Trade",f"${report['worst_trade_pnl']:,.2f}",
                  help="Largest single-trade loss")
    else:
        st.caption("No performance data yet.")

    st.divider()

    hist_col, pos_col = st.columns([3, 1])

    with hist_col:
        st.caption("TRADE HISTORY  (last 30)")
        trades = fetch("/monitor/trades")
        if trades:
            rows = [
                {
                    "Time":   t["timestamp"][11:19],
                    "Side":   t["side"],
                    "Qty":    t["qty"],
                    "Price":  f"${t['price']:,.2f}",
                    "P&L":    f"${t['pnl']:,.2f}",
                }
                for t in reversed(trades[-30:])
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No trades yet.")

    with pos_col:
        st.caption("OPEN POSITIONS")
        if portfolio and portfolio.get("positions"):
            rows = [
                {"Symbol": sym, "Qty": pos["qty"], "Cost": f"${pos['avg_cost']:,.2f}"}
                for sym, pos in portfolio["positions"].items()
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("None")


# ══════════════════════════════════════════════════════════════════════════════
# INSIGHTS — analysis · decision · history (expander)
# ══════════════════════════════════════════════════════════════════════════════
with tab_insights:
    left, right = st.columns(2)

    with left:
        st.subheader("Analysis")
        st.caption("Reads recent trades, produces a plain-English assessment. ~$0.0002/run.")
        if st.button("Run Analysis", use_container_width=True, key="btn_analysis"):
            with st.spinner("Calling OpenRouter…"):
                st.session_state.analysis_result = fetch("/monitor/analysis")

        res = st.session_state.analysis_result
        if res:
            if "error" in res:
                st.error(res["error"])
            else:
                st.markdown(res.get("analysis", ""))
                a1, a2 = st.columns(2)
                a1.metric("Win Rate Assessment", res.get("win_rate_assessment", "—"))
                a2.metric("Confidence",          res.get("confidence", "—"))
                st.caption(f"**Issue:** {res.get('biggest_issue', '—')}")
                st.caption(f"**Suggestion:** {res.get('suggested_improvement', '—')}")

    with right:
        st.subheader("Decision")
        st.caption("Interprets the analysis: keep going, collect more data, or flag for tuning.")
        if st.button("Get Decision", use_container_width=True, key="btn_decision"):
            with st.spinner("Evaluating…"):
                st.session_state.decision_result = fetch("/monitor/decision")

        raw = st.session_state.decision_result
        if raw:
            dec  = raw.get("decision", {})
            if "error" in dec:
                st.error(dec["error"])
            else:
                dval  = dec.get("decision", "—")
                color = DECISION_COLOR.get(dval, "gray")
                st.markdown(f"### :{color}[{dval.replace('_', ' ').upper()}]")
                d1, d2 = st.columns(2)
                d1.metric("Priority",   dec.get("priority", "—"))
                d2.metric("Confidence", f"{(raw.get('confidence_score') or dec.get('confidence_score') or 0)*100:.0f}%")
                st.caption(f"**Why:** {dec.get('reason', '—')}")
                st.caption(f"**Next:** {dec.get('recommended_action', '—')}")

    st.divider()

    with st.expander("Past recommendations & patterns"):
        if recs:
            for rec in recs:
                dval  = rec.get("decision", "—")
                color = DECISION_COLOR.get(dval, "gray")
                cols  = st.columns([3, 1])
                cols[0].markdown(f":{color}[**{dval.replace('_', ' ').upper()}**] — {rec.get('biggest_issue', '—')}")
                cols[1].caption(rec.get("timestamp", "")[:16])
                st.caption(f"→ {rec.get('recommended_action', '—')}")
                st.divider()
        else:
            st.caption("No recommendations yet.")

        if patterns and patterns.get("records_analyzed", 0) > 0:
            st.markdown(f"**Top issue ({patterns['occurrences']}×):** {patterns.get('most_common_issue') or '—'}")
            st.caption(f"Confidence trend: {patterns.get('confidence_trend', '—')} · {patterns['records_analyzed']} sessions")


# ══════════════════════════════════════════════════════════════════════════════
# CONTROLS — start/stop is the only primary content
# Everything else is in expanders.
# ══════════════════════════════════════════════════════════════════════════════
with tab_controls:
    if is_trading:
        ticks    = (trading or {}).get("ticks", 0)
        interval = (trading or {}).get("interval", "?")
        ago      = _time_ago((trading or {}).get("started_at"))
        st.success(f"Mock trading is ACTIVE — {ticks} tick(s) · every {interval}s · started {ago}")
        if st.button("Stop Mock Trading", use_container_width=True, type="primary"):
            post_req("/monitor/trading/stop")
            st.rerun()
    else:
        st.info("Mock trading is stopped.")
        interval_choice = st.select_slider(
            "Tick interval",
            options=[1, 2, 3, 5, 10, 15, 30],
            value=3,
            format_func=lambda x: f"{x}s",
            help="How often the strategy runs and potentially places a trade",
        )
        if st.button("Start Mock Trading", use_container_width=True, type="primary"):
            post_req("/monitor/trading/start", {"interval": interval_choice})
            st.rerun()

    st.write("")

    # ── Advanced ───────────────────────────────────────────────────────────────
    with st.expander("Advanced — AI insights"):
        ai1, ai2, ai3 = st.columns(3)
        with ai1:
            if st.button("Run Analysis", use_container_width=True, key="ctrl_analysis"):
                with st.spinner("…"):
                    st.session_state.analysis_result = fetch("/monitor/analysis")
                st.success("Done — see Insights.")
        with ai2:
            if st.button("Get Decision", use_container_width=True, key="ctrl_decision"):
                with st.spinner("…"):
                    st.session_state.decision_result = fetch("/monitor/decision")
                st.success("Done — see Insights.")
        with ai3:
            if st.button("Clear Cache", use_container_width=True, key="adv_clear"):
                res = post_req("/monitor/cache/clear")
                if res and not res.get("error"):
                    st.session_state.decision_result = None
                    st.success("Cleared.")

    # ── Strategy config + proposal + changelog ─────────────────────────────────
    with st.expander("Strategy config & tuning"):
        if config_data:
            g1, g2, g3, g4 = st.columns(4)
            g1.metric("SHORT_WINDOW",      config_data.get("SHORT_WINDOW", "—"))
            g2.metric("LONG_WINDOW",       config_data.get("LONG_WINDOW", "—"))
            g3.metric("MEAN_REV_WINDOW",   config_data.get("MEAN_REV_WINDOW", "—"))
            g4.metric("MEAN_REV_THRESHOLD",f"{config_data.get('MEAN_REV_THRESHOLD', 1.0):.2f}")

            g5, g6, g7, g8 = st.columns(4)
            g5.metric("STOP_LOSS_PCT",  f"{config_data.get('STOP_LOSS_PCT', 0)*100:.2f}%")
            g6.metric("POSITION_SIZE",  f"{config_data.get('POSITION_SIZE', 0)*100:.0f}%")
            g7.metric("MAX_ER",         f"{config_data.get('MAX_EFFICIENCY_RATIO', 1.0):.2f}",
                      help="Block mean-reversion entries when Efficiency Ratio exceeds this")
            g8.metric("TRADE_COOLDOWN", f"{config_data.get('TRADE_COOLDOWN', 0)} ticks")
        else:
            st.caption("Config unavailable.")

        if prop_data and prop_data.get("proposal"):
            prop = prop_data["proposal"]
            st.divider()
            st.caption("AI Proposal — not applied automatically")
            _FLOAT = {"STOP_LOSS_PCT", "TAKE_PROFIT_PCT", "POSITION_SIZE"}
            param  = prop.get("parameter", "")
            cur    = prop.get("current_value", "—")
            sug    = prop.get("proposed_value", "—")
            cur_d  = f"{cur*100:.2f}%" if param in _FLOAT and isinstance(cur, (int,float)) else str(cur)
            sug_d  = f"{sug*100:.2f}%" if param in _FLOAT and isinstance(sug, (int,float)) else str(sug)
            p1, p2, p3 = st.columns(3)
            p1.metric("Parameter", param)
            p2.metric("Current",   cur_d)
            p3.metric("Proposed",  sug_d)
            st.caption(f"Why: {prop.get('reason', '—')}")
            if st.button(f"Apply: set {param} → {sug_d}", type="primary", key="btn_apply"):
                res = post_json("/monitor/tuning/apply", prop)
                if res and not res.get("error"):
                    st.success(f"Applied: {res['parameter']} → {res['new_value']}")
                    st.rerun()
                else:
                    st.error(res.get("error") or str(res))

        if changelog:
            st.divider()
            st.caption("Recent parameter changes")
            for entry in changelog:
                cl1, cl2, cl3, cl4 = st.columns([2, 1, 1, 2])
                cl1.write(f"**{entry.get('parameter', '—')}**")
                cl2.metric("Before", entry.get("old_value", "—"))
                cl3.metric("After",  entry.get("new_value", "—"))
                cl4.caption(entry.get("timestamp", "")[:16] + " UTC")

    # ── Experiment history ─────────────────────────────────────────────────────
    with st.expander("Experiment history"):
        records = _val_records()
        if not records:
            st.caption("No validation records yet. Run `python scripts/validate_strategy.py`.")
        else:
            rows = []
            for _, r in records:
                b, c = r["baseline"], r["candidate"]
                rows.append({
                    "Date":       r["timestamp"][:16].replace("T", " "),
                    "Name":       r["experiment_name"],
                    "Decision":   r["decision"],
                    "Avg PnL Δ":  f"${c['avg_pnl']    - b['avg_pnl']:+,.0f}",
                    "Median Δ":   f"${c['median_pnl'] - b['median_pnl']:+,.0f}",
                    "Worst Δ":    f"${c['worst_pnl']  - b['worst_pnl']:+,.0f}",
                    "Trades Δ":   f"{c['avg_trades']  - b['avg_trades']:+.1f}",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

            _, latest = records[0]
            b, c = latest["baseline"], latest["candidate"]
            runs = latest.get("runs", [])
            if runs:
                with st.expander(f"Per-run breakdown — {latest['experiment_name']}"):
                    run_rows = [
                        {
                            "Seed": row["seed"], "Ticks": row["ticks"],
                            "Base PnL": f"${row['base_pnl']:,.2f}",
                            "Cand PnL": f"${row['cand_pnl']:,.2f}",
                            "PnL Δ":    f"${row['pnl_delta']:+,.2f}",
                            "Trade Δ":  f"{row['trade_delta']:+d}",
                        }
                        for row in runs
                    ]
                    st.dataframe(run_rows, use_container_width=True, hide_index=True)


# ── Footer ─────────────────────────────────────────────────────────────────────
st.caption(f"Auto-refresh every {REFRESH_INTERVAL}s  ·  backend {API_BASE}")
time.sleep(REFRESH_INTERVAL)
st.rerun()
