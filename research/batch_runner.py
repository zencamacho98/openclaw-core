# research/batch_runner.py
#
# Batch validation runner.
#
# Wraps the existing in-process simulation engine (app.experiment) to validate
# experiment manifests against the live baseline. Saves results to
# data/validation_runs/ using the same schema as validate_strategy.py so all
# downstream tools (view_experiments.py, promote_candidate.py) continue to work.
#
# Design:
#   - Baseline is computed once per BatchRunner instance and reused across all
#     manifests in the same batch — deterministic, no redundant computation.
#   - Each manifest is validated by governance before running.
#   - Malformed configs produce a clear error; the runner continues with remaining.
#   - No auto-promotion. No live config changes. Read-only access to live params.

from __future__ import annotations

import json
import pathlib
import statistics
import sys
from datetime import datetime, timezone
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.experiment import MODE_MR, _live_params, _run_ticks  # noqa: E402
from app.trade_review import compare as _trade_review_compare  # noqa: E402

from .governance import enforce  # noqa: E402
from .manifest import ExperimentManifest  # noqa: E402

VALIDATION_DIR = _ROOT / "data" / "validation_runs"
TRADE_FLOOR_RATIO = 0.70  # must match validate_strategy.py


# ── Internal helpers ──────────────────────────────────────────────────────────

def _run_all(params: dict, seeds: list[int], tick_sizes: list[int]) -> list[dict]:
    """Run all (ticks × seed) combinations in-process. Stable deterministic order."""
    results = []
    for ticks in tick_sizes:
        for seed in seeds:
            results.append(_run_ticks(ticks, params, seed, mode=MODE_MR))
    return results


def _stats(results: list[dict]) -> dict[str, Any]:
    pnls   = [r["realized_pnl"] for r in results]
    trades = [r["total_trades"]  for r in results]
    return {
        "avg_pnl":    round(sum(pnls)   / len(pnls),  2),
        "median_pnl": round(statistics.median(pnls),  2),
        "worst_pnl":  round(min(pnls),                2),
        "avg_trades": round(sum(trades) / len(trades), 1),
        "n":          len(pnls),
    }


def _evaluate(b: dict, c: dict) -> tuple[bool, list[str]]:
    """Strict acceptance criteria — identical to validate_strategy.py."""
    failures: list[str] = []
    if c["median_pnl"] < b["median_pnl"]:
        failures.append(
            f"median_pnl ${c['median_pnl']:,.2f} < baseline ${b['median_pnl']:,.2f}"
        )
    if c["worst_pnl"] < b["worst_pnl"]:
        failures.append(
            f"worst_pnl ${c['worst_pnl']:,.2f} < baseline ${b['worst_pnl']:,.2f}"
        )
    if b["avg_trades"] > 0:
        ratio = c["avg_trades"] / b["avg_trades"]
        if ratio < TRADE_FLOOR_RATIO:
            failures.append(
                f"avg_trades {c['avg_trades']:.1f} is {ratio * 100:.0f}% of baseline "
                f"({b['avg_trades']:.1f}) — minimum {TRADE_FLOOR_RATIO * 100:.0f}%"
            )
    return len(failures) == 0, failures


def _run_rows(baseline_runs: list[dict], candidate_runs: list[dict]) -> list[dict]:
    rows = []
    for b, c in zip(baseline_runs, candidate_runs):
        rows.append({
            "seed":        b["seed"],
            "ticks":       b["ticks"],
            "base_pnl":    b["realized_pnl"],
            "cand_pnl":    c["realized_pnl"],
            "pnl_delta":   round(c["realized_pnl"] - b["realized_pnl"], 2),
            "base_trades": b["total_trades"],
            "cand_trades": c["total_trades"],
            "trade_delta": c["total_trades"] - b["total_trades"],
        })
    return rows


# ── BatchRunner ───────────────────────────────────────────────────────────────

class BatchRunner:
    """
    Validates a sequence of ExperimentManifest objects against the live baseline.

    Usage:
        runner = BatchRunner()
        record, path = runner.run_manifest(manifest)
    """

    def __init__(self) -> None:
        self._baseline_runs: list[dict] | None = None
        self._baseline_stats: dict | None = None
        self._baseline_params: dict | None = None

    def _ensure_baseline(self, seeds: list[int], tick_sizes: list[int]) -> None:
        """Compute baseline once and cache it for the lifetime of this runner."""
        if self._baseline_runs is not None:
            return
        print("[batch_runner] Computing baseline ...", flush=True)
        self._baseline_params = _live_params()
        self._baseline_runs = _run_all(self._baseline_params, seeds, tick_sizes)
        self._baseline_stats = _stats(self._baseline_runs)
        b = self._baseline_stats
        print(
            f"[batch_runner] Baseline → "
            f"median=${b['median_pnl']:,.2f}  "
            f"worst=${b['worst_pnl']:,.2f}  "
            f"avg_trades={b['avg_trades']:.1f}",
            flush=True,
        )

    def run_manifest(self, manifest: ExperimentManifest) -> tuple[dict, str]:
        """
        Validate one experiment manifest.

        Returns:
            (record_dict, output_path_str) — the saved validation record and its path.

        Raises:
            ValueError: If the manifest fails governance validation.
            RuntimeError: If the candidate params are identical to the baseline.
        """
        # Governance hard gate
        enforce(manifest)

        self._ensure_baseline(manifest.seed_set, manifest.tick_sizes)

        # Build candidate params (live config + overrides)
        live = _live_params()
        candidate_params = {**live, **manifest.mutated_params}

        # Guard: candidate must differ from baseline in at least one effective param
        same = all(
            candidate_params.get(k) == live.get(k)
            for k in manifest.mutated_params
        )
        if same:
            raise RuntimeError(
                f"{manifest.experiment_id}: mutated_params {manifest.mutated_params} "
                "are identical to the live config — nothing to test."
            )

        print(
            f"[batch_runner] {manifest.experiment_id} "
            f"({manifest.experiment_class}) "
            f"params={manifest.mutated_params}",
            flush=True,
        )

        cand_runs = _run_all(candidate_params, manifest.seed_set, manifest.tick_sizes)

        b_stats = self._baseline_stats
        c_stats = _stats(cand_runs)
        accepted, rejection_reasons = _evaluate(b_stats, c_stats)
        trade_review = _trade_review_compare(self._baseline_runs, cand_runs)

        ts = datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "timestamp":          ts.isoformat(),
            "experiment_id":      manifest.experiment_id,
            "batch_id":           manifest.batch_id,
            "experiment_class":   manifest.experiment_class,
            "hypothesis":         manifest.hypothesis,
            "experiment_name":    manifest.experiment_id,   # compatibility
            "mode":               "mean_reversion",
            "seeds":              manifest.seed_set,
            "tick_sizes":         manifest.tick_sizes,
            "trade_floor_ratio":  TRADE_FLOOR_RATIO,
            "decision":           "ACCEPTED" if accepted else "REJECTED",
            "rejection_reasons":  rejection_reasons,
            "baseline":           b_stats,
            "candidate":          c_stats,
            "candidate_config":   manifest.mutated_params,
            "trade_review":       trade_review,
            "runs":               _run_rows(self._baseline_runs, cand_runs),
        }

        VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
        slug = ts.strftime("%Y%m%dT%H%M%S")
        out_path = VALIDATION_DIR / f"{slug}_{manifest.experiment_id}.json"
        out_path.write_text(json.dumps(record, indent=2))

        verdict = record["decision"]
        delta = c_stats["median_pnl"] - b_stats["median_pnl"]
        print(
            f"[batch_runner] → {verdict}  "
            f"PnL Δ={delta:+,.2f}  "
            f"worst Δ={c_stats['worst_pnl'] - b_stats['worst_pnl']:+,.2f}",
            flush=True,
        )

        return record, str(out_path)
