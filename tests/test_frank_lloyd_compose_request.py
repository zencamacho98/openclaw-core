# tests/test_frank_lloyd_compose_request.py
#
# Tests for the POST /frank-lloyd/compose-request endpoint and
# frank_lloyd.request_writer module.
#
# Coverage:
#   TestRequestWriterReadinessCheck   — readiness_check() validation logic
#   TestRequestWriterExtractHelpers   — extract_success_criterion, extract_title
#   TestRequestWriterQueueBuild       — queue_build() file I/O (tmpdir isolated)
#   TestComposeEndpointValidation     — compose_request endpoint rejects bad input
#   TestComposeEndpointSuccess        — compose_request endpoint happy path

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import frank_lloyd.request_writer as rw


# ── TestRequestWriterReadinessCheck ─────────────────────────────────────────

class TestRequestWriterReadinessCheck(unittest.TestCase):

    def test_valid_clears_all(self):
        missing = rw.readiness_check(
            "Add a health endpoint that checks the database connection",
            "GET /health returns 200 with status ok",
        )
        self.assertEqual(missing, [])

    def test_short_description_flagged(self):
        missing = rw.readiness_check("fix it", "success: returns 200")
        self.assertIn("description_too_vague", missing)

    def test_vague_term_with_short_desc_flagged(self):
        missing = rw.readiness_check("make it better please", "success: works")
        self.assertIn("description_too_vague", missing)

    def test_five_word_description_passes(self):
        missing = rw.readiness_check(
            "Add retry logic to the client",
            "success: retries 3 times on failure",
        )
        self.assertNotIn("description_too_vague", missing)

    def test_vague_term_long_desc_passes(self):
        # 12+ words with a vague term embedded — should pass
        missing = rw.readiness_check(
            "improve the retry logic in the HTTP client to handle 503 errors gracefully",
            "success: 503 responses trigger retry and eventually return 200",
        )
        self.assertNotIn("description_too_vague", missing)

    def test_missing_success_criterion_flagged(self):
        missing = rw.readiness_check(
            "Add a health endpoint that checks the database connection", ""
        )
        self.assertIn("missing_success_criteria", missing)

    def test_short_success_criterion_flagged(self):
        missing = rw.readiness_check(
            "Add a health endpoint that checks the database connection",
            "it works",
        )
        self.assertIn("success_criteria_too_vague", missing)

    def test_four_word_criterion_passes(self):
        missing = rw.readiness_check(
            "Add a health endpoint that checks the database connection",
            "GET /health returns 200",
        )
        self.assertNotIn("success_criteria_too_vague", missing)

    def test_multiple_failures_returned(self):
        missing = rw.readiness_check("fix", "")
        self.assertIn("description_too_vague", missing)
        self.assertIn("missing_success_criteria", missing)


# ── TestRequestWriterExtractHelpers ──────────────────────────────────────────

class TestRequestWriterExtractHelpers(unittest.TestCase):

    def test_extract_success_criterion_colon_prefix(self):
        result = rw.extract_success_criterion(
            "Build a health endpoint. success: GET /health returns 200"
        )
        self.assertEqual(result, "GET /health returns 200")

    def test_extract_success_criterion_done_when(self):
        result = rw.extract_success_criterion(
            "Build something. done when: import succeeds"
        )
        self.assertEqual(result, "import succeeds")

    def test_extract_success_criterion_test_prefix(self):
        result = rw.extract_success_criterion(
            "Build a module. test: pytest passes"
        )
        self.assertEqual(result, "pytest passes")

    def test_extract_success_criterion_none(self):
        result = rw.extract_success_criterion("No criterion here.")
        self.assertEqual(result, "")

    def test_extract_title_meaningful_words(self):
        title = rw.extract_title("Add a new health endpoint that checks the database")
        # Should skip stopwords, at most 6 words
        self.assertLessEqual(len(title.split()), 6)
        self.assertIn("health", title.lower())

    def test_extract_title_skips_stopwords(self):
        title = rw.extract_title("A new module for the connection pool")
        self.assertNotIn(" a ", f" {title.lower()} ")
        self.assertNotIn(" the ", f" {title.lower()} ")

    def test_extract_title_short_desc(self):
        title = rw.extract_title("Build it")
        self.assertTrue(len(title) > 0)


# ── TestRequestWriterQueueBuild ──────────────────────────────────────────────

class TestRequestWriterQueueBuild(unittest.TestCase):

    def _queue(self, desc: str, crit: str, tmpdir: pathlib.Path) -> dict:
        requests_dir = tmpdir / "requests"
        build_log    = tmpdir / "build_log.jsonl"
        return rw.queue_build(
            description=desc,
            success_criterion=crit,
            source="test",
            requests_dir=requests_dir,
            build_log=build_log,
        )

    def test_queue_build_ok_true(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._queue(
                "Add a health endpoint that checks the DB",
                "GET /health returns 200",
                pathlib.Path(d),
            )
        self.assertTrue(r["ok"])

    def test_queue_build_returns_build_id(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._queue(
                "Add a health endpoint that checks the DB",
                "GET /health returns 200",
                pathlib.Path(d),
            )
        self.assertRegex(r["build_id"], r"^BUILD-\d+$")

    def test_queue_build_writes_request_file(self):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            r  = self._queue(
                "Add a health endpoint that checks the DB",
                "GET /health returns 200",
                dp,
            )
            req_path = pathlib.Path(r["request_path"])
            self.assertTrue(req_path.exists())

    def test_queue_build_request_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            r  = self._queue(
                "Add a health endpoint that checks the DB",
                "GET /health returns 200",
                dp,
            )
            data = json.loads(pathlib.Path(r["request_path"]).read_text())
            self.assertEqual(data["request_id"], r["build_id"])

    def test_queue_build_appends_log_event(self):
        with tempfile.TemporaryDirectory() as d:
            dp  = pathlib.Path(d)
            rw.queue_build(
                description="Add a health endpoint that checks the DB",
                success_criterion="GET /health returns 200",
                source="test",
                requests_dir=dp / "requests",
                build_log=dp / "build_log.jsonl",
            )
            log_path = dp / "build_log.jsonl"
            self.assertTrue(log_path.exists())
            events = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertEqual(events[0]["event"], "request_queued")

    def test_queue_build_sequential_ids(self):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            kwargs = dict(
                description="Add a health endpoint that checks the DB",
                success_criterion="GET /health returns 200",
                source="test",
                requests_dir=dp / "requests",
                build_log=dp / "build_log.jsonl",
            )
            r1 = rw.queue_build(**kwargs)
            r2 = rw.queue_build(**kwargs)
            n1 = int(r1["build_id"].split("-")[1])
            n2 = int(r2["build_id"].split("-")[1])
            self.assertEqual(n2, n1 + 1)

    def test_queue_build_error_field_none_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._queue(
                "Add a health endpoint that checks the DB",
                "GET /health returns 200",
                pathlib.Path(d),
            )
        self.assertIsNone(r["error"])


# ── TestComposeEndpointValidation ────────────────────────────────────────────

class TestComposeEndpointValidation(unittest.TestCase):
    """POST /frank-lloyd/compose-request validation via the action function directly."""

    def _compose(self, body: dict) -> dict:
        from app.routes.frank_lloyd_actions import compose_request
        return compose_request(body)

    def test_empty_description_returns_ok_false(self):
        r = self._compose({"description": "", "success_criterion": "success: works"})
        self.assertFalse(r["ok"])

    def test_vague_description_returns_ok_false(self):
        r = self._compose({"description": "fix it", "success_criterion": "success: it works"})
        self.assertFalse(r["ok"])
        self.assertIn("missing_fields", r)

    def test_missing_criterion_returns_ok_false(self):
        r = self._compose({
            "description": "Add a health endpoint that checks the database connection",
            "success_criterion": "",
        })
        self.assertFalse(r["ok"])
        self.assertIn("missing_success_criteria", r.get("missing_fields", []))

    def test_short_criterion_returns_ok_false(self):
        r = self._compose({
            "description": "Add a health endpoint that checks the database connection",
            "success_criterion": "it works",
        })
        self.assertFalse(r["ok"])

    def test_error_field_present_on_failure(self):
        r = self._compose({"description": "fix", "success_criterion": ""})
        self.assertIn("error", r)
        self.assertTrue(r["error"])


# ── TestComposeEndpointSuccess ───────────────────────────────────────────────

class TestComposeEndpointSuccess(unittest.TestCase):
    """POST /frank-lloyd/compose-request happy path (mocked file I/O)."""

    def _compose(self, body: dict) -> dict:
        from app.routes.frank_lloyd_actions import compose_request
        return compose_request(body)

    def test_valid_request_returns_ok_true(self):
        with patch("frank_lloyd.request_writer.queue_build", return_value={
            "ok": True, "build_id": "BUILD-001", "title": "health endpoint",
            "request_path": "/tmp/BUILD-001_request.json", "error": None,
        }):
            r = self._compose({
                "description": "Add a health endpoint that checks the database connection",
                "success_criterion": "GET /health returns 200 with status ok",
            })
        self.assertTrue(r["ok"])

    def test_valid_request_returns_build_id(self):
        with patch("frank_lloyd.request_writer.queue_build", return_value={
            "ok": True, "build_id": "BUILD-042", "title": "health endpoint",
            "request_path": "/tmp/BUILD-042_request.json", "error": None,
        }):
            r = self._compose({
                "description": "Add a health endpoint that checks the database connection",
                "success_criterion": "GET /health returns 200 with status ok",
            })
        self.assertEqual(r["build_id"], "BUILD-042")

    def test_valid_request_message_mentions_build_id(self):
        with patch("frank_lloyd.request_writer.queue_build", return_value={
            "ok": True, "build_id": "BUILD-001", "title": "health endpoint",
            "request_path": "/tmp/BUILD-001_request.json", "error": None,
        }):
            r = self._compose({
                "description": "Add a health endpoint that checks the database connection",
                "success_criterion": "GET /health returns 200 with status ok",
            })
        self.assertIn("BUILD-001", r.get("message", ""))

    def test_criterion_extracted_from_description(self):
        """If success_criterion is blank but embedded in description, it is extracted."""
        with patch("frank_lloyd.request_writer.queue_build", return_value={
            "ok": True, "build_id": "BUILD-001", "title": "health endpoint",
            "request_path": "/tmp/BUILD-001_request.json", "error": None,
        }) as mock_q:
            self._compose({
                "description": (
                    "Add a health endpoint that pings the DB. "
                    "success: GET /health returns 200 with status ok"
                ),
                "success_criterion": "",
            })
            call_kwargs = mock_q.call_args[1]
            self.assertEqual(call_kwargs["success_criterion"], "GET /health returns 200 with status ok")

    def test_queue_build_error_surfaces(self):
        with patch("frank_lloyd.request_writer.queue_build", return_value={
            "ok": False, "build_id": None,
            "title": "health endpoint",
            "request_path": None,
            "error": "Failed to write build request: permission denied",
        }):
            r = self._compose({
                "description": "Add a health endpoint that checks the database connection",
                "success_criterion": "GET /health returns 200 with status ok",
            })
        self.assertFalse(r["ok"])
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main()
