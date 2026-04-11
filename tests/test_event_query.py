"""
tests/test_event_query.py

Route tests for GET /events (BUILD-001).

Covers:
  - empty log returns 200 with empty events list
  - events returned newest-first
  - default limit is 20
  - limit param is respected and capped at 200
  - limit=0 and limit=201 return 422 (FastAPI validation)
  - agent filter returns only matching source
  - agent filter with no match returns empty list
  - severity filter returns only matching severity
  - invalid severity returns 400
  - since filter excludes events before the threshold
  - since boundary is inclusive
  - invalid since returns 400
  - response shape: events, count, total_matched, filters_applied, truncated
  - truncated=True when total_matched exceeds limit
  - truncated=False when results fit within limit
  - filters_applied reflects passed params
  - no severity filter returns all severity levels
  - combined agent + severity + since filters
  - events with unparseable timestamps are skipped, no crash

Run with:
    python -m pytest tests/test_event_query.py -v
    python -m unittest tests.test_event_query -v
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
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _make_event(
    event_type: str,
    source: str = "operator",
    severity: str = "important",
    timestamp: str = "2026-04-11T10:00:00+00:00",
    campaign_id: str | None = None,
) -> dict:
    return {
        "timestamp": timestamp,
        "severity": severity,
        "source": source,
        "event_type": event_type,
        "summary": f"Summary for {event_type}",
        "campaign_id": campaign_id,
        "extra": {},
    }


class TestEventQueryRoute(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_path = el._LOG_PATH
        el._LOG_PATH = pathlib.Path(self._tmpdir) / "event_log.jsonl"

    def tearDown(self):
        el._LOG_PATH = self._orig_path
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_events(self, events: list[dict]) -> None:
        with el._LOG_PATH.open("w", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e) + "\n")

    # ── basic ─────────────────────────────────────────────────────────────────

    def test_empty_log_returns_200_and_empty_list(self):
        resp = client.get("/events")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["events"], [])
        self.assertEqual(body["count"], 0)
        self.assertFalse(body["truncated"])

    def test_missing_log_file_returns_200_and_empty_list(self):
        # file was never created — _LOG_PATH does not exist
        self.assertFalse(el._LOG_PATH.exists())
        resp = client.get("/events")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["events"], [])

    def test_events_returned_newest_first(self):
        self._write_events([
            _make_event("first",  timestamp="2026-04-11T08:00:00+00:00"),
            _make_event("second", timestamp="2026-04-11T09:00:00+00:00"),
            _make_event("third",  timestamp="2026-04-11T10:00:00+00:00"),
        ])
        resp = client.get("/events?limit=10")
        self.assertEqual(resp.status_code, 200)
        types = [e["event_type"] for e in resp.json()["events"]]
        self.assertEqual(types, ["third", "second", "first"])

    # ── limit ─────────────────────────────────────────────────────────────────

    def test_default_limit_is_20(self):
        self._write_events([
            _make_event(f"ev_{i}", timestamp=f"2026-04-11T{i:02d}:00:00+00:00")
            for i in range(25)
        ])
        resp = client.get("/events")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["events"]), 20)

    def test_limit_param_respected(self):
        self._write_events([_make_event(f"ev_{i}") for i in range(10)])
        resp = client.get("/events?limit=3")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["events"]), 3)

    def test_limit_200_is_valid(self):
        resp = client.get("/events?limit=200")
        self.assertEqual(resp.status_code, 200)

    def test_limit_201_returns_422(self):
        resp = client.get("/events?limit=201")
        self.assertEqual(resp.status_code, 422)

    def test_limit_0_returns_422(self):
        resp = client.get("/events?limit=0")
        self.assertEqual(resp.status_code, 422)

    # ── agent filter ──────────────────────────────────────────────────────────

    def test_agent_filter_returns_only_matching_source(self):
        self._write_events([
            _make_event("belfort_ev", source="belfort"),
            _make_event("operator_ev", source="operator"),
            _make_event("belfort_ev2", source="belfort"),
        ])
        resp = client.get("/events?agent=belfort&limit=10")
        self.assertEqual(resp.status_code, 200)
        events = resp.json()["events"]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["source"] == "belfort" for e in events))

    def test_agent_filter_no_match_returns_empty(self):
        self._write_events([_make_event("ev", source="operator")])
        resp = client.get("/events?agent=nonexistent&limit=10")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["events"], [])

    # ── severity filter ───────────────────────────────────────────────────────

    def test_severity_filter_returns_only_matching_severity(self):
        self._write_events([
            _make_event("important_ev", severity="important"),
            _make_event("routine_ev",   severity="routine"),
            _make_event("action_ev",    severity="action_needed"),
        ])
        resp = client.get("/events?severity=routine&limit=10")
        self.assertEqual(resp.status_code, 200)
        events = resp.json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "routine")

    def test_invalid_severity_returns_400(self):
        resp = client.get("/events?severity=bogus_level")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("severity", resp.json()["detail"].lower())

    def test_no_severity_filter_returns_all_severities(self):
        self._write_events([
            _make_event("imp",    severity="important"),
            _make_event("rout",   severity="routine"),
            _make_event("action", severity="action_needed"),
            _make_event("dbg",    severity="debug"),
        ])
        resp = client.get("/events?limit=10")
        self.assertEqual(resp.status_code, 200)
        severities = {e["severity"] for e in resp.json()["events"]}
        self.assertIn("important",    severities)
        self.assertIn("routine",      severities)
        self.assertIn("action_needed", severities)
        self.assertIn("debug",        severities)

    # ── since filter ──────────────────────────────────────────────────────────

    def test_since_excludes_older_events(self):
        self._write_events([
            _make_event("old", timestamp="2026-04-10T00:00:00+00:00"),
            _make_event("new", timestamp="2026-04-11T12:00:00+00:00"),
        ])
        resp = client.get("/events?since=2026-04-11T00:00:00Z&limit=10")
        self.assertEqual(resp.status_code, 200)
        events = resp.json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "new")

    def test_since_is_inclusive(self):
        # Use Z suffix in the query param — '+' in a raw URL query string means space.
        # The event timestamp uses +00:00 format (as stored in the log); Z in the
        # query maps to the same instant and the boundary check is inclusive.
        self._write_events([_make_event("exact", timestamp="2026-04-11T10:00:00+00:00")])
        resp = client.get("/events?since=2026-04-11T10:00:00Z&limit=10")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["events"]), 1)

    def test_invalid_since_returns_400(self):
        resp = client.get("/events?since=not-a-date")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("since", resp.json()["detail"].lower())

    def test_since_with_z_suffix_accepted(self):
        self._write_events([_make_event("ev", timestamp="2026-04-11T12:00:00+00:00")])
        resp = client.get("/events?since=2026-04-11T00:00:00Z&limit=10")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["events"]), 1)

    # ── response shape ────────────────────────────────────────────────────────

    def test_response_has_all_required_fields(self):
        resp = client.get("/events")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("events", "count", "total_matched", "filters_applied", "truncated"):
            self.assertIn(key, body, f"Missing key: {key}")

    def test_truncated_true_when_results_exceed_limit(self):
        self._write_events([_make_event(f"ev_{i}") for i in range(10)])
        resp = client.get("/events?limit=3")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["truncated"])
        self.assertEqual(body["total_matched"], 10)
        self.assertEqual(body["count"], 3)

    def test_truncated_false_when_results_fit_within_limit(self):
        self._write_events([_make_event("only_one")])
        resp = client.get("/events?limit=20")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["truncated"])
        self.assertEqual(body["count"], body["total_matched"])

    def test_filters_applied_reflects_params(self):
        resp = client.get("/events?agent=belfort&severity=important&limit=5")
        self.assertEqual(resp.status_code, 200)
        fa = resp.json()["filters_applied"]
        self.assertEqual(fa["agent"],    "belfort")
        self.assertEqual(fa["severity"], "important")
        self.assertEqual(fa["limit"],    5)
        self.assertIsNone(fa["since"])

    def test_filters_applied_has_none_for_unset_params(self):
        resp = client.get("/events")
        self.assertEqual(resp.status_code, 200)
        fa = resp.json()["filters_applied"]
        self.assertIsNone(fa["agent"])
        self.assertIsNone(fa["severity"])
        self.assertIsNone(fa["since"])

    # ── combined filters ──────────────────────────────────────────────────────

    def test_agent_and_severity_combined(self):
        self._write_events([
            _make_event("belfort_important", source="belfort", severity="important"),
            _make_event("belfort_routine",   source="belfort", severity="routine"),
            _make_event("op_important",      source="operator", severity="important"),
        ])
        resp = client.get("/events?agent=belfort&severity=important&limit=10")
        self.assertEqual(resp.status_code, 200)
        events = resp.json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "belfort_important")

    def test_agent_and_since_combined(self):
        self._write_events([
            _make_event("belfort_old", source="belfort", timestamp="2026-04-10T00:00:00+00:00"),
            _make_event("belfort_new", source="belfort", timestamp="2026-04-11T12:00:00+00:00"),
            _make_event("op_new",      source="operator", timestamp="2026-04-11T12:00:00+00:00"),
        ])
        resp = client.get("/events?agent=belfort&since=2026-04-11T00:00:00Z&limit=10")
        self.assertEqual(resp.status_code, 200)
        events = resp.json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "belfort_new")

    # ── resilience ────────────────────────────────────────────────────────────

    def test_events_with_unparseable_since_timestamp_are_skipped(self):
        # Write one valid event and one with a bad timestamp
        el._LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with el._LOG_PATH.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_make_event("good", timestamp="2026-04-11T12:00:00+00:00")) + "\n")
            bad = _make_event("bad_ts")
            bad["timestamp"] = "NOT-A-TIMESTAMP"
            fh.write(json.dumps(bad) + "\n")
        # Should not crash; bad_ts event is skipped when since filter is active
        resp = client.get("/events?since=2026-04-11T00:00:00Z&limit=10")
        self.assertEqual(resp.status_code, 200)
        types = [e["event_type"] for e in resp.json()["events"]]
        self.assertIn("good", types)
        self.assertNotIn("bad_ts", types)


if __name__ == "__main__":
    unittest.main()
