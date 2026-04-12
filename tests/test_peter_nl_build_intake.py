# tests/test_peter_nl_build_intake.py
#
# Tests for Peter natural-language Frank Lloyd build intake.
#
# Coverage:
#   TestNLParsePhrases      — all NL patterns route to BUILD_INTENT with nl_intake=True
#   TestNLParseExtraction   — extracted description has preamble stripped
#   TestNLParseNegative     — non-NL phrases do not match
#   TestNLHandlerResponse   — conversational success/clarification text when nl_intake=True
#   TestNLClarification     — vague NL requests get conversational clarification, not CLI text

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import CommandType, parse_command
from peter.handlers import handle_build_intent


# ── TestNLParsePhrases ───────────────────────────────────────────────────────

class TestNLParsePhrases(unittest.TestCase):
    """All recognised NL patterns route to BUILD_INTENT with nl_intake=True."""

    def _parse(self, text: str):
        return parse_command(text)

    def _assert_nl(self, text: str):
        cmd = self._parse(text)
        self.assertEqual(cmd.type, CommandType.BUILD_INTENT, f"Expected BUILD_INTENT for: {text!r}")
        self.assertTrue(cmd.args.get("nl_intake"), f"Expected nl_intake=True for: {text!r}")

    def test_have_frank_lloyd_build(self):
        self._assert_nl("have frank lloyd build a new health endpoint")

    def test_can_frank_lloyd_make(self):
        self._assert_nl("can frank lloyd make a rate-limit middleware")

    def test_ask_frank_lloyd_to_create(self):
        self._assert_nl("ask frank lloyd to create a cache module")

    def test_let_frank_lloyd_add(self):
        self._assert_nl("let frank lloyd add a new route for metrics")

    def test_get_frank_lloyd_to_write(self):
        self._assert_nl("get frank lloyd to write a helper for date parsing")

    def test_tell_frank_lloyd_to_implement(self):
        self._assert_nl("tell frank lloyd to implement a retry wrapper")

    def test_i_want_frank_lloyd_to_build(self):
        self._assert_nl("i want frank lloyd to build a notification module")

    def test_i_need_frank_lloyd_to_make(self):
        self._assert_nl("i need frank lloyd to make a CSV exporter")

    def test_id_like_frank_lloyd_to_create(self):
        self._assert_nl("i'd like frank lloyd to create a new utility")

    def test_frank_lloyd_comma_please_build(self):
        self._assert_nl("frank lloyd, please build a logging helper")

    def test_frank_lloyd_should_build(self):
        self._assert_nl("frank lloyd should build a config loader")

    def test_frank_lloyd_should_also_add(self):
        self._assert_nl("frank lloyd should also add a feature flag check")

    def test_have_frank_lloyd_develop(self):
        self._assert_nl("have frank lloyd develop a webhook dispatcher")

    def test_have_frank_lloyd_generate(self):
        self._assert_nl("have frank lloyd generate a boilerplate client")

    def test_have_franklloyd_nospace(self):
        self._assert_nl("have franklloyd build a stats aggregator")

    def test_case_insensitive_frank_lloyd(self):
        self._assert_nl("Have Frank Lloyd Build a summary reporter")

    def test_case_insensitive_all_caps(self):
        self._assert_nl("HAVE FRANK LLOYD BUILD an audit trail module")


# ── TestNLParseExtraction ────────────────────────────────────────────────────

class TestNLParseExtraction(unittest.TestCase):
    """The extracted raw_request strips the NL preamble."""

    def _raw(self, text: str) -> str:
        return parse_command(text).args["raw_request"]

    def test_have_frank_lloyd_build_extracts_remainder(self):
        raw = self._raw("have frank lloyd build a health endpoint")
        self.assertNotIn("frank lloyd", raw.lower())
        self.assertIn("health endpoint", raw)

    def test_i_want_frank_lloyd_to_build_extracts(self):
        raw = self._raw("i want frank lloyd to build a rate limiter")
        self.assertNotIn("frank lloyd", raw.lower())
        self.assertIn("rate limiter", raw)

    def test_tell_frank_lloyd_extracts_action(self):
        raw = self._raw("tell frank lloyd to implement a retry wrapper")
        self.assertNotIn("frank lloyd", raw.lower())
        self.assertIn("retry wrapper", raw)

    def test_frank_lloyd_comma_build_extracts(self):
        raw = self._raw("frank lloyd, please build a logging helper")
        self.assertNotIn("frank lloyd", raw.lower())
        self.assertIn("logging helper", raw)


# ── TestNLParseNegative ──────────────────────────────────────────────────────

class TestNLParseNegative(unittest.TestCase):
    """Phrases that should NOT route to NL intake."""

    def _type(self, text: str):
        return parse_command(text).type

    def test_plain_build_is_not_nl(self):
        # "build X" (no frank lloyd preamble) routes through standard BUILD_INTENT
        cmd = parse_command("build a new endpoint")
        self.assertEqual(cmd.type, CommandType.BUILD_INTENT)
        self.assertFalse(cmd.args.get("nl_intake"))

    def test_status_not_nl(self):
        self.assertNotEqual(self._type("status"), CommandType.BUILD_INTENT)

    def test_help_not_nl(self):
        self.assertNotEqual(self._type("help"), CommandType.BUILD_INTENT)

    def test_approve_not_nl(self):
        self.assertNotEqual(self._type("approve BUILD-001"), CommandType.BUILD_INTENT)

    def test_frank_lloyd_status_not_nl(self):
        # "frank lloyd status" is not a build intent
        cmd = parse_command("frank lloyd status")
        self.assertNotEqual(cmd.type, CommandType.BUILD_INTENT)


# ── TestNLHandlerResponse ────────────────────────────────────────────────────

class TestNLHandlerResponse(unittest.TestCase):
    """Conversational (nl_intake=True) success response uses natural language."""

    def _cmd(self, raw: str, nl: bool = True):
        from peter.commands import Command
        return Command(
            type        = CommandType.BUILD_INTENT,
            args        = {"raw_request": raw, "nl_intake": nl},
            transport   = "cli",
            operator_id = "test",
            raw_text    = raw,
        )

    def _ok_response(self, raw: str, nl: bool = True):
        cmd = self._cmd(raw, nl)
        with patch("peter.handlers._fl_write_request", return_value=pathlib.Path("/tmp/fake.json")), \
             patch("peter.handlers._fl_append_log_event"):
            return handle_build_intent(cmd)

    def test_nl_success_ok_true(self):
        r = self._ok_response(
            "a health endpoint that pings the DB. success: GET /health returns 200 with {status: ok}"
        )
        self.assertTrue(r.ok)

    def test_nl_success_summary_conversational(self):
        r = self._ok_response(
            "a health endpoint that pings the DB. success: GET /health returns 200 with {status: ok}"
        )
        # Should say "Got it" or similar — not "Frank Lloyd has received the request"
        self.assertIn("Got it", r.summary)

    def test_nl_success_mentions_build_id(self):
        r = self._ok_response(
            "a metrics aggregator module with per-symbol reporting. success: import works and aggregate() returns a dict"
        )
        self.assertRegex(r.summary, r"BUILD-\d+")

    def test_non_nl_success_summary_different(self):
        r = self._ok_response(
            "build a metrics aggregator module with per-symbol reporting. success: import works and aggregate() returns a dict",
            nl=False,
        )
        self.assertTrue(r.ok)
        # Non-NL text should say "Frank Lloyd has received" not "Got it"
        self.assertNotIn("Got it", r.summary)


# ── TestNLClarification ──────────────────────────────────────────────────────

class TestNLClarification(unittest.TestCase):
    """Vague NL requests get a conversational clarification response."""

    def _cmd(self, raw: str, nl: bool = True):
        from peter.commands import Command
        return Command(
            type        = CommandType.BUILD_INTENT,
            args        = {"raw_request": raw, "nl_intake": nl},
            transport   = "cli",
            operator_id = "test",
            raw_text    = raw,
        )

    def test_vague_nl_returns_ok_false(self):
        cmd = self._cmd("something")
        r   = handle_build_intent(cmd)
        self.assertFalse(r.ok)

    def test_vague_nl_summary_says_happy_to_queue(self):
        cmd = self._cmd("something")
        r   = handle_build_intent(cmd)
        self.assertIn("Happy to queue", r.summary)

    def test_vague_nl_does_not_say_not_clear_enough(self):
        cmd = self._cmd("something")
        r   = handle_build_intent(cmd)
        self.assertNotIn("Not clear enough", r.summary)

    def test_vague_nl_next_action_conversational(self):
        cmd = self._cmd("something")
        r   = handle_build_intent(cmd)
        self.assertIn("queue", r.next_action.lower())

    def test_vague_cli_says_not_clear_enough(self):
        cmd = self._cmd("something", nl=False)
        r   = handle_build_intent(cmd)
        self.assertFalse(r.ok)
        self.assertIn("Not clear enough", r.summary)

    def test_missing_criterion_nl_asks_conversationally(self):
        cmd = self._cmd(
            "build a rate limiting module that checks API requests per minute"
        )
        r = handle_build_intent(cmd)
        self.assertFalse(r.ok)
        # NL mode: conversational ask, not CLI-style prompt
        self.assertIn("Happy to queue", r.summary)

    def test_missing_criterion_nl_summary_not_cli_style(self):
        cmd = self._cmd(
            "build a rate limiting module that checks API requests per minute"
        )
        r = handle_build_intent(cmd)
        self.assertNotIn('What does "done" look like?', r.summary)


if __name__ == "__main__":
    unittest.main()
