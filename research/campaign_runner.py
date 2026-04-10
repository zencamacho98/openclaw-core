# research/campaign_runner.py
#
# Campaign orchestrator — runs multiple bounded sessions in sequence.
#
# CampaignRunner wraps ResearchSession and adds:
#   - five explicit campaign-level stop conditions
#   - durable state save after every session
#   - cross-session progress tracking (experiments, accepted, no-progress)
#   - best-candidate tracking with validation record path lookup
#   - final campaign brief generation on completion
#   - lock release on normal exit
#
# Stop conditions (checked before and after each session, in order):
#   1. max_sessions_reached      — hit the configured session cap
#   2. max_experiments_reached   — experiment budget exhausted
#   3. strong_candidate_confirmed — enough high-quality candidates found
#   4. no_progress_campaign      — N consecutive sessions with 0 accepted
#   5. dominant_failure_persists  — same failure mode dominated N sessions
#
# Public API:
#   CampaignRunner(state, state_path, lock_path, verbose, dry_run)
#   CampaignRunner.run() → campaign_report_dict

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from research.campaign        import (
    CampaignState, save_state, release_lock,
    stop_requested, clear_stop_signal,
)
from research.session         import ResearchSession
from research.policy          import CAMPAIGN
from observability.agent_state import (
    transition, MR_BELFORT,
    STATUS_RUNNING_CAMPAIGN, STATUS_RUNNING_SESSION,
    STATUS_IDLE, STATUS_WAITING_FOR_REVIEW, STATUS_PAUSED_BY_BUDGET,
)
from observability.budget  import BudgetConfig, evaluate_budget
from observability.telemetry import summarize as _tel_summarize

_REPORTS_DIR     = _ROOT / "data" / "research_ledger" / "reports"
_LEDGER_PATH     = _ROOT / "data" / "research_ledger" / "ledger.jsonl"

_NO_PROGRESS_LIMIT = int(CAMPAIGN.get("no_progress_sessions_limit",  2))
_STRONG_THRESHOLD  = int(CAMPAIGN.get("strong_candidates_threshold",  2))
_DOMINANT_FAIL_N   = int(CAMPAIGN.get("dominant_failure_sessions",    3))


class CampaignRunner:
    """
    Runs multiple ResearchSessions in sequence under one campaign.

    Args:
        state:      Loaded or freshly created CampaignState.
        state_path: Where to atomically save state after each session.
        lock_path:  Lock file path — released on normal completion.
        verbose:    Print progress to stdout.
        dry_run:    Passed through to each ResearchSession.
    """

    def __init__(
        self,
        state:         CampaignState,
        state_path:    pathlib.Path,
        lock_path:     pathlib.Path,
        verbose:       bool = True,
        dry_run:       bool = False,
        budget_config: BudgetConfig | None = None,
    ) -> None:
        self.state         = state
        self.state_path    = state_path
        self.lock_path     = lock_path
        self.verbose       = verbose
        self.dry_run       = dry_run
        self.budget_config = budget_config

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        """
        Execute the campaign: run sessions until a stop condition fires.

        Saves state after every session.
        Generates the final operator brief on completion.
        Returns the campaign report dict.
        """
        # Deferred import avoids circular dependency with campaign_report
        from research.campaign_report import generate_campaign_report

        cfg          = self.state.config
        max_sessions = cfg["max_sessions"]

        self._log(f"\n{'='*64}")
        self._log(f"  OpenClaw Research Campaign  |  {self.state.campaign_id}")
        self._log(f"  Goal: {self.state.goal}")
        self._log(
            f"  max_sessions={max_sessions}  "
            f"max_experiments={cfg['max_total_experiments']}"
        )
        done = self.state.progress["sessions_completed"]
        if done > 0:
            self._log(f"  [RESUMING] {done} session(s) already completed.")
        self._log(f"{'='*64}\n")

        stop_condition = self.state.stop_condition or ""
        stop_reason    = self.state.stop_reason or ""

        # ── Observability: mark campaign start ─────────────────────────────────
        transition(
            MR_BELFORT,
            agent_role    = "trading_agent",
            status        = STATUS_RUNNING_CAMPAIGN,
            campaign_id   = self.state.campaign_id,
            current_task  = f"Campaign: {self.state.goal}",
            budget_max_usd = (
                self.budget_config.max_cost_usd if self.budget_config else None
            ),
        )

        try:
            while self.state.progress["sessions_completed"] < max_sessions:

                # Pre-session campaign stop check
                should_stop, stop_condition, stop_reason = self._check_campaign_stop()
                if should_stop:
                    self._log(f"[CAMPAIGN STOP] {stop_condition}: {stop_reason}\n")
                    break

                n = self.state.progress["sessions_completed"] + 1
                self._log(f"{'─'*64}")
                self._log(f"  Session {n}/{max_sessions}  |  campaign: {self.state.campaign_id}")
                self._log(f"{'─'*64}\n")

                # Observability: mark session start
                transition(
                    MR_BELFORT,
                    agent_role   = "trading_agent",
                    status       = STATUS_RUNNING_SESSION,
                    campaign_id  = self.state.campaign_id,
                    current_task = f"Session {n}/{max_sessions} — {self.state.goal}",
                )

                session_report = self._run_one_session()

                # Observability: session done, back to campaign level
                _sid = session_report.get("session_id", "unknown")
                transition(
                    MR_BELFORT,
                    agent_role            = "trading_agent",
                    status                = STATUS_RUNNING_CAMPAIGN,
                    campaign_id           = self.state.campaign_id,
                    session_id            = _sid,
                    current_task          = f"Absorbing session {n} results",
                    last_completed_action = f"Completed session {n} ({_sid})",
                )

                self._absorb_session(session_report)

                # Budget check after each session (if budget configured)
                if self.budget_config:
                    tel   = _tel_summarize(self.state.campaign_id)
                    spent = tel.estimated_cost_usd if tel else 0.0
                    is_est = tel.is_estimated      if tel else True
                    bstatus = evaluate_budget(self.budget_config, spent, is_est)
                    if bstatus.warning_triggered:
                        self._log(
                            f"[BUDGET] {bstatus.budget_bar}  "
                            f"${spent:.4f} / ${self.budget_config.max_cost_usd:.2f}"
                        )
                    if bstatus.hard_stop_triggered:
                        stop_condition = "budget_exhausted"
                        stop_reason    = bstatus.stop_reason or "Budget limit reached."
                        transition(
                            MR_BELFORT,
                            agent_role  = "trading_agent",
                            status      = STATUS_PAUSED_BY_BUDGET,
                            stop_reason = stop_reason,
                        )
                        self._log(f"[BUDGET STOP] {stop_reason}")
                        break

                # Operator stop signal (set by UI or: touch data/campaigns/.stop_requested)
                # Checked here so the current session always completes cleanly.
                _camps_dir = self.lock_path.parent
                if stop_requested(_camps_dir):
                    clear_stop_signal(_camps_dir)
                    stop_condition = "operator_requested_stop"
                    stop_reason    = "Operator requested graceful stop (after session completion)."
                    self._log("[STOP] Operator stop signal honored after session completion.")
                    transition(
                        MR_BELFORT,
                        agent_role  = "trading_agent",
                        status      = STATUS_IDLE,
                        stop_reason = stop_reason,
                    )
                    break

                # Persist immediately — every session is checkpointed
                self.state.status = "running"
                save_state(self.state, self.state_path)
                self._log(f"[STATE] Saved after session {n}.\n")

                # Post-session campaign stop check
                should_stop, stop_condition, stop_reason = self._check_campaign_stop()
                if should_stop:
                    self._log(f"[CAMPAIGN STOP] {stop_condition}: {stop_reason}\n")
                    break

        except KeyboardInterrupt:
            self._log("\n[INTERRUPTED] Campaign interrupted by operator.")
            self.state.status = "interrupted"
            stop_condition    = "operator_interrupted"
            stop_reason       = "Campaign was manually interrupted."
            save_state(self.state, self.state_path)
            release_lock(self.lock_path)
            transition(
                MR_BELFORT,
                agent_role  = "trading_agent",
                status      = STATUS_IDLE,
                stop_reason = stop_reason,
            )
            raise

        except Exception as exc:
            self._log(f"\n[ERROR] Campaign failed: {exc}")
            self.state.status = "interrupted"
            stop_condition    = "runtime_error"
            stop_reason       = str(exc)
            save_state(self.state, self.state_path)
            release_lock(self.lock_path)
            transition(
                MR_BELFORT,
                agent_role  = "trading_agent",
                status      = STATUS_IDLE,
                stop_reason = f"Runtime error: {exc}",
            )
            raise

        # ── Normal completion ──────────────────────────────────────────────────

        if not stop_condition:
            stop_condition = "max_sessions_reached"
            stop_reason    = (
                f"Completed {self.state.progress['sessions_completed']}/{max_sessions} "
                "planned sessions."
            )

        self.state.status         = "completed"
        self.state.stop_condition = stop_condition
        self.state.stop_reason    = stop_reason

        campaign_report = generate_campaign_report(self.state)

        # Record brief artifact paths
        self.state.artifacts["campaign_brief_json"] = campaign_report.get("_brief_json_path")
        self.state.artifacts["campaign_brief_md"]   = campaign_report.get("_brief_md_path")

        save_state(self.state, self.state_path)
        release_lock(self.lock_path)

        # Observability: final agent state — waiting_for_review if good candidate found
        _bc = self.state.best_candidate
        if stop_condition == "budget_exhausted":
            _final_status = STATUS_PAUSED_BY_BUDGET
        elif _bc and _bc.get("tier") in ("strong", "review_worthy"):
            _final_status = STATUS_WAITING_FOR_REVIEW
        else:
            _final_status = STATUS_IDLE

        transition(
            MR_BELFORT,
            agent_role            = "trading_agent",
            status                = _final_status,
            stop_reason           = stop_reason,
            last_completed_action = (
                f"Campaign {self.state.campaign_id} finished: {stop_condition}"
            ),
        )

        self._print_campaign_summary()

        return campaign_report

    # ── Session execution ──────────────────────────────────────────────────────

    def _run_one_session(self) -> dict[str, Any]:
        cfg = self.state.config

        # Don't blow past the experiment budget this session
        remaining = cfg["max_total_experiments"] - self.state.progress["total_experiments"]
        exp_per_batch = max(1, min(cfg["experiments_per_batch"], remaining))

        session_notes = (
            f"Campaign: {self.state.campaign_id} | Goal: {self.state.goal}"
            + (f" | {self.state.notes}" if self.state.notes else "")
        )

        session = ResearchSession(
            max_batches=cfg["max_batches_per_session"],
            experiments_per_batch=exp_per_batch,
            notes=session_notes,
            dry_run=self.dry_run,
            verbose=self.verbose,
            campaign_id=self.state.campaign_id,
        )

        try:
            return session.run()
        except Exception as exc:
            self._log(f"[ERROR] Session failed: {exc}")
            # Return a safe stub so the campaign can continue / checkpoint
            return _failed_session_stub(
                self.state.progress["sessions_completed"] + 1, exc
            )

    # ── State absorption ───────────────────────────────────────────────────────

    def _absorb_session(self, session_report: dict[str, Any]) -> None:
        """Merge session results into campaign state. Called after each session."""
        s = self.state
        p = s.progress
        w = session_report.get("what_ran", {})
        session_id = session_report.get("session_id", "unknown")

        if session_id not in s.session_ids:
            s.session_ids.append(session_id)

        dom_failure = (
            session_report
            .get("diagnosis_snapshot", {})
            .get("dominant_failure")
        )

        s.session_summaries.append({
            "session_id":        session_id,
            "batches_completed": w.get("batches_completed", 0),
            "total_experiments": w.get("total_experiments", 0),
            "total_accepted":    w.get("total_accepted", 0),
            "classes_tested":    w.get("classes_tested", []),
            "stop_condition":    session_report.get("stop_condition"),
            "best_score":        (session_report.get("best_candidate") or {}).get("score"),
            "best_tier":         (session_report.get("best_candidate") or {}).get("tier"),
            "human_review":      session_report.get("human_review_recommended", False),
            "dominant_failure":  dom_failure,
        })

        # Progress counters
        p["sessions_completed"]  += 1
        p["total_batches"]       += w.get("batches_completed", 0)
        p["total_experiments"]   += w.get("total_experiments", 0)
        p["total_accepted"]      += w.get("total_accepted", 0)

        # No-progress streak tracking
        if w.get("total_accepted", 0) == 0:
            p["consecutive_no_progress_sessions"] = (
                p.get("consecutive_no_progress_sessions", 0) + 1
            )
        else:
            p["consecutive_no_progress_sessions"] = 0

        # Dominant failure per session — used for cross-session pattern detection
        p.setdefault("session_dominant_failures", []).append(dom_failure)

        # Update campaign best candidate
        self._update_best_candidate(session_report, session_id)

        # Track session report artifact paths
        json_path = str(_REPORTS_DIR / f"{session_id}_session.json")
        md_path   = str(_REPORTS_DIR / f"{session_id}_session_report.md")

        reps = s.artifacts.setdefault("session_reports", [])
        if json_path not in reps:
            reps.append(json_path)

        mds = s.artifacts.setdefault("session_md_reports", [])
        if md_path not in mds:
            mds.append(md_path)

    def _update_best_candidate(
        self, session_report: dict[str, Any], session_id: str
    ) -> None:
        """
        Update the campaign's best candidate if the session found a higher-scored one.

        Also resolves the validation record path from the ledger, because the
        session report's best_candidate dict does not carry output_path (that field
        only exists in the ledger's candidates_for_review entries).
        """
        session_best = session_report.get("best_candidate")
        if session_best is None:
            return

        current_score = (self.state.best_candidate or {}).get("score") or 0.0
        session_score = session_best.get("score") or 0.0

        if session_score > current_score:
            exp_id       = session_best.get("experiment_id")
            output_path  = _find_output_path_in_ledger(exp_id)

            self.state.best_candidate = {**session_best, "session_id": session_id}

            self.state.artifacts["best_experiment_id"]     = exp_id
            self.state.artifacts["best_session_id"]        = session_id
            self.state.artifacts["best_validation_record"] = output_path

    # ── Campaign stop conditions ───────────────────────────────────────────────

    def _check_campaign_stop(self) -> tuple[bool, str, str]:
        """
        Evaluate the five campaign-level stop conditions in priority order.

        Returns (should_stop, condition_name, human_reason).

        Conditions:
          1. max_sessions_reached      — sessions_completed >= max_sessions
          2. max_experiments_reached   — total_experiments >= max_total_experiments
          3. strong_candidate_confirmed — N sessions with strong/review_worthy
          4. no_progress_campaign      — N consecutive sessions with 0 accepted
          5. dominant_failure_persists  — same failure mode in last N sessions
        """
        cfg = self.state.config
        p   = self.state.progress

        # 1. Max sessions
        if p["sessions_completed"] >= cfg["max_sessions"]:
            return (
                True,
                "max_sessions_reached",
                (
                    f"Completed {p['sessions_completed']}/{cfg['max_sessions']} "
                    "planned sessions."
                ),
            )

        # 2. Experiment budget
        if p["total_experiments"] >= cfg["max_total_experiments"]:
            return (
                True,
                "max_experiments_reached",
                (
                    f"Total experiments ({p['total_experiments']}) reached the "
                    f"configured budget cap ({cfg['max_total_experiments']})."
                ),
            )

        # 3. Enough strong/review_worthy candidates found
        strong_count = sum(
            1 for s in self.state.session_summaries
            if s.get("best_tier") in ("strong", "review_worthy")
        )
        if strong_count >= _STRONG_THRESHOLD:
            return (
                True,
                "strong_candidate_confirmed",
                (
                    f"{strong_count} sessions produced strong or review_worthy "
                    "candidates — sufficient signal for human review."
                ),
            )

        # 4. Consecutive no-progress sessions
        no_prog = p.get("consecutive_no_progress_sessions", 0)
        if no_prog >= _NO_PROGRESS_LIMIT:
            return (
                True,
                "no_progress_campaign",
                (
                    f"{no_prog} consecutive sessions produced zero accepted "
                    "candidates. The current parameter space appears exhausted."
                ),
            )

        # 5. Same dominant failure mode across N consecutive sessions
        dom_failures = [
            f for f in p.get("session_dominant_failures", []) if f is not None
        ]
        if len(dom_failures) >= _DOMINANT_FAIL_N:
            recent = dom_failures[-_DOMINANT_FAIL_N:]
            if len(set(recent)) == 1:
                return (
                    True,
                    "dominant_failure_persists",
                    (
                        f"The failure mode '{recent[0]}' dominated each of the last "
                        f"{_DOMINANT_FAIL_N} sessions. A different parameter space or "
                        "strategy class is needed."
                    ),
                )

        return False, "", ""

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _print_campaign_summary(self) -> None:
        if not self.verbose:
            return
        p = self.state.progress
        print(f"\n{'='*64}")
        print(f"  Campaign Complete: {self.state.campaign_id}")
        print(f"  Goal        : {self.state.goal}")
        print(f"  Sessions    : {p['sessions_completed']}")
        print(f"  Batches     : {p['total_batches']}")
        print(
            f"  Experiments : {p['total_experiments']} total "
            f"/ {p['total_accepted']} accepted"
        )
        print(f"  Stop        : {self.state.stop_condition} — {self.state.stop_reason}")

        bc = self.state.best_candidate
        if bc:
            print(f"\n  Best candidate : {bc.get('experiment_id')}")
            print(f"    Score  : {bc.get('score')} ({bc.get('tier')})")
            print(f"    Class  : {bc.get('experiment_class')}")
            print(f"    Params : {bc.get('candidate_config')}")
            rec = self.state.artifacts.get("best_validation_record")
            if rec:
                print(f"    Record : {rec}")
                print(
                    f"\n  Promote with:\n"
                    f"    python scripts/promote_candidate.py --record {rec}"
                )

        brief = self.state.artifacts.get("campaign_brief_md")
        if brief:
            print(f"\n  Brief: {brief}")
        print(f"{'='*64}\n")


# ── Module-level helpers ───────────────────────────────────────────────────────

def _find_output_path_in_ledger(experiment_id: str | None) -> str | None:
    """
    Look up the validation record output_path for an experiment_id.

    Scans the last 40 ledger entries — enough to cover a full campaign's history.
    Returns None if not found.
    """
    if not experiment_id or not _LEDGER_PATH.exists():
        return None
    try:
        lines = [
            l.strip()
            for l in _LEDGER_PATH.read_text().splitlines()
            if l.strip()
        ]
    except Exception:
        return None

    # Walk newest-first (lines are oldest-first in file)
    for line in reversed(lines[-40:]):
        try:
            entry = json.loads(line)
        except Exception:
            continue

        # Check experiments list
        for exp in entry.get("experiments", []):
            if exp.get("experiment_id") == experiment_id:
                path = exp.get("output_path")
                if path:
                    return path

        # Check candidates_for_review (may have a superset of fields)
        for cand in entry.get("candidates_for_review", []):
            if cand.get("experiment_id") == experiment_id:
                path = cand.get("output_path")
                if path:
                    return path

    return None


def _failed_session_stub(session_num: int, exc: Exception) -> dict[str, Any]:
    """Return a minimal session report dict for a session that crashed."""
    return {
        "session_id":  f"session_failed_{session_num}",
        "what_ran": {
            "batches_completed": 0,
            "total_experiments": 0,
            "total_accepted":    0,
            "classes_tested":    [],
        },
        "best_candidate":           None,
        "dominant_findings":        [f"Session crashed: {exc}"],
        "repeated_failures":        [],
        "stop_condition":           "runtime_error",
        "stop_reason":              str(exc),
        "human_review_recommended": False,
        "batch_summaries":          [],
        "diagnosis_snapshot":       {},
    }
