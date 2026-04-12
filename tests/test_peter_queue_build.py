# tests/test_peter_queue_build.py
#
# Tests for the POST /peter/queue-build endpoint.
#
# Coverage:
#   TestPeterQueueBuildValidation  — missing/vague description or criterion
#   TestPeterQueueBuildSuccess     — valid request queues through request_writer
#   TestPeterQueueBuildInlineCrit  — success criterion extracted from message body
#   TestPeterQueueBuildWriterError — propagates writer failure gracefully
#   TestPeterQueueBuildRoute       — endpoint is registered and reachable

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _call_endpoint(message: str) -> dict:
    """Call peter_queue_build() directly, bypassing HTTP layer."""
    from app.routes.neighborhood import peter_queue_build
    return peter_queue_build({"message": message})


# ── TestPeterQueueBuildValidation ─────────────────────────────────────────────

class TestPeterQueueBuildValidation(unittest.TestCase):

    def test_empty_message_not_queued(self):
        r = _call_endpoint("")
        self.assertFalse(r["ok"])
        self.assertFalse(r["queued"])

    def test_empty_message_text_present(self):
        r = _call_endpoint("")
        self.assertTrue(len(r["text"]) > 0)

    def test_vague_description_not_queued(self):
        r = _call_endpoint("fix it")
        self.assertFalse(r["queued"])

    def test_vague_description_text_mentions_vague(self):
        r = _call_endpoint("fix it")
        self.assertIn("vague", r["text"].lower())

    def test_missing_success_criterion_not_queued(self):
        r = _call_endpoint(
            "Add a new endpoint that returns the current portfolio snapshot in JSON"
        )
        self.assertFalse(r["queued"])

    def test_missing_success_criterion_text_mentions_criterion(self):
        r = _call_endpoint(
            "Add a new endpoint that returns the current portfolio snapshot in JSON"
        )
        self.assertIn("success criterion", r["text"].lower())

    def test_vague_criterion_not_queued(self):
        r = _call_endpoint(
            "Add a health endpoint that checks the database. success: it works"
        )
        self.assertFalse(r["queued"])

    def test_vague_criterion_text_mentions_short(self):
        r = _call_endpoint(
            "Add a health endpoint that checks the database. success: it works"
        )
        self.assertIn("short", r["text"].lower())

    def test_missing_fields_returned_in_response(self):
        r = _call_endpoint("fix it")
        self.assertIn("missing_fields", r)
        self.assertTrue(len(r["missing_fields"]) > 0)


# ── TestPeterQueueBuildSuccess ────────────────────────────────────────────────

class TestPeterQueueBuildSuccess(unittest.TestCase):

    def _make_ok_result(self, build_id="BUILD-007"):
        return {
            "ok": True, "build_id": build_id, "title": "health endpoint",
            "request_path": "/tmp/x", "error": None,
        }

    def test_valid_request_is_queued(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        with patch("frank_lloyd.request_writer.queue_build", return_value=self._make_ok_result()):
            r = _call_endpoint(msg)
        self.assertTrue(r["queued"])

    def test_valid_request_ok_true(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        with patch("frank_lloyd.request_writer.queue_build", return_value=self._make_ok_result()):
            r = _call_endpoint(msg)
        self.assertTrue(r["ok"])

    def test_valid_request_build_id_returned(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        with patch("frank_lloyd.request_writer.queue_build",
                   return_value=self._make_ok_result("BUILD-042")):
            r = _call_endpoint(msg)
        self.assertEqual(r["build_id"], "BUILD-042")

    def test_valid_request_text_contains_build_id(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        with patch("frank_lloyd.request_writer.queue_build",
                   return_value=self._make_ok_result("BUILD-042")):
            r = _call_endpoint(msg)
        self.assertIn("BUILD-042", r["text"])

    def test_valid_request_text_contains_frank_lloyd(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        with patch("frank_lloyd.request_writer.queue_build", return_value=self._make_ok_result()):
            r = _call_endpoint(msg)
        self.assertIn("Frank Lloyd", r["text"])

    def test_no_missing_fields_on_success(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        with patch("frank_lloyd.request_writer.queue_build", return_value=self._make_ok_result()):
            r = _call_endpoint(msg)
        self.assertEqual(r["missing_fields"], [])


# ── TestPeterQueueBuildInlineCrit ─────────────────────────────────────────────

class TestPeterQueueBuildInlineCrit(unittest.TestCase):
    """Success criterion embedded in the message body is extracted correctly."""

    def _ok(self):
        return {"ok": True, "build_id": "BUILD-001", "title": "test", "request_path": "/x", "error": None}

    def test_inline_success_marker_extracted(self):
        msg = (
            "Build a trade count endpoint for the portfolio module. "
            "success: GET /portfolio/trade-count returns 200 with integer count field"
        )
        with patch("frank_lloyd.request_writer.queue_build", return_value=self._ok()) as mock_qb:
            _call_endpoint(msg)
        _, kwargs = mock_qb.call_args
        self.assertIn("returns 200", kwargs.get("success_criterion", ""))

    def test_done_when_marker_extracted(self):
        msg = (
            "Add a reset endpoint to the portfolio module that clears trade history. "
            "done when: POST /portfolio/reset returns 200 and trade history is empty"
        )
        with patch("frank_lloyd.request_writer.queue_build", return_value=self._ok()) as mock_qb:
            _call_endpoint(msg)
        _, kwargs = mock_qb.call_args
        self.assertIn("returns 200", kwargs.get("success_criterion", ""))

    def test_source_is_peter_chat(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        with patch("frank_lloyd.request_writer.queue_build", return_value=self._ok()) as mock_qb:
            _call_endpoint(msg)
        _, kwargs = mock_qb.call_args
        self.assertEqual(kwargs.get("source"), "peter_chat")


# ── TestPeterQueueBuildWriterError ────────────────────────────────────────────

class TestPeterQueueBuildWriterError(unittest.TestCase):

    def test_writer_error_propagated(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        fail = {"ok": False, "build_id": None, "title": "", "request_path": None,
                "error": "disk full"}
        with patch("frank_lloyd.request_writer.queue_build", return_value=fail):
            r = _call_endpoint(msg)
        self.assertFalse(r["ok"])
        self.assertFalse(r["queued"])

    def test_writer_error_text_contains_error(self):
        msg = (
            "Add a GET /health endpoint that checks backend liveness. "
            "success: GET /health returns 200 with json body containing ok: true"
        )
        fail = {"ok": False, "build_id": None, "title": "", "request_path": None,
                "error": "disk full"}
        with patch("frank_lloyd.request_writer.queue_build", return_value=fail):
            r = _call_endpoint(msg)
        self.assertIn("disk full", r["text"])


# ── TestPeterQueueBuildRoute ──────────────────────────────────────────────────

class TestPeterQueueBuildRoute(unittest.TestCase):

    def test_endpoint_is_importable(self):
        from app.routes.neighborhood import peter_queue_build
        self.assertTrue(callable(peter_queue_build))

    def test_endpoint_registered_on_router(self):
        from app.routes.neighborhood import router
        paths = [r.path for r in router.routes]
        self.assertIn("/peter/queue-build", paths)


if __name__ == "__main__":
    unittest.main()
