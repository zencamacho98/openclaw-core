#!/usr/bin/env bash
# scripts/ctl.sh — OpenClaw development control script
#
# Manages the repo-owned backend (uvicorn) and UI (streamlit) processes
# for the zen_camacho98 development environment.
#
# Canonical ports:
#   Backend : 127.0.0.1:8001   (matches API_BASE in ui/dashboard.py)
#   UI      : http://localhost:8502
#
# Usage:
#   ./scripts/ctl.sh start          # start both, wait for readiness, print URL
#   ./scripts/ctl.sh stop           # stop repo-owned processes only
#   ./scripts/ctl.sh restart        # stop then start
#   ./scripts/ctl.sh status         # show PIDs, ports, health, URL
#   ./scripts/ctl.sh logs           # tail both logs
#   ./scripts/ctl.sh logs-backend   # tail backend log
#   ./scripts/ctl.sh logs-ui        # tail UI log

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
RUN_DIR="$REPO_ROOT/run"
LOG_DIR="$REPO_ROOT/logs"

BACKEND_PORT=8001
UI_PORT=8502
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
UI_URL="http://localhost:${UI_PORT}"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
UI_PID_FILE="$RUN_DIR/ui.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
UI_LOG="$LOG_DIR/ui.log"

# ── Helpers ───────────────────────────────────────────────────────────────────

_mkdir() {
    mkdir -p "$RUN_DIR" "$LOG_DIR"
}

_is_alive() {
    local pid="${1:-}"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

_read_pid() {
    local f="$1"
    if [[ -f "$f" ]]; then cat "$f"; else echo ""; fi
}

_kill_pid_file() {
    local label="$1" f="$2"
    local pid
    pid="$(_read_pid "$f")"
    if [[ -n "$pid" ]] && _is_alive "$pid"; then
        echo "  Stopping $label (PID $pid)…"
        kill "$pid" 2>/dev/null || true
        local i=0
        while _is_alive "$pid" && (( i < 10 )); do
            sleep 0.5
            (( i++ )) || true
        done
        if _is_alive "$pid"; then
            echo "  Force-killing $label (PID $pid)…"
            kill -9 "$pid" 2>/dev/null || true
        fi
        echo "  $label stopped."
    elif [[ -n "$pid" ]]; then
        echo "  $label PID $pid not running (stale PID file cleaned up)."
    else
        echo "  $label was not running."
    fi
    rm -f "$f"
}

_wait_backend() {
    local i=0 max=15
    while (( i < max )); do
        if curl -sf "${BACKEND_URL}/health" -o /dev/null 2>/dev/null; then
            return 0
        fi
        sleep 1
        (( i++ )) || true
    done
    return 1
}

_wait_port() {
    local port="$1" max="${2:-20}" i=0
    while (( i < max )); do
        if (echo >/dev/tcp/127.0.0.1/"$port") 2>/dev/null; then
            return 0
        fi
        sleep 1
        (( i++ )) || true
    done
    return 1
}

_port_listening() {
    (echo >/dev/tcp/127.0.0.1/"$1") 2>/dev/null
}

_port_foreign_pid() {
    # Returns PID on port from ss if readable; empty if not found
    ss -tlnp 2>/dev/null \
        | awk -v p=":$1" '$4 ~ p || $4 == "0.0.0.0:"p || $4 == "127.0.0.1:"p || $4 == "*:"p' \
        | grep -o 'pid=[0-9]*' \
        | grep -o '[0-9]*' \
        | head -1 \
        || true
}

# ── start ─────────────────────────────────────────────────────────────────────

cmd_start() {
    _mkdir

    # Clean stale PID files first
    local be_pid ui_pid
    be_pid="$(_read_pid "$BACKEND_PID_FILE")"
    ui_pid="$(_read_pid "$UI_PID_FILE")"

    if [[ -n "$be_pid" ]] && ! _is_alive "$be_pid"; then
        echo "  Removing stale backend PID file (PID $be_pid is gone)."
        rm -f "$BACKEND_PID_FILE"
        be_pid=""
    fi
    if [[ -n "$ui_pid" ]] && ! _is_alive "$ui_pid"; then
        echo "  Removing stale UI PID file (PID $ui_pid is gone)."
        rm -f "$UI_PID_FILE"
        ui_pid=""
    fi

    # Stop repo-owned processes if already running
    if [[ -n "$be_pid" ]] && _is_alive "$be_pid"; then
        echo "  Backend already running — stopping first…"
        _kill_pid_file "Backend" "$BACKEND_PID_FILE"
        be_pid=""
    fi
    if [[ -n "$ui_pid" ]] && _is_alive "$ui_pid"; then
        echo "  UI already running — stopping first…"
        _kill_pid_file "UI" "$UI_PID_FILE"
        ui_pid=""
    fi

    # Warn about foreign processes on our ports
    local foreign_be foreign_ui
    foreign_be="$(_port_foreign_pid $BACKEND_PORT)"
    foreign_ui="$(_port_foreign_pid $UI_PORT)"

    if [[ -n "$foreign_be" ]]; then
        echo ""
        echo "  WARNING: Port $BACKEND_PORT occupied by PID $foreign_be (not ours)."
        echo "  Backend start will fail. Kill that process first, then retry."
        echo ""
    fi
    if [[ -n "$foreign_ui" ]]; then
        echo ""
        echo "  WARNING: Port $UI_PORT occupied by PID $foreign_ui (not ours)."
        echo "  UI start will fail. Kill that process first, then retry."
        echo ""
    fi

    # ── Launch backend ────────────────────────────────────────────────────────
    echo "Starting backend  → port ${BACKEND_PORT}  log: ${BACKEND_LOG}"
    (
        cd "$REPO_ROOT"
        "$VENV/bin/uvicorn" app.main:app \
            --host 127.0.0.1 \
            --port "$BACKEND_PORT" \
            >> "$BACKEND_LOG" 2>&1 &
        echo $!
    ) > "$BACKEND_PID_FILE"
    disown "$(cat "$BACKEND_PID_FILE")" 2>/dev/null || true
    echo "  Backend PID: $(cat "$BACKEND_PID_FILE")"

    # ── Launch UI ─────────────────────────────────────────────────────────────
    echo "Starting UI       → port ${UI_PORT}  log: ${UI_LOG}"
    (
        cd "$REPO_ROOT"
        "$VENV/bin/streamlit" run ui/dashboard.py \
            --server.port "$UI_PORT" \
            --server.address 127.0.0.1 \
            --server.headless true \
            --server.fileWatcherType poll \
            --browser.gatherUsageStats false \
            >> "$UI_LOG" 2>&1 &
        echo $!
    ) > "$UI_PID_FILE"
    disown "$(cat "$UI_PID_FILE")" 2>/dev/null || true
    echo "  UI PID: $(cat "$UI_PID_FILE")"

    # ── Health checks ─────────────────────────────────────────────────────────
    echo ""
    printf "Waiting for backend health  (up to 15s)… "
    if _wait_backend; then
        echo "OK"
    else
        echo "FAILED"
        echo ""
        echo "  Backend did not become healthy. Check log: $BACKEND_LOG"
        echo "  Last 10 lines:"
        tail -n 10 "$BACKEND_LOG" 2>/dev/null | sed 's/^/  /'
        echo ""
        echo "  Start aborted. Run './scripts/ctl.sh stop' to clean up."
        return 1
    fi

    printf "Waiting for UI port ${UI_PORT}   (up to 20s)… "
    if _wait_port "$UI_PORT" 20; then
        echo "OK"
    else
        echo "FAILED"
        echo ""
        echo "  UI did not open on port ${UI_PORT}. Check log: $UI_LOG"
        echo "  Last 10 lines:"
        tail -n 10 "$UI_LOG" 2>/dev/null | sed 's/^/  /'
        echo ""
        echo "  Start aborted. Run './scripts/ctl.sh stop' to clean up."
        return 1
    fi

    # ── Ready ─────────────────────────────────────────────────────────────────
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  OpenClaw is ready                                       ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    printf "║  Backend  : %-46s║\n" "${BACKEND_URL}/health  [OK]"
    printf "║  UI       : %-46s║\n" "${UI_URL}  [OK]"
    echo "╠══════════════════════════════════════════════════════════╣"
    printf "║  Open now : %-46s║\n" "${UI_URL}"
    echo "╚══════════════════════════════════════════════════════════╝"
}

# ── stop ──────────────────────────────────────────────────────────────────────

cmd_stop() {
    echo "Stopping OpenClaw (repo-owned processes only)…"
    _kill_pid_file "Backend" "$BACKEND_PID_FILE"
    _kill_pid_file "UI"      "$UI_PID_FILE"
    echo "Done."
}

# ── restart ───────────────────────────────────────────────────────────────────

cmd_restart() {
    cmd_stop
    echo ""
    cmd_start
}

# ── status ────────────────────────────────────────────────────────────────────

cmd_status() {
    _mkdir 2>/dev/null || true

    echo ""
    echo "OpenClaw status"
    echo "══════════════════════════════════════════════════════════"

    # Backend
    local be_pid be_alive be_health foreign_be
    be_pid="$(_read_pid "$BACKEND_PID_FILE")"
    be_alive=false
    if [[ -n "$be_pid" ]] && _is_alive "$be_pid"; then be_alive=true; fi

    echo ""
    echo "Backend  (canonical port: ${BACKEND_PORT})"
    if [[ "$be_alive" == true ]]; then
        echo "  PID    : ${be_pid}  [running]"
    elif [[ -n "$be_pid" ]]; then
        echo "  PID    : ${be_pid}  [STALE — process gone]"
    else
        echo "  PID    : none (not started via ctl.sh)"
    fi

    if curl -sf "${BACKEND_URL}/health" -o /dev/null 2>/dev/null; then
        echo "  Health : OK   ${BACKEND_URL}/health"
    else
        echo "  Health : FAILING  (${BACKEND_URL}/health not responding)"
    fi

    foreign_be="$(_port_foreign_pid $BACKEND_PORT)"
    if [[ -n "$foreign_be" ]] && [[ "$foreign_be" != "$be_pid" ]]; then
        echo "  !!! Port ${BACKEND_PORT} occupied by foreign PID ${foreign_be} — not ours"
    fi
    echo "  Log    : ${BACKEND_LOG}"

    # UI
    local ui_pid ui_alive foreign_ui
    ui_pid="$(_read_pid "$UI_PID_FILE")"
    ui_alive=false
    if [[ -n "$ui_pid" ]] && _is_alive "$ui_pid"; then ui_alive=true; fi

    echo ""
    echo "UI  (canonical port: ${UI_PORT})"
    if [[ "$ui_alive" == true ]]; then
        echo "  PID    : ${ui_pid}  [running]"
    elif [[ -n "$ui_pid" ]]; then
        echo "  PID    : ${ui_pid}  [STALE — process gone]"
    else
        echo "  PID    : none (not started via ctl.sh)"
    fi

    if _port_listening "$UI_PORT"; then
        echo "  Port   : listening"
    else
        echo "  Port   : not listening"
    fi

    foreign_ui="$(_port_foreign_pid $UI_PORT)"
    if [[ -n "$foreign_ui" ]] && [[ "$foreign_ui" != "$ui_pid" ]]; then
        echo "  !!! Port ${UI_PORT} occupied by foreign PID ${foreign_ui} — not ours"
    fi
    echo "  Log    : ${UI_LOG}"

    # Stale system-managed instance on 8501
    echo ""
    if _port_listening 8501; then
        local pid_8501
        pid_8501="$(_port_foreign_pid 8501)"
        echo "  NOTICE: Port 8501 is occupied (PID ${pid_8501:-unknown}) — likely the"
        echo "          system-managed (zenca/systemd) instance serving OLD code."
        echo "          DO NOT use http://localhost:8501 — it is NOT this repo's dev UI."
    fi

    echo ""
    echo "══════════════════════════════════════════════════════════"
    echo "  Canonical URL : ${UI_URL}"
    echo "══════════════════════════════════════════════════════════"
    echo ""
}

# ── logs ──────────────────────────────────────────────────────────────────────

cmd_logs() {
    if [[ ! -f "$BACKEND_LOG" ]] && [[ ! -f "$UI_LOG" ]]; then
        echo "No log files found. Run './scripts/ctl.sh start' first."
        exit 1
    fi
    echo "Following logs (Ctrl-C to stop)…"
    echo "  Backend : $BACKEND_LOG"
    echo "  UI      : $UI_LOG"
    echo ""
    tail -f "$BACKEND_LOG" "$UI_LOG" 2>/dev/null
}

cmd_logs_backend() {
    [[ -f "$BACKEND_LOG" ]] || { echo "No backend log: $BACKEND_LOG"; exit 1; }
    echo "Following backend log (Ctrl-C to stop)…"
    tail -f "$BACKEND_LOG"
}

cmd_logs_ui() {
    [[ -f "$UI_LOG" ]] || { echo "No UI log: $UI_LOG"; exit 1; }
    echo "Following UI log (Ctrl-C to stop)…"
    tail -f "$UI_LOG"
}

# ── Entrypoint ────────────────────────────────────────────────────────────────

case "${1:-}" in
    start)        cmd_start ;;
    stop)         cmd_stop ;;
    restart)      cmd_restart ;;
    status)       cmd_status ;;
    logs)         cmd_logs ;;
    logs-backend) cmd_logs_backend ;;
    logs-ui)      cmd_logs_ui ;;
    *)
        echo "OpenClaw control script"
        echo ""
        echo "Usage: ./scripts/ctl.sh <command>"
        echo ""
        echo "  start          Start backend + UI, wait for readiness, print URL"
        echo "  stop           Stop repo-owned backend + UI (safe, by PID)"
        echo "  restart        stop then start"
        echo "  status         PIDs, ports, health check, stale-instance warnings, URL"
        echo "  logs           Follow both logs (Ctrl-C to stop)"
        echo "  logs-backend   Follow backend log only"
        echo "  logs-ui        Follow UI log only"
        echo ""
        echo "Canonical ports:"
        echo "  Backend : 127.0.0.1:${BACKEND_PORT}  (matches API_BASE in ui/dashboard.py)"
        echo "  UI      : http://localhost:${UI_PORT}"
        exit 1
        ;;
esac
