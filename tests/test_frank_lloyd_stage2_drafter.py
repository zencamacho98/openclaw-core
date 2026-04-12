# tests/test_frank_lloyd_stage2_drafter.py
#
# Unit tests for frank_lloyd/stage2_drafter.py
#
# Coverage:
#   generate_stage2_draft():
#     - success: draft_generated, correct artifacts written, events logged
#     - wrong state (each non-stage2_authorized state) → no events, error
#     - missing authorization file → no events, error
#     - missing decision.json → no events, error
#     - missing spec.yaml → no events, error
#     - idempotency: draft_manifest.json already present → no events, error
#     - non-executable lane (config_only: CODE_DRAFT_MEDIUM) → draft_blocked, no started
#     - non-executable lane (external_supervised: CODE_DRAFT_CRITICAL) → draft_blocked, no started
#     - LM call fails → started + blocked events
#     - LM output not valid JSON → started + blocked events
#     - LM returns empty module_code → started + blocked events
#     - staging artifacts: draft_manifest.json fields, draft_module.py, draft_notes.md
#     - routing metadata: CODE_DRAFT_LOW → cheap tier, openrouter, executable
#     - staging path is under staging/, never the live repo

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import frank_lloyd.stage2_drafter as _mod
from frank_lloyd.provider_router import FLTaskClass, FLProviderTier


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ev(build_id: str, event: str) -> dict:
    return {"timestamp": _ts(), "build_id": build_id, "event": event,
            "notes": "", "extra": {}}


def _lm_ok(module_code: str = "# generated\ndef run(): pass\n",
           notes: str = "Draft notes here.") -> SimpleNamespace:
    """Mock LMResult for a successful LM call."""
    return SimpleNamespace(
        ok=True,
        content=json.dumps({"module_code": module_code, "notes": notes}),
        model_used="openai/gpt-4o-mini",
        input_tokens=120,
        output_tokens=80,
        cost_usd=0.00005,
        error="",
    )


def _lm_fail(error: str = "API key missing") -> SimpleNamespace:
    """Mock LMResult for a failed LM call."""
    return SimpleNamespace(
        ok=False, content="", model_used="", input_tokens=0, output_tokens=0,
        cost_usd=0.0, error=error,
    )


class _Env:
    """Redirect module path constants to a temp tree."""

    def __init__(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())

    @property
    def build_log(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "build_log.jsonl"

    @property
    def archives(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "archives"

    @property
    def staging(self) -> pathlib.Path:
        return self._tmp / "staging" / "frank_lloyd"

    def patch(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.archives.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self._orig = {
            "log":  _mod._FL_BUILD_LOG,
            "arch": _mod._FL_ARCHIVES,
            "stg":  _mod._FL_STAGING,
        }
        _mod._FL_BUILD_LOG = self.build_log
        _mod._FL_ARCHIVES  = self.archives
        _mod._FL_STAGING   = self.staging

    def restore(self):
        _mod._FL_BUILD_LOG = self._orig["log"]
        _mod._FL_ARCHIVES  = self._orig["arch"]
        _mod._FL_STAGING   = self._orig["stg"]

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_events(self, *events: dict):
        with self.build_log.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def read_events(self, build_id: str | None = None) -> list[dict]:
        if not self.build_log.exists():
            return []
        out = []
        for line in self.build_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if build_id is None or ev.get("build_id") == build_id:
                    out.append(ev)
            except (json.JSONDecodeError, ValueError):
                pass
        return out

    def write_decision(self, build_id: str, outcome: str = "spec_approved"):
        arch = self.archives / build_id
        arch.mkdir(parents=True, exist_ok=True)
        decision = {
            "build_id": build_id, "outcome": outcome, "stage": 1,
            "decided_at": _ts(), "decided_by": "operator",
            "notes": None, "stage2_authorized": False,
        }
        (arch / "decision.json").write_text(json.dumps(decision), encoding="utf-8")

    def write_spec(self, build_id: str, content: str | None = None):
        arch = self.archives / build_id
        arch.mkdir(parents=True, exist_ok=True)
        spec_text = content or (
            f"build_id: {build_id}\n"
            "build_type: platform_capability\n"
            "risk_level: low\n"
            "title: Test Build\n"
        )
        (arch / "spec.yaml").write_text(spec_text, encoding="utf-8")

    def write_auth(self, build_id: str):
        arch = self.archives / build_id
        arch.mkdir(parents=True, exist_ok=True)
        auth = {
            "build_id": build_id, "stage": 2, "authorized_at": _ts(),
            "authorized_by": "operator", "authorization_notes": None,
            "stage1_decision_outcome": "spec_approved",
            "provider_readiness": {
                "executable_lanes": ["cheap", "strong", "critical_only"],
                "config_only_lanes": ["coding"],
                "external_supervised_lanes": ["codex_supervised"],
            },
        }
        (arch / "stage2_authorization.json").write_text(json.dumps(auth), encoding="utf-8")

    def make_stage2_authorized(self, build_id: str):
        """Write full fixture for a build in stage2_authorized state."""
        self.write_events(
            _ev(build_id, "request_queued"),
            _ev(build_id, "spec_ready"),
            _ev(build_id, "spec_approved"),
            _ev(build_id, "stage2_authorized"),
        )
        self.write_decision(build_id)
        self.write_spec(build_id)
        self.write_auth(build_id)

    def get_stage2_staging(self, build_id: str) -> pathlib.Path:
        return self.staging / build_id / "stage2"


# ── Tests: success path ───────────────────────────────────────────────────────

class TestDraftGenerationSuccess(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_success_returns_ok(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("BUILD-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["build_id"], "BUILD-001")
        self.assertIsNone(result["error"])

    def test_success_returns_staging_path(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("BUILD-001")
        self.assertIsNotNone(result["staging_path"])
        self.assertIn("BUILD-001", result["staging_path"])
        self.assertIn("stage2",   result["staging_path"])

    def test_success_staging_path_not_live_repo(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("BUILD-001")
        # staging path must be inside staging/, not in the live source tree
        self.assertIn("staging", result["staging_path"])
        self.assertNotIn("frank_lloyd/spec", result["staging_path"])

    def test_success_files_generated_list(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("BUILD-001")
        self.assertIn("draft_manifest.json", result["files_generated"])
        self.assertIn("draft_module.py",     result["files_generated"])
        self.assertIn("draft_notes.md",      result["files_generated"])

    def test_draft_module_py_written(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok("def hello(): return 42")):
            _mod.generate_stage2_draft("BUILD-001")
        module_path = self._env.get_stage2_staging("BUILD-001") / "draft_module.py"
        self.assertTrue(module_path.exists())
        content = module_path.read_text(encoding="utf-8")
        self.assertIn("def hello", content)

    def test_draft_notes_md_written(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok(notes="Generated a stub.")):
            _mod.generate_stage2_draft("BUILD-001")
        notes_path = self._env.get_stage2_staging("BUILD-001") / "draft_notes.md"
        self.assertTrue(notes_path.exists())
        self.assertIn("Generated a stub.", notes_path.read_text(encoding="utf-8"))

    def test_draft_manifest_written_with_correct_fields(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("BUILD-001")
        manifest = json.loads(
            (self._env.get_stage2_staging("BUILD-001") / "draft_manifest.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["build_id"],        "BUILD-001")
        self.assertEqual(manifest["stage"],           2)
        self.assertEqual(manifest["task_class"],      "code_draft_low")
        self.assertEqual(manifest["provider_tier"],   "cheap")
        self.assertEqual(manifest["provider_family"], "openrouter")
        self.assertIn("model_used",      manifest)
        self.assertIn("generated_at",    manifest)
        self.assertEqual(manifest["generated_by"], "frank_lloyd")
        self.assertIn("draft_module.py", manifest["files_generated"])
        self.assertEqual(manifest["status"], "draft_generated")

    def test_routing_metadata_in_result(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("BUILD-001")
        routing = result["routing"]
        self.assertEqual(routing["task_class"],      "code_draft_low")
        self.assertEqual(routing["provider_tier"],   "cheap")
        self.assertEqual(routing["provider_family"], "openrouter")
        self.assertEqual(routing["executability"],   "executable")

    def test_model_is_openrouter_cheap(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("BUILD-001")
        # cheap tier default: openai/gpt-4o-mini (or env override, but not Claude)
        model = result["routing"]["model"]
        self.assertNotIn("claude", model.lower())
        self.assertNotIn("anthropic", model.lower())

    def test_build_id_uppercased(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            result = _mod.generate_stage2_draft("build-001")
        self.assertEqual(result["build_id"], "BUILD-001")


# ── Tests: draft_generated log event ─────────────────────────────────────────

class TestDraftGeneratedLogEvent(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_draft_generation_started_event_logged(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            _mod.generate_stage2_draft("BUILD-001")
        events = self._env.read_events("BUILD-001")
        started = [e for e in events if e["event"] == "draft_generation_started"]
        self.assertEqual(len(started), 1)

    def test_draft_generated_event_logged_on_success(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            _mod.generate_stage2_draft("BUILD-001")
        events = self._env.read_events("BUILD-001")
        generated = [e for e in events if e["event"] == "draft_generated"]
        self.assertEqual(len(generated), 1)

    def test_draft_generated_event_contains_model_and_files(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            _mod.generate_stage2_draft("BUILD-001")
        events = self._env.read_events("BUILD-001")
        gen_ev = next(e for e in events if e["event"] == "draft_generated")
        extra = gen_ev["extra"]
        self.assertIn("task_class",      extra)
        self.assertIn("provider_tier",   extra)
        self.assertIn("files_generated", extra)
        self.assertIn("staging_path",    extra)

    def test_success_event_order(self):
        """draft_generation_started must precede draft_generated."""
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_ok()):
            _mod.generate_stage2_draft("BUILD-001")
        events = self._env.read_events("BUILD-001")
        draft_events = [e for e in events
                        if e["event"] in ("draft_generation_started", "draft_generated")]
        self.assertEqual(len(draft_events), 2)
        self.assertEqual(draft_events[0]["event"], "draft_generation_started")
        self.assertEqual(draft_events[1]["event"], "draft_generated")


# ── Tests: wrong-state validation (no events logged) ─────────────────────────

class TestDraftGenerationWrongState(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def _event_count(self, build_id: str) -> int:
        return len(self._env.read_events(build_id))

    def test_unknown_build_returns_error(self):
        result = _mod.generate_stage2_draft("BUILD-999")
        self.assertFalse(result["ok"])
        self.assertIn("BUILD-999", result["error"])

    def test_unknown_build_no_events_logged(self):
        initial = self._event_count("BUILD-999")
        _mod.generate_stage2_draft("BUILD-999")
        self.assertEqual(self._event_count("BUILD-999"), initial)

    def test_pending_spec_returns_error_no_events(self):
        self._env.write_events(_ev("BUILD-001", "request_queued"))
        before = self._event_count("BUILD-001")
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("pending_spec", result["error"])
        self.assertEqual(self._event_count("BUILD-001"), before)

    def test_pending_review_returns_error_no_events(self):
        self._env.write_events(
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "spec_ready"),
        )
        before = self._event_count("BUILD-001")
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("pending_review", result["error"])
        self.assertEqual(self._event_count("BUILD-001"), before)

    def test_spec_approved_not_authorized_returns_error(self):
        self._env.write_events(
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "spec_ready"),
            _ev("BUILD-001", "spec_approved"),
        )
        self._env.write_decision("BUILD-001")
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        # Error should mention the need to authorize Stage 2 first
        self.assertIn("authorize", result["error"].lower())

    def test_spec_rejected_returns_error(self):
        self._env.write_events(
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "spec_rejected"),
        )
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("spec_rejected", result["error"])

    def test_abandoned_returns_error(self):
        self._env.write_events(_ev("BUILD-001", "abandoned"))
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])


# ── Tests: missing archive files (no events logged) ───────────────────────────

class TestDraftGenerationMissingFiles(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def _make_authorized_log_only(self, build_id: str):
        """Write log events for stage2_authorized without any archive files."""
        self._env.write_events(
            _ev(build_id, "request_queued"),
            _ev(build_id, "spec_ready"),
            _ev(build_id, "spec_approved"),
            _ev(build_id, "stage2_authorized"),
        )

    def test_missing_auth_file_returns_error(self):
        self._make_authorized_log_only("BUILD-001")
        # decision.json and spec.yaml also missing — auth checked first
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("stage2_authorization.json", result["error"])

    def test_missing_auth_file_no_events_logged(self):
        self._make_authorized_log_only("BUILD-001")
        before = len(self._env.read_events("BUILD-001"))
        _mod.generate_stage2_draft("BUILD-001")
        self.assertEqual(len(self._env.read_events("BUILD-001")), before)

    def test_missing_decision_json_returns_error(self):
        self._make_authorized_log_only("BUILD-001")
        self._env.write_auth("BUILD-001")
        # decision.json still missing
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("decision.json", result["error"])

    def test_missing_spec_yaml_returns_error(self):
        self._make_authorized_log_only("BUILD-001")
        self._env.write_auth("BUILD-001")
        self._env.write_decision("BUILD-001")
        # spec.yaml still missing
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("spec.yaml", result["error"])

    def test_missing_spec_yaml_no_events_logged(self):
        self._make_authorized_log_only("BUILD-001")
        self._env.write_auth("BUILD-001")
        self._env.write_decision("BUILD-001")
        before = len(self._env.read_events("BUILD-001"))
        _mod.generate_stage2_draft("BUILD-001")
        self.assertEqual(len(self._env.read_events("BUILD-001")), before)


# ── Tests: idempotency ────────────────────────────────────────────────────────

class TestDraftGenerationIdempotency(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_existing_draft_manifest_returns_error(self):
        self._env.make_stage2_authorized("BUILD-001")
        # Pre-create the manifest
        staging_dir = self._env.get_stage2_staging("BUILD-001")
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / "draft_manifest.json").write_text(
            json.dumps({"build_id": "BUILD-001", "status": "draft_generated"}),
            encoding="utf-8",
        )
        result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("draft", result["error"].lower())

    def test_existing_draft_manifest_no_events_logged(self):
        self._env.make_stage2_authorized("BUILD-001")
        staging_dir = self._env.get_stage2_staging("BUILD-001")
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / "draft_manifest.json").write_text("{}", encoding="utf-8")
        before = len(self._env.read_events("BUILD-001"))
        _mod.generate_stage2_draft("BUILD-001")
        self.assertEqual(len(self._env.read_events("BUILD-001")), before)


# ── Tests: non-executable lane refusal ───────────────────────────────────────

class TestDraftGenerationNonExecutableLane(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_config_only_lane_returns_error(self):
        """CODE_DRAFT_MEDIUM → coding tier → config_only → draft_blocked."""
        self._env.make_stage2_authorized("BUILD-001")
        result = _mod.generate_stage2_draft("BUILD-001",
                                            task_class=FLTaskClass.CODE_DRAFT_MEDIUM)
        self.assertFalse(result["ok"])
        self.assertIn("config_only", result["error"])

    def test_config_only_lane_logs_draft_blocked(self):
        self._env.make_stage2_authorized("BUILD-001")
        _mod.generate_stage2_draft("BUILD-001", task_class=FLTaskClass.CODE_DRAFT_MEDIUM)
        events = self._env.read_events("BUILD-001")
        blocked = [e for e in events if e["event"] == "draft_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["extra"]["reason"], "lane_not_executable")

    def test_config_only_lane_no_started_event(self):
        """Non-executable check happens before started event."""
        self._env.make_stage2_authorized("BUILD-001")
        _mod.generate_stage2_draft("BUILD-001", task_class=FLTaskClass.CODE_DRAFT_MEDIUM)
        events = self._env.read_events("BUILD-001")
        started = [e for e in events if e["event"] == "draft_generation_started"]
        self.assertEqual(len(started), 0)

    def test_external_supervised_lane_returns_error(self):
        """CODE_DRAFT_CRITICAL → codex_supervised → external_supervised → draft_blocked."""
        self._env.make_stage2_authorized("BUILD-001")
        result = _mod.generate_stage2_draft("BUILD-001",
                                            task_class=FLTaskClass.CODE_DRAFT_CRITICAL)
        self.assertFalse(result["ok"])
        self.assertIn("external_supervised", result["error"])

    def test_external_supervised_lane_logs_draft_blocked(self):
        self._env.make_stage2_authorized("BUILD-001")
        _mod.generate_stage2_draft("BUILD-001", task_class=FLTaskClass.CODE_DRAFT_CRITICAL)
        events = self._env.read_events("BUILD-001")
        blocked = [e for e in events if e["event"] == "draft_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["extra"]["reason"], "lane_not_executable")

    def test_non_executable_refusal_is_not_claude(self):
        """The refusal message must not imply Claude was silently substituted."""
        self._env.make_stage2_authorized("BUILD-001")
        result = _mod.generate_stage2_draft("BUILD-001",
                                            task_class=FLTaskClass.CODE_DRAFT_CRITICAL)
        self.assertNotIn("claude", result["error"].lower())


# ── Tests: LM failure paths ───────────────────────────────────────────────────

class TestDraftGenerationLMFailure(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_lm_failure_returns_error(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_fail("API key missing")):
            result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("API key missing", result["error"])

    def test_lm_failure_logs_started_then_blocked(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_fail()):
            _mod.generate_stage2_draft("BUILD-001")
        events = self._env.read_events("BUILD-001")
        draft_events = [e for e in events
                        if e["event"] in ("draft_generation_started", "draft_blocked")]
        self.assertEqual(len(draft_events), 2)
        self.assertEqual(draft_events[0]["event"], "draft_generation_started")
        self.assertEqual(draft_events[1]["event"], "draft_blocked")

    def test_lm_failure_blocked_event_has_lm_failed_reason(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_fail()):
            _mod.generate_stage2_draft("BUILD-001")
        events = self._env.read_events("BUILD-001")
        blocked = next(e for e in events if e["event"] == "draft_blocked")
        self.assertEqual(blocked["extra"]["reason"], "lm_failed")

    def test_lm_failure_no_staging_artifacts(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=_lm_fail()):
            _mod.generate_stage2_draft("BUILD-001")
        staging = self._env.get_stage2_staging("BUILD-001")
        # No files should have been written
        self.assertFalse((staging / "draft_module.py").exists())
        self.assertFalse((staging / "draft_manifest.json").exists())

    def test_invalid_json_output_logs_blocked(self):
        bad_result = SimpleNamespace(
            ok=True, content="not json at all", model_used="openai/gpt-4o-mini",
            input_tokens=10, output_tokens=5, cost_usd=0.0, error="",
        )
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=bad_result):
            result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        events = self._env.read_events("BUILD-001")
        blocked = [e for e in events if e["event"] == "draft_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["extra"]["reason"], "parse_failed")

    def test_empty_module_code_logs_blocked(self):
        empty_result = SimpleNamespace(
            ok=True, content=json.dumps({"module_code": "  ", "notes": "notes"}),
            model_used="openai/gpt-4o-mini", input_tokens=10, output_tokens=5,
            cost_usd=0.0, error="",
        )
        self._env.make_stage2_authorized("BUILD-001")
        with patch.object(_mod.FLLMHelper, "call", return_value=empty_result):
            result = _mod.generate_stage2_draft("BUILD-001")
        self.assertFalse(result["ok"])
        events = self._env.read_events("BUILD-001")
        blocked = [e for e in events if e["event"] == "draft_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["extra"]["reason"], "empty_output")


# ── Tests: provider routing for CODE_DRAFT_LOW ───────────────────────────────

class TestDraftGenerationRouting(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_code_draft_low_routes_to_cheap_tier(self):
        from frank_lloyd.provider_router import fl_route
        decision = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertEqual(decision.provider_tier, FLProviderTier.CHEAP)

    def test_code_draft_low_is_executable(self):
        from frank_lloyd.provider_router import fl_route
        decision = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertEqual(decision.executability, "executable")

    def test_code_draft_low_is_openrouter(self):
        from frank_lloyd.provider_router import fl_route
        decision = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertEqual(decision.provider_family, "openrouter")

    def test_code_draft_low_stage_allowed(self):
        from frank_lloyd.provider_router import fl_route
        decision = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertTrue(decision.stage_allowed)

    def test_code_draft_low_not_stage1(self):
        from frank_lloyd.provider_router import fl_route
        decision = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=1)
        self.assertFalse(decision.stage_allowed)

    def test_code_draft_low_no_operator_approval_required(self):
        from frank_lloyd.provider_router import fl_route
        decision = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertFalse(decision.operator_approval_required)


if __name__ == "__main__":
    unittest.main()
