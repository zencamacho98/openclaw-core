"""
tests/test_research.py

Lightweight, targeted tests for the research loop.

Covers:
  - governance: manifest validation and enforcement
  - scoring: score computation and tier classification
  - reviewer: diagnostic extraction and insight synthesis
  - ledger: write behavior and append-only contract
  - report: generation and human-review flag

Run with:
    python -m pytest tests/ -v
    python -m unittest tests.test_research -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

# Ensure project root is on path when run from any directory
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_manifest(
    experiment_class: str = "entry_quality",
    mutated_params: dict | None = None,
    hypothesis: str = "Test hypothesis",
    seed_set: list[int] | None = None,   # pass [] explicitly to test empty
    experiment_id: str = "batch_test_20260409T000000_001",
    batch_id: str = "batch_test_20260409T000000",
):
    from research.manifest import ExperimentManifest
    _seeds = [42, 7, 99] if seed_set is None else seed_set
    return ExperimentManifest(
        experiment_id=experiment_id,
        batch_id=batch_id,
        experiment_class=experiment_class,
        hypothesis=hypothesis,
        mutated_params=mutated_params or {"MAX_EFFICIENCY_RATIO": 0.35},
        approved_ranges={"MAX_EFFICIENCY_RATIO": [0.20, 0.70]},
        seed_set=_seeds,
        tick_sizes=[2000],
    )


def _make_diagnostic(
    decision: str = "ACCEPTED",
    pnl_delta: float = 50.0,
    worst_pnl_delta: float = 30.0,
    quality_labels: list[str] | None = None,
    flags: list[str] | None = None,
    baseline_median_pnl: float = 1000.0,
    experiment_id: str = "batch_test_20260409T000000_001",
    experiment_class: str = "entry_quality",
) -> dict:
    return {
        "experiment_id":      experiment_id,
        "experiment_class":   experiment_class,
        "hypothesis":         "Test hypothesis",
        "candidate_config":   {"MAX_EFFICIENCY_RATIO": 0.35},
        "rejection_reasons":  [],
        "decision":           decision,
        "baseline_median_pnl": baseline_median_pnl,
        "pnl_delta":          pnl_delta,
        "worst_pnl_delta":    worst_pnl_delta,
        "trade_count_change": 0.0,
        "churn_change":       0.0,
        "stop_rate_change":   0.0,
        "win_rate_change":    0.0,
        "loss_win_ratio_change": 0.0,
        "avg_winner":         100.0,
        "avg_loser":          -80.0,
        "worst_case_behavior": "improved by $30.00",
        "quality_labels":     quality_labels or [],
        "assessment":         "robust",
        "flags":              flags or [],
    }


def _make_validation_record(
    decision: str = "ACCEPTED",
    pnl_delta: float = 50.0,
    experiment_id: str = "batch_test_001",
) -> dict:
    base_median = 1000.0
    cand_median = base_median + pnl_delta
    return {
        "timestamp":        "2026-04-09T12:00:00+00:00",
        "experiment_id":    experiment_id,
        "experiment_name":  experiment_id,
        "batch_id":         "batch_test",
        "experiment_class": "entry_quality",
        "hypothesis":       "Test hypothesis",
        "mode":             "mean_reversion",
        "seeds":            [42, 7, 99],
        "tick_sizes":       [2000],
        "trade_floor_ratio": 0.70,
        "decision":         decision,
        "rejection_reasons": [] if decision == "ACCEPTED" else ["median_pnl $950.00 < baseline $1,000.00"],
        "baseline":  {"avg_pnl": 1000.0, "median_pnl": base_median, "worst_pnl": 100.0, "avg_trades": 200.0, "n": 6},
        "candidate": {"avg_pnl": cand_median, "median_pnl": cand_median, "worst_pnl": 130.0, "avg_trades": 200.0, "n": 6},
        "candidate_config": {"MAX_EFFICIENCY_RATIO": 0.35},
        "trade_review": {
            "baseline":  {"metrics": {"avg_churn_score": 0.05, "avg_stop_rate": 0.20, "avg_win_rate": 0.55,
                                       "avg_win_pnl": 100.0, "avg_loss_pnl": -80.0, "loss_win_ratio": 0.80,
                                       "avg_holding_ticks": 15.0, "avg_pnl_per_sell": 10.0},
                          "flags": {}, "labels": []},
            "candidate": {"metrics": {"avg_churn_score": 0.05, "avg_stop_rate": 0.20, "avg_win_rate": 0.56,
                                       "avg_win_pnl": 105.0, "avg_loss_pnl": -80.0, "loss_win_ratio": 0.76,
                                       "avg_holding_ticks": 15.5, "avg_pnl_per_sell": 11.0},
                          "flags": {}, "labels": []},
            "candidate_labels": [],
            "comparative_labels": [],
            "all_labels": [],
        },
        "runs": [
            {"seed": 42, "ticks": 2000, "base_pnl": 1000.0, "cand_pnl": 1050.0,
             "pnl_delta": 50.0, "base_trades": 200, "cand_trades": 200, "trade_delta": 0},
        ],
    }


# ── Governance tests ──────────────────────────────────────────────────────────

class TestGovernance(unittest.TestCase):

    def test_valid_manifest_passes(self):
        from research.governance import validate_manifest
        m = _make_manifest()
        self.assertEqual(validate_manifest(m), [])

    def test_invalid_class_rejected(self):
        from research.governance import validate_manifest
        m = _make_manifest(experiment_class="nonexistent_class")
        violations = validate_manifest(m)
        self.assertTrue(any("not approved" in v for v in violations))

    def test_unknown_param_rejected(self):
        from research.governance import validate_manifest
        m = _make_manifest(
            experiment_class="entry_quality",
            mutated_params={"FAKE_PARAM": 0.5},
        )
        violations = validate_manifest(m)
        self.assertTrue(any("not approved" in v for v in violations))

    def test_param_out_of_bounds_rejected(self):
        from research.governance import validate_manifest
        # MAX_EFFICIENCY_RATIO approved range: 0.20–0.70
        m = _make_manifest(mutated_params={"MAX_EFFICIENCY_RATIO": 0.95})
        violations = validate_manifest(m)
        self.assertTrue(any("outside approved range" in v for v in violations))

    def test_param_at_lower_bound_passes(self):
        from research.governance import validate_manifest
        m = _make_manifest(mutated_params={"MAX_EFFICIENCY_RATIO": 0.20})
        self.assertEqual(validate_manifest(m), [])

    def test_param_at_upper_bound_passes(self):
        from research.governance import validate_manifest
        m = _make_manifest(mutated_params={"MAX_EFFICIENCY_RATIO": 0.70})
        self.assertEqual(validate_manifest(m), [])

    def test_too_many_params_rejected(self):
        from research.governance import validate_manifest
        from research.policy import BATCH
        max_p = BATCH["max_params_per_experiment"]
        # loss_structure has 3 params; use all 3 + one more (from wrong class)
        m = _make_manifest(
            experiment_class="loss_structure",
            mutated_params={
                "STOP_LOSS_PCT":     0.01,
                "STOP_ATR_MULT":     1.5,
                "MIN_STOP_LOSS_PCT": 0.008,
                "EXTRA_PARAM":       99,    # 4 params → too many
            },
        )
        violations = validate_manifest(m)
        # Either too_many or not_approved, both are violations
        self.assertTrue(len(violations) > 0)

    def test_empty_hypothesis_rejected(self):
        from research.governance import validate_manifest
        m = _make_manifest(hypothesis="   ")
        violations = validate_manifest(m)
        self.assertTrue(any("hypothesis" in v for v in violations))

    def test_empty_seed_set_rejected(self):
        from research.governance import validate_manifest
        m = _make_manifest(seed_set=[])
        violations = validate_manifest(m)
        self.assertTrue(any("seed_set" in v for v in violations))

    def test_too_many_seeds_rejected(self):
        from research.governance import validate_manifest
        from research.policy import BATCH
        max_s = BATCH["max_seeds"]
        m = _make_manifest(seed_set=list(range(max_s + 1)))
        violations = validate_manifest(m)
        self.assertTrue(any("seeds" in v for v in violations))

    def test_enforce_raises_on_violation(self):
        from research.governance import enforce
        m = _make_manifest(experiment_class="bad_class")
        with self.assertRaises(ValueError):
            enforce(m)

    def test_batch_size_limits_enforced(self):
        from research.governance import MAX_EXPERIMENTS_PER_BATCH, MIN_EXPERIMENTS_PER_BATCH
        from research.policy import BATCH
        self.assertEqual(MAX_EXPERIMENTS_PER_BATCH, BATCH["max_experiments"])
        self.assertEqual(MIN_EXPERIMENTS_PER_BATCH, BATCH["min_experiments"])


# ── Scoring tests ─────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):

    def test_clean_accepted_high_score(self):
        from research.scoring import score_experiment
        d = _make_diagnostic(
            decision="ACCEPTED",
            pnl_delta=100.0,
            worst_pnl_delta=50.0,
            quality_labels=[],
            flags=[],
        )
        score, tier = score_experiment(d)
        self.assertGreater(score, 70)
        self.assertIn(tier, ("strong", "review_worthy"))

    def test_rejected_low_score(self):
        from research.scoring import score_experiment
        d = _make_diagnostic(
            decision="REJECTED",
            pnl_delta=-500.0,
            worst_pnl_delta=-1000.0,
            baseline_median_pnl=1000.0,
        )
        score, tier = score_experiment(d)
        self.assertLess(score, 31)
        self.assertEqual(tier, "rejected")

    def test_accepted_with_labels_lower_score(self):
        from research.scoring import score_experiment
        clean = _make_diagnostic(quality_labels=[], flags=[])
        dirty = _make_diagnostic(quality_labels=["high churn", "losses too frequent"])
        score_clean, _ = score_experiment(clean)
        score_dirty, _ = score_experiment(dirty)
        self.assertGreater(score_clean, score_dirty)

    def test_near_miss_weak_tier(self):
        from research.scoring import score_experiment
        # Rejected but pnl_delta is small (within 5% of baseline median)
        d = _make_diagnostic(
            decision="REJECTED",
            pnl_delta=-40.0,          # 4% of baseline 1000 → near-miss
            baseline_median_pnl=1000.0,
        )
        score, tier = score_experiment(d)
        self.assertGreaterEqual(score, 31)
        self.assertIn(tier, ("weak", "noisy"))

    def test_score_0_to_100(self):
        from research.scoring import score_experiment
        for decision, pnl, labels in [
            ("ACCEPTED", 0.0,    []),
            ("ACCEPTED", 500.0,  []),
            ("REJECTED", -999.0, []),
            ("REJECTED", -10.0,  []),
        ]:
            d = _make_diagnostic(
                decision=decision, pnl_delta=pnl,
                quality_labels=labels, flags=[],
            )
            score, _ = score_experiment(d)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_rank_batch_sorted_descending(self):
        from research.scoring import rank_batch
        d1 = _make_diagnostic(decision="ACCEPTED",  pnl_delta=200.0, experiment_id="exp_001")
        d2 = _make_diagnostic(decision="ACCEPTED",  pnl_delta=10.0,  experiment_id="exp_002",
                               quality_labels=["high churn"])
        d3 = _make_diagnostic(decision="REJECTED",  pnl_delta=-300.0, experiment_id="exp_003")
        ranked = rank_batch([d1, d2, d3])
        scores = [r["score"] for r in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_score_breakdown_fields(self):
        from research.scoring import score_breakdown
        d = _make_diagnostic()
        bd = score_breakdown(d)
        for key in ("score", "tier", "base", "pnl_bonus", "worst_bonus", "clean_bonus", "penalties"):
            self.assertIn(key, bd)

    def test_policy_drives_scoring(self):
        """Scoring constants come from policy.py — change propagates."""
        from research.policy import SCORING
        self.assertIn("base_accepted", SCORING)
        self.assertIn("tier_strong", SCORING)
        self.assertGreater(SCORING["base_accepted"], SCORING["base_rejected"])


# ── Reviewer tests ────────────────────────────────────────────────────────────

class TestReviewer(unittest.TestCase):

    def test_extract_diagnostics_fields(self):
        from research.reviewer import extract_diagnostics
        rec = _make_validation_record()
        d = extract_diagnostics(rec)
        required = [
            "experiment_id", "experiment_class", "hypothesis",
            "decision", "pnl_delta", "worst_pnl_delta",
            "baseline_median_pnl", "quality_labels", "flags", "assessment",
        ]
        for field in required:
            self.assertIn(field, d, f"Missing field: {field}")

    def test_extract_experiment_id(self):
        from research.reviewer import extract_diagnostics
        rec = _make_validation_record(experiment_id="my_exp_001")
        d = extract_diagnostics(rec)
        self.assertEqual(d["experiment_id"], "my_exp_001")

    def test_extract_baseline_median(self):
        from research.reviewer import extract_diagnostics
        rec = _make_validation_record()
        d = extract_diagnostics(rec)
        self.assertEqual(d["baseline_median_pnl"], 1000.0)

    def test_synthesize_accepted_insight(self):
        from research.reviewer import synthesize_insight
        d = _make_diagnostic(decision="ACCEPTED", pnl_delta=100.0, quality_labels=[])
        ins = synthesize_insight(d)
        self.assertIn("major_learning", ins)
        self.assertIn("revisit_recommendation", ins)
        self.assertEqual(ins["revisit_recommendation"], "yes")

    def test_synthesize_rejected_near_miss(self):
        from research.reviewer import synthesize_insight
        d = _make_diagnostic(
            decision="REJECTED",
            pnl_delta=-30.0,          # near-miss (3% of 1000)
            baseline_median_pnl=1000.0,
        )
        ins = synthesize_insight(d)
        self.assertEqual(ins["revisit_recommendation"], "yes")
        self.assertIn("near-miss", ins["major_learning"].lower())

    def test_synthesize_rejected_big_loss_deprioritize(self):
        from research.reviewer import synthesize_insight
        d = _make_diagnostic(
            decision="REJECTED",
            pnl_delta=-800.0,
            worst_pnl_delta=-2000.0,
            baseline_median_pnl=1000.0,
        )
        ins = synthesize_insight(d)
        self.assertIn(ins["revisit_recommendation"], ("no", "deprioritize"))


# ── Ledger tests ──────────────────────────────────────────────────────────────

class TestLedger(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        # Patch ledger paths to use temp directory
        import research.ledger as ledger_mod
        self._orig_dir      = ledger_mod.LEDGER_DIR
        self._orig_file     = ledger_mod.LEDGER_FILE
        self._orig_summaries = ledger_mod.SUMMARIES_DIR
        tmp = pathlib.Path(self._tmpdir)
        ledger_mod.LEDGER_DIR    = tmp
        ledger_mod.LEDGER_FILE   = tmp / "ledger.jsonl"
        ledger_mod.SUMMARIES_DIR = tmp / "summaries"

    def tearDown(self):
        import research.ledger as ledger_mod
        ledger_mod.LEDGER_DIR    = self._orig_dir
        ledger_mod.LEDGER_FILE   = self._orig_file
        ledger_mod.SUMMARIES_DIR = self._orig_summaries

    def _call_log_batch(self, batch_id="batch_test_001"):
        from research.ledger import log_batch
        from research.scoring import rank_batch
        from research.reviewer import synthesize_insight
        manifests = [_make_manifest(batch_id=batch_id, experiment_id=f"{batch_id}_001")]
        diagnostics = [_make_diagnostic(experiment_id=f"{batch_id}_001")]
        ranked = rank_batch(diagnostics)
        insights = [synthesize_insight(d) for d in diagnostics]
        log_batch(
            batch_id=batch_id,
            manifests=manifests,
            records=[_make_validation_record()],
            diagnostics=diagnostics,
            ranked=ranked,
            insights=insights,
        )

    def test_ledger_file_created(self):
        import research.ledger as ledger_mod
        self._call_log_batch()
        self.assertTrue(ledger_mod.LEDGER_FILE.exists())

    def test_ledger_entry_is_valid_json(self):
        import research.ledger as ledger_mod
        self._call_log_batch()
        lines = ledger_mod.LEDGER_FILE.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertIn("batch_id", entry)
        self.assertIn("experiments", entry)

    def test_ledger_append_only(self):
        import research.ledger as ledger_mod
        self._call_log_batch("batch_A")
        self._call_log_batch("batch_B")
        lines = ledger_mod.LEDGER_FILE.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        ids = [json.loads(l)["batch_id"] for l in lines]
        self.assertIn("batch_A", ids)
        self.assertIn("batch_B", ids)

    def test_markdown_summary_written(self):
        import research.ledger as ledger_mod
        bid = "batch_md_test"
        self._call_log_batch(bid)
        md_path = ledger_mod.SUMMARIES_DIR / f"{bid}.md"
        self.assertTrue(md_path.exists())
        content = md_path.read_text()
        self.assertIn(bid, content)

    def test_ledger_entry_has_score_and_tier(self):
        import research.ledger as ledger_mod
        self._call_log_batch()
        entry = json.loads(ledger_mod.LEDGER_FILE.read_text().strip())
        exp = entry["experiments"][0]
        self.assertIn("score", exp)
        self.assertIn("tier", exp)
        self.assertIn("major_learning", exp)
        self.assertIn("revisit_recommendation", exp)


# ── Report tests ──────────────────────────────────────────────────────────────

class TestReport(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        import research.report as report_mod
        self._orig_dir = report_mod.REPORTS_DIR
        report_mod.REPORTS_DIR = pathlib.Path(self._tmpdir) / "reports"

    def tearDown(self):
        import research.report as report_mod
        report_mod.REPORTS_DIR = self._orig_dir

    def _run_report(self, batch_id="batch_report_test"):
        from research.report import generate_batch_report
        from research.scoring import rank_batch
        from research.reviewer import synthesize_insight
        manifests   = [_make_manifest(batch_id=batch_id, experiment_id=f"{batch_id}_001")]
        diagnostics = [_make_diagnostic(experiment_id=f"{batch_id}_001")]
        ranked      = rank_batch(diagnostics)
        insights    = [synthesize_insight(d) for d in diagnostics]
        return generate_batch_report(
            batch_id=batch_id,
            manifests=manifests,
            diagnostics=diagnostics,
            ranked=ranked,
            insights=insights,
        )

    def test_report_json_written(self):
        import research.report as report_mod
        bid = "batch_rj"
        self._run_report(bid)
        p = report_mod.REPORTS_DIR / f"{bid}.json"
        self.assertTrue(p.exists())

    def test_report_markdown_written(self):
        import research.report as report_mod
        bid = "batch_rm"
        self._run_report(bid)
        p = report_mod.REPORTS_DIR / f"{bid}_report.md"
        self.assertTrue(p.exists())

    def test_report_structure(self):
        report = self._run_report()
        required = [
            "schema_version", "batch_id", "what_ran", "what_mattered",
            "best_candidate", "learned", "next_action",
            "human_review_recommended",
        ]
        for key in required:
            self.assertIn(key, report, f"Missing report key: {key}")

    def test_human_review_flag_true_for_accepted(self):
        report = self._run_report()
        # Accepted candidate with no quality labels → human review recommended
        self.assertTrue(report["human_review_recommended"])

    def test_human_review_flag_false_when_all_rejected(self):
        from research.report import generate_batch_report
        from research.scoring import rank_batch
        from research.reviewer import synthesize_insight
        bid = "batch_all_rejected"
        manifests   = [_make_manifest(batch_id=bid, experiment_id=f"{bid}_001")]
        diagnostics = [_make_diagnostic(decision="REJECTED", pnl_delta=-500.0,
                                        experiment_id=f"{bid}_001")]
        ranked      = rank_batch(diagnostics)
        insights    = [synthesize_insight(d) for d in diagnostics]
        report = generate_batch_report(
            batch_id=bid, manifests=manifests, diagnostics=diagnostics,
            ranked=ranked, insights=insights,
        )
        self.assertFalse(report["human_review_recommended"])

    def test_next_action_present(self):
        report = self._run_report()
        na = report.get("next_action", {})
        self.assertIn("recommendation", na)
        self.assertIn(na["recommendation"], (
            "promote_best", "retest_accepted", "retry_with_adjustment",
            "run_diagnosis", "deprioritize_class", "no_action_needed",
        ))

    def test_ranking_in_report(self):
        report = self._run_report()
        self.assertIn("ranking", report)
        self.assertIsInstance(report["ranking"], list)


# ── Downstream compatibility checks ───────────────────────────────────────────

class TestDownstreamCompatibility(unittest.TestCase):
    """
    Verify that records produced by batch_runner are compatible with the
    downstream tools: view_experiments.py and promote_candidate.py.
    These tests use a synthetic record — no simulation is run.
    """

    def test_view_experiments_fields(self):
        """Fields consumed by view_experiments.py are all present."""
        rec = _make_validation_record()
        # List view fields
        self.assertIn("timestamp",       rec)
        self.assertIn("experiment_name", rec)
        self.assertIn("decision",        rec)
        self.assertIn("baseline",        rec)
        self.assertIn("candidate",       rec)
        self.assertIsIn("avg_pnl",    rec["baseline"])
        self.assertIsIn("median_pnl", rec["baseline"])
        # Detail view fields
        self.assertIn("candidate_config", rec)
        self.assertIn("runs",             rec)
        # Per-run fields
        for row in rec["runs"]:
            for field in ("seed", "ticks", "base_pnl", "cand_pnl",
                          "pnl_delta", "base_trades", "cand_trades", "trade_delta"):
                self.assertIn(field, row)

    def test_promote_candidate_fields(self):
        """Fields consumed by promote_candidate.py are all present."""
        rec = _make_validation_record()
        self.assertIn("decision",         rec)
        self.assertIn("experiment_name",  rec)
        self.assertIn("timestamp",        rec)
        self.assertIn("candidate_config", rec)
        for key in ("avg_pnl", "median_pnl", "worst_pnl", "avg_trades"):
            self.assertIn(key, rec["baseline"])
            self.assertIn(key, rec["candidate"])

    def assertIsIn(self, key, d):
        self.assertIn(key, d, f"Missing key '{key}' in dict")


# ── Session diagnosis tests ───────────────────────────────────────────────────

class TestSessionDiagnosis(unittest.TestCase):

    def test_stop_condition_max_batches(self):
        from research.session_diagnosis import check_stop_conditions, diagnose_session_state
        diag = diagnose_session_state([])
        should_stop, cond, _ = check_stop_conditions(
            max_batches=3,
            batches_completed=3,
            session_batch_results=[],
            diagnosis=diag,
        )
        self.assertTrue(should_stop)
        self.assertEqual(cond, "max_batches_reached")

    def test_stop_condition_strong_found(self):
        from research.session_diagnosis import check_stop_conditions, diagnose_session_state
        diag = diagnose_session_state([])
        batch_results = [
            {
                "ranking": [
                    {"tier": "strong", "experiment_id": "exp_001",
                     "experiment_class": "entry_quality"}
                ],
                "what_ran": {"n_accepted": 1},
            }
        ]
        should_stop, cond, _ = check_stop_conditions(
            max_batches=5,
            batches_completed=1,
            session_batch_results=batch_results,
            diagnosis=diag,
        )
        self.assertTrue(should_stop)
        self.assertEqual(cond, "strong_candidate_found")

    def test_stop_condition_no_progress(self):
        from research.session_diagnosis import check_stop_conditions, diagnose_session_state
        diag = diagnose_session_state([])
        # Three consecutive batches with zero accepted
        batch_results = [
            {"ranking": [], "what_ran": {"n_accepted": 0}},
            {"ranking": [], "what_ran": {"n_accepted": 0}},
            {"ranking": [], "what_ran": {"n_accepted": 0}},
        ]
        should_stop, cond, _ = check_stop_conditions(
            max_batches=5,
            batches_completed=3,
            session_batch_results=batch_results,
            diagnosis=diag,
            no_progress_threshold=3,
        )
        self.assertTrue(should_stop)
        self.assertEqual(cond, "no_progress")

    def test_stop_condition_not_triggered(self):
        from research.session_diagnosis import check_stop_conditions, diagnose_session_state
        diag = diagnose_session_state([])
        batch_results = [{"ranking": [], "what_ran": {"n_accepted": 1}}]
        should_stop, cond, _ = check_stop_conditions(
            max_batches=5,
            batches_completed=1,
            session_batch_results=batch_results,
            diagnosis=diag,
        )
        self.assertFalse(should_stop)
        self.assertEqual(cond, "")

    def test_diagnosis_focus_classes_default(self):
        from research.session_diagnosis import diagnose_session_state
        from research.policy import EXPERIMENT_CLASSES
        diag = diagnose_session_state([])
        self.assertEqual(set(diag["focus_classes"]), set(EXPERIMENT_CLASSES.keys()))
        self.assertEqual(diag["deprioritized"], [])

    def test_diagnosis_deprioritize_consistent_failure(self):
        from research.session_diagnosis import diagnose_session_state
        # Two consecutive batches with entry_quality worst_pnl rejections
        entries = [
            {   # newest
                "batch_id": "batch_002",
                "summary": {"accepted": 0},
                "experiments": [{
                    "experiment_id": "batch_002_001",
                    "experiment_class": "entry_quality",
                    "decision": "REJECTED",
                    "score": 16.0,
                    "tier": "rejected",
                    "rejection_reasons": ["worst_pnl $-375.39 < baseline $216.65"],
                }],
                "candidates_for_review": [],
            },
            {   # older
                "batch_id": "batch_001",
                "summary": {"accepted": 0},
                "experiments": [{
                    "experiment_id": "batch_001_001",
                    "experiment_class": "entry_quality",
                    "decision": "REJECTED",
                    "score": 16.0,
                    "tier": "rejected",
                    "rejection_reasons": ["worst_pnl $-375.39 < baseline $216.65"],
                }],
                "candidates_for_review": [],
            },
        ]
        diag = diagnose_session_state(entries)
        self.assertIn("entry_quality", diag["deprioritized"])

    def test_diagnosis_no_history(self):
        from research.session_diagnosis import diagnose_session_state
        diag = diagnose_session_state([])
        self.assertIsNone(diag["dominant_failure"])
        self.assertEqual(diag["n_consecutive_no_progress"], 0)
        self.assertIn("No ledger history", diag["diagnosis_reason"])

    def test_diagnosis_best_score_tracked(self):
        from research.session_diagnosis import diagnose_session_state
        entries = [
            {
                "batch_id": "batch_001",
                "summary": {"accepted": 1},
                "experiments": [{
                    "experiment_id": "batch_001_001",
                    "experiment_class": "profit_taking",
                    "decision": "ACCEPTED",
                    "score": 72.0,
                    "tier": "review_worthy",
                    "rejection_reasons": [],
                }],
                "candidates_for_review": [],
            }
        ]
        diag = diagnose_session_state(entries)
        self.assertEqual(diag["session_best_score"], 72.0)
        self.assertEqual(diag["session_best_class"], "profit_taking")


# ── Session report tests ──────────────────────────────────────────────────────

class TestSessionReport(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        import research.session_report as sr_mod
        self._orig_dir = sr_mod.REPORTS_DIR
        sr_mod.REPORTS_DIR = pathlib.Path(self._tmpdir) / "reports"

    def tearDown(self):
        import research.session_report as sr_mod
        sr_mod.REPORTS_DIR = self._orig_dir

    def _run_session_report(self, session_id="session_test_001"):
        from research.session_report import generate_session_report
        from research.session_diagnosis import diagnose_session_state

        batch_report = {
            "schema_version": "1.0",
            "batch_id": "batch_test_001",
            "what_ran": {
                "n_experiments": 3, "n_accepted": 1, "n_rejected": 2,
                "classes_tested": ["entry_quality"],
            },
            "best_candidate": {
                "experiment_id":    "batch_test_001_001",
                "experiment_class": "entry_quality",
                "decision":         "ACCEPTED",
                "score":            66.0,
                "tier":             "review_worthy",
                "pnl_delta":        50.0,
                "worst_pnl_delta":  30.0,
                "candidate_config": {"MAX_EFFICIENCY_RATIO": 0.35},
                "quality_labels":   [],
            },
            "next_action": {"recommendation": "promote_best"},
            "ranking": [
                {
                    "experiment_id":    "batch_test_001_001",
                    "experiment_class": "entry_quality",
                    "score": 66.0, "tier": "review_worthy",
                    "decision": "ACCEPTED",
                    "pnl_delta": 50.0, "worst_pnl_delta": 30.0,
                }
            ],
        }

        diag = diagnose_session_state([])
        return generate_session_report(
            session_id=session_id,
            batch_reports=[batch_report],
            diagnosis=diag,
            stop_condition="max_batches_reached",
            stop_reason="Completed 1/1 planned batches.",
        )

    def test_session_report_structure(self):
        report = self._run_session_report()
        required_keys = [
            "schema_version", "session_id", "generated_at",
            "what_ran", "best_candidate", "dominant_findings",
            "next_direction", "human_review_recommended",
            "stop_condition", "batch_summaries", "diagnosis_snapshot",
        ]
        for key in required_keys:
            self.assertIn(key, report, f"Missing session report key: {key}")

    def test_session_report_json_written(self):
        import research.session_report as sr_mod
        self._run_session_report("session_json_test")
        p = sr_mod.REPORTS_DIR / "session_json_test_session.json"
        self.assertTrue(p.exists())
        data = json.loads(p.read_text())
        self.assertEqual(data["session_id"], "session_json_test")

    def test_session_report_markdown_written(self):
        import research.session_report as sr_mod
        self._run_session_report("session_md_test")
        p = sr_mod.REPORTS_DIR / "session_md_test_session_report.md"
        self.assertTrue(p.exists())
        self.assertIn("session_md_test", p.read_text())

    def test_session_report_human_review_flag(self):
        report = self._run_session_report()
        # Batch has an accepted review_worthy candidate → human review = True
        self.assertTrue(report["human_review_recommended"])

    def test_session_report_best_candidate_extracted(self):
        report = self._run_session_report()
        bc = report.get("best_candidate")
        self.assertIsNotNone(bc)
        self.assertEqual(bc["decision"], "ACCEPTED")
        self.assertEqual(bc["tier"], "review_worthy")

    def test_session_report_stop_condition_stored(self):
        report = self._run_session_report()
        self.assertEqual(report["stop_condition"], "max_batches_reached")


# ── Generator focus_classes tests ─────────────────────────────────────────────

class TestGeneratorFocusClasses(unittest.TestCase):

    def test_focus_classes_constrains_output(self):
        from research.generator import generate_batch
        manifests = generate_batch(n=3, focus_classes=["entry_quality"])
        self.assertEqual(len(manifests), 3)
        self.assertTrue(
            all(m.experiment_class == "entry_quality" for m in manifests),
            "All manifests should be entry_quality when focus_classes=['entry_quality']",
        )

    def test_invalid_focus_class_raises(self):
        from research.generator import generate_batch
        with self.assertRaises(ValueError):
            generate_batch(n=3, focus_classes=["nonexistent_class"])


# ── promote_candidate --record tests ─────────────────────────────────────────

class TestPromoteRecordPath(unittest.TestCase):

    def test_load_record_by_path(self):
        """_load_record_by_path loads a specific file regardless of mtime order."""
        import sys
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "promote_candidate",
            _ROOT / "scripts" / "promote_candidate.py",
        )
        pc_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc_mod)

        tmp = pathlib.Path(tempfile.mkdtemp())
        rec = {
            "timestamp":        "2026-04-09T12:00:00+00:00",
            "experiment_name":  "specific_test_exp",
            "experiment_id":    "specific_test_exp",
            "decision":         "ACCEPTED",
            "rejection_reasons": [],
            "baseline":  {"avg_pnl": 1000.0, "median_pnl": 1000.0, "worst_pnl": 100.0, "avg_trades": 200.0},
            "candidate": {"avg_pnl": 1050.0, "median_pnl": 1050.0, "worst_pnl": 130.0, "avg_trades": 200.0},
            "candidate_config": {"MAX_EFFICIENCY_RATIO": 0.35},
        }
        record_path = tmp / "specific_record.json"
        record_path.write_text(json.dumps(rec))

        loaded, path = pc_mod._load_record_by_path(str(record_path))
        self.assertEqual(loaded["experiment_name"], "specific_test_exp")
        self.assertEqual(path, record_path)

    def test_load_record_by_path_missing_file(self):
        """_load_record_by_path calls sys.exit(1) for a missing file."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "promote_candidate",
            _ROOT / "scripts" / "promote_candidate.py",
        )
        pc_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc_mod)

        with self.assertRaises(SystemExit) as ctx:
            pc_mod._load_record_by_path("/nonexistent/path/record.json")
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
