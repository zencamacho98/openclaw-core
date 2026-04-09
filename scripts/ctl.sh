#!/usr/bin/env bash
# scripts/ctl.sh
# OpenClaw service control helper.
# Usage: ./scripts/ctl.sh <command>

set -e

SERVICES="openclaw-backend openclaw-ui"

case "${1:-}" in
  start)
    sudo systemctl start $SERVICES
    echo "Started."
    ;;
  stop)
    sudo systemctl stop openclaw-ui openclaw-backend
    echo "Stopped."
    ;;
  restart)
    sudo systemctl restart $SERVICES
    echo "Restarted."
    ;;
  status)
    for svc in $SERVICES; do
      echo "── $svc ────────────────────────────────"
      sudo systemctl status "$svc" --no-pager -l
      echo ""
    done
    ;;
  logs-backend)
    sudo journalctl -u openclaw-backend -f --no-pager
    ;;
  logs-ui)
    sudo journalctl -u openclaw-ui -f --no-pager
    ;;
  logs)
    sudo journalctl -u openclaw-backend -u openclaw-ui -f --no-pager
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|logs-backend|logs-ui}"
    exit 1
    ;;
esac
