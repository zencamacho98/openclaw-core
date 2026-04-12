# tests/test_frank_lloyd_job.py
#
# BUILD-018: Tests for frank_lloyd/job.py — unified job model.
#
# Run with:
#   python -m pytest tests/test_frank_lloyd_job.py -v

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

import frank_lloyd.job as fl_job


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(offset_seconds: int = 0) -> str:
    from datetime import timedelta
    base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _ev(build_id: str, event: str, ts_offset: int = 0, extra: dict | None = None) -> dict:
    return {
        "timestamp": _ts(ts_offset),
        "build_id":  build_id,
        "event":     event,
        "notes":     "",
        "extra":     extra or {},
    }


class _Env:
    """Temp directory with a patched build log and request files."""

    def __init__(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())

    @property
    def build_log(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "build_log.jsonl"

    @property
    def requests_dir(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "requests"

    def setup(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self._orig_log  = fl_job._FL_BUILD_LOG
        self._orig_reqs = fl_job._FL_REQUESTS
        fl_job._FL_BUILD_LOG = self.build_log
        fl_job._FL_REQUESTS  = self.requests_dir

    def restore(self):
        fl_job._FL_BUILD_LOG = self._orig_log
        fl_job._FL_REQUESTS  = self._orig_reqs

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_log(self, events: list[dict]):
        with self.build_log.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def write_request(self, build_id: str, description: str = "Add a new endpoint for testing",
                      title: str = "Test Build"):
        data = {
            "build_id":        build_id,
            "title":           title,
            "description":     description,
            "success_criteria": "The endpoint returns 200.",
        }
        req_file = self.requests_dir / f"{build_id}_request.json"
        req_file.write_text(json.dumps(data), encoding="utf-8")


# ── Tests: load_job ───────────────────────────────────────────────────────────

class TestLoadJob(unittest.TestCase):

    def setUp(self):
        self._env = _Env()
        self._env.setup()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_returns_none_for_unknown_build(self):
        self.assertIsNone(fl_job.load_job("BUILD-999"))

    def test_pending_spec_status_and_phase(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        j = fl_job.load_job("BUILD-001")
        self.assertIsNotNone(j)
        self.assertEqual(j.status, "pending_spec")
        self.assertEqual(j.phase,  "intake")

    def test_pending_review_status_and_phase(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_ready",     60),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "pending_review")
        self.assertEqual(j.phase,  "intake")

    def test_spec_approved_phase_is_plan(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_ready",     60),
            _ev("BUILD-001", "spec_approved",  120, extra={"build_type": "modification", "risk_level": "high"}),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status,     "spec_approved")
        self.assertEqual(j.phase,      "plan")
        self.assertEqual(j.build_type, "modification")
        self.assertEqual(j.risk_level, "high")

    def test_stage2_authorized_phase_is_authorized(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",   0),
            _ev("BUILD-001", "spec_approved",   120),
            _ev("BUILD-001", "stage2_authorized", 240),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "stage2_authorized")
        self.assertEqual(j.phase,  "authorized")

    def test_draft_generated_phase_is_building(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",    0),
            _ev("BUILD-001", "spec_approved",    120),
            _ev("BUILD-001", "stage2_authorized", 240),
            _ev("BUILD-001", "draft_generated",  360),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "draft_generated")
        self.assertEqual(j.phase,  "building")

    def test_draft_blocked_phase_is_building(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",    0),
            _ev("BUILD-001", "spec_approved",    120),
            _ev("BUILD-001", "stage2_authorized", 240),
            _ev("BUILD-001", "draft_blocked",    360),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "draft_blocked")
        self.assertEqual(j.phase,  "building")

    def test_draft_promoted_phase_is_live(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",    0),
            _ev("BUILD-001", "spec_approved",    120),
            _ev("BUILD-001", "stage2_authorized", 240),
            _ev("BUILD-001", "draft_generated",  360),
            _ev("BUILD-001", "draft_promoted",   480),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "draft_promoted")
        self.assertEqual(j.phase,  "live")

    def test_spec_rejected_phase_is_closed(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_rejected",  120),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "spec_rejected")
        self.assertEqual(j.phase,  "closed")

    def test_abandoned_phase_is_closed(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "abandoned",      120),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "abandoned")
        self.assertEqual(j.phase,  "closed")

    def test_draft_discarded_resets_to_stage2_authorized(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",    0),
            _ev("BUILD-001", "spec_approved",    120),
            _ev("BUILD-001", "stage2_authorized", 240),
            _ev("BUILD-001", "draft_generated",  360),
            _ev("BUILD-001", "draft_discarded",  480),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.status, "stage2_authorized")
        self.assertEqual(j.phase,  "authorized")

    def test_build_id_uppercased(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        j = fl_job.load_job("build-001")
        self.assertIsNotNone(j)
        self.assertEqual(j.build_id, "BUILD-001")

    def test_waiting_on_operator_for_pending_review(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_ready",     60),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.waiting_on, "operator")

    def test_waiting_on_system_for_pending_spec(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.waiting_on, "system")

    def test_waiting_on_system_for_draft_generating(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",           0),
            _ev("BUILD-001", "stage2_authorized",        120),
            _ev("BUILD-001", "draft_generation_started", 240),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.waiting_on, "system")

    def test_waiting_on_complete_for_terminal_builds(self):
        for terminal_event in ("draft_promoted", "spec_rejected", "abandoned"):
            with self.subTest(event=terminal_event):
                self._env.build_log.unlink(missing_ok=True)
                self._env.write_log([
                    _ev("BUILD-001", "request_queued", 0),
                    _ev("BUILD-001", terminal_event,   120),
                ])
                j = fl_job.load_job("BUILD-001")
                self.assertEqual(j.waiting_on, "complete")

    def test_next_action_is_populated(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        j = fl_job.load_job("BUILD-001")
        self.assertIn("spec", j.next_action.lower())

    def test_requested_at_and_updated_at(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_ready",     60),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertIsNotNone(j.requested_at)
        self.assertIsNotNone(j.updated_at)
        # updated_at should be the spec_ready timestamp, not request_queued
        self.assertGreater(j.updated_at, j.requested_at)

    def test_title_from_request_file(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        self._env.write_request(
            "BUILD-001",
            description="Add a new REST endpoint for health checking",
            title="Health endpoint",
        )
        j = fl_job.load_job("BUILD-001")
        # Description has ≥5 words so it takes precedence over stored title
        self.assertNotEqual(j.title, "BUILD-001")
        self.assertNotIn("peter", j.title.lower())

    def test_title_fallback_to_build_id_if_no_request_file(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.title, "BUILD-001")

    def test_to_dict_has_all_fields(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        j   = fl_job.load_job("BUILD-001")
        d   = j.to_dict()
        expected_keys = {
            "build_id", "title", "status", "phase",
            "next_action", "waiting_on", "requested_at", "updated_at",
            "build_type", "risk_level",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_build_type_and_risk_level_from_spec_ready_event(self):
        """When spec_approved is absent, extract from spec_ready."""
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_ready", 60,
                extra={"build_type": "new_service", "risk_level": "medium"}),
        ])
        j = fl_job.load_job("BUILD-001")
        self.assertEqual(j.build_type, "new_service")
        self.assertEqual(j.risk_level, "medium")


# ── Tests: load_active_job ────────────────────────────────────────────────────

class TestLoadActiveJob(unittest.TestCase):

    def setUp(self):
        self._env = _Env()
        self._env.setup()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_returns_none_with_no_builds(self):
        self.assertIsNone(fl_job.load_active_job())

    def test_returns_none_with_only_terminal_builds(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "draft_promoted", 120),
        ])
        self.assertIsNone(fl_job.load_active_job())

    def test_pending_review_beats_pending_spec(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-002", "request_queued", 60),
            _ev("BUILD-002", "spec_ready",     120),
        ])
        j = fl_job.load_active_job()
        self.assertEqual(j.build_id, "BUILD-002")
        self.assertEqual(j.status,   "pending_review")

    def test_draft_generated_beats_stage2_authorized(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",   0),
            _ev("BUILD-001", "stage2_authorized", 60),
            _ev("BUILD-002", "request_queued",   0),
            _ev("BUILD-002", "stage2_authorized", 60),
            _ev("BUILD-002", "draft_generated",  120),
        ])
        j = fl_job.load_active_job()
        self.assertEqual(j.build_id, "BUILD-002")
        self.assertEqual(j.status,   "draft_generated")

    def test_draft_blocked_beats_spec_approved(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_approved",  60),
            _ev("BUILD-002", "request_queued",    0),
            _ev("BUILD-002", "stage2_authorized", 60),
            _ev("BUILD-002", "draft_blocked",    120),
        ])
        j = fl_job.load_active_job()
        self.assertEqual(j.status, "draft_blocked")

    def test_single_build_returned(self):
        self._env.write_log([_ev("BUILD-001", "request_queued")])
        j = fl_job.load_active_job()
        self.assertIsNotNone(j)
        self.assertEqual(j.build_id, "BUILD-001")


# ── Tests: list_jobs ──────────────────────────────────────────────────────────

class TestListJobs(unittest.TestCase):

    def setUp(self):
        self._env = _Env()
        self._env.setup()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_empty_log_returns_empty_list(self):
        self.assertEqual(fl_job.list_jobs(), [])

    def test_active_before_terminal(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "draft_promoted", 120),  # terminal
            _ev("BUILD-002", "request_queued", 60),
            _ev("BUILD-002", "spec_ready",     180),  # active
        ])
        jobs = fl_job.list_jobs()
        self.assertEqual(len(jobs), 2)
        # Active build should come first
        self.assertEqual(jobs[0].build_id, "BUILD-002")
        self.assertEqual(jobs[1].build_id, "BUILD-001")

    def test_active_jobs_sorted_by_priority(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),   # pending_spec
            _ev("BUILD-002", "request_queued", 0),
            _ev("BUILD-002", "spec_ready", 60),       # pending_review
            _ev("BUILD-003", "request_queued", 0),
            _ev("BUILD-003", "spec_approved", 60),    # spec_approved
        ])
        jobs = fl_job.list_jobs()
        active = [j for j in jobs if j.waiting_on != "complete"]
        self.assertEqual(active[0].status, "pending_review")   # priority 1
        self.assertEqual(active[1].status, "spec_approved")    # priority 4
        self.assertEqual(active[2].status, "pending_spec")     # priority 7

    def test_terminal_jobs_sorted_newest_first(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", 0),
            _ev("BUILD-001", "spec_rejected",  60),
            _ev("BUILD-002", "request_queued", 0),
            _ev("BUILD-002", "abandoned",      120),
        ])
        jobs = fl_job.list_jobs()
        terminal = [j for j in jobs if j.waiting_on == "complete"]
        self.assertEqual(terminal[0].build_id, "BUILD-002")  # newer
        self.assertEqual(terminal[1].build_id, "BUILD-001")  # older


if __name__ == "__main__":
    unittest.main()
