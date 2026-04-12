# tests/test_frank_lloyd_stage2_discarder.py
#
# Tests for frank_lloyd.stage2_discarder — draft discard / retry lane.
#
# Coverage:
#   TestUnknownBuild          — build not in log → clean error
#   TestNonDiscardableStates  — all states that must be rejected
#   TestMissingArtifacts      — stage2 dir absent → clean error
#   TestSuccessfulDiscard     — stage2 dir removed, log appended, status resets
#   TestStatusAfterDiscard    — status derives as stage2_authorized post-discard
#   TestAuditTrailPreserved   — stage1 and auth record not touched
#   TestRetryLane             — can discard multiple times (blocked → retry → blocked → retry)
#   TestPromotedCannotDiscard — draft_promoted is not discardable

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import frank_lloyd.stage2_discarder as discarder


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_log(log_path: pathlib.Path, events: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")


def _make_stage2_dir(staging_root: pathlib.Path, build_id: str) -> pathlib.Path:
    """Create a minimal stage2 artifact directory."""
    s2 = staging_root / build_id / "stage2"
    s2.mkdir(parents=True, exist_ok=True)
    (s2 / "draft_manifest.json").write_text(
        json.dumps({"task_class": "code_draft_low", "model_used": "test/model"}),
        encoding="utf-8",
    )
    (s2 / "draft_module.py").write_text("# draft\ndef hello(): pass\n", encoding="utf-8")
    return s2


def _event(build_id: str, event: str, ts: str = "2026-04-11T00:00:00+00:00") -> dict:
    return {"timestamp": ts, "build_id": build_id, "event": event, "notes": "", "extra": {}}


def _discard_with_tmp(
    build_id: str,
    log_events: list[dict],
    create_stage2: bool = True,
) -> tuple[dict, pathlib.Path]:
    """
    Run discard_draft() with isolated tmpdir.
    Returns (result, tmpdir_path).
    Caller is responsible for cleanup — use within TemporaryDirectory context.
    """
    raise NotImplementedError  # never called directly; use _run_discard


def _run_discard(
    build_id: str,
    log_events: list[dict],
    tmpdir: pathlib.Path,
    create_stage2: bool = True,
    notes: str = "",
) -> dict:
    """
    Monkey-patch discarder's module-level constants to use tmpdir,
    then run discard_draft().
    """
    log_path = tmpdir / "build_log.jsonl"
    staging  = tmpdir / "staging" / "frank_lloyd"

    _write_log(log_path, log_events)
    if create_stage2:
        _make_stage2_dir(staging, build_id)

    orig_log     = discarder._FL_BUILD_LOG
    orig_staging = discarder._FL_STAGING
    try:
        discarder._FL_BUILD_LOG = log_path
        discarder._FL_STAGING   = staging
        return discarder.discard_draft(build_id, notes=notes)
    finally:
        discarder._FL_BUILD_LOG = orig_log
        discarder._FL_STAGING   = orig_staging


# ── TestUnknownBuild ─────────────────────────────────────────────────────────

class TestUnknownBuild(unittest.TestCase):

    def test_unknown_build_returns_ok_false(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-999", [], pathlib.Path(d), create_stage2=False)
        self.assertFalse(r["ok"])

    def test_unknown_build_error_mentions_build_id(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-999", [], pathlib.Path(d), create_stage2=False)
        self.assertIn("BUILD-999", r["error"])

    def test_unknown_build_discarded_at_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-999", [], pathlib.Path(d), create_stage2=False)
        self.assertIsNone(r["discarded_at"])


# ── TestNonDiscardableStates ─────────────────────────────────────────────────

class TestNonDiscardableStates(unittest.TestCase):
    """All states that are NOT discardable must be cleanly rejected."""

    def _reject(self, event_name: str):
        events = [_event("BUILD-001", "request_queued"), _event("BUILD-001", event_name)]
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", events, pathlib.Path(d), create_stage2=False)
        self.assertFalse(r["ok"], f"Expected rejection for state from event: {event_name!r}")
        return r

    def test_pending_spec_not_discardable(self):
        self._reject("request_queued")

    def test_pending_review_not_discardable(self):
        self._reject("spec_ready")

    def test_spec_approved_not_discardable(self):
        self._reject("spec_approved")

    def test_spec_rejected_not_discardable(self):
        self._reject("spec_rejected")

    def test_abandoned_not_discardable(self):
        self._reject("abandoned")

    def test_stage2_authorized_not_discardable(self):
        # already the reset state; no stage2 artifacts exist anyway
        self._reject("stage2_authorized")

    def test_draft_generating_not_discardable(self):
        self._reject("draft_generation_started")

    def test_draft_promoted_not_discardable(self):
        r = self._reject("draft_promoted")
        self.assertIn("promoted", r["error"].lower())

    def test_non_discardable_error_mentions_allowed_states(self):
        events = [_event("BUILD-001", "request_queued"), _event("BUILD-001", "spec_approved")]
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", events, pathlib.Path(d), create_stage2=False)
        # Error should mention valid states
        self.assertTrue(
            "draft_generated" in r["error"] or "draft_blocked" in r["error"],
            f"Expected discardable states in error, got: {r['error']!r}",
        )


# ── TestMissingArtifacts ─────────────────────────────────────────────────────

class TestMissingArtifacts(unittest.TestCase):

    def _draft_generated_events(self) -> list[dict]:
        return [
            _event("BUILD-001", "request_queued", "2026-04-11T00:01:00+00:00"),
            _event("BUILD-001", "spec_ready",     "2026-04-11T00:02:00+00:00"),
            _event("BUILD-001", "spec_approved",  "2026-04-11T00:03:00+00:00"),
            _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
            _event("BUILD-001", "draft_generated", "2026-04-11T00:05:00+00:00"),
        ]

    def test_no_stage2_dir_returns_ok_false(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard(
                "BUILD-001", self._draft_generated_events(),
                pathlib.Path(d), create_stage2=False,
            )
        self.assertFalse(r["ok"])

    def test_no_stage2_dir_error_mentions_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard(
                "BUILD-001", self._draft_generated_events(),
                pathlib.Path(d), create_stage2=False,
            )
        self.assertIn("stage2", r["error"].lower())


# ── TestSuccessfulDiscard ─────────────────────────────────────────────────────

class TestSuccessfulDiscard(unittest.TestCase):

    def _events(self, final_event: str) -> list[dict]:
        return [
            _event("BUILD-001", "request_queued",    "2026-04-11T00:01:00+00:00"),
            _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
            _event("BUILD-001", final_event,         "2026-04-11T00:05:00+00:00"),
        ]

    def test_discard_draft_generated_returns_ok_true(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", self._events("draft_generated"), pathlib.Path(d))
        self.assertTrue(r["ok"])

    def test_discard_draft_blocked_returns_ok_true(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", self._events("draft_blocked"), pathlib.Path(d))
        self.assertTrue(r["ok"])

    def test_discard_returns_build_id(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", self._events("draft_generated"), pathlib.Path(d))
        self.assertEqual(r["build_id"], "BUILD-001")

    def test_discard_returns_discarded_at(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", self._events("draft_generated"), pathlib.Path(d))
        self.assertIsNotNone(r["discarded_at"])

    def test_discard_removes_stage2_dir(self):
        with tempfile.TemporaryDirectory() as d:
            dp      = pathlib.Path(d)
            staging = dp / "staging" / "frank_lloyd"
            s2_dir  = _make_stage2_dir(staging, "BUILD-001")
            log_path = dp / "build_log.jsonl"
            _write_log(log_path, self._events("draft_generated"))

            orig_log, orig_staging = discarder._FL_BUILD_LOG, discarder._FL_STAGING
            discarder._FL_BUILD_LOG = log_path
            discarder._FL_STAGING   = staging
            try:
                discarder.discard_draft("BUILD-001")
            finally:
                discarder._FL_BUILD_LOG = orig_log
                discarder._FL_STAGING   = orig_staging

            self.assertFalse(s2_dir.exists())

    def test_discard_appends_draft_discarded_event(self):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            _run_discard("BUILD-001", self._events("draft_generated"), dp)
            log_path = dp / "build_log.jsonl"
            events = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
            last = events[-1]
            self.assertEqual(last["event"], "draft_discarded")

    def test_discard_log_event_has_build_id(self):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            _run_discard("BUILD-001", self._events("draft_generated"), dp)
            log_path = dp / "build_log.jsonl"
            events = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
            last = events[-1]
            self.assertEqual(last["build_id"], "BUILD-001")

    def test_discard_log_event_notes_previous_state(self):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            _run_discard("BUILD-001", self._events("draft_generated"), dp)
            log_path = dp / "build_log.jsonl"
            events = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
            last = events[-1]
            self.assertIn("draft_generated", last.get("notes", "") + json.dumps(last.get("extra", {})))

    def test_discard_error_is_none_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", self._events("draft_generated"), pathlib.Path(d))
        self.assertIsNone(r["error"])


# ── TestStatusAfterDiscard ────────────────────────────────────────────────────

class TestStatusAfterDiscard(unittest.TestCase):
    """After draft_discarded event, status must derive as stage2_authorized."""

    def test_draft_discarded_derives_stage2_authorized(self):
        status = discarder._STATUS_FROM_EVENT.get("draft_discarded")
        self.assertEqual(status, "stage2_authorized")

    def test_derive_status_after_discard_returns_stage2_authorized(self):
        events = [
            _event("BUILD-001", "request_queued",    "2026-04-11T00:01:00+00:00"),
            _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
            _event("BUILD-001", "draft_generated",   "2026-04-11T00:05:00+00:00"),
            _event("BUILD-001", "draft_discarded",   "2026-04-11T00:06:00+00:00"),
        ]
        status = discarder._derive_status("BUILD-001", events)
        self.assertEqual(status, "stage2_authorized")

    def test_blocked_then_discarded_derives_stage2_authorized(self):
        events = [
            _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
            _event("BUILD-001", "draft_blocked",     "2026-04-11T00:05:00+00:00"),
            _event("BUILD-001", "draft_discarded",   "2026-04-11T00:06:00+00:00"),
        ]
        status = discarder._derive_status("BUILD-001", events)
        self.assertEqual(status, "stage2_authorized")


# ── TestAuditTrailPreserved ───────────────────────────────────────────────────

class TestAuditTrailPreserved(unittest.TestCase):
    """Stage 1 artifacts and Stage 2 authorization record are not removed on discard."""

    def test_stage1_dir_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            dp      = pathlib.Path(d)
            staging = dp / "staging" / "frank_lloyd"
            # Create stage1 dir
            s1_dir = staging / "BUILD-001" / "stage1"
            s1_dir.mkdir(parents=True, exist_ok=True)
            (s1_dir / "spec_packet.json").write_text('{"spec": "data"}', encoding="utf-8")
            # Create stage2 dir
            _make_stage2_dir(staging, "BUILD-001")

            log_path = dp / "build_log.jsonl"
            _write_log(log_path, [
                _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
                _event("BUILD-001", "draft_generated",   "2026-04-11T00:05:00+00:00"),
            ])

            orig_log, orig_staging = discarder._FL_BUILD_LOG, discarder._FL_STAGING
            discarder._FL_BUILD_LOG = log_path
            discarder._FL_STAGING   = staging
            try:
                discarder.discard_draft("BUILD-001")
            finally:
                discarder._FL_BUILD_LOG = orig_log
                discarder._FL_STAGING   = orig_staging

            self.assertTrue(s1_dir.exists())
            self.assertTrue((s1_dir / "spec_packet.json").exists())

    def test_stage2_auth_record_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            dp      = pathlib.Path(d)
            staging = dp / "staging" / "frank_lloyd"
            # Create auth record at build root (not inside stage2/)
            build_dir = staging / "BUILD-001"
            build_dir.mkdir(parents=True, exist_ok=True)
            auth_record = build_dir / "stage2_authorization.json"
            auth_record.write_text('{"authorized": true}', encoding="utf-8")
            # Create stage2 dir
            _make_stage2_dir(staging, "BUILD-001")

            log_path = dp / "build_log.jsonl"
            _write_log(log_path, [
                _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
                _event("BUILD-001", "draft_generated",   "2026-04-11T00:05:00+00:00"),
            ])

            orig_log, orig_staging = discarder._FL_BUILD_LOG, discarder._FL_STAGING
            discarder._FL_BUILD_LOG = log_path
            discarder._FL_STAGING   = staging
            try:
                discarder.discard_draft("BUILD-001")
            finally:
                discarder._FL_BUILD_LOG = orig_log
                discarder._FL_STAGING   = orig_staging

            self.assertTrue(auth_record.exists())

    def test_build_log_events_preserved(self):
        """All prior events must still be in the log after discard."""
        with tempfile.TemporaryDirectory() as d:
            dp      = pathlib.Path(d)
            staging = dp / "staging" / "frank_lloyd"
            _make_stage2_dir(staging, "BUILD-001")

            prior_events = [
                _event("BUILD-001", "request_queued",    "2026-04-11T00:01:00+00:00"),
                _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
                _event("BUILD-001", "draft_generated",   "2026-04-11T00:05:00+00:00"),
            ]
            log_path = dp / "build_log.jsonl"
            _write_log(log_path, prior_events)

            orig_log, orig_staging = discarder._FL_BUILD_LOG, discarder._FL_STAGING
            discarder._FL_BUILD_LOG = log_path
            discarder._FL_STAGING   = staging
            try:
                discarder.discard_draft("BUILD-001")
            finally:
                discarder._FL_BUILD_LOG = orig_log
                discarder._FL_STAGING   = orig_staging

            all_events = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
            event_names = [e["event"] for e in all_events]
            self.assertIn("request_queued",    event_names)
            self.assertIn("stage2_authorized", event_names)
            self.assertIn("draft_generated",   event_names)
            self.assertIn("draft_discarded",   event_names)


# ── TestRetryLane ─────────────────────────────────────────────────────────────

class TestRetryLane(unittest.TestCase):
    """After discard, a new draft_blocked can also be discarded (multi-retry)."""

    def test_discard_blocked_allows_retry(self):
        """
        A build that was previously draft_discarded and then got a new draft_blocked
        must be discardable again. Tests the retry lane: prior draft_discarded in the
        log does not block a second discard when the current state is draft_blocked.

        Pre-bakes the full event history to avoid timestamp-ordering issues with
        datetime.now() in the discard_draft() implementation.
        """
        events = [
            _event("BUILD-001", "stage2_authorized",        "2026-04-11T00:04:00+00:00"),
            _event("BUILD-001", "draft_blocked",            "2026-04-11T00:05:00+00:00"),
            _event("BUILD-001", "draft_discarded",          "2026-04-11T00:06:00+00:00"),  # prior discard
            _event("BUILD-001", "draft_generation_started", "2026-04-11T00:10:00+00:00"),
            _event("BUILD-001", "draft_blocked",            "2026-04-11T00:11:00+00:00"),  # blocked again
        ]
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", events, pathlib.Path(d), create_stage2=True)
        self.assertTrue(r["ok"], f"Second discard failed: {r['error']}")


# ── TestPromotedCannotDiscard ─────────────────────────────────────────────────

class TestPromotedCannotDiscard(unittest.TestCase):

    def test_promoted_build_rejected_with_clear_error(self):
        events = [
            _event("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
            _event("BUILD-001", "draft_generated",   "2026-04-11T00:05:00+00:00"),
            _event("BUILD-001", "draft_promoted",    "2026-04-11T00:10:00+00:00"),
        ]
        with tempfile.TemporaryDirectory() as d:
            r = _run_discard("BUILD-001", events, pathlib.Path(d), create_stage2=False)
        self.assertFalse(r["ok"])
        self.assertIn("promoted", r["error"].lower())


# ── TestDiscardableStatesConstant ─────────────────────────────────────────────

class TestDiscardableStatesConstant(unittest.TestCase):

    def test_draft_generated_in_discardable_states(self):
        self.assertIn("draft_generated", discarder.DISCARDABLE_STATES)

    def test_draft_blocked_in_discardable_states(self):
        self.assertIn("draft_blocked", discarder.DISCARDABLE_STATES)

    def test_draft_promoted_not_in_discardable_states(self):
        self.assertNotIn("draft_promoted", discarder.DISCARDABLE_STATES)

    def test_stage2_authorized_not_in_discardable_states(self):
        self.assertNotIn("stage2_authorized", discarder.DISCARDABLE_STATES)

    def test_draft_generating_not_in_discardable_states(self):
        self.assertNotIn("draft_generating", discarder.DISCARDABLE_STATES)


if __name__ == "__main__":
    unittest.main()
