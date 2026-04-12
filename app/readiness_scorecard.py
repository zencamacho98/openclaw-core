# app/readiness_scorecard.py
#
# Belfort market-readiness scorecard for THE ABODE.
#
# Aggregates evidence from all prior waves (observation, paper, shadow)
# into a structured readiness assessment. Each gate is PASS / FAIL /
# INSUFFICIENT_DATA. No gate can be self-certified by code — each requires
# a measurable record in the on-disk ledgers.
#
# Readiness levels (ascending):
#   NOT_READY          — one or more gates FAIL
#   OBSERVATION_ONLY   — feed gates pass; no paper or shadow data yet
#   PAPER_READY        — feed + paper gates pass; shadow not started
#   SHADOW_COMPLETE    — all gates PASS; human sign-off needed for live
#   LIVE_ELIGIBLE      — all gates PASS + human_signoff flag set
#
# Advancing to LIVE_ELIGIBLE requires:
#   - All gates PASS
#   - Human sign-off recorded in data/readiness_signoff.json
#   Frank Lloyd cannot auto-set LIVE_ELIGIBLE.
#
# Public API:
#   evaluate()            → ScorecardResult
#   get_last_scorecard()  → ScorecardResult | None
#   record_human_signoff(reviewer, notes) → None

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timezone
from typing import Literal

_ROOT      = pathlib.Path(__file__).resolve().parent.parent
_CARD_LOG  = _ROOT / "data" / "readiness_scorecard.jsonl"
_SIGNOFF   = _ROOT / "data" / "readiness_signoff.json"

GateStatus    = Literal["PASS", "FAIL", "INSUFFICIENT_DATA"]
ReadinessLevel = Literal[
    "NOT_READY", "OBSERVATION_ONLY", "PAPER_READY",
    "SHADOW_COMPLETE", "LIVE_ELIGIBLE",
]

# Thresholds (configurable)
_FEED_UPTIME_TARGET_PCT      = 90.0   # at least 90% of requests succeed
_RECON_SUCCESS_REQUIRED      = True   # at least one clean reconciliation
_MIN_SHADOW_POSTMORTEMS      = 5      # at least 5 post-mortem days
_MIN_PAPER_DAYS              = 3      # at least 3 days with paper orders
_OVERLAY_WARN_RATE_PASS_PCT  = 50.0   # overlay warnings on < 50% of orders = ok


@dataclass
class Gate:
    name:          str
    status:        GateStatus
    detail:        str    # plain English explanation
    evidence:      str    # where the evidence comes from (file / metric)


@dataclass
class ScorecardResult:
    timestamp_utc:   str
    level:           ReadinessLevel
    gates:           list[Gate] = field(default_factory=list)
    all_pass:        bool = False
    human_signoff:   bool = False
    signoff_by:      str = ""
    signoff_at:      str = ""
    summary:         str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp_utc": self.timestamp_utc,
            "level":         self.level,
            "all_pass":      self.all_pass,
            "human_signoff": self.human_signoff,
            "signoff_by":    self.signoff_by,
            "signoff_at":    self.signoff_at,
            "summary":       self.summary,
            "gates": [asdict(g) for g in self.gates],
        }

    def plain_summary(self) -> str:
        lines = [f"Readiness: {self.level}"]
        for g in self.gates:
            icon = {"PASS": "✓", "FAIL": "✗", "INSUFFICIENT_DATA": "?"}.get(g.status, "?")
            lines.append(f"  {icon} {g.name}: {g.detail}")
        if self.human_signoff:
            lines.append(f"  ✓ Human sign-off: {self.signoff_by} at {self.signoff_at}")
        else:
            lines.append("  ? Human sign-off: not yet recorded")
        return "\n".join(lines)


# ── Gate evaluators ───────────────────────────────────────────────────────────

def _gate_feed_liveness() -> Gate:
    """Feed must have connected successfully (any live request recorded)."""
    try:
        from app.market_data_feed import feed_status
        status = feed_status()
        if not status.has_credentials:
            return Gate(
                name     = "feed_liveness",
                status   = "INSUFFICIENT_DATA",
                detail   = "No Alpaca credentials configured. Feed is simulated.",
                evidence = "market_data_feed.feed_status()",
            )
        if status.request_count == 0:
            return Gate(
                name     = "feed_liveness",
                status   = "INSUFFICIENT_DATA",
                detail   = "No live quotes fetched yet. Start observation mode first.",
                evidence = "market_data_feed.feed_status()",
            )
        total = status.request_count
        errors = status.error_count
        uptime_pct = (total - errors) / total * 100 if total > 0 else 0.0
        if uptime_pct >= _FEED_UPTIME_TARGET_PCT:
            return Gate(
                name     = "feed_liveness",
                status   = "PASS",
                detail   = f"Feed uptime {uptime_pct:.1f}% over {total} requests.",
                evidence = "market_data_feed.feed_status()",
            )
        return Gate(
            name     = "feed_liveness",
            status   = "FAIL",
            detail   = f"Feed uptime {uptime_pct:.1f}% < required {_FEED_UPTIME_TARGET_PCT:.0f}%.",
            evidence = "market_data_feed.feed_status()",
        )
    except Exception as exc:
        return Gate(
            name="feed_liveness", status="FAIL",
            detail=f"Could not evaluate: {exc}", evidence="market_data_feed",
        )


def _gate_data_lane_labeled() -> Gate:
    """Every cost estimate and order record must carry a data_lane."""
    try:
        from app.order_ledger import replay
        records = replay()
        unlabeled = [r for r in records if not r.get("data_lane")]
        if not records:
            return Gate(
                name     = "data_lane_labeled",
                status   = "INSUFFICIENT_DATA",
                detail   = "No order records yet. Place paper or shadow orders first.",
                evidence = "data/orders/",
            )
        if unlabeled:
            return Gate(
                name     = "data_lane_labeled",
                status   = "FAIL",
                detail   = f"{len(unlabeled)} record(s) missing data_lane label.",
                evidence = "data/orders/",
            )
        return Gate(
            name     = "data_lane_labeled",
            status   = "PASS",
            detail   = f"All {len(records)} records carry a data_lane label.",
            evidence = "data/orders/",
        )
    except Exception as exc:
        return Gate(
            name="data_lane_labeled", status="INSUFFICIENT_DATA",
            detail=f"Could not evaluate: {exc}", evidence="data/orders/",
        )


def _gate_reconciliation() -> Gate:
    """At least one clean reconciliation must be on record."""
    try:
        from app.reconciler import get_last_report
        report = get_last_report()
        if report is None:
            # Check the JSONL for any past run
            if _RECON_LOG_HAS_PASS():
                return Gate(
                    name     = "reconciliation",
                    status   = "PASS",
                    detail   = "At least one successful reconciliation on record.",
                    evidence = "data/reconciliation_log.jsonl",
                )
            return Gate(
                name     = "reconciliation",
                status   = "INSUFFICIENT_DATA",
                detail   = "No reconciliation run yet. Run reconciler after paper orders.",
                evidence = "data/reconciliation_log.jsonl",
            )
        if report.passed:
            return Gate(
                name     = "reconciliation",
                status   = "PASS",
                detail   = f"Last reconciliation: PASS at {report.timestamp_utc}.",
                evidence = "reconciler.get_last_report()",
            )
        return Gate(
            name     = "reconciliation",
            status   = "FAIL",
            detail   = f"Last reconciliation: FAIL. {report.message}",
            evidence = "reconciler.get_last_report()",
        )
    except Exception as exc:
        return Gate(
            name="reconciliation", status="INSUFFICIENT_DATA",
            detail=f"Could not evaluate: {exc}", evidence="reconciler",
        )


def _RECON_LOG_HAS_PASS() -> bool:
    recon_log = _ROOT / "data" / "reconciliation_log.jsonl"
    if not recon_log.exists():
        return False
    try:
        for line in recon_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("passed") is True:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _gate_overlay_warnings() -> Gate:
    """Overlay warning rate must be below threshold."""
    try:
        from app.order_ledger import replay
        records = replay(environment="paper")
        placed  = [r for r in records if r.get("event_type") == "placed"]
        if len(placed) < 5:
            return Gate(
                name     = "overlay_warnings",
                status   = "INSUFFICIENT_DATA",
                detail   = f"Only {len(placed)} paper orders placed. Need at least 5.",
                evidence = "data/orders/ (paper)",
            )
        warned = [r for r in placed if r.get("overlay_warnings")]
        warn_rate = len(warned) / len(placed) * 100
        if warn_rate < _OVERLAY_WARN_RATE_PASS_PCT:
            return Gate(
                name     = "overlay_warnings",
                status   = "PASS",
                detail   = f"Overlay warning rate: {warn_rate:.1f}% ({len(warned)} of {len(placed)} orders).",
                evidence = "data/orders/ (paper)",
            )
        return Gate(
            name     = "overlay_warnings",
            status   = "FAIL",
            detail   = (
                f"Overlay warning rate {warn_rate:.1f}% >= {_OVERLAY_WARN_RATE_PASS_PCT:.0f}%. "
                "Too many realism issues detected."
            ),
            evidence = "data/orders/ (paper)",
        )
    except Exception as exc:
        return Gate(
            name="overlay_warnings", status="INSUFFICIENT_DATA",
            detail=f"Could not evaluate: {exc}", evidence="data/orders/",
        )


def _gate_shadow_postmortems() -> Gate:
    """At least N shadow post-mortem days must exist."""
    postmortem_dir = _ROOT / "data" / "shadow_postmortems"
    if not postmortem_dir.exists():
        return Gate(
            name     = "shadow_postmortems",
            status   = "INSUFFICIENT_DATA",
            detail   = "Shadow post-mortem directory does not exist. Start shadow mode first.",
            evidence = "data/shadow_postmortems/",
        )
    pm_files = list(postmortem_dir.glob("*.json"))
    count = len(pm_files)
    if count >= _MIN_SHADOW_POSTMORTEMS:
        return Gate(
            name     = "shadow_postmortems",
            status   = "PASS",
            detail   = f"{count} shadow post-mortem day(s) on record (min {_MIN_SHADOW_POSTMORTEMS}).",
            evidence = "data/shadow_postmortems/",
        )
    return Gate(
        name     = "shadow_postmortems",
        status   = "INSUFFICIENT_DATA" if count == 0 else "FAIL",
        detail   = f"{count} of {_MIN_SHADOW_POSTMORTEMS} required post-mortem day(s) completed.",
        evidence = "data/shadow_postmortems/",
    )


def _gate_kill_switch_tested() -> Gate:
    """Kill switch must have been engaged at least once in paper mode."""
    try:
        from app.order_ledger import replay
        records = replay(environment="paper")
        ks_events = [r for r in records if r.get("event_type") == "kill_switch"]
        if ks_events:
            return Gate(
                name     = "kill_switch_tested",
                status   = "PASS",
                detail   = f"Kill switch tested {len(ks_events)} time(s) in paper mode.",
                evidence = "data/orders/ (paper, kill_switch events)",
            )
        return Gate(
            name     = "kill_switch_tested",
            status   = "FAIL",
            detail   = "Kill switch has not been tested in paper mode. Test it before live mode.",
            evidence = "data/orders/ (paper)",
        )
    except Exception as exc:
        return Gate(
            name="kill_switch_tested", status="INSUFFICIENT_DATA",
            detail=f"Could not evaluate: {exc}", evidence="data/orders/",
        )


def _gate_paper_days() -> Gate:
    """At least N distinct trading days with paper orders must be on record."""
    orders_dir = _ROOT / "data" / "orders"
    if not orders_dir.exists():
        return Gate(
            name     = "paper_days",
            status   = "INSUFFICIENT_DATA",
            detail   = "No order ledger directory found.",
            evidence = "data/orders/",
        )
    days_with_paper: set[str] = set()
    for f in orders_dir.glob("*.jsonl"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("environment") == "paper" and r.get("event_type") == "placed":
                    days_with_paper.add(f.stem)  # filename = date
        except Exception:
            continue
    count = len(days_with_paper)
    if count >= _MIN_PAPER_DAYS:
        return Gate(
            name     = "paper_days",
            status   = "PASS",
            detail   = f"{count} trading day(s) with paper orders (min {_MIN_PAPER_DAYS}).",
            evidence = "data/orders/ (paper, placed events)",
        )
    return Gate(
        name     = "paper_days",
        status   = "INSUFFICIENT_DATA" if count == 0 else "FAIL",
        detail   = f"{count} of {_MIN_PAPER_DAYS} required paper trading day(s) completed.",
        evidence = "data/orders/ (paper)",
    )


# ── Main evaluator ────────────────────────────────────────────────────────────

def evaluate() -> ScorecardResult:
    """
    Evaluate all readiness gates and return a ScorecardResult.
    Writes the result to the scorecard log (append-only).
    """
    ts = datetime.now(timezone.utc).isoformat()

    gates = [
        _gate_feed_liveness(),
        _gate_data_lane_labeled(),
        _gate_reconciliation(),
        _gate_overlay_warnings(),
        _gate_shadow_postmortems(),
        _gate_kill_switch_tested(),
        _gate_paper_days(),
    ]

    statuses = {g.status for g in gates}
    all_pass = statuses == {"PASS"}

    # Determine readiness level
    level = _determine_level(gates, all_pass)

    # Check human sign-off
    signoff_data = _load_signoff()
    human_signoff = signoff_data is not None
    signoff_by   = signoff_data.get("reviewer", "") if signoff_data else ""
    signoff_at   = signoff_data.get("timestamp_utc", "") if signoff_data else ""

    if all_pass and human_signoff:
        level = "LIVE_ELIGIBLE"

    pass_count   = sum(1 for g in gates if g.status == "PASS")
    fail_count   = sum(1 for g in gates if g.status == "FAIL")
    insuf_count  = sum(1 for g in gates if g.status == "INSUFFICIENT_DATA")

    summary = (
        f"Readiness level: {level}. "
        f"Gates: {pass_count} PASS, {fail_count} FAIL, {insuf_count} INSUFFICIENT_DATA."
    )
    if not human_signoff:
        summary += " Human sign-off required before LIVE_ELIGIBLE."

    result = ScorecardResult(
        timestamp_utc  = ts,
        level          = level,
        gates          = gates,
        all_pass       = all_pass,
        human_signoff  = human_signoff,
        signoff_by     = signoff_by,
        signoff_at     = signoff_at,
        summary        = summary,
    )

    _write_scorecard(result)
    return result


def _determine_level(gates: list[Gate], all_pass: bool) -> ReadinessLevel:
    by_name = {g.name: g.status for g in gates}

    feed_ok  = by_name.get("feed_liveness") == "PASS"
    recon_ok = by_name.get("reconciliation") in ("PASS",)
    shadow_ok = by_name.get("shadow_postmortems") == "PASS"
    ks_ok    = by_name.get("kill_switch_tested") == "PASS"

    if any(g.status == "FAIL" for g in gates):
        return "NOT_READY"

    if not feed_ok:
        return "NOT_READY"

    # Check if we have paper activity
    paper_days_status = by_name.get("paper_days", "INSUFFICIENT_DATA")
    overlay_status    = by_name.get("overlay_warnings", "INSUFFICIENT_DATA")

    if paper_days_status == "INSUFFICIENT_DATA" and shadow_ok is False:
        return "OBSERVATION_ONLY"

    if not shadow_ok or not ks_ok:
        return "PAPER_READY"

    if all_pass:
        return "SHADOW_COMPLETE"

    return "PAPER_READY"


def _write_scorecard(result: ScorecardResult) -> None:
    try:
        _CARD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _CARD_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result.to_dict()) + "\n")
    except Exception:
        pass


def get_last_scorecard() -> ScorecardResult | None:
    if not _CARD_LOG.exists():
        return None
    try:
        lines = [l.strip() for l in _CARD_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return None
        d = json.loads(lines[-1])
        gates = [
            Gate(name=g["name"], status=g["status"], detail=g["detail"], evidence=g["evidence"])
            for g in d.get("gates", [])
        ]
        return ScorecardResult(
            timestamp_utc = d.get("timestamp_utc", ""),
            level         = d.get("level", "NOT_READY"),
            gates         = gates,
            all_pass      = d.get("all_pass", False),
            human_signoff = d.get("human_signoff", False),
            signoff_by    = d.get("signoff_by", ""),
            signoff_at    = d.get("signoff_at", ""),
            summary       = d.get("summary", ""),
        )
    except Exception:
        return None


def record_human_signoff(reviewer: str, notes: str = "") -> None:
    """
    Record a human sign-off for live mode authorization.
    This file can only be written by a human action — never auto-set.
    """
    data = {
        "reviewer":      reviewer,
        "notes":         notes,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _SIGNOFF.parent.mkdir(parents=True, exist_ok=True)
        _SIGNOFF.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_signoff() -> dict | None:
    if not _SIGNOFF.exists():
        return None
    try:
        return json.loads(_SIGNOFF.read_text(encoding="utf-8"))
    except Exception:
        return None
