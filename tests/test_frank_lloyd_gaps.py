# tests/test_frank_lloyd_gaps.py
#
# Tests for gap-filling additions:
#   - frank_lloyd/abandoner.py
#   - frank_lloyd/apply_summary._extract_all_new_file_paths
#   - frank_lloyd/job.FLJob.mode extraction

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


# ── Abandoner tests ───────────────────────────────────────────────────────────

class TestAbandonBuild(unittest.TestCase):
    """Tests for frank_lloyd/abandoner.py"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        td = pathlib.Path(self._td.name)
        import frank_lloyd.abandoner as ab
        ab._BUILD_LOG = td / "build_log.jsonl"
        self._ab = ab
        self._td_path = td

    def tearDown(self):
        self._td.cleanup()

    def _write_log(self, events: list[dict]) -> None:
        self._ab._BUILD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with self._ab._BUILD_LOG.open("w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

    def _make_ev(self, build_id: str, event: str) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "build_id":  build_id,
            "event":     event,
            "notes":     "",
            "extra":     {},
        }

    # ── basic success ─────────────────────────────────────────────────────────

    def test_abandon_pending_spec_succeeds(self):
        self._write_log([self._make_ev("BUILD-001", "request_queued")])
        r = self._ab.abandon_build("BUILD-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["outcome"], "abandoned")

    def test_abandon_pending_review_succeeds(self):
        self._write_log([
            self._make_ev("BUILD-001", "request_queued"),
            self._make_ev("BUILD-001", "spec_ready"),
        ])
        r = self._ab.abandon_build("BUILD-001")
        self.assertTrue(r["ok"])

    def test_abandon_writes_event_to_log(self):
        self._write_log([self._make_ev("BUILD-001", "request_queued")])
        self._ab.abandon_build("BUILD-001")
        lines = [
            json.loads(l) for l in self._ab._BUILD_LOG.read_text().splitlines() if l.strip()
        ]
        abandoned_events = [l for l in lines if l["event"] == "abandoned"]
        self.assertEqual(len(abandoned_events), 1)
        self.assertEqual(abandoned_events[0]["build_id"], "BUILD-001")

    def test_abandon_records_previous_state_in_extra(self):
        self._write_log([
            self._make_ev("BUILD-001", "request_queued"),
            self._make_ev("BUILD-001", "spec_ready"),
        ])
        self._ab.abandon_build("BUILD-001")
        lines = [json.loads(l) for l in self._ab._BUILD_LOG.read_text().splitlines() if l.strip()]
        ev = next(l for l in lines if l["event"] == "abandoned")
        self.assertEqual(ev["extra"]["abandoned_from"], "spec_ready")

    # ── terminal state protection ──────────────────────────────────────────────

    def test_abandon_already_abandoned_fails(self):
        self._write_log([
            self._make_ev("BUILD-001", "request_queued"),
            self._make_ev("BUILD-001", "abandoned"),
        ])
        r = self._ab.abandon_build("BUILD-001")
        self.assertFalse(r["ok"])
        self.assertIn("already", r["error"].lower())

    def test_abandon_draft_promoted_fails(self):
        self._write_log([
            self._make_ev("BUILD-001", "request_queued"),
            self._make_ev("BUILD-001", "draft_promoted"),
        ])
        r = self._ab.abandon_build("BUILD-001")
        self.assertFalse(r["ok"])

    def test_abandon_spec_rejected_fails(self):
        self._write_log([
            self._make_ev("BUILD-001", "request_queued"),
            self._make_ev("BUILD-001", "spec_rejected"),
        ])
        r = self._ab.abandon_build("BUILD-001")
        self.assertFalse(r["ok"])

    # ── not-found ─────────────────────────────────────────────────────────────

    def test_abandon_unknown_build_fails(self):
        self._write_log([self._make_ev("BUILD-001", "request_queued")])
        r = self._ab.abandon_build("BUILD-999")
        self.assertFalse(r["ok"])
        self.assertIn("not found", r["error"].lower())

    def test_abandon_missing_log_fails(self):
        r = self._ab.abandon_build("BUILD-001")
        self.assertFalse(r["ok"])

    # ── case insensitive ─────────────────────────────────────────────────────

    def test_abandon_case_insensitive(self):
        self._write_log([self._make_ev("BUILD-001", "request_queued")])
        r = self._ab.abandon_build("build-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["build_id"], "BUILD-001")

    # ── notes ────────────────────────────────────────────────────────────────

    def test_abandon_custom_notes(self):
        self._write_log([self._make_ev("BUILD-001", "request_queued")])
        self._ab.abandon_build("BUILD-001", notes="Operator cancelled — requirements changed.")
        lines = [json.loads(l) for l in self._ab._BUILD_LOG.read_text().splitlines() if l.strip()]
        ev = next(l for l in lines if l["event"] == "abandoned")
        self.assertIn("requirements changed", ev["notes"])


# ── apply_summary multi-file tests ───────────────────────────────────────────

class TestExtractAllNewFilePaths(unittest.TestCase):
    """Tests for apply_summary._extract_all_new_file_paths"""

    def setUp(self):
        from frank_lloyd.apply_summary import _extract_all_new_file_paths
        self._fn = _extract_all_new_file_paths

    def test_single_new_file(self):
        spec = (
            "affected_files:\n"
            "  new:\n"
            '    - path: "frank_lloyd/stats.py"\n'
            '      purpose: "stats"\n'
        )
        self.assertEqual(self._fn(spec), ["frank_lloyd/stats.py"])

    def test_multiple_new_files(self):
        spec = (
            "affected_files:\n"
            "  new:\n"
            '    - path: "frank_lloyd/stats.py"\n'
            '      purpose: "stats"\n'
            '    - path: "tests/test_stats.py"\n'
            '      purpose: "tests"\n'
        )
        result = self._fn(spec)
        self.assertEqual(len(result), 2)
        self.assertIn("frank_lloyd/stats.py", result)
        self.assertIn("tests/test_stats.py", result)

    def test_empty_new_section_returns_empty(self):
        spec = (
            "affected_files:\n"
            "  new:\n"
            "    []\n"
        )
        self.assertEqual(self._fn(spec), [])

    def test_no_affected_files_section_returns_empty(self):
        spec = "risk_level: low\nbuild_type: new_file\n"
        self.assertEqual(self._fn(spec), [])

    def test_stops_at_modified_section(self):
        spec = (
            "affected_files:\n"
            "  new:\n"
            '    - path: "frank_lloyd/a.py"\n'
            "  modified:\n"
            '    - path: "app/main.py"\n'
        )
        result = self._fn(spec)
        self.assertEqual(result, ["frank_lloyd/a.py"])
        self.assertNotIn("app/main.py", result)


# ── FLJob.mode extraction tests ───────────────────────────────────────────────

class TestFLJobMode(unittest.TestCase):
    """Tests for mode extraction in frank_lloyd/job.py"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        td = pathlib.Path(self._td.name)
        import frank_lloyd.job as jm
        jm._FL_BUILD_LOG = td / "build_log.jsonl"
        jm._FL_REQUESTS  = td / "requests"
        self._jm = jm
        self._td_path = td

    def tearDown(self):
        self._td.cleanup()

    def _write_log(self, events: list[dict]) -> None:
        self._jm._FL_BUILD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with self._jm._FL_BUILD_LOG.open("w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

    def _req_ev(self, build_id: str, source: str) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "build_id":  build_id,
            "event":     "request_queued",
            "notes":     f"Request queued by {source}: test",
            "extra":     {"title": "Test build", "source": source},
        }

    def test_mode_extracted_from_smart_queue_refactor(self):
        self._write_log([self._req_ev("BUILD-001", "smart_queue_refactor")])
        job = self._jm.load_job("BUILD-001")
        self.assertIsNotNone(job)
        self.assertEqual(job.mode, "refactor")

    def test_mode_extracted_from_smart_queue_diagnose(self):
        self._write_log([self._req_ev("BUILD-001", "smart_queue_diagnose")])
        job = self._jm.load_job("BUILD-001")
        self.assertEqual(job.mode, "diagnose")

    def test_mode_none_for_neighborhood_ui_source(self):
        self._write_log([self._req_ev("BUILD-001", "neighborhood_ui")])
        job = self._jm.load_job("BUILD-001")
        self.assertIsNone(job.mode)

    def test_mode_in_to_dict(self):
        self._write_log([self._req_ev("BUILD-001", "smart_queue_improve")])
        job = self._jm.load_job("BUILD-001")
        d = job.to_dict()
        self.assertEqual(d["mode"], "improve")

    def test_mode_none_in_to_dict_when_unset(self):
        self._write_log([self._req_ev("BUILD-001", "operator")])
        job = self._jm.load_job("BUILD-001")
        d = job.to_dict()
        self.assertIsNone(d["mode"])

    def test_all_modes_mapped(self):
        modes = ["build", "refactor", "cleanup", "diagnose", "improve", "monitor", "docs"]
        for mode in modes:
            with self.subTest(mode=mode):
                self._write_log([self._req_ev("BUILD-001", f"smart_queue_{mode}")])
                job = self._jm.load_job("BUILD-001")
                self.assertEqual(job.mode, mode, f"mode mismatch for smart_queue_{mode}")


if __name__ == "__main__":
    unittest.main()
