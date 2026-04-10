"""
tests/test_peter.py

Focused tests for the Peter supervisor layer.

Covers:
  - command parsing (all commands, edge cases, aliases)
  - router dispatch (correct handler called per command type)
  - response structure (all required fields present and well-formed)
  - artifact-based status answers (reads mock campaign state)
  - best candidate handler (with and without data)
  - list review-worthy (scans mock ledger)
  - promote guidance handler
  - run/resume campaign handlers
  - explain result handler (batch and session)
  - auth/identity config (approved, unknown, transport-specific)
  - transport isolation (no discord/twilio/whatsapp imports in peter/)

Run with:
    python -m unittest tests.test_peter -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands  import CommandType, Command, parse_command, HELP_TEXT
from peter.responses import Response, error_response, unauthorized_response, no_data_response
from peter.identity  import is_approved, load_identities, operator_name
from peter.router    import route
import peter.handlers as handlers


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_campaign_state(
    campaign_id: str = "campaign_test_001",
    status: str = "running",
    sessions_completed: int = 1,
    total_experiments: int = 6,
    total_accepted: int = 2,
    best_tier: str = "review_worthy",
    best_score: float = 72.0,
    rec_path: str = "data/validation_runs/test_001.json",
) -> dict:
    return {
        "schema_version": "1.0",
        "campaign_id":    campaign_id,
        "created_at":     "2026-01-01T00:00:00+00:00",
        "goal":           "test goal",
        "notes":          "",
        "status":         status,
        "config": {
            "max_sessions":           3,
            "max_batches_per_session": 2,
            "experiments_per_batch":  3,
            "max_total_experiments":  30,
        },
        "progress": {
            "sessions_completed":               sessions_completed,
            "total_batches":                    sessions_completed * 2,
            "total_experiments":                total_experiments,
            "total_accepted":                   total_accepted,
            "consecutive_no_progress_sessions": 0,
            "session_dominant_failures":        [],
        },
        "session_ids": [f"session_{i}" for i in range(sessions_completed)],
        "session_summaries": [
            {
                "session_id":        f"session_{i}",
                "total_experiments": 6,
                "total_accepted":    2,
                "best_score":        best_score,
                "best_tier":         best_tier,
                "human_review":      True,
                "stop_condition":    "max_batches_reached",
                "dominant_failure":  None,
            }
            for i in range(sessions_completed)
        ],
        "best_candidate": {
            "experiment_id":    "batch_test_001",
            "experiment_class": "entry_quality",
            "score":            best_score,
            "tier":             best_tier,
            "decision":         "ACCEPTED",
            "pnl_delta":        42.0,
            "worst_pnl_delta":  15.0,
            "candidate_config": {"MAX_EFFICIENCY_RATIO": 0.35},
            "session_id":       "session_0",
        },
        "stop_condition": None,
        "stop_reason":    None,
        "artifacts": {
            "best_validation_record": rec_path,
            "best_experiment_id":     "batch_test_001",
            "best_session_id":        "session_0",
            "session_reports":        ["data/research_ledger/reports/session_0_session.json"],
            "session_md_reports":     [],
            "campaign_brief_json":    None,
            "campaign_brief_md":      None,
        },
    }


def _make_batch_report(
    batch_id: str = "batch_test_20260101T000000",
    n_accepted: int = 1,
    n_experiments: int = 3,
    best_tier: str = "noisy",
    best_score: float = 55.0,
) -> dict:
    return {
        "schema_version": "1.0",
        "batch_id":       batch_id,
        "generated_at":   "2026-01-01T00:00:00+00:00",
        "what_ran": {
            "batch_id":       batch_id,
            "n_experiments":  n_experiments,
            "n_accepted":     n_accepted,
            "n_rejected":     n_experiments - n_accepted,
            "classes_tested": ["entry_quality"],
            "seeds_per_run":  7,
        },
        "what_mattered":  [f"{n_accepted}/{n_experiments} experiments accepted."],
        "best_candidate": {
            "experiment_id":    f"{batch_id}_001",
            "experiment_class": "entry_quality",
            "score":            best_score,
            "tier":             best_tier,
            "decision":         "ACCEPTED",
            "pnl_delta":        20.0,
            "worst_pnl_delta":  5.0,
            "candidate_config": {"MAX_EFFICIENCY_RATIO": 0.35},
        },
        "biggest_failure": None,
        "learned":         [],
        "next_action": {
            "recommendation": "retest_accepted",
            "rationale":      "Accepted but noisy.",
        },
        "human_review_recommended": True,
        "human_review_reason":      "Best candidate is noisy — check before promoting.",
        "ranking": [
            {
                "experiment_id":    f"{batch_id}_001",
                "experiment_class": "entry_quality",
                "score":            best_score,
                "tier":             best_tier,
                "decision":         "ACCEPTED",
                "pnl_delta":        20.0,
            }
        ],
    }


def _make_session_report(session_id: str = "session_test_001") -> dict:
    return {
        "schema_version": "1.0",
        "session_id":     session_id,
        "generated_at":   "2026-01-01T00:00:00+00:00",
        "what_ran": {
            "batches_completed": 2,
            "total_experiments": 6,
            "total_accepted":    2,
            "total_rejected":    4,
            "classes_tested":    ["entry_quality", "profit_taking"],
        },
        "best_candidate": {
            "experiment_id":    "batch_test_001",
            "experiment_class": "entry_quality",
            "score":            72.0,
            "tier":             "review_worthy",
            "decision":         "ACCEPTED",
            "pnl_delta":        42.0,
            "worst_pnl_delta":  15.0,
            "candidate_config": {"MAX_EFFICIENCY_RATIO": 0.35},
        },
        "dominant_findings":  ["2/6 experiments accepted across 2 batches."],
        "repeated_failures":  [],
        "next_direction": {
            "recommendation": "promote_best",
            "rationale":      "review_worthy candidate found.",
            "focus_classes":  ["entry_quality"],
        },
        "human_review_recommended": True,
        "human_review_reason":      "Best candidate ready for review.",
        "stop_condition": "max_batches_reached",
        "stop_reason":    "Completed 2/2 planned batches.",
        "batch_summaries": [],
        "diagnosis_snapshot": {},
    }


def _make_ledger_line(
    experiment_id: str = "batch_test_001",
    experiment_class: str = "entry_quality",
    score: float = 72.0,
    tier: str = "review_worthy",
    decision: str = "ACCEPTED",
    output_path: str = "data/validation_runs/test.json",
) -> str:
    entry = {
        "batch_id":  "batch_test_20260101T000000",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "summary":   {"total_experiments": 1, "accepted": 1, "rejected": 0, "failed": 0},
        "experiments": [{
            "experiment_id":    experiment_id,
            "experiment_class": experiment_class,
            "score":            score,
            "tier":             tier,
            "decision":         decision,
            "output_path":      output_path,
            "pnl_delta":        30.0,
        }],
        "candidates_for_review": [{
            "experiment_id":    experiment_id,
            "experiment_class": experiment_class,
            "score":            score,
            "tier":             tier,
            "decision":         decision,
            "output_path":      output_path,
        }],
    }
    return json.dumps(entry)


# ── 1. Command parsing ─────────────────────────────────────────────────────────

class TestCommandParsing(unittest.TestCase):

    def _parse(self, text: str) -> Command:
        return parse_command(text, transport="cli", operator_id="cli")

    def test_status(self):
        for text in ("status", "st", "s", "STATUS", "Status"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.STATUS)

    def test_inspect_campaign_no_id(self):
        cmd = self._parse("inspect campaign")
        self.assertEqual(cmd.type, CommandType.INSPECT_CAMPAIGN)
        self.assertEqual(cmd.args.get("campaign_id"), None)

    def test_inspect_campaign_with_id(self):
        cmd = self._parse("inspect campaign campaign_20260101T000000")
        self.assertEqual(cmd.type, CommandType.INSPECT_CAMPAIGN)
        self.assertEqual(cmd.args["campaign_id"], "campaign_20260101T000000")

    def test_best_candidate_aliases(self):
        for text in ("best candidate", "best", "bc"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.BEST_CANDIDATE)

    def test_list_review_worthy(self):
        for text in ("list review-worthy", "review-worthy", "review worthy", "review"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.LIST_REVIEW_WORTHY)

    def test_promote_guidance(self):
        for text in ("promote guidance", "promote", "promotion"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.PROMOTE_GUIDANCE)

    def test_explain_result_no_id(self):
        cmd = self._parse("explain result")
        self.assertEqual(cmd.type, CommandType.EXPLAIN_RESULT)
        self.assertNotIn("artifact_id", cmd.args)

    def test_explain_result_with_batch_id(self):
        cmd = self._parse("explain result batch_20260101T000000")
        self.assertEqual(cmd.type, CommandType.EXPLAIN_RESULT)
        self.assertEqual(cmd.args["artifact_id"], "batch_20260101T000000")

    def test_run_campaign_parses_goal(self):
        cmd = self._parse("run campaign reduce tail risk by 20 percent")
        self.assertEqual(cmd.type, CommandType.RUN_CAMPAIGN)
        self.assertEqual(cmd.args["goal"], "reduce tail risk by 20 percent")

    def test_resume_campaign_parses_id(self):
        cmd = self._parse("resume campaign campaign_20260101T000000")
        self.assertEqual(cmd.type, CommandType.RESUME_CAMPAIGN)
        self.assertEqual(cmd.args["campaign_id"], "campaign_20260101T000000")

    def test_resume_without_keyword(self):
        cmd = self._parse("resume campaign_20260101T000000")
        self.assertEqual(cmd.type, CommandType.RESUME_CAMPAIGN)
        self.assertEqual(cmd.args["campaign_id"], "campaign_20260101T000000")

    def test_help(self):
        for text in ("help", "h", "?"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.HELP)

    def test_unknown_command(self):
        cmd = self._parse("do something completely unknown xyz")
        self.assertEqual(cmd.type, CommandType.UNKNOWN)

    def test_transport_and_operator_id_preserved(self):
        cmd = parse_command("status", transport="discord", operator_id="123456789")
        self.assertEqual(cmd.transport,   "discord")
        self.assertEqual(cmd.operator_id, "123456789")

    def test_raw_text_preserved(self):
        raw = "best candidate please"
        cmd = self._parse(raw)
        self.assertEqual(cmd.raw_text, raw)


# ── 1b. New v1 action command parsing ────────────────────────────────────────

class TestNewCommandTypes(unittest.TestCase):
    """Parse tests for the 7 v1 action CommandTypes added to commands.py."""

    def _parse(self, text: str) -> Command:
        return parse_command(text, transport="cli", operator_id="cli")

    def test_start_auto_aliases(self):
        for text in ("start", "start auto research", "go"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.START_AUTO)

    def test_stop_campaign_aliases(self):
        for text in ("stop", "stop campaign", "halt"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.STOP_CAMPAIGN)

    def test_cancel_stop_aliases(self):
        for text in ("cancel stop", "keep going"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.CANCEL_STOP)

    def test_hold_review_aliases(self):
        for text in ("hold", "hold review", "defer"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.HOLD_REVIEW)

    def test_resume_review_precedes_resume_campaign(self):
        # "resume review" MUST match RESUME_REVIEW, not RESUME_CAMPAIGN
        cmd = self._parse("resume review")
        self.assertEqual(cmd.type, CommandType.RESUME_REVIEW)

    def test_resume_campaign_not_confused_with_resume_review(self):
        # Plain "resume" → RESUME_CAMPAIGN (no explicit campaign id)
        cmd = self._parse("resume")
        self.assertEqual(cmd.type, CommandType.RESUME_CAMPAIGN)

    def test_apply_and_continue_aliases(self):
        for text in ("apply", "apply and continue"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.APPLY_AND_CONTINUE)

    def test_what_last_aliases(self):
        for text in ("what happened last", "what happened", "last"):
            with self.subTest(text=text):
                cmd = self._parse(text)
                self.assertEqual(cmd.type, CommandType.WHAT_LAST)

    def test_what_last_precedes_status_why(self):
        # "what happened" must NOT fall through to STATUS ("what is …")
        cmd = self._parse("what happened")
        self.assertEqual(cmd.type, CommandType.WHAT_LAST)

    def test_why_still_routes_to_status(self):
        cmd = self._parse("why did it stop")
        self.assertEqual(cmd.type, CommandType.STATUS)

    def test_existing_commands_unaffected(self):
        # Spot-check that existing commands still parse correctly
        self.assertEqual(self._parse("status").type,        CommandType.STATUS)
        self.assertEqual(self._parse("best candidate").type, CommandType.BEST_CANDIDATE)
        self.assertEqual(self._parse("help").type,           CommandType.HELP)
        self.assertEqual(self._parse("review-worthy").type,  CommandType.LIST_REVIEW_WORTHY)


# ── 2. Identity / auth ────────────────────────────────────────────────────────

class TestIdentity(unittest.TestCase):

    def _mock_identities(self, operators: list[dict]):
        return patch("peter.identity.load_identities", return_value=operators)

    def test_cli_wildcard_is_approved(self):
        ops = [{"transport": "cli", "transport_id": "*", "allowed_commands": ["all"]}]
        with self._mock_identities(ops):
            self.assertTrue(is_approved("cli", "anyone", "status"))

    def test_cli_wildcard_approves_any_command(self):
        ops = [{"transport": "cli", "transport_id": "*", "allowed_commands": ["all"]}]
        with self._mock_identities(ops):
            for cmd in ("status", "best_candidate", "promote_guidance"):
                self.assertTrue(is_approved("cli", "anyone", cmd))

    def test_unknown_transport_is_rejected(self):
        ops = [{"transport": "cli", "transport_id": "*", "allowed_commands": ["all"]}]
        with self._mock_identities(ops):
            self.assertFalse(is_approved("discord", "123", "status"))

    def test_discord_specific_id_approved(self):
        ops = [{"transport": "discord", "transport_id": "888", "allowed_commands": ["all"]}]
        with self._mock_identities(ops):
            self.assertTrue(is_approved("discord", "888", "status"))

    def test_discord_wrong_id_rejected(self):
        ops = [{"transport": "discord", "transport_id": "888", "allowed_commands": ["all"]}]
        with self._mock_identities(ops):
            self.assertFalse(is_approved("discord", "999", "status"))

    def test_limited_command_scope(self):
        ops = [{"transport": "discord", "transport_id": "*", "allowed_commands": ["status"]}]
        with self._mock_identities(ops):
            self.assertTrue(is_approved("discord",  "*", "status"))
            self.assertFalse(is_approved("discord", "*", "promote_guidance"))

    def test_empty_identity_list_rejects_all(self):
        with self._mock_identities([]):
            self.assertFalse(is_approved("cli", "anyone", "status"))

    def test_operator_name_found(self):
        ops = [{"name": "zen", "transport": "discord", "transport_id": "888", "allowed_commands": ["all"]}]
        with self._mock_identities(ops):
            self.assertEqual(operator_name("discord", "888"), "zen")

    def test_operator_name_not_found(self):
        with self._mock_identities([]):
            self.assertIsNone(operator_name("discord", "999"))


# ── 3. Router dispatch ────────────────────────────────────────────────────────

class TestRouter(unittest.TestCase):

    def _approved_cmd(self, ctype: CommandType, args: dict | None = None) -> Command:
        return Command(
            type        = ctype,
            args        = args or {},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = "test",
        )

    def _patch_auth(self, approved: bool = True):
        return patch("peter.router.is_approved", return_value=approved)

    def test_unauthorized_returns_ok_false(self):
        cmd = self._approved_cmd(CommandType.STATUS)
        with self._patch_auth(False):
            resp = route(cmd)
        self.assertFalse(resp.ok)
        self.assertIn("Unauthorized", resp.summary)

    def test_status_returns_ok_response(self):
        # Verify that a STATUS command is handled and returns a Response.
        # (The _DISPATCH dict captures function refs at import time, so
        #  patching the module symbol won't redirect the call — test behavior.)
        cmd = self._approved_cmd(CommandType.STATUS)
        with self._patch_auth(True), \
             patch.object(handlers, "_load_latest_campaign_state", return_value=None), \
             patch.object(handlers, "_load_latest_batch_report", return_value=None):
            resp = route(cmd)
        self.assertIsInstance(resp, Response)
        self.assertEqual(resp.command_type, "status")

    def test_help_returns_ok_with_help_text(self):
        cmd = self._approved_cmd(CommandType.HELP)
        with self._patch_auth(True):
            resp = route(cmd)
        self.assertTrue(resp.ok)
        self.assertIn("status", resp.summary.lower())

    def test_unknown_command_returns_not_ok(self):
        # _DISPATCH captures function references at import time, so patching the
        # symbol doesn't affect it. Test behaviour instead of dispatch mechanism.
        cmd = self._approved_cmd(CommandType.UNKNOWN)
        with self._patch_auth(True):
            resp = route(cmd)
        self.assertFalse(resp.ok)
        self.assertIn("Unknown", resp.summary)


# ── 4. Response structure ─────────────────────────────────────────────────────

class TestResponseStructure(unittest.TestCase):

    def _make_response(self, **kwargs) -> Response:
        defaults = dict(command_type="status", ok=True, summary="test")
        defaults.update(kwargs)
        return Response(**defaults)

    def test_to_dict_has_all_required_keys(self):
        resp = self._make_response()
        d = resp.to_dict()
        for key in [
            "command_type", "ok", "summary", "metrics", "artifacts",
            "next_action", "human_review_needed", "human_review_reason", "raw",
        ]:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_chat_text_contains_summary(self):
        resp = self._make_response(summary="Things are looking good.")
        text = resp.to_chat_text()
        self.assertIn("Things are looking good.", text)

    def test_to_chat_text_contains_command_type(self):
        resp = self._make_response(command_type="best_candidate")
        text = resp.to_chat_text()
        self.assertIn("best candidate", text)

    def test_to_chat_text_contains_metrics(self):
        resp = self._make_response(metrics={"score": 72.0, "tier": "review_worthy"})
        text = resp.to_chat_text()
        self.assertIn("score: 72.0", text)
        self.assertIn("tier: review_worthy", text)

    def test_to_chat_text_contains_next_action(self):
        resp = self._make_response(next_action="python scripts/run_campaign.py")
        text = resp.to_chat_text()
        self.assertIn("python scripts/run_campaign.py", text)

    def test_to_chat_text_contains_human_review_flag(self):
        resp = self._make_response(
            human_review_needed=True,
            human_review_reason="Candidate ready for promotion."
        )
        text = resp.to_chat_text()
        self.assertIn("Human review", text)
        self.assertIn("Candidate ready", text)

    def test_to_chat_text_omits_review_when_not_needed(self):
        resp = self._make_response(human_review_needed=False, human_review_reason="")
        text = resp.to_chat_text()
        self.assertNotIn("Human review", text)

    def test_error_response_is_not_ok(self):
        resp = error_response("status", "Ledger file missing")
        self.assertFalse(resp.ok)
        self.assertIn("Ledger file missing", resp.summary)

    def test_unauthorized_response_is_not_ok(self):
        resp = unauthorized_response("status", "discord", "999")
        self.assertFalse(resp.ok)
        self.assertIn("Unauthorized", resp.summary)
        self.assertIn("discord", resp.summary)


# ── 5. Handler: status ────────────────────────────────────────────────────────

class TestHandlerStatus(unittest.TestCase):

    def _cmd(self) -> Command:
        return Command(
            type=CommandType.STATUS, args={},
            transport="cli", operator_id="cli", raw_text="status"
        )

    def test_status_with_running_campaign(self):
        state = _make_campaign_state(status="running")
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_status(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("running", resp.summary)
        self.assertIn("experiments", resp.metrics)
        self.assertIn("sessions", resp.metrics)

    def test_status_with_completed_campaign(self):
        state = _make_campaign_state(status="completed")
        state["stop_condition"] = "max_sessions_reached"
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_status(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("completed", resp.summary.lower())

    def test_status_with_no_campaign_falls_back_to_batch(self):
        batch = _make_batch_report()
        with patch.object(handlers, "_load_latest_campaign_state", return_value=None), \
             patch.object(handlers, "_load_latest_batch_report", return_value=batch):
            resp = handlers.handle_status(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("batch", resp.summary.lower())

    def test_status_with_no_data_returns_ok_with_guidance(self):
        with patch.object(handlers, "_load_latest_campaign_state", return_value=None), \
             patch.object(handlers, "_load_latest_batch_report", return_value=None):
            resp = handlers.handle_status(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("run", resp.next_action.lower())

    def test_status_artifacts_include_best_record(self):
        state = _make_campaign_state(rec_path="data/validation_runs/best.json")
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_status(self._cmd())
        self.assertIn("best_record", resp.artifacts)
        self.assertEqual(resp.artifacts["best_record"], "data/validation_runs/best.json")

    def test_status_human_review_flagged_when_session_has_accepted(self):
        state = _make_campaign_state(best_tier="review_worthy")
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_status(self._cmd())
        self.assertTrue(resp.human_review_needed)


# ── 6. Handler: best candidate ────────────────────────────────────────────────

class TestHandlerBestCandidate(unittest.TestCase):

    def _cmd(self) -> Command:
        return Command(
            type=CommandType.BEST_CANDIDATE, args={},
            transport="cli", operator_id="cli", raw_text="best candidate"
        )

    def test_best_candidate_with_data(self):
        state = _make_campaign_state()
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_best_candidate(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("batch_test_001", resp.summary)
        self.assertIn("experiment_id", resp.metrics)
        self.assertIn("validation_record", resp.artifacts)

    def test_best_candidate_includes_promote_command(self):
        state = _make_campaign_state(rec_path="data/validation_runs/best.json")
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_best_candidate(self._cmd())
        self.assertIn("promote_candidate.py", resp.next_action)
        self.assertIn("data/validation_runs/best.json", resp.next_action)

    def test_best_candidate_with_no_campaign(self):
        with patch.object(handlers, "_load_latest_campaign_state", return_value=None):
            resp = handlers.handle_best_candidate(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("run", resp.next_action.lower())

    def test_best_candidate_no_accepted(self):
        state = _make_campaign_state()
        state["best_candidate"] = None
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_best_candidate(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("No accepted", resp.summary)

    def test_best_candidate_human_review_for_review_worthy(self):
        state = _make_campaign_state(best_tier="review_worthy")
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_best_candidate(self._cmd())
        self.assertTrue(resp.human_review_needed)

    def test_best_candidate_rejected_tier_no_review(self):
        state = _make_campaign_state(best_tier="rejected")
        state["best_candidate"]["tier"] = "rejected"
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_best_candidate(self._cmd())
        self.assertFalse(resp.human_review_needed)


# ── 7. Handler: list review-worthy ────────────────────────────────────────────

class TestHandlerListReviewWorthy(unittest.TestCase):

    def _cmd(self) -> Command:
        return Command(
            type=CommandType.LIST_REVIEW_WORTHY, args={},
            transport="cli", operator_id="cli", raw_text="review-worthy"
        )

    def test_finds_review_worthy_candidates(self):
        candidates = [
            {"experiment_id": "exp_001", "experiment_class": "entry_quality",
             "score": 72.0, "tier": "review_worthy", "decision": "ACCEPTED",
             "output_path": "data/validation_runs/001.json"},
        ]
        with patch.object(handlers, "_scan_review_worthy_from_ledger", return_value=candidates):
            resp = handlers.handle_list_review_worthy(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("1", resp.summary)
        self.assertIn("exp_001", resp.artifacts)

    def test_empty_ledger_returns_ok_with_guidance(self):
        with patch.object(handlers, "_scan_review_worthy_from_ledger", return_value=[]):
            resp = handlers.handle_list_review_worthy(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("No review-worthy", resp.summary)

    def test_promote_command_in_next_action(self):
        candidates = [
            {"experiment_id": "exp_001", "experiment_class": "entry_quality",
             "score": 72.0, "tier": "review_worthy", "decision": "ACCEPTED",
             "output_path": "data/validation_runs/001.json"},
        ]
        with patch.object(handlers, "_scan_review_worthy_from_ledger", return_value=candidates):
            resp = handlers.handle_list_review_worthy(self._cmd())
        self.assertIn("promote_candidate.py", resp.next_action)

    def test_scan_review_worthy_from_mock_ledger(self):
        """Integration: test the actual scanner with a mock ledger file."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = pathlib.Path(tmp) / "ledger.jsonl"
            # Write two entries: one review-worthy, one rejected
            ledger_path.write_text(
                _make_ledger_line("exp_A", score=72.0, tier="review_worthy") + "\n"
                + _make_ledger_line("exp_B", score=25.0, tier="rejected", decision="REJECTED") + "\n"
            )
            original = handlers._LEDGER
            try:
                handlers._LEDGER = ledger_path
                results = handlers._scan_review_worthy_from_ledger(limit=10)
            finally:
                handlers._LEDGER = original
        # Only exp_A should qualify (score >= 66 AND ACCEPTED)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["experiment_id"], "exp_A")


# ── 8. Handler: promote guidance ──────────────────────────────────────────────

class TestHandlerPromoteGuidance(unittest.TestCase):

    def _cmd(self) -> Command:
        return Command(
            type=CommandType.PROMOTE_GUIDANCE, args={},
            transport="cli", operator_id="cli", raw_text="promote guidance"
        )

    def test_returns_exact_promote_command(self):
        state = _make_campaign_state(rec_path="data/validation_runs/best.json")
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_promote_guidance(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("promote_candidate.py", resp.next_action)
        self.assertIn("data/validation_runs/best.json", resp.next_action)

    def test_no_campaign_returns_guidance(self):
        with patch.object(handlers, "_load_latest_campaign_state", return_value=None):
            resp = handlers.handle_promote_guidance(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("run", resp.next_action.lower())

    def test_no_record_path_still_responds(self):
        state = _make_campaign_state()
        state["artifacts"]["best_validation_record"] = None
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_promote_guidance(self._cmd())
        self.assertTrue(resp.ok)

    def test_human_review_always_required_for_promote(self):
        state = _make_campaign_state(rec_path="data/validation_runs/best.json")
        with patch.object(handlers, "_load_latest_campaign_state", return_value=state):
            resp = handlers.handle_promote_guidance(self._cmd())
        self.assertTrue(resp.human_review_needed)


# ── 9. Handler: run / resume campaign ─────────────────────────────────────────

class TestHandlerRunResumeCampaign(unittest.TestCase):

    def _run_cmd(self, goal: str = "") -> Command:
        return Command(
            type=CommandType.RUN_CAMPAIGN, args={"goal": goal},
            transport="cli", operator_id="cli", raw_text=f"run campaign {goal}"
        )

    def _resume_cmd(self, campaign_id: str = "") -> Command:
        return Command(
            type=CommandType.RESUME_CAMPAIGN, args={"campaign_id": campaign_id},
            transport="cli", operator_id="cli", raw_text=f"resume campaign {campaign_id}"
        )

    def test_run_campaign_returns_command(self):
        resp = handlers.handle_run_campaign(self._run_cmd("improve entry quality"))
        self.assertTrue(resp.ok)
        self.assertIn("run_campaign.py", resp.next_action)
        self.assertIn("improve entry quality", resp.next_action)

    def test_run_campaign_empty_goal_is_error(self):
        resp = handlers.handle_run_campaign(self._run_cmd(""))
        self.assertFalse(resp.ok)
        self.assertIn("goal", resp.summary.lower())

    def test_resume_campaign_with_valid_interrupted_state(self):
        state = _make_campaign_state(status="interrupted")
        with patch.object(handlers, "_load_campaign_state", return_value=state):
            resp = handlers.handle_resume_campaign(
                self._resume_cmd("campaign_test_001")
            )
        self.assertTrue(resp.ok)
        self.assertIn("run_campaign.py", resp.next_action)
        self.assertIn("--resume", resp.next_action)

    def test_resume_campaign_completed_is_error(self):
        state = _make_campaign_state(status="completed")
        state["stop_condition"] = "max_sessions_reached"
        with patch.object(handlers, "_load_campaign_state", return_value=state):
            resp = handlers.handle_resume_campaign(
                self._resume_cmd("campaign_test_001")
            )
        self.assertFalse(resp.ok)
        self.assertIn("completed", resp.summary.lower())

    def test_resume_campaign_not_found_is_error(self):
        with patch.object(handlers, "_load_campaign_state", return_value=None), \
             patch.object(handlers, "_load_latest_interrupted_campaign", return_value=None):
            resp = handlers.handle_resume_campaign(self._resume_cmd("bad_id"))
        self.assertFalse(resp.ok)

    def test_resume_auto_finds_interrupted_when_no_id(self):
        state = _make_campaign_state(status="interrupted")
        with patch.object(handlers, "_load_campaign_state", return_value=None), \
             patch.object(handlers, "_load_latest_interrupted_campaign", return_value=state):
            resp = handlers.handle_resume_campaign(self._resume_cmd(""))
        self.assertTrue(resp.ok)
        self.assertIn("resume", resp.next_action)


# ── 10. Handler: explain result ────────────────────────────────────────────────

class TestHandlerExplainResult(unittest.TestCase):

    def _cmd(self, artifact_id: str = "") -> Command:
        return Command(
            type=CommandType.EXPLAIN_RESULT,
            args={"artifact_id": artifact_id} if artifact_id else {},
            transport="cli", operator_id="cli", raw_text="explain result"
        )

    def test_explain_latest_batch(self):
        batch = _make_batch_report()
        with patch.object(handlers, "_load_batch_report", return_value=None), \
             patch.object(handlers, "_load_latest_batch_report", return_value=batch):
            resp = handlers.handle_explain_result(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("batch", resp.summary.lower())

    def test_explain_specific_batch(self):
        batch = _make_batch_report(batch_id="batch_specific_001")
        with patch.object(handlers, "_load_batch_report", return_value=batch):
            resp = handlers.handle_explain_result(self._cmd("batch_specific_001"))
        self.assertTrue(resp.ok)
        self.assertIn("batch_specific_001", resp.summary)

    def test_explain_session_by_id(self):
        session = _make_session_report("session_test_001")
        with patch.object(handlers, "_load_session_report", return_value=session):
            resp = handlers.handle_explain_result(self._cmd("session_test_001"))
        self.assertTrue(resp.ok)
        self.assertIn("session_test_001", resp.summary)

    def test_explain_no_data_returns_ok_with_guidance(self):
        with patch.object(handlers, "_load_batch_report", return_value=None), \
             patch.object(handlers, "_load_session_report", return_value=None), \
             patch.object(handlers, "_load_latest_batch_report", return_value=None):
            resp = handlers.handle_explain_result(self._cmd())
        self.assertTrue(resp.ok)
        self.assertIn("No", resp.summary)


# ── 11. Transport isolation ───────────────────────────────────────────────────

class TestTransportIsolation(unittest.TestCase):
    """
    Verify that importing all Peter modules does NOT pull in any external
    transport libraries. This is the architectural guarantee that Peter stays
    transport-agnostic.
    """

    def test_no_discord_import(self):
        import peter
        import peter.identity
        import peter.commands
        import peter.responses
        import peter.handlers
        import peter.router
        self.assertNotIn("discord",  sys.modules)

    def test_no_twilio_import(self):
        self.assertNotIn("twilio",   sys.modules)

    def test_no_telegram_import(self):
        self.assertNotIn("telegram", sys.modules)

    def test_no_whatsapp_import(self):
        self.assertNotIn("whatsapp", sys.modules)

    def test_peter_does_not_import_research_modules(self):
        # Peter handlers must not import from research/ — it reads JSON directly.
        # We check actual import statements (lines starting with import/from),
        # not comments which may reference "research" as text.
        import peter.handlers as ph
        import_lines = [
            ln.strip() for ln in pathlib.Path(ph.__file__).read_text().splitlines()
            if ln.strip().startswith(("import ", "from "))
        ]
        for ln in import_lines:
            self.assertNotIn("research", ln, f"Unexpected research import: {ln}")

    def test_peter_does_not_import_app_modules(self):
        import peter.handlers as ph
        import_lines = [
            ln.strip() for ln in pathlib.Path(ph.__file__).read_text().splitlines()
            if ln.strip().startswith(("import ", "from "))
        ]
        for ln in import_lines:
            self.assertNotIn("from app", ln,    f"Unexpected app import: {ln}")
            self.assertNotIn("import app",  ln, f"Unexpected app import: {ln}")


# ── 12. Help command ──────────────────────────────────────────────────────────

class TestHelpCommand(unittest.TestCase):

    def test_help_response_contains_all_commands(self):
        cmd = Command(
            type=CommandType.HELP, args={},
            transport="cli", operator_id="cli", raw_text="help"
        )
        with patch("peter.router.is_approved", return_value=True):
            resp = route(cmd)
        self.assertTrue(resp.ok)
        for keyword in ["status", "inspect", "best candidate", "review", "promote", "explain", "run campaign", "resume"]:
            self.assertIn(keyword, resp.summary.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
