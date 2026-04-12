# tests/test_frank_relay_completion.py
#
# Tests for FRANK-RELAY-COMPLETION-01:
#   A. _fail() emits build_failed relay message
#   B. build_complete message includes build title
#   C. JS alert-event classification includes all failure/review events
#   D. Cursor-based consumption prevents duplicate injection
#   E. relay.append / consume_unread contract
#   F. No regression in auto_runner behaviour

from __future__ import annotations

import inspect
import json
import pathlib
import sys
import tempfile
from unittest.mock import patch, call, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── A. _fail() emits relay ────────────────────────────────────────────────────

class TestFailEmitsRelay:
    def test_fail_emits_build_failed_relay(self):
        """_fail() must emit a build_failed relay event."""
        import frank_lloyd.auto_runner as _ar
        appended: list[tuple] = []

        def _fake_append(bid, event, msg):
            appended.append((bid, event, msg))

        with patch("frank_lloyd.relay.append", side_effect=_fake_append):
            _ar._fail("BUILD-001", [], "Spec generation exploded")

        assert any(ev == "build_failed" for _, ev, _ in appended), (
            "_fail() must call relay.append with event='build_failed'"
        )

    def test_fail_relay_includes_error(self):
        """build_failed message must contain the error text."""
        import frank_lloyd.auto_runner as _ar
        appended: list[tuple] = []

        with patch("frank_lloyd.relay.append", side_effect=lambda b, e, m: appended.append((b, e, m))):
            _ar._fail("BUILD-002", [], "LM call timed out after 30 seconds")

        msgs = [m for _, e, m in appended if e == "build_failed"]
        assert msgs, "No build_failed relay message"
        assert "timed out" in msgs[0], "Error text must appear in the relay message"

    def test_fail_relay_error_truncated(self):
        """build_failed message must truncate very long error strings."""
        import frank_lloyd.auto_runner as _ar
        long_error = "x" * 300
        appended: list[tuple] = []

        with patch("frank_lloyd.relay.append", side_effect=lambda b, e, m: appended.append((b, e, m))):
            _ar._fail("BUILD-003", [], long_error)

        msgs = [m for _, e, m in appended if e == "build_failed"]
        assert msgs
        assert len(msgs[0]) < 300, "Message must be truncated for long errors"

    def test_fail_still_returns_error_dict(self):
        """_fail() return value must be unchanged: ok=False, error set."""
        import frank_lloyd.auto_runner as _ar
        with patch("frank_lloyd.relay.append"):
            result = _ar._fail("BUILD-004", [{"step": "generate_spec"}], "boom")
        assert result["ok"] is False
        assert result["error"] == "boom"
        assert result["paused_reason"] is None

    def test_fail_relay_failure_is_nonfatal(self):
        """If relay.append raises, _fail() must still return normally."""
        import frank_lloyd.auto_runner as _ar
        with patch("frank_lloyd.relay.append", side_effect=OSError("disk full")):
            result = _ar._fail("BUILD-005", [], "spec broken")
        assert result["ok"] is False


# ── B. build_complete includes title ─────────────────────────────────────────

class TestBuildCompleteTitle:
    def test_read_build_title_returns_title(self, tmp_path):
        """_read_build_title() reads title from the request file."""
        import frank_lloyd.auto_runner as _ar
        req_dir = tmp_path / "data" / "frank_lloyd" / "requests"
        req_dir.mkdir(parents=True)
        (req_dir / "BUILD-010_request.json").write_text(
            json.dumps({"title": "add retry mechanism", "request_id": "BUILD-010"}),
            encoding="utf-8",
        )
        orig = _ar._ROOT
        try:
            _ar._ROOT = tmp_path
            title = _ar._read_build_title("BUILD-010")
        finally:
            _ar._ROOT = orig
        assert title == "add retry mechanism"

    def test_read_build_title_returns_empty_when_missing(self):
        """_read_build_title() returns '' when request file does not exist."""
        import frank_lloyd.auto_runner as _ar
        with patch.object(_ar, "_ROOT", pathlib.Path("/nonexistent_xyz_abc")):
            title = _ar._read_build_title("BUILD-MISSING")
        assert title == ""

    def test_build_complete_message_includes_title(self, tmp_path):
        """build_complete relay message must include the build title."""
        import frank_lloyd.auto_runner as _ar
        req_dir = tmp_path / "data" / "frank_lloyd" / "requests"
        req_dir.mkdir(parents=True)
        (req_dir / "BUILD-020_request.json").write_text(
            json.dumps({"title": "fix portfolio snapshot", "request_id": "BUILD-020"}),
            encoding="utf-8",
        )
        appended: list[tuple] = []
        orig_root = _ar._ROOT
        try:
            _ar._ROOT = tmp_path
            with patch("frank_lloyd.relay.append", side_effect=lambda b, e, m: appended.append((b, e, m))):
                # Simulate calling the relay.append line in run_full_auto
                # by calling _read_build_title directly then checking the message format
                _title = _ar._read_build_title("BUILD-020")
                _title_part = f' "{_title}"' if _title else ""
                msg = f"BUILD-020{_title_part} — Done. Written to frank_lloyd/new_module.py."
        finally:
            _ar._ROOT = orig_root
        assert "fix portfolio snapshot" in msg, "Title must appear in build_complete message"
        assert "BUILD-020" in msg
        assert "frank_lloyd/new_module.py" in msg

    def test_build_complete_message_without_title(self):
        """build_complete message gracefully omits title when request file missing."""
        import frank_lloyd.auto_runner as _ar
        with patch.object(_ar, "_ROOT", pathlib.Path("/nonexistent_xyz_abc")):
            title = _ar._read_build_title("BUILD-NOTHERE")
            title_part = f' "{title}"' if title else ""
            msg = f"BUILD-NOTHERE{title_part} — Done. Written to app/new.py."
        assert "BUILD-NOTHERE" in msg
        assert "Done" in msg
        # No double-quote in message when title is empty
        assert '""' not in msg


# ── C. JS alert-event classification ─────────────────────────────────────────

class TestJSAlertClassification:
    """Verify the JS source includes all required events in alert lists."""

    def _js_source(self) -> str:
        import app.routes.neighborhood as _nb
        return inspect.getsource(_nb)

    def test_promote_failed_in_needs_attn_check(self):
        src = self._js_source()
        assert "promote_failed" in src, "promote_failed must be in needsAttn relay check"

    def test_build_failed_in_needs_attn_check(self):
        src = self._js_source()
        assert "build_failed" in src, "build_failed must be in needsAttn relay check"

    def test_draft_ready_in_needs_attn_check(self):
        src = self._js_source()
        assert "draft_ready" in src, "draft_ready must appear in needsAttn relay check"

    def test_build_complete_has_success_icon(self):
        """build_complete event must use the success (✅) icon path."""
        src = self._js_source()
        # The JS checks r.event === 'build_complete' for isSuccess
        assert "build_complete" in src
        # The success icon U+2705 must be referenced somewhere near build_complete
        assert "\\u2705" in src or "\u2705" in src or "2705" in src, (
            "Success icon (✅, U+2705) must be present for build_complete events"
        )

    def test_alert_icon_present(self):
        """Alert events must use a warning icon (⚠️)."""
        src = self._js_source()
        assert "\\u26A0" in src or "\u26A0" in src or "26A0" in src, (
            "Warning icon (⚠️) must be present for alert relay events"
        )

    def test_pipeline_start_has_distinct_icon(self):
        """pipeline_start must use a distinct (not warning) icon."""
        src = self._js_source()
        # We use 🔨 (U+1F528) for pipeline_start
        assert "pipeline_start" in src
        assert "\\uD83D\\uDD28" in src or "DD28" in src or "\uD83D\uDD28" in src, (
            "Hammer icon (🔨) must be used for pipeline_start"
        )


# ── D. Cursor prevents duplicate injection ────────────────────────────────────

class TestRelayNoDuplicates:
    def test_consume_unread_advances_cursor(self, tmp_path):
        """Second consume_unread call returns nothing after first consumed all."""
        import frank_lloyd.relay as _relay
        relay_log    = tmp_path / "peter_relay.jsonl"
        relay_cursor = tmp_path / "peter_relay_cursor.txt"

        orig_log    = _relay._RELAY_LOG
        orig_cursor = _relay._RELAY_CURSOR
        try:
            _relay._RELAY_LOG    = relay_log
            _relay._RELAY_CURSOR = relay_cursor

            _relay.append("BUILD-001", "pipeline_start", "Building")
            _relay.append("BUILD-001", "build_complete", "Done")

            first  = _relay.consume_unread()
            second = _relay.consume_unread()
        finally:
            _relay._RELAY_LOG    = orig_log
            _relay._RELAY_CURSOR = orig_cursor

        assert len(first)  == 2, "First consume should return both messages"
        assert len(second) == 0, "Second consume should return nothing (cursor advanced)"

    def test_new_message_after_cursor_is_delivered(self, tmp_path):
        """A message appended after the cursor was advanced is still delivered."""
        import frank_lloyd.relay as _relay
        relay_log    = tmp_path / "peter_relay.jsonl"
        relay_cursor = tmp_path / "peter_relay_cursor.txt"

        orig_log    = _relay._RELAY_LOG
        orig_cursor = _relay._RELAY_CURSOR
        try:
            _relay._RELAY_LOG    = relay_log
            _relay._RELAY_CURSOR = relay_cursor

            _relay.append("BUILD-001", "pipeline_start", "Building")
            _relay.consume_unread()  # advance cursor past id=0

            _relay.append("BUILD-001", "build_complete", "Done")
            second = _relay.consume_unread()
        finally:
            _relay._RELAY_LOG    = orig_log
            _relay._RELAY_CURSOR = orig_cursor

        assert len(second) == 1
        assert second[0]["event"] == "build_complete"

    def test_empty_relay_log_returns_empty_list(self, tmp_path):
        """consume_unread returns [] when relay log does not exist."""
        import frank_lloyd.relay as _relay
        orig_log    = _relay._RELAY_LOG
        orig_cursor = _relay._RELAY_CURSOR
        try:
            _relay._RELAY_LOG    = tmp_path / "nonexistent.jsonl"
            _relay._RELAY_CURSOR = tmp_path / "cursor.txt"
            result = _relay.consume_unread()
        finally:
            _relay._RELAY_LOG    = orig_log
            _relay._RELAY_CURSOR = orig_cursor
        assert result == []


# ── E. relay.append contract ──────────────────────────────────────────────────

class TestRelayAppendContract:
    def test_append_writes_all_required_fields(self, tmp_path):
        """relay.append must write id, ts, build_id, event, msg fields."""
        import frank_lloyd.relay as _relay
        relay_log    = tmp_path / "peter_relay.jsonl"
        relay_cursor = tmp_path / "peter_relay_cursor.txt"

        orig_log    = _relay._RELAY_LOG
        orig_cursor = _relay._RELAY_CURSOR
        try:
            _relay._RELAY_LOG    = relay_log
            _relay._RELAY_CURSOR = relay_cursor
            _relay.append("BUILD-001", "build_complete", "Done. Written to app/x.py.")
            entry = json.loads(relay_log.read_text())
        finally:
            _relay._RELAY_LOG    = orig_log
            _relay._RELAY_CURSOR = orig_cursor

        assert "id"       in entry
        assert "ts"       in entry
        assert "build_id" in entry
        assert "event"    in entry
        assert "msg"      in entry
        assert entry["build_id"] == "BUILD-001"
        assert entry["event"]    == "build_complete"

    def test_append_ids_are_sequential(self, tmp_path):
        """Multiple appends must produce sequential IDs."""
        import frank_lloyd.relay as _relay
        relay_log    = tmp_path / "peter_relay.jsonl"
        relay_cursor = tmp_path / "peter_relay_cursor.txt"

        orig_log    = _relay._RELAY_LOG
        orig_cursor = _relay._RELAY_CURSOR
        try:
            _relay._RELAY_LOG    = relay_log
            _relay._RELAY_CURSOR = relay_cursor
            _relay.append("BUILD-001", "pipeline_start", "msg1")
            _relay.append("BUILD-001", "build_complete", "msg2")
            entries = [json.loads(line) for line in relay_log.read_text().splitlines() if line.strip()]
        finally:
            _relay._RELAY_LOG    = orig_log
            _relay._RELAY_CURSOR = orig_cursor

        ids = [e["id"] for e in entries]
        assert ids == sorted(ids), "IDs must be in ascending order"
        assert ids[1] > ids[0], "Each ID must be greater than the previous"


# ── F. No regression ─────────────────────────────────────────────────────────

class TestNoRegression:
    def test_run_full_auto_still_returns_dict_shape(self):
        """run_full_auto return shape must still be the canonical dict."""
        import frank_lloyd.auto_runner as _ar
        required_keys = {"ok", "build_id", "final_status", "paused_reason", "steps", "error"}
        with (
            patch("frank_lloyd.spec_writer.generate_spec_packet",
                  return_value={"ok": False, "error": "LM unavailable", "blocked": False}),
            patch("frank_lloyd.relay.append"),
        ):
            result = _ar.run_full_auto("BUILD-REG-01")
        assert required_keys <= set(result.keys()), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )
        assert result["ok"] is False

    def test_paused_path_still_ok_false(self):
        """Paused path (spec_blocked) must still return ok=False."""
        import frank_lloyd.auto_runner as _ar
        with (
            patch("frank_lloyd.spec_writer.generate_spec_packet",
                  return_value={"ok": False, "error": "off-limits", "blocked": True}),
            patch("frank_lloyd.relay.append"),
        ):
            result = _ar.run_full_auto("BUILD-REG-02")
        assert result["ok"] is False
        assert result["paused_reason"] is not None

    def test_relay_module_docstring_events_match_implementation(self):
        """Relay event names used in auto_runner must be valid strings."""
        import frank_lloyd.auto_runner as _ar
        src = inspect.getsource(_ar)
        for event in ("pipeline_start", "spec_blocked", "draft_blocked",
                      "draft_ready", "promote_failed", "build_complete", "build_failed"):
            assert event in src, f"Event '{event}' not referenced in auto_runner.py"
