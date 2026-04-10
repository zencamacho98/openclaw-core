# tests/test_candidate_queue.py
#
# Unit tests for research/candidate_queue.py.
# Uses a temp dir to avoid touching the real queue file.

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch


def _make_entry(**overrides) -> dict:
    base = {
        "experiment_id":  "exp_test_001",
        "campaign_id":    "campaign_test",
        "title":          "Strong: 0.5% PnL · 1 param(s)",
        "tier":           "strong",
        "score":          82.0,
        "pnl_delta":      0.005,
        "worst_pnl_delta": 0.001,
        "n_changed_params": 1,
        "quality_labels": [],
        "flags":          [],
        "status":         "pending",
        "record_path":    "data/validation_runs/test.json",
    }
    base.update(overrides)
    return base


class TestCandidateQueue(unittest.TestCase):

    def setUp(self):
        """Each test gets its own temp queue file."""
        self._tmpdir = tempfile.TemporaryDirectory()
        self._queue_path = pathlib.Path(self._tmpdir.name) / "candidate_queue.json"
        # Patch the module-level _QUEUE_PATH
        self._patcher = patch("research.candidate_queue._QUEUE_PATH", self._queue_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    # ── Import after patch ─────────────────────────────────────────────────────
    def _q(self):
        import importlib
        import research.candidate_queue as m
        return m

    def test_ensure_queue_exists_creates_file(self):
        q = self._q()
        self.assertFalse(self._queue_path.exists())
        q.ensure_queue_exists()
        self.assertTrue(self._queue_path.exists())
        data = json.loads(self._queue_path.read_text())
        self.assertIsInstance(data["candidates"], list)

    def test_add_returns_queue_id(self):
        q = self._q()
        qid = q.add_to_queue(_make_entry())
        self.assertIsInstance(qid, str)
        self.assertTrue(qid.startswith("cq_"))

    def test_add_then_read(self):
        q = self._q()
        q.add_to_queue(_make_entry(experiment_id="exp_001"))
        q.add_to_queue(_make_entry(experiment_id="exp_002"))
        items = q.read_queue()
        self.assertEqual(len(items), 2)
        # Newest-first — exp_002 should come first or equal (same second)
        exp_ids = [i["experiment_id"] for i in items]
        self.assertIn("exp_001", exp_ids)
        self.assertIn("exp_002", exp_ids)

    def test_pending_candidates_filter(self):
        q = self._q()
        q.add_to_queue(_make_entry(experiment_id="e1", status="pending"))
        q.add_to_queue(_make_entry(experiment_id="e2", status="approved"))
        q.add_to_queue(_make_entry(experiment_id="e3", status="pending"))
        pending = q.pending_candidates()
        self.assertEqual(len(pending), 2)
        self.assertTrue(all(p["status"] == "pending" for p in pending))

    def test_get_queue_item(self):
        q = self._q()
        qid = q.add_to_queue(_make_entry())
        item = q.get_queue_item(qid)
        self.assertIsNotNone(item)
        self.assertEqual(item["queue_id"], qid)

    def test_get_queue_item_missing_returns_none(self):
        q = self._q()
        self.assertIsNone(q.get_queue_item("cq_nonexistent"))

    def test_update_status(self):
        q = self._q()
        qid = q.add_to_queue(_make_entry())
        ok = q.update_queue_item(qid, status="approved", resolved_at="2026-04-10T00:00:00+00:00")
        self.assertTrue(ok)
        item = q.get_queue_item(qid)
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["resolved_at"], "2026-04-10T00:00:00+00:00")

    def test_update_invalid_status_ignored(self):
        q = self._q()
        qid = q.add_to_queue(_make_entry())
        q.update_queue_item(qid, status="BOGUS_STATUS")
        item = q.get_queue_item(qid)
        # status should remain "pending" — invalid status was ignored
        self.assertEqual(item["status"], "pending")

    def test_update_immutable_created_at_ignored(self):
        q = self._q()
        qid = q.add_to_queue(_make_entry())
        original_ts = q.get_queue_item(qid)["created_at"]
        q.update_queue_item(qid, created_at="1970-01-01T00:00:00+00:00")
        item = q.get_queue_item(qid)
        self.assertEqual(item["created_at"], original_ts)

    def test_update_nonexistent_returns_false(self):
        q = self._q()
        ok = q.update_queue_item("cq_ghost", status="rejected")
        self.assertFalse(ok)

    def test_top_pending_returns_most_recent(self):
        q = self._q()
        import time
        q.add_to_queue(_make_entry(experiment_id="older"))
        time.sleep(0.01)
        q.add_to_queue(_make_entry(experiment_id="newer"))
        top = q.top_pending()
        self.assertIsNotNone(top)
        self.assertEqual(top["experiment_id"], "newer")

    def test_top_pending_none_when_empty(self):
        q = self._q()
        self.assertIsNone(q.top_pending())

    def test_atomic_write_on_missing_dir(self):
        """Queue writes should create parent dirs if missing."""
        nested_path = pathlib.Path(self._tmpdir.name) / "sub" / "deep" / "queue.json"
        with patch("research.candidate_queue._QUEUE_PATH", nested_path):
            import research.candidate_queue as q
            qid = q.add_to_queue(_make_entry())
            self.assertTrue(nested_path.exists())
            self.assertIsNotNone(q.get_queue_item(qid))


if __name__ == "__main__":
    unittest.main()
