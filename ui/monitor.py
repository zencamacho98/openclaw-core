import time
from datetime import datetime, timezone

import requests
import streamlit as st

API_BASE        = "http://127.0.0.1:8000"
REFRESH_INTERVAL = 5

st.set_page_config(
    page_title="OpenClaw Operator Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Colour maps ────────────────────────────────────────────────────────────────
DECISION_COLOR = {"flag_for_tuning": "red", "collect_more_data": "orange", "monitor": "green"}
SIGNAL_COLOR   = {"BUY": "green", "SELL": "red", "HOLD": "gray"}
CONF_COLOR     = {"high": "red", "medium": "orange", "low": "gray"}
STATUS_COLOR   = {"idle": "green", "working": "orange"}

# ── HTTP helpers ───────────────────────────────────────────────────────────────
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


def _time_ago(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        started = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta   = int((datetime.now(timezone.utc) - started).total_seconds())
        if delta < 60:   return f"{delta}s ago"
        if delta < 3600: return f"{delta // 60}m ago"
        return f"{delta // 3600}h {(delta % 3600) // 60}m ago"
    except Exception:
        return ""


# ── Session state ──────────────────────────────────────────────────────────────
for key in ("analysis_result", "decision_result", "ctrl_msg"):
    if key not in st.session_state:
        st.session_state[key] = None

# ── Fetch all auto-refresh data ────────────────────────────────────────────────
portfolio    = fetch("/monitor/portfolio")
report       = fetch("/monitor/report")
agents       = fetch("/monitor/agents")
strategy     = fetch("/monitor/strategy?symbol=SPY")
logs         = fetch("/logs")
recs         = fetch("/monitor/recommendations?n=5")
patterns     = fetch("/monitor/patterns?n=20")
prop_data    = fetch("/monitor/proposal")
trading      = fetch("/monitor/trading/status")   # live trading loop status
config_data    = fetch("/monitor/config")
changelog_data = fetch("/monitor/tuning/changelog?n=10")
regime_data    = fetch("/monitor/regime?symbol=SPY")

# ── Title ──────────────────────────────────────────────────────────────────────
st.title("OpenClaw Operator Dashboard")

# ── Trading status banner (always visible) ─────────────────────────────────────
is_trading = (trading or {}).get("running", False)

if is_trading:
    ticks    = (trading or {}).get("ticks", 0)
    interval = (trading or {}).get("interval", "?")
    ago      = _time_ago((trading or {}).get("started_at"))
    st.success(
        f"Mock trading is ACTIVE — {ticks} tick(s) completed | "
        f"every {interval}s | started {ago}"
    )
else:
    st.info("Mock trading is STOPPED. Go to Controls to start.")

# ── Portfolio summary strip ────────────────────────────────────────────────────
if portfolio and report:
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Cash",            f"${portfolio['cash']:,.2f}")
    m2.metric("Portfolio Value", f"${report['portfolio_value']:,.2f}")
    m3.metric("Realized P&L",    f"${portfolio['realized_pnl']:,.2f}")
    m4.metric("Unrealized P&L",  f"${portfolio['unrealized_pnl']:,.2f}")
    m5.metric("Total Trades",    portfolio["trade_count"])

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_overview, tab_trading, tab_insights, tab_suggestions, tab_controls = st.tabs(
    ["Overview", "Trading", "AI Insights", "Suggestions", "Controls"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_overview:
    left, right = st.columns([1, 1])

    with left:
        # ── Trader agent (primary) ─────────────────────────────────────────────
        st.subheader("Trader Agent")
        trader = (agents or {}).get("trader", {})
        if trader:
            status = trader.get("status", "unknown")
            color  = STATUS_COLOR.get(status, "gray")
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                c1.markdown(f"### :{color}[{status.upper()}]")
                c2.write(f"**Current task:** `{trader.get('current_task') or '—'}`")
                c2.write(f"**Queue:** {trader.get('queue') or '(empty)'}")
        else:
            st.caption("No trader data.")

        # ── Strategy signal ────────────────────────────────────────────────────
        st.subheader("Strategy Signal — SPY")
        if strategy:
            signal = strategy.get("signal", "—")
            color  = SIGNAL_COLOR.get(signal, "gray")
            sw  = strategy.get("short_window",   (config_data or {}).get("SHORT_WINDOW",   3))
            lw  = strategy.get("long_window",    (config_data or {}).get("LONG_WINDOW",    7))
            mg  = strategy.get("min_signal_gap", (config_data or {}).get("MIN_SIGNAL_GAP", 0.0))
            gap = strategy.get("signal_gap")

            s1, s2, s3, s4 = st.columns(4)
            s1.markdown(f"# :{color}[{signal}]")
            s2.metric(f"Short MA ({sw})", f"${strategy['short_ma']:,.2f}" if strategy.get("short_ma") else "—")
            s3.metric(f"Long MA ({lw})",  f"${strategy['long_ma']:,.2f}"  if strategy.get("long_ma")  else "—")
            gap_display = f"{gap:.4f}" if gap is not None else "—"
            gap_ok      = strategy.get("gap_sufficient", True)
            s4.metric("MA Gap", gap_display, help=f"Min required: {mg:.2f}")
            if not strategy.get("warmed_up"):
                left_ticks = max(0, lw - strategy.get("price_count", 0))
                st.caption(f"Warming up — strategy needs {left_ticks} more tick(s) before it produces signals.")
            elif gap is not None and not gap_ok:
                st.caption(f"Gap {gap:.4f} ≤ MIN_SIGNAL_GAP {mg:.2f} — signal suppressed (HOLD).")
            else:
                st.caption(f"Strategy is warmed up. {strategy.get('price_count', 0)} price observations recorded.")

        # ── Regime state ───────────────────────────────────────────────────────
        st.subheader("Market Regime — SPY")
        if regime_data and not regime_data.get("error"):
            reg    = regime_data.get("regime", "—")
            active = regime_data.get("active_strategy", "—")
            er     = regime_data.get("efficiency_ratio")
            reg_color = "green" if reg == "trending" else "orange"
            r1, r2, r3 = st.columns(3)
            r1.markdown(f"### :{reg_color}[{reg.upper()}]")
            r2.metric("Active strategy", active.replace("_", " "))
            r3.metric("Efficiency Ratio", f"{er:.3f}" if er is not None else "—")

            mr = regime_data.get("mean_reversion", {})
            ma = regime_data.get("ma_crossover", {})
            with st.expander("Sub-strategy details"):
                sc1, sc2 = st.columns(2)
                with sc1:
                    st.caption("MA Crossover")
                    st.write(f"Signal: `{ma.get('signal', '—')}`  "
                             f"| gap: {ma.get('signal_gap', '—')}")
                with sc2:
                    st.caption("Mean Reversion")
                    st.write(f"Signal: `{mr.get('signal', '—')}`  "
                             f"| mean: {mr.get('mean', '—')}  "
                             f"| lower: {mr.get('lower_band', '—')}")
        else:
            st.caption("Regime data unavailable — start mock trading to populate price history.")

    with right:
        # ── Recent execution log ───────────────────────────────────────────────
        st.subheader("Recent Activity")
        if logs:
            rows = [
                {
                    "Time":   e["time"][:19],
                    "Agent":  e["agent"],
                    "Task":   e["task"],
                    "Status": e["status"],
                }
                for e in reversed(logs[-15:])
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No activity yet. Start mock trading to see executions here.")

    # ── Other agents (not part of current workflow) ────────────────────────────
    with st.expander("Other agents (not part of current workflow)"):
        for name, info in (agents or {}).items():
            if name == "trader":
                continue
            status = info.get("status", "unknown")
            st.write(f"**{name}** — {status} | task: {info.get('current_task') or '—'}")
        st.caption("ui_builder is defined in the system but is not used in the mock trading workflow.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — TRADING
# ══════════════════════════════════════════════════════════════════════════════
with tab_trading:
    if report:
        p1, p2, p3, p4, p5, p6 = st.columns(6)
        p1.metric("Win Rate",    f"{report['win_rate'] * 100:.1f}%")
        p2.metric("Avg P&L",     f"${report['avg_pnl_per_sell']:,.2f}")
        p3.metric("Best Trade",  f"${report['best_trade_pnl']:,.2f}")
        p4.metric("Worst Trade", f"${report['worst_trade_pnl']:,.2f}")
        p5.metric("Buys",        report["total_buys"])
        p6.metric("Sells",       report["total_sells"])
    else:
        st.caption("No performance data yet.")

    st.divider()

    st.subheader("Open Positions")
    if portfolio and portfolio.get("positions"):
        rows = [
            {
                "Symbol":       sym,
                "Qty":          pos["qty"],
                "Avg Cost":     f"${pos['avg_cost']:,.2f}",
                "Market Value": f"${pos['qty'] * pos['avg_cost']:,.2f}",
            }
            for sym, pos in portfolio["positions"].items()
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No open positions.")

    st.divider()

    st.subheader("Trade History")
    trades = fetch("/monitor/trades")
    if trades:
        rows = [
            {
                "Time":   t["timestamp"][:19],
                "Symbol": t["symbol"],
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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — AI INSIGHTS
# Manually triggered. Calls OpenRouter (~$0.0002/run).
# ══════════════════════════════════════════════════════════════════════════════
with tab_insights:
    st.caption(
        "AI Insights reads recent trade history and produces a plain-English assessment. "
        "Run it after enough trades have accumulated. Each run costs ~$0.0002."
    )
    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("Analysis")
        st.caption("What the strategy is doing and what the main problem is.")

        if st.button("Run Analysis", use_container_width=True, key="btn_analysis"):
            with st.spinner("Calling OpenRouter..."):
                st.session_state.analysis_result = fetch("/monitor/analysis")

        result = st.session_state.analysis_result
        if result:
            if "error" in result:
                st.error(result["error"])
            else:
                st.markdown(result.get("analysis", ""))
                r1, r2 = st.columns(2)
                r1.metric("Win Rate Assessment", result.get("win_rate_assessment", "—"))
                r2.metric("Confidence",          result.get("confidence", "—"))
                st.markdown(f"**Main issue:** {result.get('biggest_issue', '—')}")
                st.markdown(f"**Suggestion:** {result.get('suggested_improvement', '—')}")
                tokens = result.get("tokens", {})
                st.caption(f"Tokens: {tokens.get('total', '—')} | Model: {result.get('model', '—')}")

    with right:
        st.subheader("Decision")
        st.caption(
            "Interprets the analysis and tells you what to do next: "
            "keep going, collect more data, or flag for tuning."
        )

        if st.button("Get Decision", use_container_width=True, key="btn_decision"):
            with st.spinner("Evaluating..."):
                st.session_state.decision_result = fetch("/monitor/decision")

        raw = st.session_state.decision_result
        if raw:
            dec = raw.get("decision", {})
            if "error" in dec:
                st.error(dec["error"])
            else:
                dval  = dec.get("decision", "—")
                color = DECISION_COLOR.get(dval, "gray")
                st.markdown(f"### :{color}[{dval.replace('_', ' ').upper()}]")
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("Priority",        dec.get("priority", "—"))
                d2.metric("Action type",     raw.get("action_type") or dec.get("action_type") or "—")
                d3.metric("Confidence",      f"{(raw.get('confidence_score') or dec.get('confidence_score') or 0) * 100:.0f}%")
                d4.metric("From cache",      "Yes" if raw.get("cache_used") else "No")
                st.markdown(f"**Why:** {dec.get('reason', '—')}")
                st.markdown(f"**Next step:** {dec.get('recommended_action', '—')}")
                if raw.get("cached_at"):
                    st.caption(f"Analysis cached: {raw['cached_at'][:19]} UTC")

    st.divider()
    st.caption("Use the button below if you want to force a completely fresh analysis on the next 'Get Decision' call.")
    if st.button("Reset cached analysis", key="btn_clear_analysis"):
        res = post_req("/monitor/cache/clear")
        if res and not res.get("error"):
            st.session_state.decision_result = None
            st.success("Cache cleared.")
        else:
            st.error(str(res))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SUGGESTIONS
# Read-only. Shows AI recommendations and pattern trends over time.
# Nothing here is ever applied automatically.
# ══════════════════════════════════════════════════════════════════════════════
with tab_suggestions:
    st.caption(
        "Suggestions are produced by the AI analysis and decision engine. "
        "They are stored for review only — nothing is ever changed automatically."
    )
    st.divider()

    left, right = st.columns([1, 1])

    with left:
        st.subheader("Recent AI Recommendations")
        if recs:
            for rec in recs:
                dval  = rec.get("decision", "—")
                color = DECISION_COLOR.get(dval, "gray")
                with st.container(border=True):
                    h1, h2 = st.columns([2, 1])
                    h1.markdown(f":{color}[**{dval.replace('_', ' ').upper()}**]")
                    h2.caption(rec.get("timestamp", "")[:16] + " UTC")
                    st.write(f"**Issue:** {rec.get('biggest_issue', '—')}")
                    st.write(f"**Suggested action:** {rec.get('recommended_action', '—')}")
                    st.caption(
                        f"Win rate: {rec.get('win_rate_assessment', '—')} | "
                        f"Confidence: {rec.get('confidence', '—')} | "
                        f"Trades analyzed: {rec.get('trades_analyzed', '—')}"
                    )
        else:
            st.caption("No recommendations yet. Run 'Get Decision' in AI Insights to generate one.")

    with right:
        st.subheader("Recurring Patterns")
        if patterns and patterns.get("records_analyzed", 0) > 0:
            pa, pb, pc = st.columns(3)
            pa.metric("Sessions analyzed",  patterns["records_analyzed"])
            pb.metric("Confidence trend",   patterns["confidence_trend"].capitalize())
            pc.metric("Top issue seen",     f"{patterns['occurrences']}×")

            dec = patterns.get("decision_counts", {})
            da, db, dc = st.columns(3)
            da.metric("Flag for tuning",   dec.get("flag_for_tuning", 0))
            db.metric("Monitor",           dec.get("monitor", 0))
            dc.metric("Need more data",    dec.get("collect_more_data", 0))

            st.markdown(f"**Most repeated issue:** {patterns.get('most_common_issue') or '—'}")
            st.markdown(f"**Most repeated suggestion:** {patterns.get('most_common_recommendation') or '—'}")

            with st.expander("Full issue breakdown"):
                for issue, count in (patterns.get("issue_frequency") or {}).items():
                    st.write(f"- ({count}×) {issue}")
        else:
            st.caption("No pattern data yet. Run several AI Insight sessions to see trends.")

    # ── Current strategy config ────────────────────────────────────────────────
    st.divider()
    st.subheader("Current Strategy Parameters")
    if config_data:
        # Row 1 — MA crossover
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("SHORT_WINDOW",   config_data.get("SHORT_WINDOW", "—"))
        sc2.metric("LONG_WINDOW",    config_data.get("LONG_WINDOW", "—"))
        sc3.metric("MIN_SIGNAL_GAP", f"{config_data.get('MIN_SIGNAL_GAP', 0.0):.2f}")
        # Row 2 — regime + mean reversion
        rr1, rr2, rr3, rr4 = st.columns(4)
        rr1.metric("REGIME_WINDOW",      config_data.get("REGIME_WINDOW", "—"))
        rr2.metric("REGIME_THRESHOLD",   f"{config_data.get('REGIME_THRESHOLD', 0.3):.2f}")
        rr3.metric("MEAN_REV_WINDOW",    config_data.get("MEAN_REV_WINDOW", "—"))
        rr4.metric("MEAN_REV_THRESHOLD", f"{config_data.get('MEAN_REV_THRESHOLD', 1.0):.2f}")
        # Row 2b — mean reversion sizing and exit
        rv1, rv2, rv3, rv4 = st.columns(4)
        rv1.metric("MEAN_REV_EXIT_FRACTION", f"{config_data.get('MEAN_REV_EXIT_FRACTION', 1.0):.2f}",
                   help="1.0 = exit at mean; 0.5 = exit halfway back toward mean")
        rv2.metric("MIN_VOLATILITY", f"{config_data.get('MIN_VOLATILITY', 0.0):.2f}",
                   help="Min rolling std to allow entry (0.0 = disabled)")
        rv3.metric("MEAN_REV_SIZE_MULT", f"{config_data.get('MEAN_REV_SIZE_MULTIPLIER', 0.0):.2f}",
                   help="Scales position size with signal depth (0 = fixed POSITION_SIZE)")
        rv4.metric("MAX_POSITION_SIZE", f"{config_data.get('MAX_POSITION_SIZE', 0.5) * 100:.0f}%",
                   help="Hard cap on dynamic MR position size (applies when SIZE_MULT > 0)")
        # Row 2c — entry quality filters
        rq1, rq2 = st.columns(2)
        rq1.metric("MIN_ENTRY_DEPTH", f"{config_data.get('MIN_ENTRY_DEPTH', 0.0):.2f}",
                   help="Min normalized depth below lower band to allow BUY (0 = any breach)")
        rq2.metric("MAX_EFFICIENCY_RATIO", f"{config_data.get('MAX_EFFICIENCY_RATIO', 1.0):.2f}",
                   help="Block MR entries when ER exceeds this (1.0 = disabled; lower = stricter)")
        # Row 3 — risk management
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("STOP_LOSS_PCT",   f"{config_data.get('STOP_LOSS_PCT', 0) * 100:.2f}%")
        rc2.metric("TAKE_PROFIT_PCT", f"{config_data.get('TAKE_PROFIT_PCT', 0) * 100:.2f}%" if config_data.get('TAKE_PROFIT_PCT', 0) > 0 else "off")
        rc3.metric("POSITION_SIZE",   f"{config_data.get('POSITION_SIZE', 0) * 100:.0f}%")
        rc4.metric("TRADE_COOLDOWN",  f"{config_data.get('TRADE_COOLDOWN', 0)} ticks")
        # Row 3b — MR dynamic stop
        rd1, rd2 = st.columns(2)
        rd1.metric("MEAN_REV_STOP_VOL_MULT", f"{config_data.get('MEAN_REV_STOP_VOL_MULT', 0.0):.2f}",
                   help="Dynamic stop = max(MIN_STOP, (std/price) × this). 0 = fixed STOP_LOSS_PCT")
        rd2.metric("MIN_STOP_LOSS_PCT", f"{config_data.get('MIN_STOP_LOSS_PCT', 0.01) * 100:.2f}%",
                   help="Floor on the dynamic stop so it never becomes unrealistically tight")
    else:
        st.caption("Config unavailable.")

    # ── Structured parameter proposal ─────────────────────────────────────────
    st.divider()
    st.subheader("Structured Parameter Proposal")

    if prop_data:
        prop   = prop_data.get("proposal")
        source = prop_data.get("source", {})
        if prop:
            confidence = prop.get("source_confidence", "—")
            conf_color = CONF_COLOR.get(confidence, "gray")
            with st.container(border=True):
                st.warning(
                    "This is a suggestion only. It has NOT been applied and will NOT be applied "
                    "automatically. Manual approval is required before anything changes."
                )
                _FLOAT_PARAMS = {"STOP_LOSS_PCT", "TAKE_PROFIT_PCT", "POSITION_SIZE"}
                param = prop.get("parameter", "")
                cur   = prop.get("current_value", "—")
                sug   = prop.get("proposed_value", "—")
                if param in _FLOAT_PARAMS and isinstance(cur, (int, float)):
                    cur_display = f"{cur * 100:.2f}%"
                    sug_display = f"{sug * 100:.2f}%" if isinstance(sug, (int, float)) else sug
                else:
                    cur_display = str(cur)
                    sug_display = str(sug)

                pr1, pr2, pr3, pr4 = st.columns(4)
                pr1.metric("Parameter",       param or "—")
                pr2.metric("Current value",   cur_display)
                pr3.metric("Suggested value", sug_display)
                pr4.markdown(
                    f"**Confidence:** :{conf_color}[{confidence}]  \n"
                    f"Seen in {prop.get('occurrence_ratio', 0)*100:.0f}% of sessions"
                )
                st.markdown(f"**Why:** {prop.get('reason', '—')}")
                st.caption(f"Matched from: _{prop.get('matched_recommendation', '—')}_")

                st.divider()
                st.markdown("**Apply this proposal manually**")
                st.caption(
                    "Clicking Apply sends this proposal to the backend. "
                    "The change takes effect on the next tick. This action is logged."
                )
                if st.button(
                    f"Apply: set {param} = {sug_display}  (was {cur_display})",
                    type="primary",
                    key="btn_apply_proposal",
                ):
                    result = post_json("/monitor/tuning/apply", prop)
                    if result and not result.get("error"):
                        st.success(
                            f"Applied: {result['parameter']} changed "
                            f"{result['old_value']} → {result['new_value']}"
                        )
                        st.rerun()
                    else:
                        st.error(result.get("error") or str(result))
        else:
            st.info(
                "No structured parameter proposal yet. The AI suggestion did not match a "
                "recognized parameter pattern, or there is not enough data."
            )
            if source.get("most_common_recommendation"):
                st.caption(f"Latest unmatched suggestion: _{source['most_common_recommendation']}_")
    else:
        st.caption("No proposal data available.")

    # ── Parameter change changelog ─────────────────────────────────────────────
    st.divider()
    st.subheader("Parameter Change Log")
    if changelog_data:
        for entry in changelog_data:
            with st.container(border=True):
                cl1, cl2, cl3, cl4 = st.columns([2, 1, 1, 2])
                cl1.write(f"**{entry.get('parameter', '—')}**")
                cl2.metric("Before", entry.get("old_value", "—"))
                cl3.metric("After",  entry.get("new_value", "—"))
                cl4.caption(entry.get("timestamp", "")[:19] + " UTC")
                st.caption(f"Reason: {entry.get('reason', '—')}")
                perf = entry.get("performance_snapshot", {})
                if perf:
                    p1, p2, p3 = st.columns(3)
                    p1.caption(f"Win rate at change: {perf.get('win_rate', 0)*100:.1f}%")
                    p2.caption(f"Avg P&L: ${perf.get('avg_pnl_per_sell', 0):,.2f}")
                    p3.caption(f"Portfolio value: ${perf.get('portfolio_value', 0):,.2f}")
    else:
        st.caption("No parameter changes recorded yet. Apply a proposal above to create the first entry.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — CONTROLS
# Operator workflow: start/stop trading, trigger AI, advanced options hidden.
# ══════════════════════════════════════════════════════════════════════════════
with tab_controls:

    # ── PRIMARY: Mock Trading ──────────────────────────────────────────────────
    st.subheader("Mock Trading")
    st.caption(
        "Runs the simulated SPY strategy on repeat. Each tick assigns a trade task "
        "to the trader agent and executes it automatically."
    )

    if is_trading:
        ticks    = (trading or {}).get("ticks", 0)
        interval = (trading or {}).get("interval", "?")
        ago      = _time_ago((trading or {}).get("started_at"))
        st.success(f"ACTIVE — {ticks} tick(s) | every {interval}s | started {ago}")
        if st.button("Stop Mock Trading", use_container_width=True, type="primary"):
            post_req("/monitor/trading/stop")
            st.rerun()
    else:
        st.error("STOPPED")
        interval_choice = st.select_slider(
            "Run a tick every",
            options=[1, 2, 3, 5, 10, 15, 30],
            value=3,
            format_func=lambda x: f"{x} seconds",
            key="trading_interval",
        )
        if st.button("Start Mock Trading", use_container_width=True, type="primary"):
            post_req("/monitor/trading/start", {"interval": interval_choice})
            st.rerun()

    st.divider()

    # ── AI Insights shortcuts ──────────────────────────────────────────────────
    st.subheader("AI Insights")
    st.caption("Run after enough trades have accumulated. Each call costs ~$0.0002.")
    ai1, ai2 = st.columns(2)

    with ai1:
        if st.button("Run Analysis", use_container_width=True, key="ctrl_analysis"):
            with st.spinner("Calling OpenRouter..."):
                st.session_state.analysis_result = fetch("/monitor/analysis")
                st.success("Done — see AI Insights tab.")

    with ai2:
        if st.button("Get Decision", use_container_width=True, key="ctrl_decision"):
            with st.spinner("Evaluating..."):
                st.session_state.decision_result = fetch("/monitor/decision")
                st.success("Done — see AI Insights tab.")

    st.divider()

    # ── Advanced (hidden by default) ───────────────────────────────────────────
    with st.expander("Advanced — developer controls"):
        st.caption(
            "These controls expose the underlying execution system directly. "
            "Use only if you know what you are doing. "
            "Do not run the raw loop while mock trading is already active."
        )
        st.divider()

        # Assign a specific task manually
        st.markdown("**Assign a specific task**")
        adv1, adv2, adv3 = st.columns([1, 2, 1])
        adv_agent = adv1.selectbox("Agent", ["trader", "ui_builder"], key="adv_agent")
        adv_task  = adv2.text_input("Task name", placeholder="mock_trade_spy", key="adv_task")
        if adv3.button("Assign", key="adv_assign"):
            if adv_task.strip():
                res = post_req("/agents/assign", {"agent": adv_agent, "task": adv_task.strip()})
                st.session_state.ctrl_msg = res.get("message") or res.get("error") or str(res)
            else:
                st.session_state.ctrl_msg = "Enter a task name."

        # Run worker manually
        st.markdown("**Run worker once**")
        wk1, wk2 = st.columns([1, 2])
        wk_max = wk1.number_input("Max tasks", min_value=1, max_value=20, value=1, key="adv_max")
        if wk2.button("Run Worker", key="adv_run", use_container_width=True):
            res = post_req("/run", {"max_tasks": int(wk_max)})
            n = res.get("processed", "?")
            st.session_state.ctrl_msg = f"Processed {n} task(s)." if "error" not in res else res["error"]

        if st.session_state.ctrl_msg:
            st.info(st.session_state.ctrl_msg)

        st.divider()

        # Raw background loop (app/loop.py)
        st.markdown("**Raw execution loop** (processes any queued tasks)")
        raw_loop = fetch("/monitor/loop") or {}
        raw_running = raw_loop.get("running", False)
        if raw_running:
            st.warning("Raw loop is RUNNING")
            if st.button("Stop Raw Loop", key="adv_loop_stop"):
                post_req("/loop/stop")
                st.rerun()
        else:
            st.write("Raw loop is stopped.")
            rl1, rl2, rl3 = st.columns(3)
            rl_int = rl1.number_input("Interval (s)", 1, 60, 5, key="adv_loop_int")
            rl_max = rl2.number_input("Max tasks",    1, 10, 1, key="adv_loop_max")
            if rl3.button("Start Raw Loop", key="adv_loop_start"):
                post_req("/loop/start", {"interval": int(rl_int), "max_tasks": int(rl_max)})
                st.rerun()

        st.divider()

        # Cache management
        st.markdown("**Analysis cache**")
        st.caption("Clear this to force a fresh OpenRouter call on the next 'Get Decision'.")
        if st.button("Clear Analysis Cache", key="adv_clear"):
            res = post_req("/monitor/cache/clear")
            if res and not res.get("error"):
                st.session_state.decision_result = None
                st.success("Cache cleared.")
            else:
                st.error(str(res))


# ── Footer / auto-refresh ──────────────────────────────────────────────────────
st.divider()
st.caption(f"Auto-refreshing every {REFRESH_INTERVAL}s")
time.sleep(REFRESH_INTERVAL)
st.rerun()
