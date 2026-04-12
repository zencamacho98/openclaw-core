# tests/test_peter_action_dispatch.py
#
# PETER-COMMAND-DISPATCH-01: Verify that /peter/action correctly recognises and
# dispatches the commands that previously fell through to LM chat.
#
# These tests exercise the HTTP endpoint (peter_action) directly with a FastAPI
# TestClient, confirming that command_type is NOT "unknown" for recognised
# commands, and IS "unknown" for freeform questions.
#
# Covers:
#   - belfort status
#   - abandon frank queue
#   - belfort advance / belfort regress
#   - run BUILD-N
#   - approve BUILD-N, reject BUILD-N, authorize BUILD-N stage2
#   - generic unknown freeform input stays unknown
#   - no regression for existing FL lifecycle commands (approve/reject/discard)

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


# ── Build the test client ─────────────────────────────────────────────────────

def _make_client():
    from app.routes.neighborhood import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _post(client, msg: str) -> dict:
    r = client.post("/peter/action", json={"message": msg})
    assert r.status_code == 200
    return r.json()


# ── Helpers for mocking handler responses ────────────────────────────────────

def _mock_response(command_type: str, ok: bool = True, summary: str = "ok") -> MagicMock:
    resp = MagicMock()
    resp.command_type = command_type
    resp.ok           = ok
    resp.summary      = summary
    resp.next_action  = ""
    resp.raw          = {}
    resp.metrics      = {}
    return resp


# ── belfort status ────────────────────────────────────────────────────────────

class TestBelfortStatusDispatch:
    def test_belfort_status_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("belfort_status", summary="Belfort preflight: OBSERVATION_ONLY.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "belfort status")
        assert d["command_type"] == "belfort_status"
        assert d["command_type"] != "unknown"

    def test_belfort_alone_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("belfort_status", summary="Belfort preflight.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "belfort")
        assert d["command_type"] == "belfort_status"

    def test_preflight_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("belfort_status", summary="Preflight status.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "preflight")
        assert d["command_type"] == "belfort_status"


# ── abandon frank queue ───────────────────────────────────────────────────────

class TestAbandonFrankQueueDispatch:
    def test_abandon_frank_queue_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("fl_bulk_abandon", summary="Abandoned 3 builds.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "abandon frank queue")
        assert d["command_type"] == "fl_bulk_abandon"
        assert d["command_type"] != "unknown"

    def test_clean_frank_queue_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("fl_bulk_abandon", summary="Abandoned 5 builds.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "clean frank queue")
        assert d["command_type"] == "fl_bulk_abandon"

    def test_abandon_peter_chat_builds_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("fl_bulk_abandon", summary="Abandoned 2 builds.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "abandon peter chat builds")
        assert d["command_type"] == "fl_bulk_abandon"


# ── belfort advance / regress ─────────────────────────────────────────────────

class TestBelfortModeControlDispatch:
    def test_belfort_advance_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("belfort_mode_control", summary="Belfort advanced to shadow.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "belfort advance")
        assert d["command_type"] == "belfort_mode_control"
        assert d["command_type"] != "unknown"

    def test_belfort_regress_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("belfort_mode_control", summary="Belfort regressed to observation.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "belfort regress")
        assert d["command_type"] == "belfort_mode_control"

    def test_belfort_set_shadow_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("belfort_mode_control", summary="Belfort set to shadow.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "belfort set shadow")
        assert d["command_type"] == "belfort_mode_control"

    def test_belfort_advance_with_reason_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("belfort_mode_control", summary="Advanced.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "belfort advance because testing is looking good")
        assert d["command_type"] == "belfort_mode_control"


# ── run BUILD-N ───────────────────────────────────────────────────────────────

class TestRunBuildDispatch:
    def test_run_build_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("fl_lifecycle_nl", summary="Frank Lloyd ran BUILD-042.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "run BUILD-042")
        assert d["command_type"] == "fl_lifecycle_nl"
        assert d["command_type"] != "unknown"

    def test_run_build_uppercase_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("fl_lifecycle_nl", summary="Ran BUILD-007.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "run BUILD-007")
        assert d["command_type"] == "fl_lifecycle_nl"


# ── approve / reject / authorize (existing gates — no regression) ─────────────

class TestExistingGatesNoRegression:
    def test_approve_build_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("approve_build", summary="BUILD-042 approved.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "approve BUILD-042")
        assert d["command_type"] == "approve_build"

    def test_reject_build_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("reject_build", summary="BUILD-042 rejected.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "reject BUILD-042 wrong approach")
        assert d["command_type"] == "reject_build"

    def test_authorize_stage2_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("authorize_stage2", summary="Stage 2 authorized.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "authorize BUILD-042 stage2")
        assert d["command_type"] == "authorize_stage2"

    def test_discard_draft_not_unknown(self):
        client = _make_client()
        mock_resp = _mock_response("discard_draft", summary="Draft discarded.")
        with patch("peter.router.route", return_value=mock_resp):
            d = _post(client, "discard BUILD-042")
        assert d["command_type"] == "discard_draft"


# ── Unknown input stays unknown → falls through to LM ────────────────────────

class TestUnknownCommandPassthrough:
    """
    Truly freeform questions must return command_type='unknown' so the frontend
    knows to fall through to /peter/chat (LM) instead of showing a handler response.
    """
    def test_freeform_question_is_unknown(self):
        client = _make_client()
        d = _post(client, "what should I have for lunch today?")
        assert d["command_type"] == "unknown"

    def test_generic_question_is_unknown(self):
        client = _make_client()
        d = _post(client, "how is the weather in London?")
        assert d["command_type"] == "unknown"

    def test_empty_message_is_unknown(self):
        client = _make_client()
        d = _post(client, "")
        assert d["command_type"] == "unknown"


# ── parse_command correctly classifies the problem inputs ─────────────────────
# These verify parse_command directly (no HTTP), confirming the dispatch table
# is correct for the commands that previously fell through.

class TestParseCommandClassification:
    def test_belfort_status(self):
        from peter.commands import parse_command, CommandType
        assert parse_command("belfort status").type == CommandType.BELFORT_STATUS

    def test_belfort_alone(self):
        from peter.commands import parse_command, CommandType
        assert parse_command("belfort").type == CommandType.BELFORT_STATUS

    def test_belfort_advance(self):
        from peter.commands import parse_command, CommandType
        assert parse_command("belfort advance").type == CommandType.BELFORT_MODE_CONTROL

    def test_belfort_regress(self):
        from peter.commands import parse_command, CommandType
        assert parse_command("belfort regress").type == CommandType.BELFORT_MODE_CONTROL

    def test_abandon_frank_queue(self):
        from peter.commands import parse_command, CommandType
        assert parse_command("abandon frank queue").type == CommandType.FL_BULK_ABANDON

    def test_clean_frank_queue(self):
        from peter.commands import parse_command, CommandType
        assert parse_command("clean frank queue").type == CommandType.FL_BULK_ABANDON

    def test_run_build_n(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("run BUILD-042")
        assert cmd.type == CommandType.FL_LIFECYCLE_NL
        assert cmd.args.get("action") == "run"

    def test_freeform_is_unknown(self):
        from peter.commands import parse_command, CommandType
        assert parse_command("what should I have for lunch").type == CommandType.UNKNOWN
