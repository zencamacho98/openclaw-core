"""
tests/test_candidate_apply_route.py

Direct backend route tests for POST /monitor/candidate/apply.

Covers:
  - success: valid ACCEPTED record → 200 + applied=True
  - missing record_path → 400
  - nonexistent file → 400
  - rejected/invalid record → 400
  - duplicate apply (all values already match baseline) → 400

Run with:
    python -m pytest tests/test_candidate_apply_route.py -v
    python -m unittest tests.test_candidate_apply_route -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# ── helpers ───────────────────────────────────────────────────────────────────

def _write_record(tmp_dir: pathlib.Path, data: dict) -> str:
    path = tmp_dir / "record.json"
    path.write_text(json.dumps(data))
    return str(path)


class _PatchedConfig:
    """
    Context manager that patches app.strategy.config and app.strategy.changelog
    so tests don't touch real files and remain idempotent.
    """
    def __init__(self, initial_cfg: dict | None = None):
        self._store = initial_cfg or {"POSITION_SIZE": 0.05, "TRADE_COOLDOWN": 30}
        self._patches = []

    def __enter__(self):
        from app.strategy import config as _cfg_mod, changelog as _cl_mod
        self._cfg_mod = _cfg_mod
        self._cl_mod = _cl_mod

        # Patch config
        self._patches.append(patch.object(_cfg_mod, "get_config", lambda: dict(self._store)))
        def _fake_update(d):
            self._store.update(d)
            return dict(self._store)
        self._patches.append(patch.object(_cfg_mod, "update", _fake_update))

        # Patch changelog
        self._patches.append(patch.object(_cl_mod, "record", lambda **kw: {"recorded": True, **kw}))

        # Patch compute_report (optional — may not exist)
        try:
            import app.report as _rep_mod
            self._patches.append(patch.object(_rep_mod, "compute_report", lambda: {}))
        except Exception:
            pass

        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *_):
        for p in reversed(self._patches):
            try:
                p.stop()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCandidateApplyRoute(unittest.TestCase):

    # ── 400 guard: missing record_path ────────────────────────────────────────

    def test_missing_record_path_returns_400(self):
        resp = client.post("/monitor/candidate/apply", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("record_path", resp.json().get("detail", "").lower())

    def test_empty_record_path_returns_400(self):
        resp = client.post("/monitor/candidate/apply", json={"record_path": ""})
        self.assertEqual(resp.status_code, 400)

    # ── 400 guard: nonexistent file ───────────────────────────────────────────

    def test_nonexistent_file_returns_400(self):
        resp = client.post(
            "/monitor/candidate/apply",
            json={"record_path": "/nonexistent/path.json"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not found", resp.json().get("detail", "").lower())

    # ── 400 guard: rejected record ────────────────────────────────────────────

    def test_rejected_record_returns_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_record(
                pathlib.Path(tmp),
                {"decision": "REJECTED", "candidate_config": {"POSITION_SIZE": 0.2}},
            )
            resp = client.post("/monitor/candidate/apply", json={"record_path": path})
        self.assertEqual(resp.status_code, 400)
        detail = resp.json().get("detail", "")
        self.assertIn("REJECTED", detail)

    # ── 400 guard: duplicate apply ────────────────────────────────────────────

    def test_duplicate_apply_returns_400(self):
        with _PatchedConfig({"POSITION_SIZE": 0.1, "TRADE_COOLDOWN": 30}):
            with tempfile.TemporaryDirectory() as tmp:
                # candidate_config already matches the patched baseline
                path = _write_record(
                    pathlib.Path(tmp),
                    {
                        "decision": "ACCEPTED",
                        "candidate_config": {"POSITION_SIZE": 0.1},
                        "experiment_name": "dupe_exp",
                    },
                )
                resp = client.post("/monitor/candidate/apply", json={"record_path": path})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Duplicate", resp.json().get("detail", ""))

    # ── 200 success ───────────────────────────────────────────────────────────

    def test_valid_accepted_record_returns_200(self):
        with _PatchedConfig({"POSITION_SIZE": 0.05, "TRADE_COOLDOWN": 30}):
            with tempfile.TemporaryDirectory() as tmp:
                path = _write_record(
                    pathlib.Path(tmp),
                    {
                        "decision": "ACCEPTED",
                        "candidate_config": {"POSITION_SIZE": 0.1},
                        "experiment_name": "test_exp",
                    },
                )
                with patch("observability.agent_state.save_state"):
                    resp = client.post(
                        "/monitor/candidate/apply",
                        json={"record_path": path, "reason": "test run"},
                    )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("applied"))
        self.assertIn("POSITION_SIZE", body.get("changed", {}))
        self.assertEqual(body.get("experiment_name"), "test_exp")

    def test_success_response_has_expected_keys(self):
        with _PatchedConfig({"POSITION_SIZE": 0.05, "TRADE_COOLDOWN": 30}):
            with tempfile.TemporaryDirectory() as tmp:
                path = _write_record(
                    pathlib.Path(tmp),
                    {
                        "decision": "ACCEPTED",
                        "candidate_config": {"POSITION_SIZE": 0.15},
                        "experiment_name": "exp_keys_test",
                    },
                )
                with patch("observability.agent_state.save_state"):
                    resp = client.post("/monitor/candidate/apply", json={"record_path": path})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("applied", "changed", "experiment_name", "record_path", "new_config"):
            self.assertIn(key, body, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main()
