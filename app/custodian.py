# app/custodian.py
#
# Runtime health monitor for The Abode.
#
# The Custodian checks whether canonical services are up, detects runtime drift
# (stale PID files, wrong-port processes, control-script vs reality mismatch),
# and produces a plain-English health report for Peter and the dashboard.
#
# Role boundary:
#   - Custodian: runtime health / environment drift — read/diagnose/report only
#   - Checker:   trading loop health (stalls, queue backlog, supervisor errors)
#   - Peter:     operator interface — reads Custodian report for briefings
#   - Supervisor: execution coordinator — runs research campaigns
#
# Safety rule (v1):
#   Custodian does NOT auto-restart services, kill processes, or repair state.
#   All findings are recommendations for operator review only.
#
# Canonical ports (must match scripts/ctl.sh):
#   Backend : 127.0.0.1:8001
#   UI      : 127.0.0.1:8502
#   Stale   : 8501 — system-managed, not canonical; flag if listening
#
# Public API:
#   run_health_check() → HealthReport
#   get_last_report()  → dict | None   (cached from disk)
#   report_to_dict(r)  → dict

from __future__ import annotations

import json
import os
import pathlib
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import List

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_HEALTH_CACHE = _ROOT / "data" / "custodian_health.json"
_PID_DIR      = _ROOT / "run"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8001
UI_PORT      = 8502
STALE_PORT   = 8501   # system-managed Streamlit — flag if active


@dataclass
class HealthItem:
    """One check result."""
    service:  str   # "backend", "ui", "stale_ui", "pid_backend", "pid_ui"
    status:   str   # "ok" | "down" | "drift" | "notice"
    severity: str   # "ok" | "warning" | "notice"
    detail:   str   # plain English, one sentence


@dataclass
class HealthReport:
    """Full Custodian health report."""
    timestamp:       str
    overall:         str          # "healthy" | "degraded" | "critical"
    summary:         str          # one-line plain English for Peter
    items:           List[HealthItem]
    recommendations: List[str]    # repair steps — operator must approve, never auto-applied


def run_health_check() -> HealthReport:
    """
    Run all Custodian health checks and return a structured report.
    Caches the result to data/custodian_health.json for Peter to read.

    Checks performed:
      1. Backend port 8001 — TCP reachability (is it listening?)
      2. UI port 8502      — TCP reachability
      3. Stale port 8501   — flag if a process is listening there
      4. Backend PID file  — does it exist and does the PID point to a live process?
      5. UI PID file       — same
    """
    items:           list[HealthItem] = []
    recommendations: list[str]       = []
    now = datetime.now(timezone.utc).isoformat()

    # ── 1. Backend port reachability ──────────────────────────────────────────
    # The Custodian runs inside the backend process, so if we receive a request
    # the HTTP layer is up. We check the TCP port independently to detect
    # PID/port drift scenarios where the control script's view may differ.
    if _port_open(BACKEND_HOST, BACKEND_PORT):
        items.append(HealthItem(
            service="backend", status="ok", severity="ok",
            detail=f"Backend is reachable on {BACKEND_PORT}.",
        ))
    else:
        items.append(HealthItem(
            service="backend", status="down", severity="warning",
            detail=f"Backend port {BACKEND_PORT} is not listening.",
        ))
        recommendations.append("Run `./scripts/ctl.sh start` or check logs/backend.log.")

    # ── 2. UI port reachability ───────────────────────────────────────────────
    if _port_open("127.0.0.1", UI_PORT):
        items.append(HealthItem(
            service="ui", status="ok", severity="ok",
            detail=f"UI is reachable on {UI_PORT}.",
        ))
    else:
        items.append(HealthItem(
            service="ui", status="down", severity="warning",
            detail=f"UI port {UI_PORT} is not listening.",
        ))
        recommendations.append("Run `./scripts/ctl.sh start` or check logs/ui.log.")

    # ── 3. Stale port 8501 ────────────────────────────────────────────────────
    if _port_open("127.0.0.1", STALE_PORT):
        items.append(HealthItem(
            service="stale_ui", status="notice", severity="notice",
            detail=(
                f"A process is listening on port {STALE_PORT}. "
                f"This may be a stale system-managed UI. "
                f"Use port {UI_PORT} — not {STALE_PORT}."
            ),
        ))

    # ── 4 & 5. PID file consistency ───────────────────────────────────────────
    _check_pid("backend", _PID_DIR / "backend.pid", items, recommendations)
    _check_pid("ui",      _PID_DIR / "ui.pid",      items, recommendations)

    # ── Derive overall status ──────────────────────────────────────────────────
    severities = {i.severity for i in items}
    if "warning" in severities:
        overall = "degraded"
    else:
        overall = "healthy"

    summary = _build_summary(items, overall)

    report = HealthReport(
        timestamp       = now,
        overall         = overall,
        summary         = summary,
        items           = items,
        recommendations = recommendations,
    )

    _cache(report)
    return report


def get_last_report() -> dict | None:
    """Return the last cached health report from disk, or None if unavailable."""
    if not _HEALTH_CACHE.exists():
        return None
    try:
        return json.loads(_HEALTH_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def report_to_dict(report: HealthReport) -> dict:
    return asdict(report)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _port_open(host: str, port: int) -> bool:
    """Return True if a TCP connection to host:port succeeds (within 1 s)."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def _check_pid(
    name: str,
    pid_path: pathlib.Path,
    items: list,
    recommendations: list,
) -> None:
    """Check a ctl.sh PID file: exists? readable? process alive?"""
    if not pid_path.exists():
        items.append(HealthItem(
            service=f"pid_{name}", status="drift", severity="notice",
            detail=(
                f"No PID file for {name} ({pid_path.name}). "
                f"Service may not have been started via ctl.sh."
            ),
        ))
        return

    try:
        pid = int(pid_path.read_text().strip())
    except Exception:
        items.append(HealthItem(
            service=f"pid_{name}", status="drift", severity="notice",
            detail=f"PID file for {name} exists but is unreadable.",
        ))
        return

    try:
        os.kill(pid, 0)   # signal 0 = liveness probe, no signal sent
        alive = True
    except (ProcessLookupError, PermissionError):
        alive = False

    if alive:
        items.append(HealthItem(
            service=f"pid_{name}", status="ok", severity="ok",
            detail=f"{name.capitalize()} PID {pid} is alive (started via ctl.sh).",
        ))
    else:
        items.append(HealthItem(
            service=f"pid_{name}", status="drift", severity="warning",
            detail=(
                f"{name.capitalize()} PID file records pid={pid} "
                f"but that process is not running — stale PID file."
            ),
        ))
        recommendations.append(
            "Run `./scripts/ctl.sh stop && ./scripts/ctl.sh start` to clean up stale state."
        )


def _build_summary(items: list[HealthItem], overall: str) -> str:
    """One-line plain-English summary for Peter."""
    backend = next((i for i in items if i.service == "backend"), None)
    ui      = next((i for i in items if i.service == "ui"), None)
    stale   = next((i for i in items if i.service == "stale_ui"), None)

    parts: list[str] = []

    if backend:
        parts.append(
            f"Backend is healthy on {BACKEND_PORT}"
            if backend.status == "ok"
            else f"Backend is DOWN on {BACKEND_PORT}"
        )
    if ui:
        parts.append(
            f"UI is healthy on {UI_PORT}"
            if ui.status == "ok"
            else f"UI is DOWN on {UI_PORT}"
        )
    if stale:
        parts.append(f"stale instance may exist on {STALE_PORT}")

    base = ". ".join(parts) + "." if parts else "No service data."

    if overall == "healthy" and not stale:
        return base + " No action needed."
    elif overall == "degraded":
        return base + " Needs review: runtime drift detected."
    else:
        return base


def _cache(report: HealthReport) -> None:
    """Atomically write the health report to disk. Best-effort — never crashes caller."""
    try:
        _HEALTH_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _HEALTH_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        tmp.rename(_HEALTH_CACHE)
    except Exception:
        pass
