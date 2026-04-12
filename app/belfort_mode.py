# app/belfort_mode.py
#
# Belfort operating mode state machine.
#
# Modes (advancement order):
#   OBSERVATION → SHADOW → PAPER → LIVE
#
# Rules:
#   - LIVE is unreachable without a human sign-off file.
#   - Journal entry is written FIRST; state file written SECOND.
#   - If journal write fails, state file is never written.
#   - Regression (advance=False) is allowed without gate check.
#   - set_mode() returns a result dict — never raises.
#
# Public API:
#   BelfortMode           — str enum
#   current_mode()        → BelfortMode
#   set_mode(mode, reason, initiated_by, force_regression) → dict
#   can_advance_to(target) → tuple[bool, str]  (allowed, reason)

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
_STATE_FILE = _ROOT / "data" / "agent_state" / "belfort_mode.json"
_JOURNAL    = _ROOT / "data" / "belfort" / "mode_journal.jsonl"
_SIGN_OFF   = _ROOT / "data" / "belfort" / "live_sign_off.json"


class BelfortMode(str, Enum):
    OBSERVATION = "observation"
    SHADOW      = "shadow"
    PAPER       = "paper"
    LIVE        = "live"


_ORDER = [
    BelfortMode.OBSERVATION,
    BelfortMode.SHADOW,
    BelfortMode.PAPER,
    BelfortMode.LIVE,
]


def _index(mode: BelfortMode) -> int:
    return _ORDER.index(mode)


def current_mode() -> BelfortMode:
    """Read current mode from state file. Defaults to OBSERVATION if absent/corrupt."""
    if not _STATE_FILE.exists():
        return BelfortMode.OBSERVATION
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return BelfortMode(data.get("mode", "observation"))
    except (OSError, json.JSONDecodeError, ValueError):
        return BelfortMode.OBSERVATION


def can_advance_to(target: BelfortMode) -> tuple[bool, str]:
    """
    Check whether Belfort can advance to the target mode from the current mode.
    Returns (allowed: bool, reason: str).

    Regression is always allowed via set_mode(force_regression=True).
    This function only covers forward advancement checks.
    """
    cur = current_mode()
    cur_idx = _index(cur)
    tgt_idx = _index(target)

    if tgt_idx <= cur_idx:
        return False, f"Already at or past {target.value}"

    if tgt_idx > cur_idx + 1:
        return False, f"Cannot skip modes: must advance through {_ORDER[cur_idx + 1].value} first"

    if target == BelfortMode.LIVE:
        if not _SIGN_OFF.exists():
            return False, "LIVE requires human sign-off file (data/belfort/live_sign_off.json)"
        try:
            data = json.loads(_SIGN_OFF.read_text(encoding="utf-8"))
            if not data.get("approved"):
                return False, "Sign-off file present but 'approved' is not true"
        except (OSError, json.JSONDecodeError):
            return False, "Sign-off file could not be read"

    return True, ""


def set_mode(
    mode: BelfortMode,
    reason: str = "",
    initiated_by: str = "operator",
    force_regression: bool = False,
) -> dict:
    """
    Transition Belfort to the given mode.

    Safety rules:
    - Journal entry written first; state file written second.
    - If journal write fails, state file is never written.
    - Forward advancement: gate checked via can_advance_to().
    - Regression: allowed if force_regression=True, no gate check.

    Returns {ok, mode, previous_mode, error}.
    """
    cur = current_mode()

    if mode == cur:
        return {"ok": True, "mode": mode.value, "previous_mode": cur.value, "error": None}

    cur_idx = _index(cur)
    tgt_idx = _index(mode)
    is_regression = tgt_idx < cur_idx

    if is_regression and not force_regression:
        return {
            "ok": False,
            "mode": cur.value,
            "previous_mode": cur.value,
            "error": f"Regression from {cur.value} to {mode.value} requires force_regression=True",
        }

    if not is_regression:
        allowed, gate_reason = can_advance_to(mode)
        if not allowed:
            return {
                "ok": False,
                "mode": cur.value,
                "previous_mode": cur.value,
                "error": gate_reason,
            }

    now_str = datetime.now(timezone.utc).isoformat()
    journal_entry = {
        "timestamp":    now_str,
        "event":        "mode_transition",
        "from_mode":    cur.value,
        "to_mode":      mode.value,
        "initiated_by": initiated_by,
        "reason":       reason or "",
    }

    # Journal first — if this fails, abort
    try:
        _JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with _JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(journal_entry) + "\n")
    except OSError as exc:
        return {
            "ok": False,
            "mode": cur.value,
            "previous_mode": cur.value,
            "error": f"Journal write failed — state not changed: {exc}",
        }

    # State file second
    state = {
        "mode":         mode.value,
        "set_at":       now_str,
        "set_by":       initiated_by,
        "previous_mode": cur.value,
    }
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        return {
            "ok": False,
            "mode": cur.value,
            "previous_mode": cur.value,
            "error": f"State file write failed after journal write: {exc}",
        }

    return {"ok": True, "mode": mode.value, "previous_mode": cur.value, "error": None}
