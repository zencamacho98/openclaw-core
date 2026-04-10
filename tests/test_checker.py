# tests/test_checker.py
#
# Unit tests for app/checker.py.
# Uses temp dirs; mocks observability and queue modules.

import json
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch


def _make_agent(status="running_campaign", hb_secs_ago=0):
    """Fake AgentState-like object."""
    from datetime import datetime, timezone, timedelta
    hb = (datetime.now(timezone.utc) - timedelta(seconds=hb_secs_ago)).isoformat()
    m = MagicMock()
    m.status = status
    m.last_heartbeat_at = hb
    return m


class TestCheckerFindings(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._findings = pathlib.Path(self._tmp.name) / "checker_findings.jsonl"
        self._patch_path = patch("app.checker._FINDINGS_PATH", self._findings)
        self._patch_path.start()
        # Also patch event_log to avoid disk I/O
        self._patch_event = patch("app.checker.append_event")
        self._patch_event.start()

    def tearDown(self):
        self._patch_path.stop()
        self._patch_event.stop()
        self._tmp.cleanup()

    def _checker(self):
        import importlib
        import app.checker as m
        importlib.reload(m)
        return m

    # ── read_findings / acknowledge_finding ───────────────────────────────────

    def test_read_findings_empty_when_no_file(self):
        import app.checker as ch
        results = ch.read_findings()
        self.assertEqual(results, [])

    def test_read_findings_returns_unacknowledged(self):
        import app.checker as ch
        # Manually write a finding
        rec = {
            "timestamp": "2026-04-10T00:00:00+00:00",
            "finding_id": "chk_001",
            "finding_type": "stalled_belfort",
            "severity": "warning",
            "title": "Stall test",
            "detail": "Test detail",
            "acknowledged": False,
            "acknowledged_at": None,
            "acknowledged_by": None,
        }
        self._findings.write_text(json.dumps(rec) + "\n")
        results = ch.read_findings(include_acknowledged=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["finding_id"], "chk_001")

    def test_read_findings_excludes_acknowledged_by_default(self):
        import app.checker as ch
        rec = {
            "timestamp": "2026-04-10T00:00:00+00:00",
            "finding_id": "chk_002",
            "finding_type": "queue_backlog",
            "severity": "info",
            "title": "Acknowledged",
            "detail": "",
            "acknowledged": True,
            "acknowledged_at": "2026-04-10T01:00:00+00:00",
            "acknowledged_by": "operator",
        }
        self._findings.write_text(json.dumps(rec) + "\n")
        results = ch.read_findings(include_acknowledged=False)
        self.assertEqual(results, [])

    def test_acknowledge_finding_marks_acknowledged(self):
        import app.checker as ch
        rec = {
            "timestamp": "2026-04-10T00:00:00+00:00",
            "finding_id": "chk_ack_001",
            "finding_type": "stalled_belfort",
            "severity": "warning",
            "title": "Ack test",
            "detail": "",
            "acknowledged": False,
            "acknowledged_at": None,
            "acknowledged_by": None,
        }
        self._findings.write_text(json.dumps(rec) + "\n")
        ok = ch.acknowledge_finding("chk_ack_001", "test_operator")
        self.assertTrue(ok)
        results = ch.read_findings(include_acknowledged=True)
        self.assertTrue(results[0]["acknowledged"])
        self.assertEqual(results[0]["acknowledged_by"], "test_operator")

    def test_acknowledge_nonexistent_returns_false(self):
        import app.checker as ch
        self._findings.write_text("")
        ok = ch.acknowledge_finding("chk_ghost")
        self.assertFalse(ok)

    # ── Stalled Belfort check ─────────────────────────────────────────────────

    def test_stall_check_emits_finding_when_stale(self):
        import app.checker as ch
        stale_agent = _make_agent(status="running_campaign", hb_secs_ago=2000)
        with patch("app.checker.load_state", return_value=stale_agent):
            ch._check_stalled_belfort(ch._now(), {})
        results = ch.read_findings()
        self.assertTrue(any(f["finding_type"] == "stalled_belfort" for f in results))

    def test_stall_check_no_finding_when_fresh(self):
        import app.checker as ch
        fresh_agent = _make_agent(status="running_campaign", hb_secs_ago=10)
        with patch("app.checker.load_state", return_value=fresh_agent):
            ch._check_stalled_belfort(ch._now(), {})
        results = ch.read_findings()
        self.assertEqual(results, [])

    def test_stall_check_no_finding_when_idle(self):
        import app.checker as ch
        idle_agent = _make_agent(status="idle", hb_secs_ago=9000)
        with patch("app.checker.load_state", return_value=idle_agent):
            ch._check_stalled_belfort(ch._now(), {})
        results = ch.read_findings()
        self.assertEqual(results, [])

    # ── Queue backlog check ───────────────────────────────────────────────────

    def test_queue_backlog_emits_when_over_limit(self):
        import app.checker as ch
        big_queue = [{"queue_id": f"cq_{i}", "status": "pending"} for i in range(6)]
        with patch("app.checker.pending_candidates", return_value=big_queue):
            ch._check_queue_backlog(ch._now(), {})
        results = ch.read_findings()
        self.assertTrue(any(f["finding_type"] == "queue_backlog" for f in results))

    def test_queue_backlog_no_finding_when_small(self):
        import app.checker as ch
        small_queue = [{"queue_id": "cq_1", "status": "pending"}]
        with patch("app.checker.pending_candidates", return_value=small_queue):
            ch._check_queue_backlog(ch._now(), {})
        results = ch.read_findings()
        self.assertEqual(results, [])

    # ── Deduplication ─────────────────────────────────────────────────────────

    def test_suppressed_finding_not_emitted_twice(self):
        import app.checker as ch
        stale_agent = _make_agent(status="running_campaign", hb_secs_ago=2000)
        with patch("app.checker.load_state", return_value=stale_agent):
            ch._check_stalled_belfort(ch._now(), {})
            # Second call — recent dict should show suppression
            recent = ch._load_recent_finding_times()
            ch._check_stalled_belfort(ch._now(), recent)
        results = ch.read_findings()
        # Only one finding despite two check calls
        stall_findings = [f for f in results if f["finding_type"] == "stalled_belfort"]
        self.assertEqual(len(stall_findings), 1)

    # ── Severity → event_log mapping ─────────────────────────────────────────

    def test_warning_maps_to_important_in_event(self):
        """Internal 'warning' must call append_event with severity='important'."""
        import app.checker as ch
        from unittest.mock import call
        ch._emit_finding("test_type", "warning", "Test", "Detail")
        # The patched append_event should have been called with severity="important"
        calls = ch.append_event.call_args_list  # type: ignore[attr-defined]
        self.assertTrue(any(
            c[1].get("severity") == "important" or (len(c[0]) >= 4 and c[0][3] == "important")
            for c in calls
        ))

    def test_info_maps_to_routine_in_event(self):
        """Internal 'info' must call append_event with severity='routine'."""
        import app.checker as ch
        ch._emit_finding("test_type", "info", "Test", "Detail")
        calls = ch.append_event.call_args_list  # type: ignore[attr-defined]
        self.assertTrue(any(
            c[1].get("severity") == "routine" or (len(c[0]) >= 4 and c[0][3] == "routine")
            for c in calls
        ))

    # ── get_checker_state ─────────────────────────────────────────────────────

    def test_get_checker_state_shape(self):
        import app.checker as ch
        state = ch.get_checker_state()
        self.assertIn("running", state)
        self.assertIn("check_interval_secs", state)
        self.assertIn("dedup_threshold_secs", state)


if __name__ == "__main__":
    unittest.main()
