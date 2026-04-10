# tests/test_approval_policy.py
#
# Unit tests for research/approval_policy.py.
# No I/O — all pure function calls.

import unittest

from research.approval_policy import (
    auto_apply_eligible,
    classify_candidate,
    build_risk_summary,
    should_continue_loop,
)


def _good() -> dict:
    """A candidate that passes all five V1 auto-apply criteria."""
    return {
        "tier":             "strong",
        "score":            85.0,
        "n_changed_params": 1,
        "pnl_delta":        0.005,
        "worst_pnl_delta":  0.001,
        "quality_labels":   [],
        "flags":            [],
    }


class TestAutoApplyEligible(unittest.TestCase):

    def test_all_criteria_pass(self):
        eligible, reasons = auto_apply_eligible(_good())
        self.assertTrue(eligible)
        self.assertEqual(reasons, [])

    # ── Criterion 1: tier == "strong" ─────────────────────────────────────────

    def test_tier_noisy_not_eligible(self):
        c = {**_good(), "tier": "noisy"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("tier" in r for r in reasons))

    def test_tier_review_worthy_not_eligible(self):
        c = {**_good(), "tier": "review_worthy"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    # ── Criterion 2: n_changed_params <= 2 ───────────────────────────────────

    def test_n_changed_params_at_limit(self):
        c = {**_good(), "n_changed_params": 2}
        eligible, _ = auto_apply_eligible(c)
        self.assertTrue(eligible)

    def test_n_changed_params_exceeded(self):
        c = {**_good(), "n_changed_params": 3}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("n_changed_params" in r for r in reasons))

    # ── Criterion 3: pnl_delta > 0 ───────────────────────────────────────────

    def test_pnl_zero_not_eligible(self):
        c = {**_good(), "pnl_delta": 0.0}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("pnl_delta" in r for r in reasons))

    def test_pnl_negative_not_eligible(self):
        c = {**_good(), "pnl_delta": -0.001}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    # ── Criterion 4: worst_pnl_delta >= -0.001 ───────────────────────────────

    def test_worst_pnl_at_threshold(self):
        c = {**_good(), "worst_pnl_delta": -0.001}
        eligible, _ = auto_apply_eligible(c)
        self.assertTrue(eligible)

    def test_worst_pnl_below_threshold(self):
        c = {**_good(), "worst_pnl_delta": -0.0011}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("worst_pnl_delta" in r for r in reasons))

    # ── Criterion 5: no quality labels or flags ───────────────────────────────

    def test_quality_label_blocks_auto_apply(self):
        c = {**_good(), "quality_labels": ["overfit"]}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("quality label" in r for r in reasons))

    def test_flag_blocks_auto_apply(self):
        c = {**_good(), "flags": ["low_sample"]}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("flag" in r for r in reasons))

    # ── Fail-safe: missing required fields ───────────────────────────────────

    def test_missing_tier_fail_safe(self):
        c = {k: v for k, v in _good().items() if k != "tier"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("tier" in r for r in reasons))

    def test_missing_score_fail_safe(self):
        c = {k: v for k, v in _good().items() if k != "score"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    def test_missing_n_changed_params_fail_safe(self):
        c = {k: v for k, v in _good().items() if k != "n_changed_params"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    def test_missing_pnl_delta_fail_safe(self):
        c = {k: v for k, v in _good().items() if k != "pnl_delta"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    def test_missing_worst_pnl_delta_fail_safe(self):
        c = {k: v for k, v in _good().items() if k != "worst_pnl_delta"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    def test_missing_quality_labels_fail_safe(self):
        c = {k: v for k, v in _good().items() if k != "quality_labels"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    def test_missing_flags_fail_safe(self):
        c = {k: v for k, v in _good().items() if k != "flags"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)

    def test_non_dict_fail_safe(self):
        eligible, reasons = auto_apply_eligible("not a dict")  # type: ignore[arg-type]
        self.assertFalse(eligible)
        self.assertTrue(len(reasons) > 0)

    def test_malformed_score_fail_safe(self):
        c = {**_good(), "score": "not_a_number"}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)
        self.assertTrue(any("score" in r for r in reasons))

    def test_negative_n_changed_params_fail_safe(self):
        c = {**_good(), "n_changed_params": -1}
        eligible, reasons = auto_apply_eligible(c)
        self.assertFalse(eligible)


class TestClassifyCandidate(unittest.TestCase):

    def test_auto_apply_path(self):
        self.assertEqual(classify_candidate(_good()), "auto_apply")

    def test_weak_tier_skip(self):
        c = {**_good(), "tier": "weak"}
        self.assertEqual(classify_candidate(c), "skip")

    def test_rejected_tier_skip(self):
        c = {**_good(), "tier": "rejected"}
        self.assertEqual(classify_candidate(c), "skip")

    def test_non_eligible_strong_review_required(self):
        c = {**_good(), "flags": ["overfit"]}
        self.assertEqual(classify_candidate(c), "review_required")

    def test_noisy_tier_review_required(self):
        c = {**_good(), "tier": "noisy"}
        self.assertEqual(classify_candidate(c), "review_required")

    def test_malformed_review_required_not_auto_apply(self):
        # Malformed data must never yield auto_apply
        self.assertEqual(classify_candidate({"tier": "strong"}), "review_required")

    def test_non_dict_review_required(self):
        self.assertEqual(classify_candidate(None), "review_required")  # type: ignore[arg-type]


class TestBuildRiskSummary(unittest.TestCase):

    def test_eligible_summary_contains_all_met(self):
        c = _good()
        summary = build_risk_summary(c, True, [])
        self.assertIn("all criteria met", summary)

    def test_ineligible_summary_contains_reason(self):
        c = {**_good(), "flags": ["overfit"]}
        summary = build_risk_summary(c, False, ["1 flag(s) present"])
        self.assertIn("blocked", summary)
        self.assertIn("flag", summary)

    def test_ineligible_no_reasons_fallback(self):
        summary = build_risk_summary(_good(), False, [])
        self.assertIn("not eligible", summary)


class TestShouldContinueLoop(unittest.TestCase):

    def test_ok_when_enabled(self):
        ok, reason = should_continue_loop({"enabled": True, "stop_requested": False}, "idle")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_stop_requested_halts(self):
        ok, reason = should_continue_loop({"enabled": True, "stop_requested": True}, "idle")
        self.assertFalse(ok)
        self.assertEqual(reason, "stop_requested")

    def test_paused_by_budget_halts(self):
        ok, reason = should_continue_loop({"enabled": True, "stop_requested": False}, "paused_by_budget")
        self.assertFalse(ok)
        self.assertIn("paused_by_budget", reason)

    def test_guardrail_halts(self):
        ok, reason = should_continue_loop({"enabled": True, "stop_requested": False}, "stopped_by_guardrail")
        self.assertFalse(ok)
        self.assertIn("stopped_by_guardrail", reason)

    def test_malformed_state_halts(self):
        ok, reason = should_continue_loop("not_a_dict", "idle")  # type: ignore[arg-type]
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
