"""
ui/dashboard.py  —  The Abode operator console.

Tabs: Home · Peter · Mr Belfort · Controls

Home is the landing view: system status, agent cards, attention items, recent activity.
Peter is the communication hub and primary operator interface.
Mr Belfort's home shows trading activity, learning progress, and strategy upgrades.
Controls holds developer tools, cost tracking, and advanced settings.
"""
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

import requests
import streamlit as st
import streamlit.components.v1 as _stc

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from ui.campaign_control import (
    validate_campaign_form, start_campaign, resume_campaign, request_stop,
    cancel_stop_signal, stop_signal_pending, list_campaigns,
    list_resumable_campaigns, check_lock, load_campaign_state,
    get_best_candidate, get_promotion_command, get_campaign_brief_paths,
    _CAP_SESSIONS, _CAP_BATCHES, _MIN_EXP_BATCH, _CAP_EXP_BATCH, _CAP_EXP_TOTAL,
    _DEFAULT_SESSIONS, _DEFAULT_BATCHES, _DEFAULT_EXP, _DEFAULT_EXP_TOTAL,
)
from ui.peter_helpers import (
    belfort_action_state, auto_continue_goal, loop_explanation_text,
)
from ui.review_actions import (
    get_review_payload, skip_and_continue_action, hold_review, resume_review, skip_review,
)
from ui.trade_helpers import format_trade_row, format_pnl, trading_status_summary

try:
    from observability.event_log import append_event as _append_event, read_recent_events as _read_events
except Exception:
    def _append_event(*args, **kwargs): pass  # type: ignore[misc]
    def _read_events(*args, **kwargs): return []  # type: ignore[misc]

try:
    from ui.peter_command import execute_ui_command as _peter_execute
except Exception:
    def _peter_execute(*args: object, **kwargs: object) -> dict:  # type: ignore[misc]
        return {"ok": False, "message": "Peter command handler not available.", "event_type": "", "severity": "", "extra": {}, "command_type": ""}

try:
    from ui.peter_lm import (
        is_available as _lm_available,
        build_peter_context as _build_peter_context,
        peter_briefing as _peter_lm_briefing,
        peter_understand as _peter_lm_understand,
    )
    _PETER_LM_LOADED = True
except Exception:
    _PETER_LM_LOADED = False
    def _lm_available() -> bool: return False  # type: ignore[misc]
    def _build_peter_context(*a, **kw) -> dict: return {}  # type: ignore[misc]
    def _peter_lm_briefing(ctx: dict) -> dict: return {"ok": False, "text": "", "error": "not loaded"}  # type: ignore[misc]
    def _peter_lm_understand(text: str, ctx: dict) -> dict: return {"ok": False, "command": "none", "needs_confirmation": False, "response": "", "intent_summary": "", "error": "not loaded"}  # type: ignore[misc]

try:
    from ui.peter_build import route_build_task as _route_build_task, is_build_task as _is_build_task
    _PETER_BUILD_LOADED = True
except Exception:
    _PETER_BUILD_LOADED = False
    def _route_build_task(text: str, ctx: dict) -> dict: return {"route": "error", "ok": False, "summary": "Build module not loaded.", "edits": [], "needs_approval": False, "escalation_reason": "", "builder_confidence": 0.0, "model_used": ""}  # type: ignore[misc]
    def _is_build_task(text: str) -> bool: return False  # type: ignore[misc]

API_BASE         = "http://127.0.0.1:8001"
REFRESH_INTERVAL = 5
VALIDATION_DIR   = pathlib.Path("data/validation_runs")
AGENT_STATE_DIR  = _REPO_ROOT / "data" / "agent_state"
TELEMETRY_DIR    = _REPO_ROOT / "data" / "telemetry"

SIGNAL_COLOR   = {"BUY": "green", "SELL": "red", "HOLD": "gray"}
DECISION_COLOR = {"flag_for_tuning": "red", "collect_more_data": "orange", "monitor": "green"}

st.set_page_config(page_title="The Abode", layout="wide", initial_sidebar_state="collapsed")


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


# ── UI helpers ─────────────────────────────────────────────────────────────────

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

def _load_agent_state(agent_name: str) -> dict:
    path = AGENT_STATE_DIR / f"{agent_name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

def _load_telemetry_summary(scope_id: str) -> dict:
    empty = {
        "request_count": 0, "input_tokens": 0, "output_tokens": 0,
        "total_tokens": 0, "estimated_cost_usd": 0.0, "is_estimated": True,
        "event_count": 0,
    }
    if not scope_id:
        return empty
    path = TELEMETRY_DIR / f"{scope_id}_telemetry.jsonl"
    if not path.exists():
        return empty
    try:
        events = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    except Exception:
        return empty
    if not events:
        return empty
    return {
        "event_count":        len(events),
        "request_count":      sum(e.get("request_count", 0)      for e in events),
        "input_tokens":       sum(e.get("input_tokens", 0)        for e in events),
        "output_tokens":      sum(e.get("output_tokens", 0)       for e in events),
        "total_tokens":       sum(e.get("total_tokens", 0)        for e in events),
        "estimated_cost_usd": sum(e.get("estimated_cost_usd", 0)  for e in events),
        "is_estimated":       any(e.get("is_estimated", True)     for e in events),
    }

def _status_color(status: str) -> str:
    return {
        "running_campaign":     "orange",
        "running_session":      "orange",
        "running_batch":        "orange",
        "waiting_for_review":   "blue",
        "paused_by_budget":     "red",
        "stopped_by_guardrail": "red",
        "idle":                 "gray",
    }.get(status, "gray")

def _budget_bar_str(pct: float, width: int = 20) -> str:
    filled = min(int(pct / 100 * width), width)
    return "█" * filled + "░" * (width - filled)

def _peter_next_action(action_state: str, campaign_id: str | None) -> str:
    """Plain-English recommended next operator action for the Peter tab."""
    if action_state == "running":
        return "Mr Belfort is running. Monitor progress in the Mr Belfort tab or send Stop when ready."
    if action_state == "stop_pending":
        return "Stop signal sent. Mr Belfort will finish the current session and halt cleanly."
    if action_state == "waiting_for_review":
        return "Review needed: a strong candidate is waiting. Use the buttons below to apply, skip, or defer."
    if action_state == "review_held":
        return "Deferred review pending — a strong candidate is still waiting. Resume review when ready."
    if action_state == "idle_with_resumable":
        return "Mr Belfort is idle. Send 'resume' to continue the most recent research run, or 'start' for a new one."
    return "Mr Belfort is idle. Send 'start' to begin auto research."


def _peter_briefing_text(
    action_state: str,
    b_status: str,
    sup_enabled: bool,
    sup_cycles: int,
    queue_pending: list,
    checker_findings: list,
) -> str:
    """Two or three plain-English sentences that Peter would deliver as a briefing."""
    parts: list[str] = []

    if b_status in ("running_campaign", "running_session", "running_batch"):
        parts.append("Mr Belfort is actively running research experiments.")
    elif b_status == "waiting_for_review":
        parts.append("Mr Belfort has found a strong candidate strategy and is waiting for your review.")
    elif b_status == "review_held":
        parts.append("A candidate review is deferred and is still waiting for your decision.")
    elif b_status == "paused_by_budget":
        parts.append("Mr Belfort has paused — the budget limit was reached.")
    elif b_status == "stopped_by_guardrail":
        parts.append("Mr Belfort stopped after a guardrail was triggered.")
    else:
        parts.append("Mr Belfort is idle and ready to start research.")

    if sup_enabled:
        parts.append(f"The learning loop is active — cycle {sup_cycles + 1} is in progress.")
    elif sup_cycles > 0:
        parts.append(f"{sup_cycles} learning cycle(s) completed.")

    n_q = len(queue_pending)
    if n_q:
        parts.append(f"{n_q} candidate(s) in the upgrade queue are waiting for your review.")

    n_warn = sum(1 for f in checker_findings if f.get("severity") == "warning")
    if n_warn:
        parts.append(f"The loop checker has flagged {n_warn} issue(s) worth looking at.")

    return " ".join(parts)

def _belfort_plain_status(b_status: str, b_learning: bool, camp_state: dict) -> str:
    """One plain-English sentence describing what Belfort is doing."""
    goal     = camp_state.get("goal", "")
    sess_sums = camp_state.get("session_summaries", [])
    classes  = ""
    if sess_sums:
        recent_classes = sess_sums[-1].get("classes_tested", [])
        if recent_classes:
            classes = " · testing " + ", ".join(recent_classes[:2])

    if b_status in ("running_campaign", "running_session", "running_batch"):
        if goal:
            return f"Mr Belfort is running experiments — goal: {goal[:80]}{classes}"
        return f"Mr Belfort is running experiments{classes}"
    if b_status == "waiting_for_review":
        return "Mr Belfort found a candidate and is waiting for your review."
    if b_status == "review_held":
        return "Review deferred — a candidate is held pending your decision."
    if b_status == "paused_by_budget":
        return "Mr Belfort is paused — budget limit reached."
    if b_status == "stopped_by_guardrail":
        return "Mr Belfort stopped — a guardrail was triggered."
    if b_learning:
        return "Mr Belfort is learning (loop active)."
    return "Mr Belfort is idle."


# ── Session state ──────────────────────────────────────────────────────────────
for _k in ("analysis_result", "decision_result", "ctrl_result", "peter_cmd_response"):
    if _k not in st.session_state:
        st.session_state[_k] = None

# LM state: briefing cache + pending confirmation
if "peter_lm_brief_ts"    not in st.session_state: st.session_state["peter_lm_brief_ts"]    = 0.0
if "peter_lm_brief_txt"   not in st.session_state: st.session_state["peter_lm_brief_txt"]   = ""
if "peter_lm_brief_tier"  not in st.session_state: st.session_state["peter_lm_brief_tier"]  = ""
if "peter_lm_brief_model" not in st.session_state: st.session_state["peter_lm_brief_model"] = ""
if "peter_lm_pending"   not in st.session_state: st.session_state["peter_lm_pending"]   = None
# Build state: pending patch draft awaiting operator approval
if "peter_build_pending" not in st.session_state: st.session_state["peter_build_pending"] = None


# ── Backend fetch ──────────────────────────────────────────────────────────────
recs        = fetch("/monitor/recommendations?n=5")
patterns    = fetch("/monitor/patterns?n=20")
prop_data   = fetch("/monitor/proposal")
trading     = fetch("/monitor/trading/status")
config_data = fetch("/monitor/config")
changelog   = fetch("/monitor/tuning/changelog?n=10")
portfolio   = fetch("/monitor/portfolio")
report      = fetch("/monitor/report")
trades      = fetch("/monitor/trades")

is_trading = (trading or {}).get("running", False)


# ── Belfort state (shared across tabs, loaded once per render) ─────────────────
_bs          = _load_agent_state("mr_belfort")
_b_status    = _bs.get("status", "unknown")
_b_learning  = _bs.get("actively_learning", False)
_campaign_id = _bs.get("campaign_id")
_tel         = _load_telemetry_summary(_campaign_id or "")
_budget_max  = _bs.get("budget_max_usd")
_live_lock   = check_lock()
_is_running  = _b_status in ("running_campaign", "running_session", "running_batch")
_stop_pend   = stop_signal_pending()
_resumable   = list_resumable_campaigns()
_camp_state  = (load_campaign_state(_campaign_id) or {}) if _campaign_id else {}
_bc          = _camp_state.get("best_candidate")
_rec_path    = ((_camp_state.get("artifacts") or {}).get("best_validation_record") or "")
_action_st   = belfort_action_state(_b_status, _stop_pend, _resumable)


# ── Supervisor state (shared across tabs) ──────────────────────────────────────
try:
    from app.supervisor import get_supervisor_state as _get_sup, enable_continuous, disable_continuous, start_supervisor
    _sup_state    = _get_sup()
    _sup_enabled  = _sup_state.get("enabled", False)
    _sup_stop_req = _sup_state.get("stop_requested", False)
    _sup_cycles   = _sup_state.get("cycle_count", 0)
    _sup_errors   = _sup_state.get("consecutive_start_errors", 0)
    _sup_last_err = _sup_state.get("last_error", "")
    _sup_ok       = True
except Exception as _sup_exc:
    _sup_state = {}; _sup_enabled = False; _sup_stop_req = False
    _sup_cycles = 0; _sup_errors = 0; _sup_last_err = ""; _sup_ok = False


# ── Queue state (shared across tabs) ──────────────────────────────────────────
try:
    from research.candidate_queue import (
        pending_candidates as _pending_cands,
        read_queue as _read_queue_all,
        update_queue_item as _upd_q,
    )
    from datetime import datetime as _dt_q, timezone as _tz_q
    _queue_pending    = _pending_cands()
    _all_queue_items  = _read_queue_all()
    _latest_queue_item = _all_queue_items[0] if _all_queue_items else None
except Exception:
    _queue_pending = []; _all_queue_items = []; _latest_queue_item = None
    def _upd_q(*a, **kw): pass  # type: ignore[misc]


# ── Checker findings (shared across tabs) ──────────────────────────────────────
try:
    from app.checker import read_findings as _read_findings, acknowledge_finding as _ack_finding
    _checker_findings = _read_findings(limit=10, include_acknowledged=False)
except Exception:
    _checker_findings = []

# ── Custodian health (shared across tabs) ─────────────────────────────────────
_custodian_data: dict = fetch("/custodian/last") or {}
_custodian_overall   = _custodian_data.get("overall", "unknown")
_custodian_summary   = _custodian_data.get("summary", "No health check has been run yet.")
_custodian_warnings  = [i for i in _custodian_data.get("items", []) if i.get("severity") == "warning"]


# ── Peter LM context (built once per render, used in Peter tab) ────────────────
_peter_context: dict = {}
if _PETER_LM_LOADED and _lm_available():
    _recent_ev_ctx = _read_events(limit=4, severity_filter=frozenset({"action_needed", "important"}))
    _peter_context = _build_peter_context(
        b_status         = _b_status,
        b_learning       = _b_learning,
        campaign_id      = _campaign_id,
        camp_state       = _camp_state,
        sup_state        = _sup_state,
        queue_pending    = _queue_pending,
        checker_findings = _checker_findings,
        recent_events    = _recent_ev_ctx,
        is_trading       = is_trading,
    )


# ── Page header ────────────────────────────────────────────────────────────────
_hdr, _badge = st.columns([5, 1])
with _hdr:
    st.title("The Abode")
    st.caption("Where your agents live and work")
with _badge:
    if _is_running:
        st.success(f"RUNNING · {_time_ago(_bs.get('started_at', ''))}")
    elif _b_status == "waiting_for_review":
        st.info("REVIEW NEEDED")
    elif _b_status == "review_held":
        st.warning("REVIEW HELD")
    elif _b_status in ("paused_by_budget", "stopped_by_guardrail"):
        st.error(_b_status.replace("_", " ").upper())
    else:
        st.caption(f"Belfort: {_b_status}")

st.divider()


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_home, tab_peter, tab_belfort, tab_controls = st.tabs(
    ["Home", "Peter", "Mr Belfort", "Controls"]
)

# ── Deep-link: jump to requested tab on first page load ────────────────────
# Neighbourhood passes ?view=peter / ?view=belfort / ?view=controls.
# sessionStorage prevents re-firing on subsequent Streamlit rerenders.
_view_param   = (st.query_params.get("view") or "").lower()
_ts_param     = (st.query_params.get("ts") or "0")
_deeplink_idx = {"home": 0, "peter": 1, "belfort": 2, "controls": 3}.get(_view_param, -1)
if _deeplink_idx >= 0:
    _stc.html(f"""<script>
(function(){{
  var key = "abode_view_{_view_param}_{_ts_param}";
  if (sessionStorage.getItem(key)) return;
  sessionStorage.setItem(key, "1");
  var n = 0;
  var t = setInterval(function(){{
    var tabs = window.parent.document.querySelectorAll('button[role="tab"]');
    if (tabs[{_deeplink_idx}]) {{ tabs[{_deeplink_idx}].click(); clearInterval(t); }}
    if (++n > 30) clearInterval(t);
  }}, 80);
}})();
</script>""", height=0)


# ══════════════════════════════════════════════════════════════════════════════
# HOME — system overview, agent status, attention items, recent activity
# ══════════════════════════════════════════════════════════════════════════════
with tab_home:

    # ── System status banner ─────────────────────────────────────────────────
    try:
        from observability.summary import belfort_status_summary as _bss
        _home_status = _bss()
    except Exception:
        _home_status = _belfort_plain_status(_b_status, _b_learning, _camp_state)

    if _is_running:
        st.success(f"**{_home_status}**")
    elif _b_status in ("waiting_for_review", "review_held"):
        st.info(f"**{_home_status}**")
    elif _b_status in ("paused_by_budget", "stopped_by_guardrail"):
        st.error(f"**{_home_status}**")
    else:
        st.info(f"**{_home_status}**")

    st.divider()

    # ── Agent cards ───────────────────────────────────────────────────────────
    _home_peter_col, _home_belfort_col = st.columns(2)

    with _home_peter_col:
        with st.container(border=True):
            st.caption("PETER")
            st.markdown("### :gray[COORDINATOR]")
            st.markdown("Your front door to The Abode — gives updates, takes instructions, surfaces decisions.")
            st.caption("Send commands in the **Peter** tab →")

    with _home_belfort_col:
        _hbc_color = _status_color(_b_status)
        with st.container(border=True):
            st.caption("MR BELFORT")
            st.markdown(f"### :{_hbc_color}[{_b_status.upper().replace('_', ' ')}]")
            if _is_running:
                st.success("Working")
            elif _b_learning:
                st.success("Learning")
            else:
                st.info("Idle")
            _hb_home = _bs.get("last_heartbeat_at", "")
            if _hb_home:
                st.caption(f"Heartbeat: {_time_ago(_hb_home)}")
            if _campaign_id:
                st.caption(f"Cycle: `{_campaign_id[-20:]}`")
            _lca_home = _bs.get("last_completed_action")
            if _lca_home:
                st.caption(f"Last: {_lca_home}")

    # ── Custodian health line ─────────────────────────────────────────────────
    _cust_col, _cust_btn_col = st.columns([6, 1])
    with _cust_col:
        if _custodian_overall == "healthy":
            st.caption(f"**Custodian** · {_custodian_summary}")
        elif _custodian_overall == "degraded":
            st.warning(f"**Custodian** · {_custodian_summary}")
        elif _custodian_overall == "unknown":
            st.caption(f"**Custodian** · {_custodian_summary}")
        else:
            st.caption(f"**Custodian** · {_custodian_summary}")
    with _cust_btn_col:
        if st.button("Check", key="home_custodian_check"):
            _fresh = fetch("/custodian/health")
            if _fresh:
                st.rerun()

    st.divider()

    # ── Needs your attention ──────────────────────────────────────────────────
    _needs_attention = (
        bool(_queue_pending)
        or any(f.get("severity") == "warning" for f in _checker_findings)
        or bool(_custodian_warnings)
        or _b_status in ("waiting_for_review", "review_held")
    )

    if _needs_attention:
        st.subheader("Needs Your Attention")

        if _b_status == "waiting_for_review":
            st.warning("**Review needed** — a candidate strategy is waiting for your decision. Go to the **Peter** tab to approve, skip, or defer.")
        elif _b_status == "review_held":
            st.warning("**Review deferred** — a candidate is held pending your decision. Go to the **Peter** tab when ready.")

        if _queue_pending:
            st.info(f"**{len(_queue_pending)} candidate(s)** in the upgrade queue. Go to the **Peter** tab to review.")

        _warn_findings = [f for f in _checker_findings if f.get("severity") == "warning"]
        if _warn_findings:
            for _wf in _warn_findings[:3]:
                st.warning(f"**Checker:** {_wf.get('title', '?')} — {_wf.get('detail', '')[:100]}")

        if _custodian_warnings:
            for _cw in _custodian_warnings[:3]:
                st.warning(f"**Custodian:** {_cw.get('detail', '')[:120]}")

        st.divider()

    # ── Recent activity ───────────────────────────────────────────────────────
    st.subheader("Recent Activity")

    _home_events = _read_events(limit=4, severity_filter=frozenset({"action_needed", "important"}))
    if _home_events:
        _home_sev_badge = {"action_needed": ":red[ACTION]", "important": ":blue[INFO]"}
        for _he in _home_events:
            _hbadge = _home_sev_badge.get(_he.get("severity", "important"), ":gray[INFO]")
            _hetype = _he.get("event_type", "").replace("_", " ")
            _hsum   = _he.get("summary", "")
            _hago   = _time_ago(_he.get("timestamp", ""))
            st.markdown(f"{_hbadge} · **{_hetype}** · {_hsum}" + (f" · {_hago}" if _hago else ""))
    else:
        st.caption("No recent events — actions (apply, skip, hold, start, stop) will appear here.")

    st.divider()

    # ── Navigation hints ──────────────────────────────────────────────────────
    st.caption(
        "**Peter** — talk to Peter, review candidates, start/stop research  ·  "
        "**Mr Belfort** — trading activity, learning progress, strategy upgrades  ·  "
        "**Controls** — developer tools, AI analysis, cost tracking"
    )


# ══════════════════════════════════════════════════════════════════════════════
# PETER — coordinator, reporter, front door to The Abode
# ══════════════════════════════════════════════════════════════════════════════
with tab_peter:

    # ── 1. Peter status card ──────────────────────────────────────────────────
    try:
        from observability.summary import belfort_status_summary as _pt_bss
        _pt_status_line = _pt_bss()
    except Exception:
        _pt_status_line = _belfort_plain_status(_b_status, _b_learning, _camp_state)

    _pt_next = _peter_next_action(_action_st, _campaign_id)

    with st.container(border=True):
        _pt_h1, _pt_h2 = st.columns([5, 1])
        with _pt_h1:
            st.markdown("### Peter")
            st.caption("Coordinator · reporter · front door to The Abode")
        with _pt_h2:
            if _is_running:
                st.success("ACTIVE")
            elif _b_status in ("waiting_for_review", "review_held"):
                st.info("REVIEW")
            elif _b_status in ("paused_by_budget", "stopped_by_guardrail"):
                st.error("STOPPED")
            else:
                st.caption("IDLE")

        if _is_running:
            st.success(_pt_status_line)
        elif _b_status in ("waiting_for_review", "review_held"):
            st.info(_pt_status_line)
        elif _b_status in ("paused_by_budget", "stopped_by_guardrail"):
            st.error(_pt_status_line)
        else:
            st.info(_pt_status_line)

        st.caption(f"Next: {_pt_next}")

    # Feedback from the last command or action
    _pcr_show = st.session_state.get("peter_cmd_response")
    if _pcr_show:
        if _pcr_show.get("ok"):
            st.success(f"Done: {_pcr_show['message']}")
        else:
            st.warning(f"Peter: {_pcr_show['message']}")

    _ctrl_res = st.session_state.ctrl_result
    if _ctrl_res:
        if _ctrl_res.get("ok"):
            st.success(_ctrl_res["message"])
        else:
            st.error(_ctrl_res["message"])

    st.divider()

    # ── 2. Peter briefing ─────────────────────────────────────────────────────
    st.subheader("Briefing")

    import time as _time_mod
    _LM_BRIEF_TTL = 60.0  # seconds

    _lm_on = _PETER_LM_LOADED and _lm_available() and bool(_peter_context)

    if _lm_on:
        _now_ts = _time_mod.time()
        _brief_age = _now_ts - st.session_state["peter_lm_brief_ts"]
        if _brief_age > _LM_BRIEF_TTL or not st.session_state["peter_lm_brief_txt"]:
            with st.spinner("Peter is thinking…"):
                _br = _peter_lm_briefing(_peter_context)
            if _br["ok"] and _br["text"]:
                st.session_state["peter_lm_brief_txt"]   = _br["text"]
                st.session_state["peter_lm_brief_ts"]    = _now_ts
                st.session_state["peter_lm_brief_tier"]  = _br.get("tier_used", "cheap")
                st.session_state["peter_lm_brief_model"] = _br.get("model_used", "")
            else:
                # Fall back to deterministic text; keep stale cache if available
                if not st.session_state["peter_lm_brief_txt"]:
                    st.session_state["peter_lm_brief_txt"] = _peter_briefing_text(
                        _action_st, _b_status, _sup_enabled, _sup_cycles,
                        _queue_pending, _checker_findings,
                    )

        st.markdown(st.session_state["peter_lm_brief_txt"])
        _brief_age_now  = _time_mod.time() - st.session_state["peter_lm_brief_ts"]
        _brief_tier     = st.session_state.get("peter_lm_brief_tier", "cheap")
        _brief_model    = st.session_state.get("peter_lm_brief_model", "")
        _brief_model_s  = _brief_model.split("/")[-1] if _brief_model else ""
        _tier_badge     = f" · :orange[strong route]" if _brief_tier == "strong" else " · cheap route"
        _model_badge    = f" · {_brief_model_s}" if _brief_model_s else ""
        st.caption(f":gray[Peter{_tier_badge}{_model_badge} · {int(_brief_age_now)}s ago · {_LM_BRIEF_TTL:.0f}s cache]")
    else:
        # Deterministic fallback (no API key or module not loaded)
        _pt_brief = _peter_briefing_text(
            _action_st, _b_status, _sup_enabled, _sup_cycles,
            _queue_pending, _checker_findings,
        )
        st.markdown(_pt_brief)

    # Last 2 important events as brief highlights
    _pt_highlights = _read_events(limit=2, severity_filter=frozenset({"action_needed", "important"}))
    if _pt_highlights:
        for _ph in _pt_highlights:
            _ph_ago = _time_ago(_ph.get("timestamp", ""))
            _ph_sum = _ph.get("summary", "")
            _ph_typ = _ph.get("event_type", "").replace("_", " ")
            st.caption(
                f":gray[—] {_ph_typ} · {_ph_sum}"
                + (f" · {_ph_ago}" if _ph_ago else "")
            )

    st.divider()

    # ── 3. Waiting on / needs review ─────────────────────────────────────────
    _has_review = _action_st in ("waiting_for_review", "review_held")
    _has_queue  = bool(_queue_pending)
    _has_warns  = any(f.get("severity") == "warning" for f in _checker_findings)

    if _has_review or _has_queue or _has_warns:
        st.subheader("Needs Your Attention")

        # Candidate review from the campaign state machine
        if _action_st == "waiting_for_review":
            st.markdown("**A strategy candidate is ready for your decision.**")
            _ok_rec, _err_rec, _rec_data = get_review_payload(_rec_path)

            with st.container(border=True):
                st.caption("CANDIDATE")
                if _bc:
                    _rsc1, _rsc2, _rsc3 = st.columns(3)
                    _rsc1.metric("Score", _bc.get("score", "?"))
                    _rsc2.metric("Tier",  _bc.get("tier", "?"))
                    _rsc3.metric("Class", _bc.get("experiment_class", "?") or "?")
                _cand_cfg_rev = (
                    _rec_data.get("candidate_config")
                    or (_bc or {}).get("candidate_config")
                    or {}
                )
                if _cand_cfg_rev:
                    st.markdown("**Parameter changes:**")
                    _cfg_now = config_data or {}
                    for _pk, _pv_new in _cand_cfg_rev.items():
                        _pv_old = _cfg_now.get(_pk, "?")
                        if _pv_old != "?":
                            st.markdown(f"- `{_pk}`: **{_pv_old}** → **{_pv_new}**")
                        else:
                            st.markdown(f"- `{_pk}` = `{_pv_new}`")
                if not _ok_rec:
                    st.warning(f"Cannot apply: {_err_rec}")

            _rev_c1, _rev_c2, _rev_c3 = st.columns([2, 1, 1])
            with _rev_c1:
                if st.button(
                    "Apply and Continue →",
                    type="primary",
                    key="p_rev_apply_continue",
                    use_container_width=True,
                    disabled=not _ok_rec,
                    help="Apply the candidate config and immediately start the next research run.",
                ):
                    _apply_r = post_json("/monitor/candidate/apply", {"record_path": _rec_path})
                    if "error" in _apply_r:
                        st.session_state.ctrl_result = {"ok": False, "message": f"Apply failed: {_apply_r['error']}"}
                    else:
                        _exp_name = _apply_r.get("experiment_name", "?")
                        _ca, _ct = skip_and_continue_action(_resumable, list_campaigns())
                        _cr = resume_campaign(_ct) if _ca == "resume" else start_campaign(goal=_ct)
                        if _cr.get("ok"):
                            st.session_state.ctrl_result = {
                                "ok": True,
                                "message": f"Applied {_exp_name} · {'resumed' if _ca == 'resume' else 'started'} next research run.",
                            }
                            _append_event(
                                "candidate_applied_and_continued",
                                f"Applied {_exp_name} · {'resumed' if _ca == 'resume' else 'started'} next run",
                                "important",
                                campaign_id=_campaign_id,
                                extra={"experiment_name": _exp_name, "continue_action": _ca},
                            )
                        else:
                            st.session_state.ctrl_result = {
                                "ok": False,
                                "message": f"Config applied ({_exp_name}) — but could not auto-start next run: {_cr.get('message', '?')}. Belfort is idle; start a run manually.",
                            }
                            _append_event(
                                "candidate_applied_continue_failed",
                                f"Applied {_exp_name} — auto-continue failed: {_cr.get('message', '?')}",
                                "important",
                                campaign_id=_campaign_id,
                                extra={"experiment_name": _exp_name},
                            )
                    st.rerun()

            with _rev_c2:
                if st.button(
                    "Skip and Continue",
                    key="p_rev_skip_continue",
                    use_container_width=True,
                    help="Discard this candidate and start the next research run without applying.",
                ):
                    skip_review(_rec_path)
                    _ca2, _ct2 = skip_and_continue_action(_resumable, list_campaigns())
                    _cr2 = resume_campaign(_ct2) if _ca2 == "resume" else start_campaign(goal=_ct2)
                    if _cr2.get("ok"):
                        st.session_state.ctrl_result = {"ok": True, "message": "Candidate skipped · " + (_cr2.get("message") or "next run started.")}
                        _append_event(
                            "candidate_skipped_and_continued",
                            "Candidate skipped · " + ("resumed" if _ca2 == "resume" else "started") + " next run",
                            "important",
                            campaign_id=_campaign_id,
                        )
                    else:
                        st.session_state.ctrl_result = {"ok": False, "message": f"Candidate skipped — but could not start next run: {_cr2.get('message', '?')}. Start a run manually."}
                        _append_event(
                            "candidate_skipped_continue_failed",
                            f"Candidate skipped — auto-continue failed: {_cr2.get('message', '?')}",
                            "important",
                            campaign_id=_campaign_id,
                        )
                    st.rerun()

            with _rev_c3:
                if st.button(
                    "Hold for Later",
                    key="p_rev_hold",
                    use_container_width=True,
                    help="Defer this decision. Candidate remains pending until you return.",
                ):
                    hold_review(_rec_path)
                    st.session_state.ctrl_result = {"ok": True, "message": "Review deferred — candidate is held."}
                    _append_event("review_held", "Review deferred — candidate held for later", "action_needed", campaign_id=_campaign_id)
                    st.rerun()

            with st.expander("Apply only (no auto-continue)"):
                st.caption("Applies config to the live strategy without starting a new research run.")
                if st.button("Apply Only", key="p_rev_apply_only", disabled=not _ok_rec):
                    _ao_r = post_json("/monitor/candidate/apply", {"record_path": _rec_path})
                    if "error" in _ao_r:
                        st.session_state.ctrl_result = {"ok": False, "message": f"Apply failed: {_ao_r['error']}"}
                    else:
                        st.session_state.ctrl_result = {"ok": True, "message": f"Applied {_ao_r.get('experiment_name', '?')} — Belfort is now idle."}
                        _append_event(
                            "candidate_applied",
                            f"Applied {_ao_r.get('experiment_name', '?')} — no auto-continue",
                            "important",
                            campaign_id=_campaign_id,
                            extra={"experiment_name": _ao_r.get("experiment_name"), "auto_continue": False},
                        )
                    st.rerun()

        elif _action_st == "review_held":
            st.warning("A candidate review is deferred — still pending your decision.")
            _rh_c1, _rh_c2 = st.columns(2)
            with _rh_c1:
                if st.button(
                    "Resume Review",
                    type="primary",
                    key="p_rh_resume",
                    use_container_width=True,
                ):
                    resume_review(_rec_path)
                    st.session_state.ctrl_result = {"ok": True, "message": "Review resumed — candidate is ready for decision."}
                    _append_event("review_resumed", "Review resumed — candidate ready for decision", "routine", campaign_id=_campaign_id)
                    st.rerun()
            with _rh_c2:
                if st.button(
                    "Dismiss and Continue",
                    key="p_rh_dismiss",
                    use_container_width=True,
                    help="Start a new research run without applying the held candidate.",
                ):
                    skip_review(_rec_path)
                    _ca3, _ct3 = skip_and_continue_action(_resumable, list_campaigns())
                    _cr3 = resume_campaign(_ct3) if _ca3 == "resume" else start_campaign(goal=_ct3)
                    if _cr3.get("ok"):
                        st.session_state.ctrl_result = {"ok": True, "message": "Held candidate dismissed · " + (_cr3.get("message") or "next run started.")}
                        _append_event(
                            "candidate_dismissed_and_continued",
                            "Held candidate dismissed · " + ("resumed" if _ca3 == "resume" else "started") + " next run",
                            "important",
                            campaign_id=_campaign_id,
                        )
                    else:
                        st.session_state.ctrl_result = {"ok": False, "message": f"Candidate dismissed — but could not start next run: {_cr3.get('message', '?')}. Start a run manually."}
                        _append_event(
                            "candidate_dismissed_continue_failed",
                            f"Held candidate dismissed — auto-continue failed: {_cr3.get('message', '?')}",
                            "important",
                            campaign_id=_campaign_id,
                        )
                    st.rerun()

        # Upgrade queue (always shown if there are pending items)
        if _has_queue:
            st.markdown(f"**Upgrade queue — {len(_queue_pending)} pending:**")
            for _qi in _queue_pending[:5]:
                _qq_id    = _qi.get("queue_id", "?")
                _qq_title = _qi.get("title", _qi.get("experiment_id", "?"))
                _qq_tier  = _qi.get("tier", "?")
                _qq_score = _qi.get("score", "?")
                _qq_pnl   = _qi.get("pnl_delta")
                _qq_risk  = _qi.get("risk_summary", "")
                _qq_rec   = _qi.get("record_path", "")

                with st.container(border=True):
                    _qa1, _qa2, _qa3, _qa4 = st.columns([3, 1, 1, 1])
                    with _qa1:
                        st.markdown(f"**{_qq_title}**")
                        if _qq_risk:
                            st.caption(_qq_risk[:120])
                    _qa2.metric("Score", _qq_score)
                    _qa3.metric("Tier", _qq_tier)
                    if _qq_pnl is not None:
                        _qa4.metric("P&L Δ", f"{_qq_pnl*100:+.2f}%" if isinstance(_qq_pnl, (int, float)) else str(_qq_pnl))

                    _qb1, _qb2, _qb3 = st.columns(3)
                    with _qb1:
                        if st.button("Approve", key=f"q_approve_{_qq_id}", use_container_width=True, type="primary"):
                            from datetime import datetime as _dt_q2, timezone as _tz_q2
                            _upd_q(_qq_id, status="approved", resolved_at=_dt_q2.now(_tz_q2.utc).isoformat(), resolution="Approved from dashboard")
                            _append_event("candidate_approved", f"Approved {_qq_title}", "important", campaign_id=_qi.get("campaign_id"))
                            if _qq_rec:
                                post_json("/monitor/candidate/apply", {"record_path": _qq_rec, "reason": "Approved from dashboard"})
                            st.rerun()
                    with _qb2:
                        if st.button("Reject", key=f"q_reject_{_qq_id}", use_container_width=True):
                            from datetime import datetime as _dt_q2, timezone as _tz_q2
                            _upd_q(_qq_id, status="rejected", resolved_at=_dt_q2.now(_tz_q2.utc).isoformat(), resolution="Rejected from dashboard")
                            _append_event("candidate_rejected", f"Rejected {_qq_title}", "important", campaign_id=_qi.get("campaign_id"))
                            st.rerun()
                    with _qb3:
                        if st.button("Hold", key=f"q_hold_{_qq_id}", use_container_width=True):
                            _upd_q(_qq_id, status="held", resolution="Deferred from dashboard")
                            st.rerun()

            if len(_queue_pending) > 5:
                st.caption(f"… and {len(_queue_pending) - 5} more.")

        # Checker warnings (top 3 only, acknowledge inline)
        if _has_warns:
            _warn_fds = [f for f in _checker_findings if f.get("severity") == "warning"]
            st.markdown(f"**Loop checker — {len(_warn_fds)} warning(s):**")
            for _cf in _warn_fds[:3]:
                _cf_id    = _cf.get("finding_id", "?")
                _cf_title = _cf.get("title", "?")
                _cf_det   = _cf.get("detail", "")
                _cf_ts    = _cf.get("timestamp", "")
                st.warning(f"**{_cf_title}** · {_time_ago(_cf_ts)}")
                if _cf_det:
                    st.caption(_cf_det[:200])
                if st.button("Acknowledge", key=f"cf_ack_warn_{_cf_id}"):
                    _ack_finding(_cf_id, operator_id="dashboard")
                    st.rerun()

        st.divider()

    # ── 4. Recommended actions ────────────────────────────────────────────────
    st.subheader("Actions")

    if _action_st == "stop_pending":
        st.warning("Stop signal is in flight — Belfort will finish the current session and halt cleanly.")
        if st.button("Cancel Stop Signal", key="p_btn_cancel_stop"):
            _r = cancel_stop_signal()
            st.session_state.ctrl_result = _r
            if _r.get("ok"):
                _append_event("stop_cancelled", "Stop signal cancelled — campaign continuing", "routine", campaign_id=_campaign_id)
            st.rerun()

    elif _action_st == "running":
        st.caption(f"Running · `{(_live_lock or {}).get('campaign_id', '?')[-20:]}`")
        if st.button(
            "Request Stop (after current session)",
            type="primary", key="p_btn_stop",
            help="Sends a stop signal. The current session finishes cleanly, then Belfort halts.",
        ):
            _r = request_stop()
            st.session_state.ctrl_result = _r
            if _r.get("ok"):
                _append_event("stop_requested", "Stop requested — will halt after current session", "important", campaign_id=_campaign_id)
            st.rerun()

    elif _action_st in ("waiting_for_review", "review_held"):
        st.caption("Review actions are in the section above.")

    else:
        # idle or idle_with_resumable
        _pa_left, _pa_right = st.columns(2)

        with _pa_left:
            _auto_goal = auto_continue_goal(list_campaigns())
            if st.button(
                "Start Auto Research →",
                type="primary",
                key="p_btn_auto_start",
                use_container_width=True,
            ):
                _r = start_campaign(goal=_auto_goal)
                st.session_state.ctrl_result = _r
                if _r.get("ok"):
                    _append_event("campaign_started", f"Campaign started — {_auto_goal[:60]}", "important", extra={"goal": _auto_goal, "auto": True})
                else:
                    _append_event("campaign_start_failed", f"Campaign start failed — {_r.get('message', '?')[:80]}", "important")
                st.rerun()
            st.caption(f"Goal: {_auto_goal[:60]}")

        with _pa_right:
            if _resumable:
                _r_opts = {
                    f"{c['campaign_id'][-20:]} — {c['goal'][:30]}": c["campaign_id"]
                    for c in _resumable
                }
                _r_label = st.selectbox("Resume run", list(_r_opts.keys()), key="p_resume_sel", label_visibility="collapsed")
                _r_id    = _r_opts.get(_r_label, "")
                if st.button("Resume →", key="p_btn_resume", use_container_width=True, disabled=not _r_id):
                    _r = resume_campaign(_r_id)
                    st.session_state.ctrl_result = _r
                    if _r.get("ok"):
                        _append_event("campaign_resumed", f"Campaign resumed — {_r_id[-20:]}", "important", campaign_id=_r_id)
                    else:
                        _append_event("campaign_resume_failed", f"Campaign resume failed — {_r.get('message', '?')[:80]}", "important", campaign_id=_r_id)
                    st.rerun()
            else:
                st.caption("No interrupted research runs to resume.")

    # Loop toggle (compact, part of actions)
    _loop_info = loop_explanation_text(_sup_state, _camp_state)
    _lc1, _lc2, _lc3 = st.columns([4, 1, 1])
    with _lc1:
        if _sup_enabled and not _sup_stop_req:
            st.caption(f":green[Learning loop: active] · {_loop_info['status_line']}")
        elif _sup_stop_req:
            st.caption(f":orange[Learning loop: stopping] · {_loop_info['status_line']}")
        else:
            st.caption(f":gray[Learning loop: off] · {_loop_info['status_line']}")
        if _sup_errors > 0:
            st.caption(f":orange[{_sup_errors} start error(s): {_sup_last_err[:60]}]")
    with _lc2:
        if _sup_ok and (not _sup_enabled or _sup_stop_req):
            if st.button("Enable Loop", key="sup_enable_btn", use_container_width=True):
                _sr = enable_continuous()
                start_supervisor()
                if _sr.get("ok"):
                    _append_event("continuous_learning_enabled", "Loop enabled from dashboard", "important")
                st.session_state.ctrl_result = {"ok": _sr.get("ok", False), "message": _sr.get("message", "")}
                st.rerun()
    with _lc3:
        if _sup_ok and _sup_enabled and not _sup_stop_req:
            if st.button("Disable Loop", key="sup_disable_btn", use_container_width=True):
                _sd = disable_continuous()
                if _sd.get("ok"):
                    _append_event("continuous_learning_stop_requested", "Loop stop requested from dashboard", "important")
                st.session_state.ctrl_result = {"ok": _sd.get("ok", False), "message": _sd.get("message", "")}
                st.rerun()

    st.divider()

    # ── 5. Inbox ─────────────────────────────────────────────────────────────
    st.subheader("Inbox")

    _lca_inbox = _bs.get("last_completed_action")
    _hb_inbox  = _bs.get("last_heartbeat_at", "")
    if _lca_inbox:
        _ago_inbox = f" · {_time_ago(_hb_inbox)}" if _hb_inbox else ""
        st.caption(f"Belfort's last action: {_lca_inbox}{_ago_inbox}")

    _ev_main = _read_events(limit=50, severity_filter=frozenset({"action_needed", "important"}))

    _cl_feed = [
        {
            "timestamp":  _clce.get("timestamp", ""),
            "severity":   "important",
            "source":     "system",
            "event_type": "param changed",
            "summary": (
                (_clce.get("parameter", "?")[10:]
                 if _clce.get("parameter", "").startswith("promotion:")
                 else _clce.get("parameter", "?"))
                + ": " + str(_clce.get("old_value", "?"))[:20]
                + " → " + str(_clce.get("new_value", "?"))[:20]
            ),
        }
        for _clce in (changelog or [])[:5]
    ]

    _inbox_feed = sorted(
        _ev_main + _cl_feed,
        key=lambda _e: _e.get("timestamp", ""),
        reverse=True,
    )[:8]

    _sev_badge = {"action_needed": ":red[ACTION]", "important": ":blue[INFO]"}

    if _inbox_feed:
        for _fe in _inbox_feed:
            _badge   = _sev_badge.get(_fe.get("severity", "important"), ":gray[INFO]")
            _etype   = _fe.get("event_type", "").replace("_", " ")
            _fsum    = _fe.get("summary", "")
            _fago    = _time_ago(_fe.get("timestamp", ""))
            _ago_str = f" · {_fago}" if _fago else ""
            st.markdown(f"{_badge} · **{_etype}** · {_fsum}{_ago_str}")
    else:
        st.caption("No events yet — actions (apply, skip, hold, start, stop) will appear here.")

    _ev_routine = _read_events(limit=10, severity_filter=frozenset({"routine"}))
    if _ev_routine:
        with st.expander(f"Routine events ({len(_ev_routine)})"):
            for _re in _ev_routine:
                _rts = _re.get("timestamp", "")
                st.caption(
                    f":gray[—] {_re.get('event_type', '').replace('_', ' ')} · "
                    f"{_re.get('summary', '')}"
                    + (f" · {_time_ago(_rts)}" if _rts else "")
                )

    st.divider()

    # ── 6. System readouts ────────────────────────────────────────────────────
    st.caption("SYSTEM READOUTS")

    _sr1, _sr2, _sr3 = st.columns(3)

    with _sr1:
        _sr_b_color = _status_color(_b_status)
        st.markdown(f"**Mr Belfort** · :{_sr_b_color}[{_b_status.replace('_', ' ')}]")
        if _hb_inbox:
            st.caption(f"Heartbeat {_time_ago(_hb_inbox)}")
        if _campaign_id:
            st.caption(f"Cycle: `{_campaign_id[-16:]}`")
        if _bs.get("last_completed_action"):
            st.caption(f"Last: {_bs['last_completed_action']}")

    with _sr2:
        if _sup_enabled and not _sup_stop_req:
            st.markdown("**Loop Supervisor** · :green[active]")
            st.caption(f"Cycle {_sup_cycles + 1} in progress")
        elif _sup_stop_req:
            st.markdown("**Loop Supervisor** · :orange[stopping]")
            st.caption(f"{_sup_cycles} cycle(s) completed")
        else:
            st.markdown("**Loop Supervisor** · :gray[off]")
            st.caption(f"{_sup_cycles} cycle(s) completed")
        if _loop_info.get("how_it_works"):
            with st.expander("How cycles work"):
                st.caption(_loop_info["how_it_works"])

    with _sr3:
        _info_fds  = [f for f in _checker_findings if f.get("severity") == "info"]
        _warn_fds2 = [f for f in _checker_findings if f.get("severity") == "warning"]
        if _warn_fds2:
            st.markdown(f"**Loop Checker** · :orange[{len(_warn_fds2)} warning(s)]")
        elif _info_fds:
            st.markdown(f"**Loop Checker** · :blue[{len(_info_fds)} finding(s)]")
        else:
            st.markdown("**Loop Checker** · :green[clear]")
        if _checker_findings:
            with st.expander("All findings"):
                for _cf in _checker_findings:
                    _cf_id    = _cf.get("finding_id", "?")
                    _cf_sev   = _cf.get("severity", "info")
                    _cf_title = _cf.get("title", "?")
                    _cf_det   = _cf.get("detail", "")
                    _cf_ts    = _cf.get("timestamp", "")
                    _cf_badge = ":orange[WARNING]" if _cf_sev == "warning" else ":gray[INFO]"
                    st.markdown(f"{_cf_badge} **{_cf_title}** · {_time_ago(_cf_ts)}")
                    if _cf_det:
                        st.caption(_cf_det[:200])
                    if st.button("Acknowledge", key=f"cf_ack_{_cf_id}"):
                        _ack_finding(_cf_id, operator_id="dashboard")
                        st.rerun()

    if _budget_max:
        _spent_p = _tel["estimated_cost_usd"]
        _pct_p   = min((_spent_p / _budget_max) * 100, 100.0) if _budget_max > 0 else 0.0
        if _pct_p >= 100:
            st.error(f"Budget exhausted: ${_spent_p:.4f} of ${_budget_max:.2f} used.")
        elif _pct_p >= 80:
            st.warning(f"Budget: {_pct_p:.1f}% used (${_spent_p:.4f} of ${_budget_max:.2f}).")
        else:
            st.caption(f"Budget: ${_spent_p:.4f} of ${_budget_max:.2f} ({_pct_p:.1f}%)")

    st.divider()

    # ── 7. Tell Peter ─────────────────────────────────────────────────────────
    st.caption("TELL PETER")

    # ── LM pending confirmation UI (shown above the input form) ───────────────
    _lm_pending = st.session_state.get("peter_lm_pending")
    if _lm_pending:
        st.info(_lm_pending.get("response", ""))
        _pconf_c1, _pconf_c2 = st.columns(2)
        with _pconf_c1:
            if st.button("Confirm →", key="lm_confirm_btn", type="primary", use_container_width=True):
                _exec_text = _lm_pending.get("exec_text", "")
                st.session_state["peter_lm_pending"] = None
                if _exec_text:
                    _pcr2 = _peter_execute(
                        text=_exec_text,
                        all_campaigns=list_campaigns(),
                        resumable=_resumable,
                        rec_path=_rec_path,
                        b_action_state=_action_st,
                        last_completed_action=_bs.get("last_completed_action", ""),
                        apply_candidate_fn=lambda p: post_json("/monitor/candidate/apply", {"record_path": p}),
                    )
                    st.session_state.peter_cmd_response = _pcr2
                    if _pcr2.get("event_type"):
                        _append_event(
                            _pcr2["event_type"],
                            _pcr2["message"][:200],
                            _pcr2["severity"],
                            campaign_id=_campaign_id,
                            extra=_pcr2.get("extra", {}),
                        )
                st.rerun()
        with _pconf_c2:
            if st.button("Cancel", key="lm_cancel_btn", use_container_width=True):
                st.session_state["peter_lm_pending"] = None
                st.rerun()

    # ── Build draft review UI ──────────────────────────────────────────────────
    _bt_pending = st.session_state.get("peter_build_pending")
    if _bt_pending:
        _bt_route  = _bt_pending.get("route", "builder")
        _bt_model  = _bt_pending.get("model_used", "")
        _bt_conf   = _bt_pending.get("builder_confidence", 0.0)
        _bt_esc    = _bt_pending.get("escalation_reason", "")
        _bt_edits  = _bt_pending.get("edits", [])

        # Routing explanation
        _bt_route_label = (
            ":orange[Reviewer] (strong model)"
            if _bt_route == "reviewer"
            else ":blue[Builder] (cheap model)"
        )
        st.markdown(f"**Build draft ready** · Path: {_bt_route_label}")
        if _bt_esc:
            st.warning(f"Escalation reason: {_bt_esc}")

        st.markdown(_bt_pending.get("summary", ""))
        st.caption(
            f"Model: `{_bt_model}` · "
            + (f"Confidence: {_bt_conf:.0%}" if _bt_conf else "")
        )

        # Show edits
        if _bt_edits:
            for _i, _edit in enumerate(_bt_edits):
                with st.expander(
                    f"Edit {_i+1}: `{_edit.get('file', '?')}` — {_edit.get('description', '')}",
                    expanded=(_i == 0),
                ):
                    _old = _edit.get("old_string", "")
                    _new = _edit.get("new_string", "")
                    if _old:
                        st.code(_old, language="python")
                        st.caption("↓ becomes ↓")
                    st.code(_new, language="python")
        else:
            st.caption("No edits generated — builder could not produce a valid patch.")

        _bta1, _bta2, _bta3 = st.columns([2, 1, 1])
        with _bta1:
            _apply_disabled = not bool(_bt_edits)
            if st.button(
                "Apply Patch →",
                key="build_apply_btn",
                type="primary",
                use_container_width=True,
                disabled=_apply_disabled,
            ):
                _apply_errors: list[str] = []
                _apply_count  = 0
                for _edit in _bt_edits:
                    _fpath = _REPO_ROOT / _edit.get("file", "")
                    _old   = _edit.get("old_string", "")
                    _new   = _edit.get("new_string", "")
                    try:
                        _fc = _fpath.read_text()
                        if _old and _old not in _fc:
                            _apply_errors.append(f"`{_edit.get('file')}`: old_string not found — skipped")
                            continue
                        if _old:
                            _fc = _fc.replace(_old, _new, 1)
                        else:
                            # new file (old_string empty)
                            _fpath.parent.mkdir(parents=True, exist_ok=True)
                            _fc = _new
                        _fpath.write_text(_fc)
                        _apply_count += 1
                    except Exception as _pe:
                        _apply_errors.append(f"`{_edit.get('file')}`: {_pe}")

                _task_desc = _bt_pending.get("task_text", "build task")[:80]
                if _apply_errors:
                    _emsg = f"Applied {_apply_count}/{len(_bt_edits)} edit(s). Issues: " + "; ".join(_apply_errors)
                    st.session_state.peter_cmd_response = {"ok": False, "message": _emsg, "event_type": "", "severity": "", "extra": {}, "command_type": "build_apply"}
                else:
                    _omsg = f"Applied {_apply_count} edit(s) — {_task_desc}"
                    st.session_state.peter_cmd_response = {"ok": True, "message": _omsg, "event_type": "build_applied", "severity": "important", "extra": {"edits": _apply_count, "route": _bt_route}, "command_type": "build_apply"}
                    _append_event("build_applied", _omsg, "important", extra={"route": _bt_route, "model": _bt_model})

                st.session_state["peter_build_pending"] = None
                st.rerun()

        with _bta2:
            if st.button("Discard", key="build_discard_btn", use_container_width=True):
                st.session_state["peter_build_pending"] = None
                st.session_state.peter_cmd_response = {"ok": True, "message": "Build draft discarded.", "event_type": "", "severity": "", "extra": {}, "command_type": "build_discard"}
                st.rerun()

        with _bta3:
            if _bt_route == "builder" and _PETER_BUILD_LOADED and st.button(
                "Escalate →", key="build_escalate_btn", use_container_width=True,
                help="Re-run with the strong reviewer model."
            ):
                with st.spinner("Asking the strong reviewer…"):
                    _esc_out = _route_build_task.__module__ and None  # import guard
                    try:
                        from ui.peter_build import _run_reviewer as _rev_fn, _read_file_context as _rfc_fn, _extract_file_hints as _efh_fn
                        _esc_hints   = _efh_fn(_bt_pending.get("task_text", ""))
                        _esc_fctx    = _rfc_fn(_esc_hints)
                        _esc_out     = _rev_fn(_bt_pending.get("task_text", ""), _esc_fctx, _bt_pending)
                        _esc_out["task_text"] = _bt_pending.get("task_text", "")
                        st.session_state["peter_build_pending"] = _esc_out
                    except Exception as _esc_exc:
                        st.error(f"Escalation failed: {_esc_exc}")
                st.rerun()

        st.divider()

    with st.form("peter_cmd_form", clear_on_submit=True):
        _pcmd_col, _pbtn_col = st.columns([5, 1])
        with _pcmd_col:
            _cmd_text = st.text_input(
                "Command",
                placeholder="start · stop · hold · status · why · what happened · help",
                label_visibility="collapsed",
            )
        with _pbtn_col:
            _cmd_submit = st.form_submit_button("Send →", use_container_width=True)

    if _cmd_submit and _cmd_text.strip():
        _pcr = _peter_execute(
            text=_cmd_text,
            all_campaigns=list_campaigns(),
            resumable=_resumable,
            rec_path=_rec_path,
            b_action_state=_action_st,
            last_completed_action=_bs.get("last_completed_action", ""),
            apply_candidate_fn=lambda p: post_json("/monitor/candidate/apply", {"record_path": p}),
        )

        # ── LM intent fallback for UNKNOWN commands ────────────────────────────
        if _pcr.get("command_type") == "unknown" and _lm_on and bool(_peter_context):
            with st.spinner("Peter is thinking…"):
                _lm_r = _peter_lm_understand(_cmd_text.strip(), _peter_context)

            if _lm_r.get("ok") and _lm_r.get("command") not in ("none", ""):
                _lm_cmd     = _lm_r["command"]
                _lm_summary = _lm_r.get("intent_summary", "")
                _lm_resp    = _lm_r.get("response", "")

                # ── Path B/C: build/coding task ────────────────────────────────
                if _lm_cmd == "build" and _PETER_BUILD_LOADED:
                    _raw_task = _cmd_text.strip()
                    with st.spinner("Peter is routing this to the builder…"):
                        _bt_out = _route_build_task(_raw_task, _peter_context)
                    _bt_out["task_text"] = _raw_task

                    _bt_route_name = _bt_out.get("route", "builder")
                    _bt_path_label = (
                        "the strong reviewer (architecture/safety scope)"
                        if _bt_route_name == "reviewer"
                        else "the cheap builder (routine implementation)"
                    )
                    _esc = _bt_out.get("escalation_reason", "")
                    _esc_note = f" Escalated: {_esc}." if _esc else ""

                    st.session_state.peter_cmd_response = {
                        "ok":           True,
                        "message":      (
                            f"I routed this to {_bt_path_label}.{_esc_note} "
                            f"Review the draft below and apply if it looks right."
                        ),
                        "event_type":   "",
                        "severity":     "",
                        "extra":        {"route": _bt_route_name},
                        "command_type": "build",
                    }

                    if _bt_out.get("ok") or _bt_out.get("edits"):
                        st.session_state["peter_build_pending"] = _bt_out
                    else:
                        # Build failed — show error as command response
                        st.session_state.peter_cmd_response = {
                            "ok":           False,
                            "message":      _bt_out.get("summary", "Build failed."),
                            "event_type":   "",
                            "severity":     "",
                            "extra":        {},
                            "command_type": "build",
                        }

                # ── Path A: consequential action → confirmation gate ───────────
                elif _lm_r.get("needs_confirmation"):
                    st.session_state["peter_lm_pending"] = {
                        "response":       (
                            _lm_resp or
                            f"I think you want to **{_lm_cmd.replace('_', ' ')}**. "
                            "Shall I go ahead?"
                        ),
                        "exec_text":      _lm_cmd,
                        "intent_summary": _lm_summary,
                    }
                    st.session_state.peter_cmd_response = {
                        "ok": True,
                        "message": f"Peter understood: {_lm_summary or _lm_cmd}",
                        "event_type": "", "severity": "", "extra": {}, "command_type": "lm_confirm",
                    }

                # ── Path A: read-only info command → execute directly ──────────
                else:
                    _pcr2 = _peter_execute(
                        text=_lm_cmd,
                        all_campaigns=list_campaigns(),
                        resumable=_resumable,
                        rec_path=_rec_path,
                        b_action_state=_action_st,
                        last_completed_action=_bs.get("last_completed_action", ""),
                        apply_candidate_fn=lambda p: post_json("/monitor/candidate/apply", {"record_path": p}),
                    )
                    if _lm_resp:
                        _pcr2["message"] = f"{_lm_resp}\n\n{_pcr2.get('message', '')}".strip()
                    st.session_state.peter_cmd_response = _pcr2
                    if _pcr2.get("event_type"):
                        _append_event(
                            _pcr2["event_type"],
                            _pcr2["message"][:200],
                            _pcr2["severity"],
                            campaign_id=_campaign_id,
                            extra=_pcr2.get("extra", {}),
                        )
            else:
                # LM returned "none" or failed
                _lm_resp = _lm_r.get("response", "")
                st.session_state.peter_cmd_response = {
                    "ok":           False,
                    "message":      _lm_resp or _pcr.get("message", "I didn't understand that."),
                    "event_type":   "",
                    "severity":     "",
                    "extra":        {},
                    "command_type": "unknown",
                }
        else:
            # Known deterministic command (or LM not available) — standard path
            st.session_state.peter_cmd_response = _pcr
            if _pcr.get("event_type"):
                _append_event(
                    _pcr["event_type"],
                    _pcr["message"][:200],
                    _pcr["severity"],
                    campaign_id=_campaign_id,
                    extra=_pcr.get("extra", {}),
                )

        st.rerun()

    if _lm_on:
        st.caption(
            ":gray[Peter understands plain English. "
            "For build tasks try: 'fix the X in Y', 'add a test for Z', 'edit the caption in …']"
        )
    else:
        st.caption(":gray[Say 'help' to see available commands.]")


# ══════════════════════════════════════════════════════════════════════════════
# MR BELFORT — trading agent · learning agent · visible worker
# ══════════════════════════════════════════════════════════════════════════════
with tab_belfort:

    # Pre-compute shared loop/campaign vars for this tab
    _plain_status     = _belfort_plain_status(_b_status, _b_learning, _camp_state)
    _camp_goal        = _camp_state.get("goal", "")
    _sess_sums        = _camp_state.get("session_summaries", [])
    _camp_classes     = (_sess_sums[-1].get("classes_tested", []) if _sess_sums else [])
    _loop_cfg_b       = _camp_state.get("config") or {}
    _loop_sess_b      = int(_loop_cfg_b.get("max_sessions",            _DEFAULT_SESSIONS))
    _loop_batches_b   = int(_loop_cfg_b.get("max_batches_per_session", _DEFAULT_BATCHES))
    _loop_exp_b       = int(_loop_cfg_b.get("experiments_per_batch",   _DEFAULT_EXP))
    _loop_total_b     = _loop_sess_b * _loop_batches_b * _loop_exp_b
    _loop_prog_b      = _camp_state.get("progress") or {}
    _loop_sess_done_b = int(_loop_prog_b.get("sessions_completed", 0))
    _loop_exp_done_b  = int(_loop_prog_b.get("total_experiments",  0))

    # ── 1. Identity / current focus ──────────────────────────────────────────
    with st.container(border=True):
        _bid_h, _bid_badge = st.columns([5, 1])
        with _bid_h:
            st.markdown("### Mr Belfort")
            st.caption("Trading research · learning agent")
        with _bid_badge:
            if _is_running:
                st.success("RUNNING")
            elif _b_status in ("waiting_for_review", "review_held"):
                st.info("REVIEW")
            elif _b_status in ("paused_by_budget", "stopped_by_guardrail"):
                st.error("STOPPED")
            else:
                st.caption("IDLE")

        if _is_running:
            st.success(_plain_status)
        elif _b_status in ("waiting_for_review", "review_held"):
            st.info(_plain_status)
        elif _b_status in ("paused_by_budget", "stopped_by_guardrail"):
            st.error(_plain_status)
        else:
            st.info(_plain_status)

        _foc1, _foc2 = st.columns(2)
        with _foc1:
            if _camp_goal:
                st.caption(f"**Goal:** {_camp_goal[:80]}")
            if _camp_classes:
                st.caption(f"**Testing:** {', '.join(_camp_classes[:4])}")
            elif _sess_sums:
                _last_cls = _sess_sums[-1].get("classes_tested", [])
                if _last_cls:
                    st.caption(f"**Last tested:** {', '.join(_last_cls[:4])}")
        with _foc2:
            if _is_running or _camp_state:
                st.caption(f"Round {_loop_sess_done_b}/{_loop_sess_b} · {_loop_exp_done_b} experiments")
            _hb_b = _bs.get("last_heartbeat_at", "")
            if _hb_b:
                st.caption(f"Heartbeat: {_time_ago(_hb_b)}")
            if _bs.get("last_completed_action"):
                st.caption(f"Last: {_bs['last_completed_action']}")

        # Inline controls
        _bctrl = st.session_state.ctrl_result
        if _bctrl:
            if _bctrl.get("ok"):
                st.success(_bctrl["message"])
            else:
                st.error(_bctrl["message"])

        if _action_st == "stop_pending":
            st.warning("Stop signal in flight — will halt after the current session.")
            if st.button("Cancel Stop Signal", key="b_btn_cancel_stop"):
                _r = cancel_stop_signal()
                st.session_state.ctrl_result = _r
                if _r.get("ok"):
                    _append_event("stop_cancelled", "Stop signal cancelled", "routine", campaign_id=_campaign_id)
                st.rerun()
        elif _action_st == "running":
            if st.button("Request Stop (after current session)", type="primary", key="b_btn_stop"):
                _r = request_stop()
                st.session_state.ctrl_result = _r
                if _r.get("ok"):
                    _append_event("stop_requested", "Stop requested", "important", campaign_id=_campaign_id)
                st.rerun()
        elif _action_st in ("waiting_for_review", "review_held"):
            st.info("Use the **Peter** tab to approve, skip, or defer the candidate.")
        else:
            st.caption("Use the **Peter** tab to start or resume a research run.")

    st.divider()

    # ── 2. Trading performance snapshot ──────────────────────────────────────
    if is_trading and trades:
        _tp_hdr, _tp_stop = st.columns([5, 1])
        with _tp_hdr:
            st.subheader("Trading Performance")
        with _tp_stop:
            if st.button("Stop Trading", key="b_stop_trading_top", use_container_width=True):
                post_req("/monitor/trading/stop")
                st.rerun()

        st.success(trading_status_summary(is_trading, trading, trades))

        if report:
            _ta1, _ta2, _ta3, _ta4 = st.columns(4)
            _ta1.metric("Win Rate",    f"{report.get('win_rate', 0) * 100:.1f}%",
                        help="Percentage of sell trades closed with a profit")
            _ta2.metric("Avg P&L",    format_pnl(report.get("avg_pnl_per_sell", 0)))
            _ta3.metric("Best Trade", format_pnl(report.get("best_trade_pnl", 0)))
            _ta4.metric("Worst Trade", format_pnl(report.get("worst_trade_pnl", 0)))

        # ── 3. Recent trading activity ─────────────────────────────────────────
        _feed_col, _pos_col = st.columns([3, 1])
        with _feed_col:
            st.caption(f"RECENT TRADES (last {min(20, len(trades))})")
            _trows = [format_trade_row(t) for t in reversed(trades[-20:])]
            st.dataframe(_trows, use_container_width=True, hide_index=True)
        with _pos_col:
            st.caption("POSITIONS")
            if portfolio and portfolio.get("positions"):
                _prows = [
                    {"Symbol": sym, "Qty": pos["qty"], "Cost Basis": f"${pos['avg_cost']:,.2f}"}
                    for sym, pos in portfolio["positions"].items()
                ]
                st.dataframe(_prows, use_container_width=True, hide_index=True)
            else:
                st.caption("No open positions")
            if portfolio:
                st.metric("Cash", f"${portfolio.get('cash', 0):,.2f}")
                st.metric("Realized P&L", format_pnl(portfolio.get("realized_pnl", 0)))

    elif is_trading and not trades:
        st.subheader("Trading Performance")
        st.info(
            "Paper trading is running — no trades yet. "
            "Belfort will enter when conditions meet the strategy's entry rules."
        )
        _ticks_b    = (trading or {}).get("ticks", 0)
        _interval_b = (trading or {}).get("interval", "?")
        _nt1, _nt2, _nt3 = st.columns(3)
        _nt1.metric("Ticks run", _ticks_b)
        _nt2.metric("Interval", f"{_interval_b}s")
        if portfolio:
            _nt3.metric("Starting cash", f"${portfolio.get('cash', 0):,.2f}")
        if st.button("Stop Paper Trading", key="b_stop_trading_empty"):
            post_req("/monitor/trading/stop")
            st.rerun()

    else:
        _tp_off_h, _tp_sl, _tp_btn = st.columns([3, 2, 1])
        with _tp_off_h:
            st.subheader("Trading Performance")
        with _tp_sl:
            _interval_b = st.select_slider(
                "Tick interval",
                options=[1, 2, 3, 5, 10, 15, 30],
                value=3,
                format_func=lambda x: f"{x}s",
                key="b_interval_slider",
                label_visibility="collapsed",
            )
        with _tp_btn:
            if st.button("Start →", key="b_start_trading", use_container_width=True, type="primary"):
                post_req("/monitor/trading/start", {"interval": _interval_b})
                st.rerun()

        st.caption("Paper trading is off. Start it to watch Belfort trade using the current strategy.")
        if portfolio:
            _pf1, _pf2, _pf3 = st.columns(3)
            _pf1.metric("Cash", f"${portfolio.get('cash', 0):,.2f}")
            _pf2.metric("Realized P&L", format_pnl(portfolio.get("realized_pnl", 0)))
            _pf3.metric("Open positions", len(portfolio.get("positions", {})))
            if trades:
                st.caption(f"Last session: {len(trades)} trade(s) recorded.")
            else:
                st.caption("No trades recorded yet.")

    st.divider()

    # ── 4. Learning loop (compact) ────────────────────────────────────────────
    st.subheader("Learning Loop")

    _ll1, _ll2, _ll3, _ll4 = st.columns(4)
    _ll1.metric("Cycle",       _sup_cycles + 1 if _sup_enabled else _sup_cycles,
                help="Current learning cycle number")
    _ll2.metric("Round",       f"{_loop_sess_done_b}/{_loop_sess_b}")
    _ll3.metric("Experiments", f"{_loop_exp_done_b}/{_loop_total_b}")
    _ll4.metric("Accepted",    _loop_prog_b.get("total_accepted", 0))

    if _sup_enabled and not _sup_stop_req:
        st.success(
            f"Active · cycle {_sup_cycles + 1} · "
            f"round {_loop_sess_done_b} of {_loop_sess_b} · "
            f"{_loop_exp_done_b} experiments run"
        )
    elif _b_status == "waiting_for_review":
        st.info(f"Cycle {_sup_cycles} complete — candidate ready for your review.")
    elif _sup_stop_req:
        st.warning(f"Loop stopping after the current cycle ({_sup_cycles} completed).")
    else:
        st.caption(
            f"Loop off · {_sup_cycles} cycle(s) completed · "
            f"up to {_loop_total_b} experiments per cycle "
            f"({_loop_sess_b} rounds × {_loop_batches_b} batches × {_loop_exp_b} exp)"
        )

    if _camp_state.get("stop_condition"):
        st.info(f"Stopped: **{_camp_state['stop_condition']}** — {_camp_state.get('stop_reason', '')}")

    st.divider()

    # ── 5. Current strategy ───────────────────────────────────────────────────
    st.subheader("Current Strategy")

    if config_data:
        _sg1, _sg2, _sg3, _sg4, _sg5, _sg6 = st.columns(6)
        _sg1.metric("Position",  f"{config_data.get('POSITION_SIZE', 0)*100:.0f}%")
        _sg2.metric("Stop Loss", f"{config_data.get('STOP_LOSS_PCT', 0)*100:.2f}%")
        _sg3.metric("Cooldown",  f"{config_data.get('TRADE_COOLDOWN', 0)} ticks")
        _sg4.metric("Short MA",  config_data.get("SHORT_WINDOW", "?"))
        _sg5.metric("Long MA",   config_data.get("LONG_WINDOW", "?"))
        _sg6.metric("Max ER",    f"{config_data.get('MAX_EFFICIENCY_RATIO', 1.0):.2f}",
                    help="Mean-reversion entries blocked above this Efficiency Ratio")
    else:
        st.caption("Strategy config unavailable.")

    if _camp_classes:
        st.caption(f"Currently testing: {', '.join(_camp_classes[:4])}")

    st.divider()

    # ── 6. Latest candidate ───────────────────────────────────────────────────
    st.subheader("Latest Candidate")

    _upgrade_item   = _latest_queue_item
    _upgrade_source = "queue"

    if not _upgrade_item and _bc:
        _upgrade_item = {
            "title":            _bc.get("experiment_id", "Unnamed candidate"),
            "status":           "pending" if _action_st == "waiting_for_review" else "reviewed",
            "tier":             _bc.get("tier", "?"),
            "score":            _bc.get("score", "?"),
            "pnl_delta":        _bc.get("pnl_delta"),
            "candidate_config": _bc.get("candidate_config", {}),
            "hypothesis":       _bc.get("hypothesis", ""),
            "quality_labels":   _bc.get("quality_labels", []),
            "experiment_class": _bc.get("experiment_class", ""),
            "record_path":      _rec_path,
        }
        _upgrade_source = "campaign"

    if _upgrade_item:
        _uq_status = _upgrade_item.get("status", "?")
        _uq_status_display = {
            "pending":      (":blue[QUEUED FOR REVIEW]",  "Waiting for your approval — go to Peter to decide."),
            "held":         (":orange[REVIEW DEFERRED]",   "You deferred this — still waiting for a decision."),
            "approved":     (":green[APPROVED]",           "Applied to the live strategy."),
            "rejected":     (":gray[REJECTED]",            "Not applied."),
            "auto_applied": (":green[AUTO-APPLIED]",       "Automatically applied by the learning loop."),
            "reviewed":     (":gray[REVIEWED]",            "Previously reviewed."),
        }.get(_uq_status, (f":gray[{_uq_status.upper()}]", ""))
        _uq_badge, _uq_meaning = _uq_status_display

        with st.container(border=True):
            _uh1, _uh2 = st.columns([4, 1])
            with _uh1:
                _uq_title = _upgrade_item.get("title", "?")
                st.markdown(f"**{_uq_title}**")
                st.caption(_uq_meaning)
            with _uh2:
                st.markdown(f"### {_uq_badge}")

            _um1, _um2, _um3 = st.columns(3)
            _um1.metric("Score", _upgrade_item.get("score", "?"))
            _um2.metric("Tier",  _upgrade_item.get("tier", "?"))
            _um3.metric("Class", _upgrade_item.get("experiment_class") or "—")

            _uq_cfg = _upgrade_item.get("candidate_config") or {}
            if _uq_cfg:
                st.markdown("**What would change:**")
                _cfg_now = config_data or {}
                for _pk, _pv_new in _uq_cfg.items():
                    _pv_old = _cfg_now.get(_pk, "?")
                    if _pv_old != "?":
                        st.markdown(f"- `{_pk}`: {_pv_old} → **{_pv_new}**")
                    else:
                        st.markdown(f"- `{_pk}` → **{_pv_new}**")

            _uq_pnl    = _upgrade_item.get("pnl_delta")
            _uq_hyp    = _upgrade_item.get("hypothesis", "")
            _uq_labels = _upgrade_item.get("quality_labels") or []
            _uq_res    = _upgrade_item.get("resolution", "")
            if _uq_pnl is not None:
                st.caption(f"Median P&L impact: {format_pnl(float(_uq_pnl))}")
            if _uq_hyp:
                st.caption(f"What was tested: {_uq_hyp[:200]}")
            if _uq_labels:
                st.caption(f"Quality notes: {', '.join(str(l) for l in _uq_labels[:3])}")
            if _uq_res:
                st.caption(f"Decision: {_uq_res}")

            if _uq_status in ("pending", "held") and _upgrade_source == "queue":
                st.divider()
                st.caption("Quick decision (full options — Apply & Continue, Skip — in the **Peter** tab):")
                _uact1, _uact2, _uact3 = st.columns(3)
                _uq_id  = _upgrade_item.get("queue_id", "")
                _uq_rec = _upgrade_item.get("record_path", "")
                with _uact1:
                    if st.button("Approve & Apply", key="blft_q_approve", use_container_width=True, type="primary"):
                        from datetime import datetime as _dt_blft, timezone as _tz_blft
                        _upd_q(_uq_id, status="approved", resolved_at=_dt_blft.now(_tz_blft.utc).isoformat(), resolution="Approved from Belfort home")
                        _append_event("candidate_approved", f"Approved {_uq_title}", "important", campaign_id=_upgrade_item.get("campaign_id"))
                        if _uq_rec:
                            post_json("/monitor/candidate/apply", {"record_path": _uq_rec, "reason": "Approved from Belfort home"})
                        st.rerun()
                with _uact2:
                    if st.button("Reject", key="blft_q_reject", use_container_width=True):
                        from datetime import datetime as _dt_blft, timezone as _tz_blft
                        _upd_q(_uq_id, status="rejected", resolved_at=_dt_blft.now(_tz_blft.utc).isoformat(), resolution="Rejected from Belfort home")
                        _append_event("candidate_rejected", f"Rejected {_uq_title}", "important", campaign_id=_upgrade_item.get("campaign_id"))
                        st.rerun()
                with _uact3:
                    if st.button("Hold for Later", key="blft_q_hold", use_container_width=True):
                        _upd_q(_uq_id, status="held", resolution="Deferred from Belfort home")
                        st.rerun()

    else:
        with st.container(border=True):
            st.caption("No candidates yet.")
            st.markdown(
                "When Belfort finds a parameter improvement, it will appear here "
                "with its score, what changed, and why it mattered."
            )

    st.divider()

    # ── 7. Research history & advanced ────────────────────────────────────────
    with st.expander("Research history & advanced", expanded=False):

        # Session history (learning momentum)
        if _sess_sums:
            st.subheader("Round History")
            _srows = [
                {
                    "Round":     s.get("session_id", "?")[-20:],
                    "Batches":   s.get("batches_completed", 0),
                    "Exp":       s.get("total_experiments", 0),
                    "Accepted":  s.get("total_accepted", 0),
                    "Best Tier": s.get("best_tier") or "—",
                    "Score":     s.get("best_score") or "—",
                }
                for s in reversed(_sess_sums)
            ]
            st.dataframe(_srows, use_container_width=True, hide_index=True)

        # Cycle summary
        if _camp_state:
            _p2, _cfg2 = _camp_state.get("progress", {}), _camp_state.get("config", {})
            _rp1, _rp2, _rp3, _rp4 = st.columns(4)
            _rp1.metric("Rounds",      f"{_p2.get('sessions_completed', 0)}/{_cfg2.get('max_sessions', '?')}")
            _rp2.metric("Experiments", f"{_p2.get('total_experiments', 0)}/{_cfg2.get('max_total_experiments', '?')}")
            _rp3.metric("Accepted",    _p2.get("total_accepted", 0))
            _rp4.metric("Status",      _camp_state.get("status", "?"))
            st.caption(f"Goal: {_camp_state.get('goal', '—')}")
            if _camp_state.get("stop_condition"):
                st.info(f"Stopped: **{_camp_state['stop_condition']}** — {_camp_state.get('stop_reason', '')}")

        # All cycles table
        _all_camps = list_campaigns()
        if _all_camps:
            st.subheader("All Research Cycles")
            _camp_rows = [
                {
                    "ID":       c["campaign_id"][-20:],
                    "Goal":     c["goal"][:50],
                    "Status":   c["status"],
                    "Rounds":   f"{c['sessions_completed']}/{c['max_sessions']}",
                    "Exp":      c["total_experiments"],
                    "Accepted": c["total_accepted"],
                    "Best":     c["best_tier"] or "—",
                }
                for c in _all_camps
            ]
            st.dataframe(_camp_rows, use_container_width=True, hide_index=True)

        # Research brief
        if _campaign_id:
            _brief_paths = get_campaign_brief_paths(_campaign_id)
            st.caption(f"Cycle ID: `{_campaign_id}`")
            _bmd = _brief_paths.get("md")
            if _bmd:
                _bfile = (
                    _REPO_ROOT / _bmd
                    if not pathlib.Path(_bmd).is_absolute()
                    else pathlib.Path(_bmd)
                )
                if _bfile.exists():
                    with st.expander("View research brief"):
                        st.markdown(_bfile.read_text())

        st.divider()

        # Custom research run (power user)
        st.subheader("Start Custom Research Run")
        with st.form("b_form_start"):
            _f_goal = st.text_input(
                "Research goal *",
                placeholder="e.g. improve entry quality filters",
                help="Minimum 5 characters.",
            )
            _f_notes = st.text_input(
                "Notes (optional)",
                placeholder="e.g. focus on loss_structure after recent rejections",
            )
            _f_sessions = st.slider(
                "Max rounds", 1, _CAP_SESSIONS, _DEFAULT_SESSIONS,
                help=f"Hard cap: {_CAP_SESSIONS} rounds per cycle",
            )
            _f_batches = st.slider(
                "Max batches per round", 1, _CAP_BATCHES, _DEFAULT_BATCHES,
                help=f"Hard cap: {_CAP_BATCHES}",
            )
            _f_exp = st.slider(
                "Experiments per batch", _MIN_EXP_BATCH, _CAP_EXP_BATCH, _DEFAULT_EXP,
                help=f"Min {_MIN_EXP_BATCH}, max {_CAP_EXP_BATCH}",
            )
            _f_max_exp = st.number_input(
                "Total experiment budget",
                min_value=1, max_value=_CAP_EXP_TOTAL, value=_DEFAULT_EXP_TOTAL, step=5,
                help=f"Cycle stops when this many experiments run. Hard cap: {_CAP_EXP_TOTAL}",
            )
            _f_budget = st.number_input(
                "Cost budget USD (0 = no limit)",
                min_value=0.0, max_value=500.0, value=0.0, step=1.0, format="%.2f",
            )
            _f_dry = st.checkbox("Dry run (manifests only, no simulation)", value=False)
            _b_submit = st.form_submit_button(
                "Start Research Run →", type="primary", use_container_width=True
            )
            if _b_submit:
                _ok, _errs, _ = validate_campaign_form(
                    _f_goal, _f_sessions, _f_batches, _f_exp, _f_max_exp, _f_budget,
                )
                if not _ok:
                    st.error("\n".join(_errs))
                else:
                    _r = start_campaign(
                        goal=_f_goal, notes=_f_notes,
                        max_sessions=_f_sessions, max_batches=_f_batches,
                        experiments=_f_exp, max_experiments=int(_f_max_exp),
                        budget_usd=float(_f_budget), dry_run=_f_dry,
                    )
                    st.session_state.ctrl_result = _r
                    if _r.get("ok"):
                        _append_event("campaign_started", f"Campaign started — {_f_goal[:60]}", "important", extra={"goal": _f_goal})
                    else:
                        _append_event("campaign_start_failed", f"Campaign start failed — {_r.get('message', '?')[:80]}", "important")
                    st.rerun()

        with st.form("b_form_resume"):
            st.caption("Resume an interrupted research run")
            if not _resumable:
                st.caption("No interrupted runs to resume.")
                st.form_submit_button("Resume", disabled=True)
            else:
                _b_resume_opts = {
                    f"{c['campaign_id'][-20:]} — {c['goal'][:40]} ({c['status']})": c["campaign_id"]
                    for c in _resumable
                }
                _b_sel_label = st.selectbox("Select run", list(_b_resume_opts.keys()), key="b_resume_select")
                _b_sel_id = _b_resume_opts.get(_b_sel_label, "")
                if st.form_submit_button("Resume Research Run →", use_container_width=True):
                    if _b_sel_id:
                        _r = resume_campaign(_b_sel_id)
                        st.session_state.ctrl_result = _r
                        if _r.get("ok"):
                            _append_event("campaign_resumed", f"Campaign resumed — {_b_sel_id[-20:]}", "important", campaign_id=_b_sel_id)
                        else:
                            _append_event("campaign_resume_failed", f"Campaign resume failed — {_r.get('message', '?')[:80]}", "important", campaign_id=_b_sel_id)
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# CONTROLS — developer tools, cost tracking, AI analysis, advanced settings
# ══════════════════════════════════════════════════════════════════════════════
with tab_controls:
    st.caption("Developer tools · for building and debugging, not daily use.")

    # ── Cost & token usage ────────────────────────────────────────────────────
    with st.expander("Cost & token usage"):
        _cost_lbl = " *(ESTIMATED)*" if _tel["is_estimated"] else ""
        _tc1, _tc2, _tc3, _tc4 = st.columns(4)
        _tc1.metric(f"Estimated cost{_cost_lbl}", f"${_tel['estimated_cost_usd']:.4f}")
        _tc2.metric("Total tokens",     f"{_tel['total_tokens']:,}")
        _tc3.metric("Requests",         f"{_tel['request_count']:,}")
        _tc4.metric("Telemetry events", f"{_tel['event_count']:,}")
        st.caption(
            "Simulation batches use in-process Python — no API tokens consumed. "
            "Cost is $0.00 until OpenRouter LLM calls are wired in."
        )
        if _budget_max:
            _spent_b   = _tel["estimated_cost_usd"]
            _pct_b     = min((_spent_b / _budget_max) * 100, 100.0) if _budget_max > 0 else 0.0
            _remaining = max(0.0, _budget_max - _spent_b)
            _bg1, _bg2, _bg3 = st.columns(3)
            _bg1.metric("Budget max",       f"${_budget_max:.2f}")
            _bg2.metric("Spent (est.)",     f"${_spent_b:.4f}")
            _bg3.metric("Remaining (est.)", f"${_remaining:.4f}")
            st.markdown(f"**Usage:** `{_budget_bar_str(_pct_b)}` {_pct_b:.1f}%")
            if _pct_b >= 100:
                st.error("Budget exhausted — campaign paused.")
            elif _pct_b >= 80:
                st.warning(f"Budget warning: {_pct_b:.1f}% used.")

    # ── AI analysis & decision ────────────────────────────────────────────────
    with st.expander("AI analysis & decision"):
        st.caption("Reads recent trades and produces a plain-English assessment. ~$0.0002/run.")
        _ai_left, _ai_right = st.columns(2)

        with _ai_left:
            st.subheader("Analysis")
            if st.button("Run Analysis", use_container_width=True, key="ctrl_analysis"):
                with st.spinner("Calling OpenRouter…"):
                    st.session_state.analysis_result = fetch("/monitor/analysis")
            _res = st.session_state.analysis_result
            if _res:
                if "error" in _res:
                    st.error(_res["error"])
                else:
                    st.markdown(_res.get("analysis", ""))
                    _a1, _a2 = st.columns(2)
                    _a1.metric("Win Rate Assessment", _res.get("win_rate_assessment", "—"))
                    _a2.metric("Confidence",          _res.get("confidence", "—"))
                    st.caption(f"**Issue:** {_res.get('biggest_issue', '—')}")
                    st.caption(f"**Suggestion:** {_res.get('suggested_improvement', '—')}")

        with _ai_right:
            st.subheader("Decision")
            st.caption("Interprets the analysis: keep going, collect more data, or flag for tuning.")
            if st.button("Get Decision", use_container_width=True, key="ctrl_decision"):
                with st.spinner("Evaluating…"):
                    st.session_state.decision_result = fetch("/monitor/decision")
            _raw = st.session_state.decision_result
            if _raw:
                _dec = _raw.get("decision", {})
                if "error" in _dec:
                    st.error(_dec["error"])
                else:
                    _dval  = _dec.get("decision", "—")
                    _color = DECISION_COLOR.get(_dval, "gray")
                    st.markdown(f"### :{_color}[{_dval.replace('_', ' ').upper()}]")
                    _d1, _d2 = st.columns(2)
                    _d1.metric("Priority",   _dec.get("priority", "—"))
                    _d2.metric("Confidence", f"{(_raw.get('confidence_score') or _dec.get('confidence_score') or 0)*100:.0f}%")
                    st.caption(f"**Why:** {_dec.get('reason', '—')}")
                    st.caption(f"**Next:** {_dec.get('recommended_action', '—')}")

        st.divider()
        if st.button("Clear analysis cache", key="adv_clear"):
            _cres = post_req("/monitor/cache/clear")
            if _cres and not _cres.get("error"):
                st.session_state.decision_result = None
                st.success("Cleared.")

        with st.expander("Past recommendations & patterns"):
            if recs:
                for _rec in recs:
                    _rv    = _rec.get("decision", "—")
                    _rc    = DECISION_COLOR.get(_rv, "gray")
                    _rcols = st.columns([3, 1])
                    _rcols[0].markdown(
                        f":{_rc}[**{_rv.replace('_', ' ').upper()}**] — {_rec.get('biggest_issue', '—')}"
                    )
                    _rcols[1].caption(_rec.get("timestamp", "")[:16])
                    st.caption(f"→ {_rec.get('recommended_action', '—')}")
                    st.divider()
            else:
                st.caption("No recommendations yet.")
            if patterns and patterns.get("records_analyzed", 0) > 0:
                st.markdown(
                    f"**Top issue ({patterns['occurrences']}×):** {patterns.get('most_common_issue') or '—'}"
                )
                st.caption(
                    f"Confidence trend: {patterns.get('confidence_trend', '—')} · "
                    f"{patterns['records_analyzed']} sessions"
                )

    # ── Strategy config & tuning ───────────────────────────────────────────────
    with st.expander("Strategy config & tuning"):
        if config_data:
            _g1, _g2, _g3, _g4 = st.columns(4)
            _g1.metric("SHORT_WINDOW",       config_data.get("SHORT_WINDOW", "—"))
            _g2.metric("LONG_WINDOW",        config_data.get("LONG_WINDOW", "—"))
            _g3.metric("MEAN_REV_WINDOW",    config_data.get("MEAN_REV_WINDOW", "—"))
            _g4.metric("MEAN_REV_THRESHOLD", f"{config_data.get('MEAN_REV_THRESHOLD', 1.0):.2f}")
            _g5, _g6, _g7, _g8 = st.columns(4)
            _g5.metric("STOP_LOSS_PCT",  f"{config_data.get('STOP_LOSS_PCT', 0)*100:.2f}%")
            _g6.metric("POSITION_SIZE",  f"{config_data.get('POSITION_SIZE', 0)*100:.0f}%")
            _g7.metric("MAX_ER",         f"{config_data.get('MAX_EFFICIENCY_RATIO', 1.0):.2f}",
                       help="Block mean-reversion entries when Efficiency Ratio exceeds this")
            _g8.metric("TRADE_COOLDOWN", f"{config_data.get('TRADE_COOLDOWN', 0)} ticks")
        else:
            st.caption("Config unavailable.")

        if prop_data and prop_data.get("proposal"):
            _prop = prop_data["proposal"]
            st.divider()
            st.caption("AI Proposal — not applied automatically")
            _FLOAT = {"STOP_LOSS_PCT", "TAKE_PROFIT_PCT", "POSITION_SIZE"}
            _param = _prop.get("parameter", "")
            _cur   = _prop.get("current_value", "—")
            _sug   = _prop.get("proposed_value", "—")
            _cur_d = f"{_cur*100:.2f}%" if _param in _FLOAT and isinstance(_cur, (int, float)) else str(_cur)
            _sug_d = f"{_sug*100:.2f}%" if _param in _FLOAT and isinstance(_sug, (int, float)) else str(_sug)
            _cp1, _cp2, _cp3 = st.columns(3)
            _cp1.metric("Parameter", _param)
            _cp2.metric("Current",   _cur_d)
            _cp3.metric("Proposed",  _sug_d)
            st.caption(f"Why: {_prop.get('reason', '—')}")
            if st.button(f"Apply: set {_param} → {_sug_d}", type="primary", key="btn_apply"):
                _res = post_json("/monitor/tuning/apply", _prop)
                if _res and not _res.get("error"):
                    st.success(f"Applied: {_res['parameter']} → {_res['new_value']}")
                    st.rerun()
                else:
                    st.error(_res.get("error") or str(_res))

        if changelog:
            st.divider()
            st.caption("Recent parameter changes")
            for _entry in changelog:
                _cl1, _cl2, _cl3, _cl4 = st.columns([2, 1, 1, 2])
                _cl1.write(f"**{_entry.get('parameter', '—')}**")
                _cl2.metric("Before", _entry.get("old_value", "—"))
                _cl3.metric("After",  _entry.get("new_value", "—"))
                _cl4.caption(_entry.get("timestamp", "")[:16] + " UTC")

    # ── Cost Warden ───────────────────────────────────────────────────────────
    with st.expander("Cost Warden — LM routing policy"):
        _cw_policy  = fetch("/warden/policy") or {}
        _cw_summary = fetch("/warden/summary") or {}
        _cw_cheap   = _cw_policy.get("cheap_model", "?")
        _cw_strong  = _cw_policy.get("strong_model", "?")
        _cw_calls   = _cw_summary.get("total_calls", 0)
        _cw_cost    = _cw_summary.get("total_cost_usd", 0.0)
        _cw_esc     = _cw_summary.get("escalation_rate_pct", 0.0)
        _cw_tiers   = _cw_summary.get("tier_breakdown", {})

        _cw1, _cw2, _cw3 = st.columns(3)
        _cw1.metric("Cheap default",  _cw_cheap.split("/")[-1] if "/" in _cw_cheap else _cw_cheap)
        _cw2.metric("Strong escalation", _cw_strong.split("/")[-1] if "/" in _cw_strong else _cw_strong)
        _cw3.metric("LM calls (recent)", _cw_calls)

        _pol_line = _cw_summary.get("policy_line", "")
        if _pol_line:
            st.caption(_pol_line)

        if _cw_calls > 0:
            _cw4, _cw5, _cw6 = st.columns(3)
            _cw4.metric("Total cost",     f"${_cw_cost:.4f}")
            _cw5.metric("Cheap calls",    _cw_tiers.get("cheap", 0))
            _cw6.metric("Strong calls",   _cw_tiers.get("strong", 0))
            if _cw_esc > 0:
                st.caption(f"Escalation rate: {_cw_esc:.0f}% of LM calls were escalated to strong model.")

        if _cw_policy:
            st.divider()
            st.caption(
                f"**Cheap tasks** ({_cw_policy.get('task_counts',{}).get('cheap',0)}): "
                + ", ".join(_cw_policy.get("cheap_tasks", [])[:6])
            )
            st.caption(
                f"**Strong tasks** ({_cw_policy.get('task_counts',{}).get('strong',0)}): "
                + ", ".join(_cw_policy.get("strong_tasks", [])[:4])
            )
            st.caption(
                f"**Deterministic** ({_cw_policy.get('task_counts',{}).get('deterministic',0)}): "
                + ", ".join(_cw_policy.get("deterministic_tasks", [])[:4])
            )

    # ── Test Sentinel ─────────────────────────────────────────────────────────
    with st.expander("Test Sentinel — patch safety"):
        _sent_data    = fetch("/sentinel/last") or {}
        _sent_verdict = _sent_data.get("verdict", "unknown")
        _sent_summary = _sent_data.get("summary", "No check has been run yet.")
        _sent_ts      = (_sent_data.get("timestamp") or "")[:16].replace("T", " ")
        _sent_passed  = _sent_data.get("passed", 0)
        _sent_failed  = _sent_data.get("failed", 0)
        _sent_scope   = _sent_data.get("scope", "—")
        _sent_fails   = _sent_data.get("failures", [])

        _sv1, _sv2, _sv3 = st.columns(3)
        _vc = {"safe": "normal", "review": "off", "not_ready": "inverse"}.get(_sent_verdict, "off")
        _sv1.metric("Verdict", _sent_verdict.upper())
        _sv2.metric("Passed",  _sent_passed)
        _sv3.metric("Failed",  _sent_failed)

        if _sent_verdict == "safe":
            st.success(_sent_summary)
        elif _sent_verdict == "not_ready":
            st.error(_sent_summary)
        elif _sent_verdict in ("review",):
            st.warning(_sent_summary)
        else:
            st.caption(_sent_summary)

        if _sent_ts:
            st.caption(f"Last check: {_sent_ts} UTC · scope: {_sent_scope}")

        if _sent_fails:
            st.caption("Failures:")
            for _sf in _sent_fails[:5]:
                st.code(f"[{_sf.get('kind','?')}] {_sf.get('test_id','?')}", language=None)

        st.divider()
        _sb1, _sb2, _sb3 = st.columns(3)
        if _sb1.button("Run smoke check", key="sentinel_smoke"):
            with st.spinner("Running smoke tests…"):
                _sres = post_json("/sentinel/run", {"scope": "smoke"})
            st.rerun()
        if _sb2.button("Auto-detect changes", key="sentinel_auto"):
            with st.spinner("Detecting changed files and running targeted tests…"):
                _sres = post_json("/sentinel/run", {"scope": "auto", "auto_detect": True})
            st.rerun()
        if _sb3.button("Full suite", key="sentinel_full"):
            with st.spinner("Running full test suite…"):
                _sres = post_json("/sentinel/run", {"scope": "full"})
            st.rerun()

    # ── Experiment history ────────────────────────────────────────────────────
    with st.expander("Experiment history"):
        _records = _val_records()
        if not _records:
            st.caption("No validation records yet.")
        else:
            _erows = []
            for _, _r in _records:
                _b, _c = _r["baseline"], _r["candidate"]
                _erows.append({
                    "Date":       _r["timestamp"][:16].replace("T", " "),
                    "Name":       _r["experiment_name"],
                    "Decision":   _r["decision"],
                    "Avg PnL Δ":  f"${_c['avg_pnl']    - _b['avg_pnl']:+,.0f}",
                    "Median Δ":   f"${_c['median_pnl'] - _b['median_pnl']:+,.0f}",
                    "Worst Δ":    f"${_c['worst_pnl']  - _b['worst_pnl']:+,.0f}",
                    "Trades Δ":   f"{_c['avg_trades']  - _b['avg_trades']:+.1f}",
                })
            st.dataframe(_erows, use_container_width=True, hide_index=True)

            _, _latest = _records[0]
            _runs = _latest.get("runs", [])
            if _runs:
                with st.expander(f"Per-run breakdown — {_latest['experiment_name']}"):
                    _rrows = [
                        {
                            "Seed":     _row["seed"],
                            "Ticks":    _row["ticks"],
                            "Base PnL": f"${_row['base_pnl']:,.2f}",
                            "Cand PnL": f"${_row['cand_pnl']:,.2f}",
                            "PnL Δ":    f"${_row['pnl_delta']:+,.2f}",
                            "Trade Δ":  f"{_row['trade_delta']:+d}",
                        }
                        for _row in _runs
                    ]
                    st.dataframe(_rrows, use_container_width=True, hide_index=True)

    # ── Paper trading (dev tool) ───────────────────────────────────────────────
    with st.expander("Paper trading (dev tool)"):
        st.caption(
            "Paper trading simulates Belfort's strategy using tick data. "
            "You can also start it from the **Mr Belfort** tab."
        )
        if is_trading:
            _ticks    = (trading or {}).get("ticks", 0)
            _interval = (trading or {}).get("interval", "?")
            _ago      = _time_ago((trading or {}).get("started_at"))
            st.success(f"Active — {_ticks} tick(s) · every {_interval}s · started {_ago}")
            if st.button("Stop Paper Trading", use_container_width=True,
                         type="primary", key="dev_stop_trading"):
                post_req("/monitor/trading/stop")
                st.rerun()
        else:
            st.info("Paper trading is stopped.")
            _interval_choice = st.select_slider(
                "Tick interval",
                options=[1, 2, 3, 5, 10, 15, 30],
                value=3,
                format_func=lambda x: f"{x}s",
                key="dev_interval",
            )
            if st.button("Start Paper Trading", use_container_width=True, key="dev_start_trading"):
                post_req("/monitor/trading/start", {"interval": _interval_choice})
                st.rerun()


# ── Footer ─────────────────────────────────────────────────────────────────────
st.caption(f"Auto-refresh every {REFRESH_INTERVAL}s  ·  backend {API_BASE}  ·  The Abode")
time.sleep(REFRESH_INTERVAL)
st.rerun()
