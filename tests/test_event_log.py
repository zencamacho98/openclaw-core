"""
tests/test_event_log.py

Unit tests for observability/event_log.py.

Covers:
  - append creates file when absent
  - append does not overwrite existing entries
  - read returns newest-first
  - severity_filter excludes non-matching events
  - default filter excludes routine events
  - limit is respected
  - malformed JSONL line is skipped gracefully (no crash)
  - missing file returns []
  - full field round-trip
  - partial-failure events (candidate_applied_continue_failed) are visible by default
  - multiple reads produce no duplicate entries

Run with:
    python -m pytest tests/test_event_log.py -v
    python -m unittest tests.test_event_log -v
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import observability.event_log as el


class TestEventLog(unittest.TestCase):

    def setUp(self):
        self._tmpdir  = tempfile.mkdtemp()
        self._orig    = el._LOG_PATH
        el._LOG_PATH  = pathlib.Path(self._tmpdir) / "event_log.jsonl"

    def tearDown(self):
        el._LOG_PATH = self._orig
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── append ────────────────────────────────────────────────────────────────

    def test_append_creates_file_when_absent(self):
        self.assertFalse(el._LOG_PATH.exists())
        el.append_event("campaign_started", "Campaign started — test", "important")
        self.assertTrue(el._LOG_PATH.exists())

    def test_append_does_not_overwrite_existing_entries(self):
        el.append_event("campaign_started",  "First event",  "important")
        el.append_event("campaign_resumed",  "Second event", "important")
        lines = [l for l in el._LOG_PATH.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2, "Both lines must be present")
        e1 = json.loads(lines[0])
        e2 = json.loads(lines[1])
        self.assertEqual(e1["event_type"], "campaign_started")
        self.assertEqual(e2["event_type"], "campaign_resumed")

    def test_append_all_required_fields_present(self):
        el.append_event(
            "candidate_applied_and_continued",
            "Applied exp123 · resumed next run",
            "important",
            source="operator",
            campaign_id="campaign_abc",
            extra={"experiment_name": "exp123", "continue_action": "resume"},
        )
        line = el._LOG_PATH.read_text().strip()
        ev   = json.loads(line)
        for field in ("timestamp", "severity", "source", "event_type", "summary", "campaign_id", "extra"):
            self.assertIn(field, ev, f"Field '{field}' missing from event record")
        self.assertEqual(ev["event_type"],  "candidate_applied_and_continued")
        self.assertEqual(ev["severity"],    "important")
        self.assertEqual(ev["campaign_id"], "campaign_abc")
        self.assertEqual(ev["extra"]["continue_action"], "resume")

    # ── read_recent_events ────────────────────────────────────────────────────

    def test_missing_file_returns_empty_list(self):
        # file does not exist yet
        result = el.read_recent_events()
        self.assertEqual(result, [])

    def test_read_returns_newest_first(self):
        for label in ("first", "second", "third"):
            el.append_event(f"campaign_{label}", f"Summary {label}", "important")
        events = el.read_recent_events(limit=10)
        types  = [e["event_type"] for e in events]
        self.assertEqual(types, ["campaign_third", "campaign_second", "campaign_first"])

    def test_severity_filter_excludes_non_matching(self):
        el.append_event("stop_cancelled", "Stop cancelled", "routine")
        el.append_event("campaign_started", "Campaign started", "important")
        # Default filter is action_needed + important — routine is excluded
        events = el.read_recent_events()
        types  = [e["event_type"] for e in events]
        self.assertIn("campaign_started", types)
        self.assertNotIn("stop_cancelled", types)

    def test_default_filter_excludes_routine_events(self):
        el.append_event("review_resumed", "Review resumed", "routine")
        el.append_event("stop_cancelled", "Stop cancelled", "routine")
        events = el.read_recent_events()  # default filter
        self.assertEqual(events, [], "Routine events must not appear in the default feed")

    def test_explicit_routine_filter_returns_routine_only(self):
        el.append_event("campaign_started", "Started",  "important")
        el.append_event("stop_cancelled",   "Cancelled","routine")
        events = el.read_recent_events(limit=10, severity_filter=frozenset({"routine"}))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "stop_cancelled")

    def test_limit_caps_results(self):
        for i in range(10):
            el.append_event("campaign_started", f"Event {i}", "important")
        events = el.read_recent_events(limit=5)
        self.assertEqual(len(events), 5)

    def test_malformed_jsonl_line_skipped_no_crash(self):
        # Write one valid, one malformed, one valid line
        el._LOG_PATH.write_text(
            '{"timestamp":"2026-04-10T00:00:00+00:00","severity":"important","source":"operator",'
            '"event_type":"campaign_started","summary":"ok","campaign_id":null,"extra":{}}\n'
            'THIS IS NOT JSON\n'
            '{"timestamp":"2026-04-10T01:00:00+00:00","severity":"important","source":"operator",'
            '"event_type":"campaign_resumed","summary":"ok2","campaign_id":null,"extra":{}}\n',
            encoding="utf-8",
        )
        events = el.read_recent_events(limit=10)
        # Should get 2 valid events, newest first, no crash
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_type"], "campaign_resumed")
        self.assertEqual(events[1]["event_type"], "campaign_started")

    # ── Outcome-specific events ───────────────────────────────────────────────

    def test_partial_failure_event_visible_by_default(self):
        """candidate_applied_continue_failed has severity=important → visible in default feed."""
        el.append_event(
            "candidate_applied_continue_failed",
            "Applied exp99 — auto-continue failed: already running",
            "important",
            campaign_id="campaign_xyz",
        )
        events = el.read_recent_events()  # default filter
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "candidate_applied_continue_failed")

    def test_review_held_is_action_needed_and_visible(self):
        el.append_event("review_held", "Review deferred — candidate held", "action_needed", campaign_id="c1")
        events = el.read_recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "action_needed")

    def test_campaign_start_failed_visible_by_default(self):
        el.append_event("campaign_start_failed", "Campaign start failed — already running", "important")
        events = el.read_recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "campaign_start_failed")

    # ── No duplicates on multiple reads ───────────────────────────────────────

    def test_multiple_reads_produce_no_duplicates(self):
        el.append_event("campaign_started", "Started", "important")
        first  = el.read_recent_events()
        second = el.read_recent_events()
        self.assertEqual(len(first),  1)
        self.assertEqual(len(second), 1)
        # File should not grow from reads
        lines = [l for l in el._LOG_PATH.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)

    # ── Round-trip ────────────────────────────────────────────────────────────

    def test_roundtrip_preserves_all_fields(self):
        el.append_event(
            event_type="candidate_skipped_and_continued",
            summary="Candidate skipped · started next run",
            severity="important",
            source="operator",
            campaign_id="campaign_test_001",
            extra={"foo": "bar"},
        )
        events = el.read_recent_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event_type"],  "candidate_skipped_and_continued")
        self.assertEqual(ev["severity"],    "important")
        self.assertEqual(ev["source"],      "operator")
        self.assertEqual(ev["campaign_id"], "campaign_test_001")
        self.assertEqual(ev["summary"],     "Candidate skipped · started next run")
        self.assertEqual(ev["extra"],       {"foo": "bar"})
        self.assertTrue(ev["timestamp"])    # non-empty ISO timestamp


if __name__ == "__main__":
    unittest.main()
