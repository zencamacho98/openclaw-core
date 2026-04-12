# observability/belfort_summary.py
#
# Belfort observability bridge for THE ABODE.
#
# Reads from disk artifacts written by app/belfort_observer.py.
# This module is the only legal path for Peter's handlers and the UI
# to access Belfort's operating mode and preflight state.
#
# No app.* imports. No net calls. Read-only.
#
# Public API:
#   read_belfort_preflight() → dict
#   read_belfort_mode()      → str
#   read_observation_log(n)  → list[dict]

from __future__ import annotations

import json
import pathlib

_ROOT      = pathlib.Path(__file__).resolve().parent.parent
_PREFLIGHT = _ROOT / "data" / "belfort" / "preflight.json"
_OBS_LOG   = _ROOT / "data" / "belfort" / "observation_log.jsonl"
_MODE_FILE = _ROOT / "data" / "agent_state" / "belfort_mode.json"


def read_belfort_preflight() -> dict:
    """
    Read the most recent Belfort preflight snapshot from disk.

    Returns the snapshot dict, or a safe default if no snapshot exists yet.

    Default:
        mode: "observation"
        readiness_level: "NOT_READY"
        data_lane: "UNKNOWN"
        observation_ticks_today: 0
        (all other fields: None or empty)
    """
    if not _PREFLIGHT.exists():
        return {
            "written_at":              None,
            "mode":                    "observation",
            "broker_environment":      "not_configured",
            "paper_credentials":       False,
            "data_lane":               "UNKNOWN",
            "session_type":            "unknown",
            "universe":                [],
            "readiness_level":         "NOT_READY",
            "can_advance_to":          None,
            "advancement_blocked_by":  "No preflight snapshot written yet",
            "observation_ticks_today": 0,
            "last_tick_at":            None,
        }
    try:
        return json.loads(_PREFLIGHT.read_text(encoding="utf-8"))
    except Exception:
        return {
            "written_at":              None,
            "mode":                    "observation",
            "broker_environment":      "not_configured",
            "paper_credentials":       False,
            "data_lane":               "UNKNOWN",
            "session_type":            "unknown",
            "universe":                [],
            "readiness_level":         "NOT_READY",
            "can_advance_to":          None,
            "advancement_blocked_by":  "Preflight snapshot unreadable",
            "observation_ticks_today": 0,
            "last_tick_at":            None,
        }


def read_belfort_mode() -> str:
    """
    Read Belfort's current operating mode from disk.
    Returns "observation" if the state file is absent or corrupt.
    """
    if not _MODE_FILE.exists():
        return "observation"
    try:
        data = json.loads(_MODE_FILE.read_text(encoding="utf-8"))
        return data.get("mode", "observation")
    except Exception:
        return "observation"


def read_observation_log(n: int = 20) -> list[dict]:
    """
    Read the last n observation records from observation_log.jsonl.
    Returns an empty list if the log does not exist or is unreadable.
    """
    if not _OBS_LOG.exists():
        return []
    try:
        lines = [l.strip() for l in _OBS_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        records: list[dict] = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
        return records[-n:] if len(records) > n else records
    except Exception:
        return []
