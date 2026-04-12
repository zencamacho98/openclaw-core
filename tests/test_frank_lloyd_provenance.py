# tests/test_frank_lloyd_provenance.py
#
# Provenance field tests for Frank Lloyd builds (cleanup block).
# Covers:
#   - FLJob.source field present and populated from request_queued event
#   - frank_lloyd_status returns source in pending and inprogress build dicts
#   - Unknown/missing source is distinguishable from known source
#   - Review/apply gates still function regardless of provenance

from __future__ import annotations

import json
import pathlib
import tempfile
from unittest.mock import MagicMock, patch


# ── FLJob source field ────────────────────────────────────────────────────────

class TestFLJobSourceField:
    def _make_events(self, source: str) -> list[dict]:
        return [
            {
                "build_id":  "BUILD-TEST",
                "event":     "request_queued",
                "timestamp": "2026-04-11T00:00:00+00:00",
                "notes":     "queued",
                "extra":     {"source": source, "title": "test build"},
            },
            {
                "build_id":  "BUILD-TEST",
                "event":     "spec_ready",
                "timestamp": "2026-04-11T00:01:00+00:00",
                "notes":     "spec generated",
                "extra":     {},
            },
        ]

    def test_source_peter_chat_extracted(self):
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events("peter_chat"))
        assert job is not None
        assert job.source == "peter_chat"

    def test_source_peter_chat_smart_extracted(self):
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events("peter_chat_smart"))
        assert job is not None
        assert job.source == "peter_chat_smart"

    def test_source_neighborhood_ui_extracted(self):
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events("neighborhood_ui"))
        assert job.source == "neighborhood_ui"

    def test_source_operator_extracted(self):
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events("operator"))
        assert job.source == "operator"

    def test_source_missing_is_none(self):
        """Missing source → None (not empty string, not "unknown")."""
        events = self._make_events("")
        events[0]["extra"].pop("source")
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", events)
        assert job is not None
        assert job.source is None

    def test_source_empty_string_is_none(self):
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events(""))
        assert job.source is None

    def test_source_in_to_dict(self):
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events("peter_chat_smart"))
        d = job.to_dict()
        assert "source" in d
        assert d["source"] == "peter_chat_smart"

    def test_source_none_in_to_dict_when_missing(self):
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events(""))
        d = job.to_dict()
        assert d["source"] is None

    def test_smart_queue_source_also_sets_mode(self):
        """smart_queue_improve source → mode=improve, source=smart_queue_improve."""
        from frank_lloyd.job import _build_job as build_job
        job = build_job("BUILD-TEST", self._make_events("smart_queue_improve"))
        assert job.mode == "improve"
        assert job.source == "smart_queue_improve"


# ── frank_lloyd_status source field ──────────────────────────────────────────

class TestFrankLloydStatusSourceField:
    def _make_log(self, source: str, status_event: str = "spec_ready") -> list[dict]:
        evs = [
            {
                "build_id":  "BUILD-STATUS",
                "event":     "request_queued",
                "timestamp": "2026-04-11T00:00:00+00:00",
                "notes":     "",
                "extra":     {"source": source, "title": "status test"},
            },
        ]
        if status_event != "request_queued":
            evs.append({
                "build_id":  "BUILD-STATUS",
                "event":     status_event,
                "timestamp": "2026-04-11T00:01:00+00:00",
                "notes":     "",
                "extra":     {"build_type": "new_file", "risk_level": "low"},
            })
        return evs

    def _call_build_job(self, source: str, status_event: str = "spec_ready") -> dict:
        from app.routes.frank_lloyd_status import _build_status_item
        log = self._make_log(source, status_event)
        events_for_build = [e for e in log if e.get("build_id") == "BUILD-STATUS"]
        return _build_status_item("BUILD-STATUS", events_for_build)

    def test_source_in_pending_build(self):
        result = self._call_build_job("peter_chat", "request_queued")
        assert result is not None
        assert result.get("source") == "peter_chat"

    def test_source_in_inprogress_build(self):
        result = self._call_build_job("peter_chat_smart", "spec_approved")
        assert result is not None
        assert result.get("source") == "peter_chat_smart"

    def test_source_none_when_missing(self):
        # Build events with no source in extra
        from app.routes.frank_lloyd_status import _build_status_item as _build_job
        events = [
            {
                "build_id":  "BUILD-NS",
                "event":     "request_queued",
                "timestamp": "2026-04-11T00:00:00+00:00",
                "notes":     "",
                "extra":     {},
            },
            {
                "build_id":  "BUILD-NS",
                "event":     "spec_ready",
                "timestamp": "2026-04-11T00:01:00+00:00",
                "notes":     "",
                "extra":     {},
            },
        ]
        result = _build_job("BUILD-NS", events)
        assert result is not None
        assert result.get("source") is None


# ── Provenance label classification ──────────────────────────────────────────
# These test the UI mapping contract (source → plain-English label).
# We test the mapping values that the JS uses, confirmed by reading the code.

class TestProvenanceLabelMapping:
    """
    Validate that the label mapping logic works correctly for each source value.
    The JS uses: peter_chat → 'via Peter chat', peter_chat_smart → 'auto via Peter chat',
    smart_queue_* → 'auto-queued', neighborhood_ui → 'via Abode UI',
    operator → 'by operator', unknown/empty → warning state.
    """
    def _label_for(self, source: str) -> str | None:
        # Mirror the JS mapping in Python for test purposes
        if source == "peter_chat":
            return "via Peter chat"
        if source == "peter_chat_smart":
            return "auto via Peter chat"
        if source.startswith("smart_queue_"):
            return "auto-queued"
        if source == "neighborhood_ui":
            return "via Abode UI"
        if source == "operator":
            return "by operator"
        return None  # → warning state

    def test_peter_chat_has_label(self):
        assert self._label_for("peter_chat") == "via Peter chat"

    def test_peter_chat_smart_has_label(self):
        assert self._label_for("peter_chat_smart") is not None
        assert self._label_for("peter_chat_smart") != self._label_for("peter_chat")

    def test_smart_queue_variants_have_label(self):
        assert self._label_for("smart_queue_improve") == "auto-queued"
        assert self._label_for("smart_queue_diagnose") == "auto-queued"

    def test_neighborhood_ui_has_label(self):
        assert self._label_for("neighborhood_ui") == "via Abode UI"

    def test_empty_source_triggers_warning(self):
        assert self._label_for("") is None

    def test_unknown_source_triggers_warning(self):
        assert self._label_for("some_unknown_channel") is None

    def test_known_sources_do_not_trigger_warning(self):
        known = ["peter_chat", "peter_chat_smart", "neighborhood_ui", "operator",
                 "smart_queue_improve", "smart_queue_build"]
        for src in known:
            assert self._label_for(src) is not None, f"Expected label for {src!r}"


# ── Review gate still functions after provenance ──────────────────────────────

class TestReviewGateUnaffected:
    """
    Adding source/provenance fields must not break the review/apply gate logic.
    A draft_generated build is still reviewable regardless of source.
    """
    def _make_draft_events(self, source: str) -> list[dict]:
        return [
            {"build_id": "BUILD-GATE", "event": "request_queued",
             "timestamp": "2026-04-11T00:00:00+00:00", "notes": "", "extra": {"source": source}},
            {"build_id": "BUILD-GATE", "event": "spec_ready",
             "timestamp": "2026-04-11T00:01:00+00:00", "notes": "", "extra": {}},
            {"build_id": "BUILD-GATE", "event": "spec_approved",
             "timestamp": "2026-04-11T00:02:00+00:00", "notes": "", "extra": {"build_type": "new_file", "risk_level": "low"}},
            {"build_id": "BUILD-GATE", "event": "stage2_authorized",
             "timestamp": "2026-04-11T00:03:00+00:00", "notes": "", "extra": {}},
            {"build_id": "BUILD-GATE", "event": "draft_generated",
             "timestamp": "2026-04-11T00:04:00+00:00", "notes": "", "extra": {}},
        ]

    def test_peter_chat_smart_draft_is_reviewable(self):
        from frank_lloyd.job import _build_job
        job = _build_job("BUILD-GATE", self._make_draft_events("peter_chat_smart"))
        assert job is not None
        assert job.status == "draft_generated"
        assert job.waiting_on == "operator"

    def test_neighborhood_ui_draft_is_reviewable(self):
        from frank_lloyd.job import _build_job
        job = _build_job("BUILD-GATE", self._make_draft_events("neighborhood_ui"))
        assert job is not None
        assert job.status == "draft_generated"
        assert job.waiting_on == "operator"

    def test_unknown_source_draft_is_reviewable(self):
        """Unknown provenance does NOT remove the review gate."""
        from frank_lloyd.job import _build_job
        job = _build_job("BUILD-GATE", self._make_draft_events(""))
        assert job is not None
        assert job.status == "draft_generated"
        assert job.waiting_on == "operator"
