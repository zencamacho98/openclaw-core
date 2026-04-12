# app/test_sentinel.py
#
# Targeted test runner and patch-safety validator for The Abode.
#
# Test Sentinel selects the minimal relevant test scope for a set of touched
# files, runs pytest in a subprocess, parses the results, and produces a
# structured verdict for Peter and the dashboard.
#
# Role boundary:
#   - Test Sentinel: code/test validation, patch safety — read/run/report only
#   - Custodian:     runtime health / environment drift
#   - Checker:       trading loop health (stalls, queue backlog)
#   - Peter:         operator interface — reads Sentinel findings for briefings
#
# Safety rule (v1):
#   Sentinel does NOT auto-fix failing tests, does NOT rewrite product code.
#   Findings are verdicts for operator review only.
#
# Routing strategy:
#   1. Map touched files → targeted test files (FILE_TEST_MAP)
#   2. If no targeted tests found → fall back to SMOKE_TESTS
#   3. For explicit smoke or full runs → use SMOKE_TESTS or ALL_TESTS
#
# Verdict logic:
#   "safe"      — 0 failures, 0 errors in all run tests
#   "review"    — 1-2 failures in non-core tests; safe enough but warrants a look
#   "not_ready" — 3+ failures OR any failure in CORE_TESTS
#
# Public API:
#   run_sentinel(files, scope)  → SentinelReport
#   detect_touched_files()      → list[str]  (git diff --name-only HEAD)
#   get_last_report()           → dict | None
#   report_to_dict(r)           → dict

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import List, Optional

_ROOT          = pathlib.Path(__file__).resolve().parent.parent
_TESTS_DIR     = _ROOT / "tests"
_REPORT_CACHE  = _ROOT / "data" / "sentinel_report.json"

# ── Test routing map ──────────────────────────────────────────────────────────
# Maps source file path fragments → test files to run.
# Use normalized relative paths (forward slashes, no leading /).

FILE_TEST_MAP: dict[str, list[str]] = {
    # Peter subsystem
    "peter/commands.py":        ["test_peter.py", "test_peter_command.py", "test_peter_build_intake.py", "test_peter_build_approval.py", "test_peter_stage2_authorization.py", "test_peter_draft_stage2.py", "test_peter_promote_draft.py", "test_peter_nl_build_intake.py", "test_peter_discard_draft.py", "test_peter_fl_lifecycle_nl.py"],
    "peter/handlers.py":        ["test_peter.py", "test_peter_build_intake.py", "test_peter_build_approval.py", "test_peter_stage2_authorization.py", "test_peter_draft_stage2.py", "test_peter_promote_draft.py", "test_peter_nl_build_intake.py", "test_peter_discard_draft.py", "test_peter_fl_lifecycle_nl.py"],
    "peter/router.py":          ["test_peter.py", "test_peter_build_intake.py", "test_peter_build_approval.py", "test_peter_stage2_authorization.py", "test_peter_draft_stage2.py", "test_peter_promote_draft.py", "test_peter_nl_build_intake.py", "test_peter_discard_draft.py", "test_peter_fl_lifecycle_nl.py"],
    "peter/responses.py":       ["test_peter.py", "test_peter_command.py"],
    "peter/identity.py":        ["test_peter.py"],
    # App / backend
    "app/checker.py":           ["test_checker.py"],
    "app/main.py":              ["test_candidate_apply_route.py"],
    "app/routes/event_query.py":          ["test_event_query.py"],
    "app/routes/frank_lloyd_status.py":   ["test_frank_lloyd_status.py", "test_frank_lloyd_build016.py", "test_frank_lloyd_build017.py"],
    "app/routes/frank_lloyd_spec.py":    ["test_frank_lloyd_spec_writer.py"],
    "app/routes/frank_lloyd_actions.py": ["test_frank_lloyd_actions.py", "test_frank_lloyd_draft_review.py", "test_frank_lloyd_stage2_promoter.py", "test_frank_lloyd_compose_request.py", "test_frank_lloyd_stage2_discarder.py", "test_frank_lloyd_build016.py", "test_frank_lloyd_build017.py", "test_frank_lloyd_job.py", "test_frank_lloyd_build018.py"],
    "frank_lloyd/request_writer.py":    ["test_frank_lloyd_compose_request.py", "test_frank_lloyd_build016.py"],
    "frank_lloyd/stage2_discarder.py":  ["test_frank_lloyd_stage2_discarder.py", "test_peter_discard_draft.py"],
    "frank_lloyd/stage2_promoter.py":   ["test_frank_lloyd_stage2_promoter.py", "test_peter_promote_draft.py"],
    "frank_lloyd/spec_writer.py":        ["test_frank_lloyd_spec_writer.py"],
    "frank_lloyd/spec_validator.py":     ["test_frank_lloyd_spec_validator.py", "test_frank_lloyd_spec_writer.py"],
    "frank_lloyd/spec_approver.py":      ["test_frank_lloyd_spec_approver.py", "test_peter_build_approval.py"],
    "frank_lloyd/stage2_authorizer.py": ["test_frank_lloyd_stage2_authorizer.py", "test_peter_stage2_authorization.py"],
    "frank_lloyd/stage2_drafter.py":    ["test_frank_lloyd_stage2_drafter.py", "test_peter_draft_stage2.py", "test_frank_lloyd_draft_review.py", "test_frank_lloyd_stage2_promoter.py"],
    "frank_lloyd/provider_router.py":   ["test_frank_lloyd_provider_router.py", "test_frank_lloyd_spec_writer.py", "test_frank_lloyd_stage2_drafter.py"],
    "frank_lloyd/job.py":               ["test_frank_lloyd_job.py", "test_frank_lloyd_build018.py"],
    "app/cost_warden.py":               ["test_warden.py", "test_frank_lloyd_provider_router.py"],
    "app/routes/neighborhood.py":        ["test_neighborhood.py", "test_frank_lloyd_draft_review.py", "test_frank_lloyd_stage2_promoter.py", "test_frank_lloyd_build018.py"],
    "app/routes/monitor.py":    ["test_candidate_apply_route.py"],
    "app/routes/supervisor.py": ["test_candidate_apply_route.py"],
    "app/strategy/applier.py":  ["test_candidate_apply_route.py", "test_review_actions.py"],
    "app/strategy/config.py":   ["test_candidate_apply_route.py"],
    "app/strategy/changelog.py":["test_candidate_apply_route.py"],
    # Research subsystem
    "research/manifest.py":         ["test_research.py"],
    "research/governance.py":       ["test_research.py"],
    "research/scoring.py":          ["test_research.py"],
    "research/reviewer.py":         ["test_research.py"],
    "research/ledger.py":           ["test_research.py"],
    "research/report.py":           ["test_research.py"],
    "research/campaign.py":         ["test_campaign.py", "test_campaign_control.py"],
    "research/campaign_runner.py":  ["test_campaign.py"],
    "research/campaign_report.py":  ["test_campaign.py"],
    "research/candidate_queue.py":  ["test_candidate_queue.py"],
    "research/approval_policy.py":  ["test_approval_policy.py"],
    # Observability subsystem
    "observability/agent_state.py": ["test_observability.py", "test_review_actions.py"],
    "observability/event_log.py":   ["test_event_log.py"],
    "observability/telemetry.py":   ["test_observability.py"],
    "observability/budget.py":      ["test_observability.py"],
    "observability/summary.py":     ["test_observability.py"],
    # UI subsystem
    "ui/campaign_control.py":   ["test_campaign_control.py"],
    "ui/peter_command.py":      ["test_peter_command.py"],
    "ui/peter_helpers.py":      ["test_peter_helpers.py"],
    "ui/peter_build.py":        ["test_peter_build.py"],
    "ui/review_actions.py":     ["test_review_actions.py"],
    "ui/trade_helpers.py":      ["test_trade_helpers.py"],
}

# Smoke suite — core tests to run when no targeted match or explicitly requested
SMOKE_TESTS: list[str] = [
    "test_peter.py",
    "test_research.py",
    "test_observability.py",
    "test_approval_policy.py",
    "test_candidate_queue.py",
]

# Core tests — failures here are escalated to "not_ready" (not just "review")
CORE_TESTS: frozenset[str] = frozenset({
    "test_peter.py",
    "test_research.py",
})

ALL_TESTS: list[str] = [p.name for p in sorted(_TESTS_DIR.glob("test_*.py"))]

# Pytest output limits — truncate giant raw output for readability
_MAX_RAW_LINES = 200


@dataclass
class FailureDetail:
    test_id:   str    # tests/test_foo.py::TestClass::test_method
    test_file: str    # test_foo.py
    kind:      str    # "FAILED" | "ERROR"
    excerpt:   str    # short traceback or reason (first 3 lines)


@dataclass
class SentinelReport:
    timestamp:     str
    scope:         str              # "targeted" | "smoke" | "full" | "none"
    touched_files: List[str]        # files that triggered this run (empty = manual)
    tests_run:     List[str]        # test files actually executed
    passed:        int
    failed:        int
    errors:        int
    failures:      List[FailureDetail]
    verdict:       str              # "safe" | "review" | "not_ready"
    summary:       str              # one-line plain English for Peter
    elapsed_secs:  float


def run_sentinel(
    files:       list[str] | None = None,
    scope:       str              = "auto",
) -> SentinelReport:
    """
    Run targeted (or smoke) tests and return a structured verdict.

    Args:
        files: relative paths of touched/changed files to target.
               If empty/None and scope="auto", runs SMOKE_TESTS.
        scope: "auto"     — targeted from files, fall back to smoke
               "smoke"    — always run SMOKE_TESTS
               "full"     — always run ALL_TESTS
    """
    t0             = time.monotonic()
    touched_files  = [_normalise(f) for f in (files or [])]
    tests_to_run:  list[str]
    actual_scope:  str

    if scope == "full":
        tests_to_run = ALL_TESTS
        actual_scope = "full"
    elif scope == "smoke":
        tests_to_run = SMOKE_TESTS
        actual_scope = "smoke"
    else:
        # "auto": derive targeted set from touched files
        targeted = _select_tests(touched_files)
        if targeted:
            tests_to_run = targeted
            actual_scope = "targeted"
        elif touched_files:
            # Files were specified but none matched the map — warn via smoke
            tests_to_run = SMOKE_TESTS
            actual_scope = "smoke"
        else:
            tests_to_run = SMOKE_TESTS
            actual_scope = "smoke"

    # Verify test files exist
    existing = [t for t in tests_to_run if (_TESTS_DIR / t).exists()]
    if not existing:
        elapsed = time.monotonic() - t0
        report = SentinelReport(
            timestamp     = _now(),
            scope         = "none",
            touched_files = touched_files,
            tests_run     = [],
            passed        = 0,
            failed        = 0,
            errors        = 0,
            failures      = [],
            verdict       = "review",
            summary       = "No test files found to run. Recommend manual review.",
            elapsed_secs  = elapsed,
        )
        _cache(report)
        return report

    # Run pytest
    raw_output, returncode = _run_pytest(existing)
    elapsed = time.monotonic() - t0

    # Parse output
    passed, failed, errors = _parse_counts(raw_output)
    failures = _parse_failures(raw_output)

    # Determine verdict
    verdict = _compute_verdict(failed, errors, failures, existing, actual_scope)
    summary = _build_summary(verdict, actual_scope, passed, failed, errors, failures, existing)

    report = SentinelReport(
        timestamp     = _now(),
        scope         = actual_scope,
        touched_files = touched_files,
        tests_run     = existing,
        passed        = passed,
        failed        = failed,
        errors        = errors,
        failures      = failures,
        verdict       = verdict,
        summary       = summary,
        elapsed_secs  = round(elapsed, 2),
    )
    _cache(report)
    return report


def detect_touched_files() -> list[str]:
    """
    Return files modified since the last commit (staged + unstaged).
    Uses `git diff --name-only HEAD`. Returns [] if git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=str(_ROOT), timeout=10,
        )
        lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        # Also include staged changes not yet committed
        result2 = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True, text=True, cwd=str(_ROOT), timeout=10,
        )
        lines += [ln.strip() for ln in result2.stdout.splitlines() if ln.strip()]
        return sorted(set(lines))
    except Exception:
        return []


def get_last_report() -> dict | None:
    """Return the last cached Sentinel report from disk, or None."""
    if not _REPORT_CACHE.exists():
        return None
    try:
        return json.loads(_REPORT_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def report_to_dict(report: SentinelReport) -> dict:
    return asdict(report)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _normalise(path: str) -> str:
    """Normalise a file path to forward slashes, strip leading ./ or /."""
    p = path.replace("\\", "/").lstrip("./")
    # Remove repo-root prefix if present
    root_str = str(_ROOT).replace("\\", "/").rstrip("/") + "/"
    if p.startswith(root_str):
        p = p[len(root_str):]
    return p


def _select_tests(touched: list[str]) -> list[str]:
    """Return deduplicated test files for the given touched source files."""
    selected: list[str] = []
    for src in touched:
        for key, tests in FILE_TEST_MAP.items():
            if src == key or src.endswith("/" + key) or key in src:
                for t in tests:
                    if t not in selected:
                        selected.append(t)
    return selected


def _run_pytest(test_files: list[str]) -> tuple[str, int]:
    """Run pytest on the given test files. Returns (combined output, returncode)."""
    args = [
        sys.executable, "-m", "pytest",
        *[str(_TESTS_DIR / f) for f in test_files],
        "-v", "--tb=short", "--no-header",
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
            timeout=120,
        )
        combined = result.stdout + ("\n" + result.stderr if result.stderr.strip() else "")
        # Truncate for storage/display while preserving the summary line at the bottom.
        # Keep first N lines + always keep last 20 lines (contains the summary).
        lines = combined.splitlines()
        if len(lines) > _MAX_RAW_LINES:
            head = lines[: _MAX_RAW_LINES - 25]
            tail = lines[-20:]
            lines = head + [f"... (truncated, {len(lines)} total lines) ..."] + tail
        return "\n".join(lines), result.returncode
    except subprocess.TimeoutExpired:
        return "pytest timed out after 120s", 1
    except Exception as exc:
        return f"Failed to launch pytest: {exc}", 1


_SUMMARY_RE = re.compile(
    r"(\d+)\s+failed|(\d+)\s+passed|(\d+)\s+error",
    re.IGNORECASE,
)
_SUMMARY_LINE_RE = re.compile(
    r"=+\s+([\d\w\s,]+(?:passed|failed|error)[^=]*)\s+=+",
    re.IGNORECASE,
)


def _parse_counts(output: str) -> tuple[int, int, int]:
    """Extract (passed, failed, errors) from pytest output."""
    passed = failed = errors = 0
    # Find the final summary line: "= 3 passed, 1 failed in 0.5s ="
    for line in reversed(output.splitlines()):
        m = _SUMMARY_LINE_RE.search(line)
        if m:
            chunk = m.group(1)
            for m2 in _SUMMARY_RE.finditer(chunk):
                if m2.group(1):
                    failed = int(m2.group(1))
                elif m2.group(2):
                    passed = int(m2.group(2))
                elif m2.group(3):
                    errors = int(m2.group(3))
            break
    return passed, failed, errors


_FAILED_RE = re.compile(r"^(FAILED|ERROR)\s+(tests/[\w/]+\.py::[\w:]+)", re.MULTILINE)


def _parse_failures(output: str) -> list[FailureDetail]:
    """Extract individual failure/error test IDs and short excerpts."""
    failures: list[FailureDetail] = []
    seen: set[str] = set()

    for m in _FAILED_RE.finditer(output):
        kind    = m.group(1)
        test_id = m.group(2).strip()
        if test_id in seen:
            continue
        seen.add(test_id)

        test_file = test_id.split("::")[0].split("/")[-1] if "::" in test_id else test_id

        # Extract a short excerpt from the output near this test ID
        excerpt = _extract_excerpt(output, test_id)

        failures.append(FailureDetail(
            test_id   = test_id,
            test_file = test_file,
            kind      = kind,
            excerpt   = excerpt,
        ))

    return failures


def _extract_excerpt(output: str, test_id: str) -> str:
    """Find the short traceback block for a test_id in pytest --tb=short output."""
    lines      = output.splitlines()
    # Find the block starting with "FAILED test_id" or "__ test_name __"
    test_name  = test_id.split("::")[-1] if "::" in test_id else test_id
    excerpt    = []
    in_block   = False

    for i, line in enumerate(lines):
        if test_name in line and ("FAILED" in line or "ERROR" in line or "___" in line):
            in_block = True
            excerpt  = []
        if in_block:
            excerpt.append(line)
            # Stop at the next separator or after 8 lines
            if len(excerpt) > 8 or (len(excerpt) > 2 and line.startswith("=")):
                break

    return "\n".join(excerpt[:6]).strip() if excerpt else ""


def _compute_verdict(
    failed:      int,
    errors:      int,
    failures:    list[FailureDetail],
    tests_run:   list[str],
    scope:       str,
) -> str:
    total_bad = failed + errors
    if total_bad == 0:
        return "safe"

    # Check if any failures are in core test files
    failing_files = {f.test_file for f in failures}
    core_hit      = any(f in CORE_TESTS for f in failing_files)

    if core_hit or total_bad >= 3:
        return "not_ready"

    return "review"


def _build_summary(
    verdict:    str,
    scope:      str,
    passed:     int,
    failed:     int,
    errors:     int,
    failures:   list[FailureDetail],
    tests_run:  list[str],
) -> str:
    total_bad = failed + errors
    scope_label = {
        "targeted": f"targeted ({len(tests_run)} file(s))",
        "smoke":    "smoke check",
        "full":     "full suite",
        "none":     "no tests",
    }.get(scope, scope)

    if verdict == "safe":
        return (
            f"Targeted validation passed for {scope_label}. "
            f"{passed} test(s) passed. Looks safe enough for review."
        )

    fail_labels = []
    for f in failures[:3]:
        name = f.test_id.split("::")[-1] if "::" in f.test_id else f.test_id
        fail_labels.append(name)
    fail_str = ", ".join(fail_labels) if fail_labels else f"{total_bad} failure(s)"

    if verdict == "review":
        return (
            f"{scope_label.capitalize()}: {passed} passed, {total_bad} failed. "
            f"Needs review — {fail_str}."
        )
    else:  # not_ready
        return (
            f"This patch is not ready: {total_bad} test(s) failed in {scope_label}. "
            f"Failures: {fail_str}."
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache(report: SentinelReport) -> None:
    """Atomically write the report to disk."""
    try:
        _REPORT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _REPORT_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        tmp.rename(_REPORT_CACHE)
    except Exception:
        pass
