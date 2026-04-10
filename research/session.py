# research/session.py
#
# Bounded supervised multi-batch research session manager.
#
# ResearchSession orchestrates a sequence of research batches:
#   1. Load cross-batch diagnosis from the ledger.
#   2. Generate a batch with focus_classes from the diagnosis.
#   3. Execute validation via BatchRunner.
#   4. Score, log, and report each batch (same pipeline as run_research.py).
#   5. Evaluate stop conditions after each batch.
#   6. On termination, produce a session-level report.
#
# Hard limits are enforced at every step:
#   - max_batches is capped at SESSION["max_batches_hard_cap"].
#   - experiments_per_batch is capped at SESSION["max_experiments_hard_cap"].
#   - No auto-promotion; session surfaces candidates for manual action.
#
# Public API:
#   ResearchSession(max_batches, experiments_per_batch, notes, dry_run, verbose)
#   ResearchSession.run() → session_report dict

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from research.generator         import generate_batch
from research.batch_runner      import BatchRunner
from research.reviewer          import extract_diagnostics, synthesize_insight
from research.scoring           import rank_batch
from research.ledger            import log_batch
from research.report            import generate_batch_report
from research.session_diagnosis import (
    load_recent_ledger_entries,
    diagnose_session_state,
    check_stop_conditions,
)
from research.session_report    import generate_session_report
from research.manifest          import make_batch_id
from research.policy            import SESSION
from observability.agent_state  import (
    transition, update_heartbeat, MR_BELFORT,
    STATUS_RUNNING_SESSION, STATUS_RUNNING_BATCH,
)
from observability.telemetry    import record_event

_HARD_CAP_BATCHES = int(SESSION.get("max_batches_hard_cap", 4))
_HARD_CAP_EXP     = int(SESSION.get("max_experiments_hard_cap", 5))
_DEFAULT_BATCHES  = int(SESSION.get("default_batches", 3))
_DEFAULT_EXP      = int(SESSION.get("default_experiments_per_batch", 3))

_FAILED_DIAG: dict = {
    "experiment_id": None, "experiment_class": "unknown",
    "hypothesis": "run failed or was blocked",
    "candidate_config": {}, "rejection_reasons": [],
    "decision": "FAILED", "baseline_median_pnl": None,
    "pnl_delta": None, "worst_pnl_delta": None, "trade_count_change": None,
    "churn_change": None, "stop_rate_change": None, "win_rate_change": None,
    "loss_win_ratio_change": None, "avg_winner": None, "avg_loser": None,
    "worst_case_behavior": "N/A", "quality_labels": [], "assessment": "failed",
    "flags": [],
}
_FAILED_INSIGHT: dict = {
    "major_learning": "Experiment failed to run — no data to analyze.",
    "revisit_recommendation": "deprioritize",
}


class ResearchSession:
    """
    Bounded supervised multi-batch research session.

    Args:
        max_batches:           Number of batches to run (capped at hard cap).
        experiments_per_batch: Experiments per batch (capped at hard cap).
        notes:                 Optional context string stored in reports.
        dry_run:               If True, generate manifests only — no simulation.
        verbose:               Print progress to stdout.
    """

    def __init__(
        self,
        max_batches:           int | None = None,
        experiments_per_batch: int | None = None,
        notes:                 str = "",
        dry_run:               bool = False,
        verbose:               bool = True,
        campaign_id:           str | None = None,
    ) -> None:
        self.max_batches = min(
            max_batches if max_batches is not None else _DEFAULT_BATCHES,
            _HARD_CAP_BATCHES,
        )
        self.experiments_per_batch = min(
            experiments_per_batch if experiments_per_batch is not None else _DEFAULT_EXP,
            _HARD_CAP_EXP,
        )
        self.notes       = notes
        self.dry_run     = dry_run
        self.verbose     = verbose
        self.campaign_id = campaign_id   # None for standalone sessions

        self._session_id        = _make_session_id()
        self._batch_reports:    list[dict] = []
        self._batches_completed = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        """
        Execute the session: run up to max_batches batches, stopping early
        when a stop condition is triggered.

        Returns the session report dict.
        """
        self._log(f"\n{'='*64}")
        self._log(f"  OpenClaw Research Session  |  {self._session_id}")
        self._log(
            f"  max_batches={self.max_batches}  "
            f"experiments_per_batch={self.experiments_per_batch}"
        )
        self._log(f"{'='*64}\n")

        # Observability: mark session start (for standalone runs; campaign_runner
        # also transitions to RUNNING_SESSION before calling session.run())
        transition(
            MR_BELFORT,
            agent_role   = "trading_agent",
            status       = STATUS_RUNNING_SESSION,
            campaign_id  = self.campaign_id,
            session_id   = self._session_id,
            current_task = f"Session {self._session_id}",
        )

        stop_condition = ""
        stop_reason    = ""

        while self._batches_completed < self.max_batches:
            # Cross-batch diagnosis
            entries = load_recent_ledger_entries()
            diag    = diagnose_session_state(entries)

            self._log(f"[Diagnosis] {diag['diagnosis_reason']}")
            if diag["deprioritized"]:
                self._log(f"  Deprioritized: {diag['deprioritized']}")
            self._log(f"  Focus: {diag['focus_classes']}\n")

            # Pre-batch stop check
            should_stop, stop_condition, stop_reason = check_stop_conditions(
                max_batches=self.max_batches,
                batches_completed=self._batches_completed,
                session_batch_results=self._batch_reports,
                diagnosis=diag,
            )
            if should_stop:
                self._log(f"[STOP] {stop_condition}: {stop_reason}\n")
                break

            # Run one batch
            batch_report = self._run_one_batch(diag["focus_classes"])
            if batch_report is not None:
                self._batch_reports.append(batch_report)
            self._batches_completed += 1

            # Post-batch stop check (catches strong candidate found this batch)
            entries = load_recent_ledger_entries()
            diag    = diagnose_session_state(entries)
            should_stop, stop_condition, stop_reason = check_stop_conditions(
                max_batches=self.max_batches,
                batches_completed=self._batches_completed,
                session_batch_results=self._batch_reports,
                diagnosis=diag,
            )
            if should_stop:
                self._log(f"[STOP] {stop_condition}: {stop_reason}\n")
                break

        # Loop ended without an explicit stop
        if not stop_condition:
            stop_condition = "max_batches_reached"
            stop_reason = (
                f"Completed {self._batches_completed}/{self.max_batches} planned batches."
            )

        # Final diagnosis snapshot for session report
        entries = load_recent_ledger_entries()
        final_diag = diagnose_session_state(entries)

        session_report = generate_session_report(
            session_id=self._session_id,
            batch_reports=self._batch_reports,
            diagnosis=final_diag,
            stop_condition=stop_condition,
            stop_reason=stop_reason,
            notes=self.notes,
        )

        self._print_session_summary(session_report)

        return session_report

    # ── Batch execution ────────────────────────────────────────────────────────

    def _run_one_batch(self, focus_classes: list[str]) -> dict | None:
        batch_id = make_batch_id()
        n        = self.experiments_per_batch

        self._log(f"{'─'*64}")
        self._log(
            f"  Batch {self._batches_completed + 1}/{self.max_batches}  |  {batch_id}"
        )
        self._log(f"  Focus: {focus_classes}")
        self._log(f"{'─'*64}\n")

        # Observability: mark batch start
        transition(
            MR_BELFORT,
            agent_role   = "trading_agent",
            status       = STATUS_RUNNING_BATCH,
            campaign_id  = self.campaign_id,
            session_id   = self._session_id,
            batch_id     = batch_id,
            current_task = (
                f"Batch {self._batches_completed + 1}/{self.max_batches}: "
                f"{focus_classes}"
            ),
        )

        # Step 1: Generate
        self._log("[1/5] Generating manifests ...")
        try:
            manifests = generate_batch(
                batch_id=batch_id,
                n=n,
                focus_classes=focus_classes,
            )
        except (ValueError, RuntimeError) as exc:
            self._log(f"[ABORT] Generation failed: {exc}\n")
            return None

        for m in manifests:
            self._log(
                f"  [{m.experiment_id}] {m.experiment_class} "
                f"— {list(m.mutated_params.keys())}"
            )
        self._log("")

        if self.dry_run:
            self._log("[DRY RUN] Skipping validation.\n")
            return None

        # Step 2: Validate
        self._log(f"[2/5] Running validation ({n} experiments) ...")
        runner  = BatchRunner()
        records: list[dict | None] = []

        for i, manifest in enumerate(manifests, 1):
            self._log(f"  [{i}/{n}] {manifest.experiment_id}")
            try:
                record, path = runner.run_manifest(manifest)
                records.append(record)
                manifest.status      = "complete"
                manifest.output_path = path
            except Exception as exc:
                self._log(f"  [ERROR] {exc}")
                manifest.status = "failed"
                records.append(None)
        self._log("")

        if all(r is None for r in records):
            self._log("[ABORT] All experiments failed.\n")
            return None

        # Step 3: Diagnostics and insights
        self._log("[3/5] Extracting diagnostics ...")
        diagnostics: list[dict] = []
        insights:    list[dict] = []

        for m, record in zip(manifests, records):
            if record is None:
                diagnostics.append({**_FAILED_DIAG, "experiment_id": m.experiment_id})
                insights.append(dict(_FAILED_INSIGHT))
            else:
                d = extract_diagnostics(record)
                diagnostics.append(d)
                insights.append(synthesize_insight(d))

        valid_diags    = [d for d in diagnostics if d.get("decision") != "FAILED"]
        valid_manifests = [m for m, r in zip(manifests, records) if r is not None]
        valid_records  = [r for r in records if r is not None]
        valid_insights = [
            ins for d, ins in zip(diagnostics, insights)
            if d.get("decision") != "FAILED"
        ]

        ranked = rank_batch(valid_diags)
        self._log("")

        # Step 4: Log
        self._log("[4/5] Writing ledger entry ...")
        log_batch(
            batch_id=batch_id,
            manifests=valid_manifests,
            records=valid_records,
            diagnostics=valid_diags,
            ranked=ranked,
            insights=valid_insights,
            notes=self.notes,
        )
        self._log("")

        # Step 5: Batch report
        self._log("[5/5] Generating batch report ...")
        batch_report = generate_batch_report(
            batch_id=batch_id,
            manifests=valid_manifests,
            diagnostics=valid_diags,
            ranked=ranked,
            insights=valid_insights,
            notes=self.notes,
        )
        self._log("")

        n_acc = sum(1 for d in valid_diags if d.get("decision") == "ACCEPTED")
        self._log(f"  Result: {n_acc}/{n} accepted")
        if ranked:
            top = ranked[0]
            self._log(
                f"  Best  : {top.get('experiment_id')}  "
                f"score={top.get('score', 0):.0f} ({top.get('tier')})"
            )
        self._log("")

        # Observability: record telemetry stub for this batch.
        # Validation is in-process simulation — zero API tokens consumed.
        # The scope_id is campaign_id if known, else batch_id, so cost
        # accumulates at campaign level where possible.
        _tel_scope_id = self.campaign_id or batch_id
        record_event(
            MR_BELFORT,
            scope          = "campaign" if self.campaign_id else "batch",
            scope_id       = _tel_scope_id,
            provider       = "simulation",
            model          = "simulation",
            input_tokens   = 0,
            output_tokens  = 0,
            request_count  = len(valid_manifests),
            is_estimated   = True,
            # Note: in-process simulation incurs $0 API cost.
            # Wire real OpenRouter token counts here when LLM calls are added.
        )
        update_heartbeat(MR_BELFORT)

        return batch_report

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _print_session_summary(self, session_report: dict) -> None:
        if not self.verbose:
            return
        w = session_report.get("what_ran", {})
        print(f"\n{'='*64}")
        print(f"  Session Complete: {self._session_id}")
        print(f"  Batches run     : {w.get('batches_completed', self._batches_completed)}")
        print(f"  Experiments     : {w.get('total_experiments', '?')} total")
        print(f"  Accepted        : {w.get('total_accepted', '?')}")
        print(f"  Stop            : {session_report.get('stop_condition')} — "
              f"{session_report.get('stop_reason')}")

        bc = session_report.get("best_candidate")
        if bc:
            print(
                f"\n  Best candidate: {bc.get('experiment_id')}  "
                f"score={bc.get('score')} ({bc.get('tier')})"
            )
            print(f"    Class : {bc.get('experiment_class')}")
            print(f"    Params: {bc.get('candidate_config')}")

        hr = session_report.get("human_review_recommended", False)
        if hr:
            print(f"\n  ⚑ Human review recommended:")
            print(f"    {session_report.get('human_review_reason', '')}")

        nd = session_report.get("next_direction", {})
        if nd:
            print(f"\n  Next direction: {nd.get('recommendation', '')}")
            if nd.get("rationale"):
                print(f"    {nd['rationale']}")

        print(f"{'='*64}\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session_id() -> str:
    return "session_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
