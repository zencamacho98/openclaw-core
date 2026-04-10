# research/campaign.py
#
# Campaign state management, lock safety, and ID generation.
#
# A campaign is a bounded sequence of research sessions running under one goal,
# one budget, and one durable state file. This module handles all persistence
# and mutual-exclusion concerns so the runner can stay focused on orchestration.
#
# Public API:
#   make_campaign_id()                       → str
#   CampaignState                            — all campaign state in one object
#   save_state(state, path)                  → None   (atomic write)
#   load_state(path)                         → CampaignState
#   acquire_lock(campaigns_dir, campaign_id) → Path   (raises RuntimeError if blocked)
#   release_lock(lock_path)                  → None
#   check_existing_lock(campaigns_dir)       → dict | None

from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone
from typing import Any


# ── ID generation ─────────────────────────────────────────────────────────────

def make_campaign_id() -> str:
    return "campaign_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


# ── Campaign state ─────────────────────────────────────────────────────────────

class CampaignState:
    """
    All mutable campaign state. Designed for straightforward JSON round-trip.

    Fields:
        schema_version  — for future migration.
        campaign_id     — unique identifier.
        created_at      — ISO timestamp.
        goal            — operator-supplied campaign objective.
        notes           — optional context string.
        status          — "running" | "completed" | "interrupted".
        config          — immutable limits set at campaign creation.
        progress        — counters updated after each session.
        session_ids     — ordered list of session identifiers run so far.
        session_summaries — condensed per-session result dicts.
        best_candidate  — highest-scored accepted experiment seen across the campaign.
        stop_condition  — condition name that ended the campaign (None while running).
        stop_reason     — human-readable explanation (None while running).
        artifacts       — paths to key output files.
    """

    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        campaign_id:       str,
        created_at:        str,
        goal:              str,
        notes:             str,
        status:            str,
        config:            dict[str, Any],
        progress:          dict[str, Any],
        session_ids:       list[str],
        session_summaries: list[dict[str, Any]],
        best_candidate:    dict[str, Any] | None,
        stop_condition:    str | None,
        stop_reason:       str | None,
        artifacts:         dict[str, Any],
        schema_version:    str = SCHEMA_VERSION,
    ) -> None:
        self.schema_version   = schema_version
        self.campaign_id      = campaign_id
        self.created_at       = created_at
        self.goal             = goal
        self.notes            = notes
        self.status           = status
        self.config           = config
        self.progress         = progress
        self.session_ids      = session_ids
        self.session_summaries = session_summaries
        self.best_candidate   = best_candidate
        self.stop_condition   = stop_condition
        self.stop_reason      = stop_reason
        self.artifacts        = artifacts

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version":    self.schema_version,
            "campaign_id":       self.campaign_id,
            "created_at":        self.created_at,
            "goal":              self.goal,
            "notes":             self.notes,
            "status":            self.status,
            "config":            self.config,
            "progress":          self.progress,
            "session_ids":       self.session_ids,
            "session_summaries": self.session_summaries,
            "best_candidate":    self.best_candidate,
            "stop_condition":    self.stop_condition,
            "stop_reason":       self.stop_reason,
            "artifacts":         self.artifacts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CampaignState":
        # Tolerant loading: supply defaults for any fields added in future schema versions
        return cls(
            schema_version    = d.get("schema_version", cls.SCHEMA_VERSION),
            campaign_id       = d["campaign_id"],
            created_at        = d["created_at"],
            goal              = d.get("goal", ""),
            notes             = d.get("notes", ""),
            status            = d.get("status", "running"),
            config            = d.get("config", {}),
            progress          = _default_progress(d.get("progress", {})),
            session_ids       = d.get("session_ids", []),
            session_summaries = d.get("session_summaries", []),
            best_candidate    = d.get("best_candidate"),
            stop_condition    = d.get("stop_condition"),
            stop_reason       = d.get("stop_reason"),
            artifacts         = _default_artifacts(d.get("artifacts", {})),
        )


def _default_progress(p: dict) -> dict:
    """Ensure all expected progress keys exist (forward-compatible resume)."""
    defaults: dict[str, Any] = {
        "sessions_completed":               0,
        "total_batches":                    0,
        "total_experiments":                0,
        "total_accepted":                   0,
        "consecutive_no_progress_sessions": 0,
        "session_dominant_failures":        [],
    }
    defaults.update(p)
    return defaults


def _default_artifacts(a: dict) -> dict:
    defaults: dict[str, Any] = {
        "best_validation_record": None,
        "best_experiment_id":     None,
        "best_session_id":        None,
        "session_reports":        [],
        "session_md_reports":     [],
        "campaign_brief_json":    None,
        "campaign_brief_md":      None,
    }
    defaults.update(a)
    return defaults


# ── Persistence ────────────────────────────────────────────────────────────────

def save_state(state: CampaignState, path: pathlib.Path) -> None:
    """
    Atomically write campaign state to disk.

    Writes to a .tmp sibling first, then renames — safe against partial writes
    and process kills mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2))
    tmp.replace(path)   # atomic on POSIX


def load_state(path: pathlib.Path) -> CampaignState:
    """
    Load campaign state from disk.

    Raises FileNotFoundError if the file does not exist.
    Raises json.JSONDecodeError if the file is corrupt.
    """
    return CampaignState.from_dict(json.loads(path.read_text()))


# ── Lock management ────────────────────────────────────────────────────────────

_LOCK_FILENAME = ".campaign.lock"


def acquire_lock(campaigns_dir: pathlib.Path, campaign_id: str) -> pathlib.Path:
    """
    Acquire the campaign run lock.

    Behaviour:
      - If no lock exists: write one and return its path.
      - If a stale lock exists (PID no longer running): clear it with a warning
        and write a fresh lock.
      - If a live lock exists: raise RuntimeError immediately.

    Returns the lock file path (needed by release_lock).
    """
    campaigns_dir.mkdir(parents=True, exist_ok=True)
    lock_path = campaigns_dir / _LOCK_FILENAME

    if lock_path.exists():
        try:
            existing = json.loads(lock_path.read_text())
        except Exception:
            existing = {}

        pid = existing.get("pid")
        existing_id = existing.get("campaign_id", "?")

        if pid and _pid_alive(pid):
            raise RuntimeError(
                f"Campaign '{existing_id}' is already running (PID {pid}).\n"
                f"Aborting to prevent overlap. If that process is gone, delete:\n"
                f"  {lock_path}"
            )
        else:
            print(
                f"[WARN] Clearing stale lock for campaign '{existing_id}' "
                f"(PID {pid} is no longer running)."
            )

    lock_data = {
        "pid":         os.getpid(),
        "campaign_id": campaign_id,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_path.write_text(json.dumps(lock_data, indent=2))
    return lock_path


def release_lock(lock_path: pathlib.Path) -> None:
    """
    Remove the lock file if it belongs to the current process.

    Safe to call even if the file is already gone.
    """
    if not lock_path.exists():
        return
    try:
        data = json.loads(lock_path.read_text())
        if data.get("pid") == os.getpid():
            lock_path.unlink()
    except Exception:
        pass


def check_existing_lock(campaigns_dir: pathlib.Path) -> dict | None:
    """
    Return the lock data dict if a live lock exists, else None.

    A lock is "live" when the stored PID is still running.
    Purely informational — does not raise.
    """
    lock_path = campaigns_dir / _LOCK_FILENAME
    if not lock_path.exists():
        return None
    try:
        data = json.loads(lock_path.read_text())
        pid  = data.get("pid")
        if pid and _pid_alive(pid):
            return data
    except Exception:
        pass
    return None


# ── Operator stop signal ──────────────────────────────────────────────────────
#
# A sentinel file that operators (or the UI) write to request a graceful
# campaign stop. CampaignRunner checks for it after each session completes,
# so the current session always finishes cleanly before the stop takes effect.
#
# File: campaigns_dir / _STOP_SIGNAL_FILE
# Lifecycle: written by request_stop() → read by stop_requested() → deleted by clear_stop_signal()

_STOP_SIGNAL_FILE = ".stop_requested"


def request_stop(campaigns_dir: pathlib.Path) -> None:
    """Write the stop-signal file. CampaignRunner checks this after each session."""
    campaigns_dir.mkdir(parents=True, exist_ok=True)
    (campaigns_dir / _STOP_SIGNAL_FILE).touch()


def stop_requested(campaigns_dir: pathlib.Path) -> bool:
    """Return True if the stop-signal file exists."""
    return (campaigns_dir / _STOP_SIGNAL_FILE).exists()


def clear_stop_signal(campaigns_dir: pathlib.Path) -> None:
    """Remove the stop-signal file (called by the runner when it honors the signal)."""
    try:
        (campaigns_dir / _STOP_SIGNAL_FILE).unlink(missing_ok=True)
    except Exception:
        pass


# ── Internal helpers ───────────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    """Return True if the given PID is currently running."""
    try:
        os.kill(pid, 0)   # signal 0 = existence check only
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True       # process exists, we just can't signal it
    except Exception:
        return False
