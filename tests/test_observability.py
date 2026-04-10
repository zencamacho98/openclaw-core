# tests/test_observability.py
#
# Lightweight tests for the observability layer:
#   - agent state transitions and learning-state classification
#   - telemetry accumulation and formatting
#   - budget threshold behavior
#   - summary helpers (text and structured output)

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Monkeypatch storage dirs before import so tests never touch real data
_TMP = tempfile.mkdtemp()
_TMP_PATH = pathlib.Path(_TMP)

import observability.agent_state as _as_mod
import observability.telemetry   as _tel_mod

_as_mod.STATE_DIR    = _TMP_PATH / "agent_state"
_tel_mod.TELEMETRY_DIR = _TMP_PATH / "telemetry"

from observability.agent_state import (
    AgentState, load_state, save_state, transition, update_heartbeat,
    MR_BELFORT, PETER,
    STATUS_IDLE, STATUS_RUNNING_BATCH, STATUS_RUNNING_SESSION,
    STATUS_RUNNING_CAMPAIGN, STATUS_WAITING_FOR_REVIEW, STATUS_PAUSED_BY_BUDGET,
    ACTIVE_STATUSES,
)
from observability.telemetry import (
    record_event, load_events, summarize, estimate_cost_usd,
    TelemetryEvent, TelemetrySummary,
)
from observability.budget import (
    BudgetConfig, BudgetStatus, evaluate_budget,
    DEFAULT_MAX_COST_USD, DEFAULT_WARNING_THRESHOLD, DEFAULT_HARD_STOP,
)
from observability.summary import (
    belfort_status_summary, belfort_learning_status,
    belfort_cost_summary, belfort_stop_reason, full_belfort_brief,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """Each test gets its own isolated state and telemetry directories."""
    state_dir = tmp_path / "agent_state"
    tel_dir   = tmp_path / "telemetry"
    monkeypatch.setattr(_as_mod,  "STATE_DIR",     state_dir)
    monkeypatch.setattr(_tel_mod, "TELEMETRY_DIR", tel_dir)
    yield


# ══════════════════════════════════════════════════════════════════════════════
# AGENT STATE
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentStateDefault:
    def test_default_is_idle(self):
        state = load_state(MR_BELFORT, "trading_agent")
        assert state.status           == STATUS_IDLE
        assert state.actively_learning is False
        assert state.campaign_id      is None
        assert state.batch_id         is None

    def test_default_creates_no_file(self, tmp_path):
        state = load_state(MR_BELFORT, "trading_agent")
        assert not (tmp_path / "agent_state" / "mr_belfort.json").exists()

    def test_save_and_reload(self, tmp_path):
        state = AgentState.default(MR_BELFORT, "trading_agent")
        state.campaign_id = "camp_test_001"
        save_state(state)
        reloaded = load_state(MR_BELFORT, "trading_agent")
        assert reloaded.campaign_id == "camp_test_001"
        assert reloaded.status      == STATUS_IDLE


class TestAgentStateTransition:
    def test_transition_to_running_campaign(self):
        state = transition(
            MR_BELFORT,
            agent_role  = "trading_agent",
            status      = STATUS_RUNNING_CAMPAIGN,
            campaign_id = "camp_001",
            current_task = "Explore entry quality",
        )
        assert state.status           == STATUS_RUNNING_CAMPAIGN
        assert state.actively_learning is True
        assert state.campaign_id      == "camp_001"
        assert state.current_task     == "Explore entry quality"
        assert state.started_at       is not None
        assert state.stop_reason      is None   # cleared on active entry

    def test_transition_to_running_batch(self):
        transition(MR_BELFORT, agent_role="trading_agent", status=STATUS_RUNNING_CAMPAIGN,
                   campaign_id="camp_001")
        state = transition(
            MR_BELFORT,
            agent_role = "trading_agent",
            status     = STATUS_RUNNING_BATCH,
            batch_id   = "batch_001",
        )
        assert state.status           == STATUS_RUNNING_BATCH
        assert state.actively_learning is True
        assert state.batch_id         == "batch_001"
        assert state.campaign_id      == "camp_001"   # inherited

    def test_transition_to_idle_clears_started_at(self):
        transition(MR_BELFORT, agent_role="trading_agent", status=STATUS_RUNNING_CAMPAIGN,
                   campaign_id="camp_001")
        state = transition(
            MR_BELFORT,
            agent_role  = "trading_agent",
            status      = STATUS_IDLE,
            stop_reason = "max_sessions_reached",
        )
        assert state.status           == STATUS_IDLE
        assert state.actively_learning is False
        assert state.started_at       is None
        assert state.stop_reason      == "max_sessions_reached"

    def test_transition_waiting_for_review(self):
        state = transition(MR_BELFORT, agent_role="trading_agent",
                           status=STATUS_WAITING_FOR_REVIEW)
        assert state.actively_learning is False   # not in ACTIVE_STATUSES
        assert state.status == STATUS_WAITING_FOR_REVIEW

    def test_transition_paused_by_budget(self):
        state = transition(MR_BELFORT, agent_role="trading_agent",
                           status=STATUS_PAUSED_BY_BUDGET,
                           stop_reason="Budget exhausted: $5.00/$5.00")
        assert state.actively_learning is False
        assert "exhausted" in (state.stop_reason or "")

    def test_heartbeat_does_not_change_status(self):
        transition(MR_BELFORT, agent_role="trading_agent", status=STATUS_RUNNING_CAMPAIGN)
        old_hb = load_state(MR_BELFORT).last_heartbeat_at
        import time; time.sleep(0.01)
        update_heartbeat(MR_BELFORT)
        new_state = load_state(MR_BELFORT)
        assert new_state.status == STATUS_RUNNING_CAMPAIGN
        assert new_state.last_heartbeat_at != old_hb

    def test_active_statuses_coverage(self):
        for status in ACTIVE_STATUSES:
            state = transition(MR_BELFORT, agent_role="trading_agent", status=status)
            assert state.actively_learning is True

    def test_inactive_statuses(self):
        for status in [STATUS_IDLE, STATUS_WAITING_FOR_REVIEW, STATUS_PAUSED_BY_BUDGET]:
            state = transition(MR_BELFORT, agent_role="trading_agent", status=status)
            assert state.actively_learning is False

    def test_fields_inherited_across_transitions(self):
        transition(MR_BELFORT, agent_role="trading_agent", status=STATUS_RUNNING_CAMPAIGN,
                   campaign_id="camp_persist")
        state = transition(MR_BELFORT, agent_role="trading_agent",
                           status=STATUS_RUNNING_BATCH, batch_id="b_001")
        assert state.campaign_id == "camp_persist"   # not cleared

    def test_budget_max_usd_stored(self):
        state = transition(MR_BELFORT, agent_role="trading_agent",
                           status=STATUS_RUNNING_CAMPAIGN,
                           budget_max_usd=10.0)
        assert state.budget_max_usd == pytest.approx(10.0)
        reloaded = load_state(MR_BELFORT)
        assert reloaded.budget_max_usd == pytest.approx(10.0)


# ══════════════════════════════════════════════════════════════════════════════
# TELEMETRY
# ══════════════════════════════════════════════════════════════════════════════

class TestTelemetryCostEstimation:
    def test_simulation_model_zero_cost(self):
        assert estimate_cost_usd("simulation", 1000, 500) == pytest.approx(0.0)

    def test_placeholder_model_zero_cost(self):
        assert estimate_cost_usd("placeholder", 9999, 9999) == pytest.approx(0.0)

    def test_known_model_cost(self):
        # claude-sonnet-4-6: $3/M input, $15/M output
        cost = estimate_cost_usd("anthropic/claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)   # $3 + $15

    def test_unknown_model_zero_cost(self):
        cost = estimate_cost_usd("mystery/model-v99", 1_000, 1_000)
        assert cost == pytest.approx(0.0)


class TestTelemetryRecordAndLoad:
    def test_record_creates_jsonl(self, tmp_path):
        record_event(MR_BELFORT, scope="batch", scope_id="b_001",
                     provider="simulation", model="simulation")
        path = tmp_path / "telemetry" / "b_001_telemetry.jsonl"
        assert path.exists()
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_multiple_events_accumulate(self, tmp_path):
        for i in range(5):
            record_event(MR_BELFORT, scope="campaign", scope_id="camp_001",
                         provider="simulation", model="simulation",
                         request_count=2)
        events = load_events("camp_001")
        assert len(events) == 5
        assert all(isinstance(e, TelemetryEvent) for e in events)

    def test_summary_totals(self):
        record_event(MR_BELFORT, scope="campaign", scope_id="camp_tel",
                     provider="placeholder", model="placeholder",
                     input_tokens=100, output_tokens=50, request_count=3)
        record_event(MR_BELFORT, scope="campaign", scope_id="camp_tel",
                     provider="placeholder", model="placeholder",
                     input_tokens=200, output_tokens=100, request_count=1)
        s = summarize("camp_tel")
        assert s is not None
        assert s.input_tokens   == 300
        assert s.output_tokens  == 150
        assert s.total_tokens   == 450
        assert s.request_count  == 4
        assert s.event_count    == 2

    def test_summary_returns_none_for_empty(self):
        assert summarize("nonexistent_scope_xyz") is None

    def test_is_estimated_flag_propagates(self):
        record_event(MR_BELFORT, scope="campaign", scope_id="camp_est",
                     is_estimated=True)
        s = summarize("camp_est")
        assert s.is_estimated is True

    def test_simulation_events_zero_cost(self):
        for _ in range(3):
            record_event(MR_BELFORT, scope="batch", scope_id="b_sim",
                         provider="simulation", model="simulation",
                         input_tokens=0, output_tokens=0)
        s = summarize("b_sim")
        assert s.estimated_cost_usd == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════════════
# BUDGET
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetEvaluation:
    def test_no_spend_no_warning(self):
        cfg = BudgetConfig(max_cost_usd=5.0, warning_threshold_pct=0.8)
        bs  = evaluate_budget(cfg, 0.0)
        assert bs.warning_triggered   is False
        assert bs.hard_stop_triggered is False
        assert bs.stop_reason         is None
        assert bs.pct_used            == pytest.approx(0.0)
        assert bs.remaining_usd       == pytest.approx(5.0)

    def test_warning_triggers_at_threshold(self):
        cfg = BudgetConfig(max_cost_usd=10.0, warning_threshold_pct=0.80)
        bs  = evaluate_budget(cfg, 8.0)   # exactly 80%
        assert bs.warning_triggered   is True
        assert bs.hard_stop_triggered is False
        assert bs.stop_reason         is None

    def test_hard_stop_triggers_at_100_pct(self):
        cfg = BudgetConfig(max_cost_usd=5.0, hard_stop_pct=1.0)
        bs  = evaluate_budget(cfg, 5.0)
        assert bs.hard_stop_triggered is True
        assert bs.stop_reason         is not None
        assert "exhausted" in bs.stop_reason.lower()

    def test_hard_stop_triggers_over_budget(self):
        cfg = BudgetConfig(max_cost_usd=5.0, hard_stop_pct=1.0)
        bs  = evaluate_budget(cfg, 6.5)
        assert bs.hard_stop_triggered is True
        assert bs.remaining_usd       == pytest.approx(0.0)

    def test_no_hard_stop_below_threshold(self):
        cfg = BudgetConfig(max_cost_usd=5.0, hard_stop_pct=1.0)
        bs  = evaluate_budget(cfg, 4.99)
        assert bs.hard_stop_triggered is False

    def test_zero_budget_does_not_divide_by_zero(self):
        cfg = BudgetConfig(max_cost_usd=0.0)
        bs  = evaluate_budget(cfg, 0.0)
        assert bs.pct_used == pytest.approx(0.0)

    def test_pct_used_display(self):
        cfg = BudgetConfig(max_cost_usd=10.0)
        bs  = evaluate_budget(cfg, 2.5)
        assert bs.pct_used_display == "25.0%"

    def test_budget_bar_format(self):
        cfg = BudgetConfig(max_cost_usd=10.0)
        bs  = evaluate_budget(cfg, 5.0)   # 50%
        assert "[" in bs.budget_bar
        assert "50.0%" in bs.budget_bar

    def test_estimated_label_in_stop_reason(self):
        cfg = BudgetConfig(max_cost_usd=1.0)
        bs  = evaluate_budget(cfg, 1.0, is_estimated=True)
        assert "(estimated)" in (bs.stop_reason or "")

    def test_from_dict_round_trip(self):
        cfg  = BudgetConfig(max_cost_usd=7.5, warning_threshold_pct=0.75, hard_stop_pct=0.95)
        cfg2 = BudgetConfig.from_dict(cfg.to_dict())
        assert cfg2.max_cost_usd          == pytest.approx(7.5)
        assert cfg2.warning_threshold_pct == pytest.approx(0.75)
        assert cfg2.hard_stop_pct         == pytest.approx(0.95)


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARIES
# ══════════════════════════════════════════════════════════════════════════════

class TestSummaries:
    def test_status_summary_idle(self):
        transition(MR_BELFORT, agent_role="trading_agent", status=STATUS_IDLE,
                   stop_reason="max_sessions_reached")
        s = belfort_status_summary()
        assert "INACTIVE" in s
        assert "idle" in s.lower()
        assert "max_sessions_reached" in s

    def test_status_summary_active(self):
        transition(MR_BELFORT, agent_role="trading_agent",
                   status=STATUS_RUNNING_CAMPAIGN,
                   campaign_id="camp_X",
                   current_task="Explore profit_taking")
        s = belfort_status_summary()
        assert "ACTIVE" in s
        assert "camp_X" in s
        assert "Explore profit_taking" in s

    def test_learning_status_active(self):
        transition(MR_BELFORT, agent_role="trading_agent",
                   status=STATUS_RUNNING_BATCH)
        s = belfort_learning_status()
        assert s.startswith("Yes")

    def test_learning_status_idle(self):
        transition(MR_BELFORT, agent_role="trading_agent", status=STATUS_IDLE)
        s = belfort_learning_status()
        assert s.startswith("No")

    def test_cost_summary_no_campaign(self):
        # No campaign_id set in state
        s = belfort_cost_summary()
        assert "no cost data" in s.lower() or "no active" in s.lower()

    def test_cost_summary_with_scope(self):
        record_event(MR_BELFORT, scope="campaign", scope_id="camp_summary_test",
                     provider="simulation", model="simulation")
        transition(MR_BELFORT, agent_role="trading_agent",
                   status=STATUS_RUNNING_CAMPAIGN,
                   campaign_id="camp_summary_test")
        s = belfort_cost_summary()
        assert "camp_summary_test" in s
        assert "requests" in s.lower()

    def test_stop_reason_active(self):
        transition(MR_BELFORT, agent_role="trading_agent",
                   status=STATUS_RUNNING_SESSION)
        s = belfort_stop_reason()
        assert "has not stopped" in s

    def test_stop_reason_idle_with_reason(self):
        transition(MR_BELFORT, agent_role="trading_agent",
                   status=STATUS_IDLE, stop_reason="budget_exhausted")
        s = belfort_stop_reason()
        assert "budget_exhausted" in s

    def test_full_brief_structure(self):
        transition(MR_BELFORT, agent_role="trading_agent",
                   status=STATUS_RUNNING_CAMPAIGN,
                   campaign_id="camp_brief",
                   budget_max_usd=5.0)
        brief = full_belfort_brief("camp_brief")
        assert brief["agent"]            == "Mr Belfort"
        assert "status"                  in brief
        assert "actively_learning"       in brief
        assert "telemetry"               in brief
        assert "budget"                  in brief
        assert "summaries"               in brief
        assert "status"                  in brief["summaries"]
        assert "learning"                in brief["summaries"]
        assert "cost"                    in brief["summaries"]
        assert "stop_reason"             in brief["summaries"]
        assert "next_review"             in brief["summaries"]
        assert brief["budget"]["max_usd"] == pytest.approx(5.0)

    def test_full_brief_no_campaign(self):
        brief = full_belfort_brief()
        assert brief["campaign_id"]      is None
        assert brief["telemetry"]["estimated_cost_usd"] == pytest.approx(0.0)
        assert brief["budget"]           == {"configured": False}

    def test_full_brief_learning_flag_matches_status(self):
        for status in [STATUS_RUNNING_BATCH, STATUS_RUNNING_SESSION, STATUS_RUNNING_CAMPAIGN]:
            transition(MR_BELFORT, agent_role="trading_agent", status=status)
            brief = full_belfort_brief()
            assert brief["actively_learning"] is True

        transition(MR_BELFORT, agent_role="trading_agent", status=STATUS_IDLE)
        brief = full_belfort_brief()
        assert brief["actively_learning"] is False
