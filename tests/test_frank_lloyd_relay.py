# tests/test_frank_lloyd_relay.py
#
# Unit tests for frank_lloyd/relay.py
#
# Tests the append/consume_unread relay queue.

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import frank_lloyd.relay as relay


class TestRelay(unittest.TestCase):
    def setUp(self):
        """Set up a fresh temp directory for each test."""
        self._td = tempfile.TemporaryDirectory()
        td = pathlib.Path(self._td.name)
        # Patch the module-level paths to use temp dir
        relay._RELAY_LOG    = td / "peter_relay.jsonl"
        relay._RELAY_CURSOR = td / "peter_relay_cursor.txt"

    def tearDown(self):
        self._td.cleanup()

    def test_append_creates_file(self):
        relay.append("BUILD-001", "pipeline_start", "Working on it.")
        self.assertTrue(relay._RELAY_LOG.exists())

    def test_append_writes_json_entry(self):
        relay.append("BUILD-001", "draft_ready", "Draft is ready.")
        lines = [l for l in relay._RELAY_LOG.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["build_id"], "BUILD-001")
        self.assertEqual(entry["event"],    "draft_ready")
        self.assertEqual(entry["msg"],      "Draft is ready.")
        self.assertEqual(entry["id"],       0)

    def test_append_sequential_ids(self):
        relay.append("BUILD-001", "pipeline_start", "msg1")
        relay.append("BUILD-001", "draft_ready",    "msg2")
        relay.append("BUILD-001", "review_needed",  "msg3")
        lines = [json.loads(l) for l in relay._RELAY_LOG.read_text().splitlines() if l.strip()]
        ids = [e["id"] for e in lines]
        self.assertEqual(ids, [0, 1, 2])

    def test_consume_unread_returns_all_when_no_cursor(self):
        relay.append("BUILD-001", "pipeline_start", "msg1")
        relay.append("BUILD-001", "draft_ready",    "msg2")
        result = relay.consume_unread()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["event"], "pipeline_start")
        self.assertEqual(result[1]["event"], "draft_ready")

    def test_consume_unread_advances_cursor(self):
        relay.append("BUILD-001", "pipeline_start", "msg1")
        relay.append("BUILD-001", "draft_ready",    "msg2")
        relay.consume_unread()
        # Second call should return nothing
        result2 = relay.consume_unread()
        self.assertEqual(len(result2), 0)

    def test_consume_unread_only_new_after_cursor(self):
        relay.append("BUILD-001", "pipeline_start", "msg1")
        relay.consume_unread()
        # Append more after consuming
        relay.append("BUILD-001", "draft_ready", "msg2")
        relay.append("BUILD-001", "review_needed", "msg3")
        result = relay.consume_unread()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["event"], "draft_ready")
        self.assertEqual(result[1]["event"], "review_needed")

    def test_consume_unread_respects_max_messages(self):
        for i in range(10):
            relay.append("BUILD-001", "pipeline_start", f"msg{i}")
        result = relay.consume_unread(max_messages=3)
        self.assertEqual(len(result), 3)
        # Cursor should be at id=2 (first 3 consumed: 0,1,2)
        cursor = relay._read_cursor()
        self.assertEqual(cursor, 2)

    def test_consume_unread_empty_when_no_log(self):
        # No file exists
        result = relay.consume_unread()
        self.assertEqual(result, [])

    def test_consume_unread_empty_after_all_consumed(self):
        relay.append("BUILD-001", "draft_ready", "msg1")
        relay.consume_unread()
        result = relay.consume_unread()
        self.assertEqual(result, [])

    def test_cursor_persists_between_calls(self):
        relay.append("BUILD-001", "pipeline_start", "msg1")
        relay.append("BUILD-001", "draft_ready",    "msg2")
        relay.consume_unread()
        # Cursor should be at id=1
        self.assertEqual(relay._read_cursor(), 1)

    def test_multiple_builds(self):
        relay.append("BUILD-001", "pipeline_start", "A started.")
        relay.append("BUILD-002", "pipeline_start", "B started.")
        relay.append("BUILD-001", "draft_ready",    "A done.")
        result = relay.consume_unread()
        self.assertEqual(len(result), 3)
        build_ids = [r["build_id"] for r in result]
        self.assertIn("BUILD-001", build_ids)
        self.assertIn("BUILD-002", build_ids)

    def test_read_cursor_default_minus_one(self):
        self.assertEqual(relay._read_cursor(), -1)

    def test_write_and_read_cursor(self):
        relay._write_cursor(42)
        self.assertEqual(relay._read_cursor(), 42)

    def test_next_id_increments(self):
        self.assertEqual(relay._next_id(), 0)
        relay.append("BUILD-001", "x", "y")
        self.assertEqual(relay._next_id(), 1)
        relay.append("BUILD-001", "x", "y")
        self.assertEqual(relay._next_id(), 2)

    def test_append_is_non_fatal_on_bad_path(self):
        """Append should not raise even if the path is bad."""
        relay._RELAY_LOG = pathlib.Path("/nonexistent/deep/path/relay.jsonl")
        try:
            relay.append("BUILD-001", "x", "y")
        except Exception as e:
            self.fail(f"append raised unexpectedly: {e}")


class TestJobHumanizeEvents(unittest.TestCase):
    """Test job.py event humanization."""

    def setUp(self):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    def test_humanize_request_queued(self):
        from frank_lloyd.job import _humanize_event
        ev = {"event": "request_queued", "timestamp": "2026-04-11T10:00:00+00:00", "notes": "", "extra": {}}
        result = _humanize_event(ev)
        self.assertIsNotNone(result)
        self.assertEqual(result["cls"], "ok")
        self.assertIn("queued", result["label"].lower())

    def test_humanize_spec_ready_includes_risk(self):
        from frank_lloyd.job import _humanize_event
        ev = {"event": "spec_ready", "timestamp": "2026-04-11T10:01:00+00:00",
              "notes": "", "extra": {"build_type": "new_file", "risk_level": "low"}}
        result = _humanize_event(ev)
        self.assertIsNotNone(result)
        self.assertIn("low risk", result["detail"])

    def test_humanize_auto_approved(self):
        from frank_lloyd.job import _humanize_event
        ev = {"event": "spec_approved", "timestamp": "2026-04-11T10:02:00+00:00",
              "notes": "Auto-approved by safe lane", "extra": {}}
        result = _humanize_event(ev)
        self.assertIsNotNone(result)
        self.assertIn("auto", result["label"].lower())

    def test_humanize_unknown_event_returns_none(self):
        from frank_lloyd.job import _humanize_event
        ev = {"event": "totally_unknown_event", "timestamp": "", "notes": "", "extra": {}}
        self.assertIsNone(_humanize_event(ev))

    def test_humanize_ts_short(self):
        from frank_lloyd.job import _humanize_event
        ev = {"event": "draft_generated", "timestamp": "2026-04-11T14:32:00+00:00", "notes": "", "extra": {}}
        result = _humanize_event(ev)
        self.assertEqual(result["ts_short"], "14:32")

    def test_humanize_draft_blocked_includes_reason(self):
        from frank_lloyd.job import _humanize_event
        ev = {"event": "draft_blocked", "timestamp": "2026-04-11T10:03:00+00:00",
              "notes": "blocked", "extra": {"reason": "lane_not_executable"}}
        result = _humanize_event(ev)
        self.assertIsNotNone(result)
        self.assertIn("lane", result["detail"])


class TestExtractNewFilePath(unittest.TestCase):
    """Test apply_summary._extract_new_file_path."""

    def test_extracts_path(self):
        from frank_lloyd.apply_summary import _extract_new_file_path
        spec = (
            "affected_files:\n"
            "  new:\n"
            '    - path: "frank_lloyd/stats.py"\n'
            '      purpose: "stats module"\n'
            "  modified:\n"
            "    []\n"
        )
        self.assertEqual(_extract_new_file_path(spec), "frank_lloyd/stats.py")

    def test_returns_none_when_new_is_empty(self):
        from frank_lloyd.apply_summary import _extract_new_file_path
        spec = (
            "affected_files:\n"
            "  new:\n"
            "    []\n"
            "  modified:\n"
            "    []\n"
        )
        self.assertIsNone(_extract_new_file_path(spec))

    def test_returns_none_when_no_section(self):
        from frank_lloyd.apply_summary import _extract_new_file_path
        spec = "risk_level: low\nbuild_type: new_file\n"
        self.assertIsNone(_extract_new_file_path(spec))

    def test_returns_first_path_when_multiple(self):
        from frank_lloyd.apply_summary import _extract_new_file_path
        spec = (
            "affected_files:\n"
            "  new:\n"
            '    - path: "frank_lloyd/first.py"\n'
            '      purpose: "first"\n'
            '    - path: "frank_lloyd/second.py"\n'
            '      purpose: "second"\n'
        )
        self.assertEqual(_extract_new_file_path(spec), "frank_lloyd/first.py")


if __name__ == "__main__":
    unittest.main()
