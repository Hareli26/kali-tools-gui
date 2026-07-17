#!/usr/bin/env bash
# ============================================================================
# 🛰️ Sensor installer — run this on PRODUCTION (kali.dudaei.com).
#
# Installs a systemd timer that polls every registered honeypot on a schedule,
# so attacks show up in the UI without anyone pressing "משוך עכשיו".
#
# The pots themselves are installed by deploy/install-honeypot.sh on the
# SACRIFICIAL host. This script only sets up the pulling side.
#
# Usage:
#   sudo ./install-sensor.sh
#   sudo SENSOR_INTERVAL=60 ./install-sensor.sh
#   sudo POT_ID=web POT_URL=http://187.124.189.97:8081 POT_TOKEN=<t> ./install-sensor.sh
# ============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/kali-gui}"
SENSOR_INTERVAL="${SENSOR_INTERVAL:-60}"      # seconds between polls
POT_ID="${POT_ID:-}"
POT_URL="${POT_URL:-}"
POT_TOKEN="${POT_TOKEN:-}"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m/!\\\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (sudo)"
[ -f "$APP_DIR/sensor.py" ] || die "sensor.py not found in ${APP_DIR} — git pull first"

# --- optionally register a pot ---------------------------------------------
if [ -n "$POT_ID" ] && [ -n "$POT_URL" ] && [ -n "$POT_TOKEN" ]; then
  say "registering pot '${POT_ID}' -> ${POT_URL}"
  ( cd "$APP_DIR" && python3 sensor.py --add "$POT_ID" "$POT_URL" "$POT_TOKEN" )
fi

# --- reachability check -----------------------------------------------------
# Fail here rather than after the timer is silently erroring every minute.
if [ -n "$POT_URL" ]; then
  say "checking the collector is reachable"
  if curl -fsS --max-time 8 "${POT_URL%/}/health" >/dev/null 2>&1; then
    say "collector responded"
  else
    warn "could not reach ${POT_URL%/}/health"
    warn "check: the pot's firewall allows THIS host, and hp-collector is running there."
  fi
fi

# --- systemd service + timer ------------------------------------------------
say "installing the poll timer (every ${SENSOR_INTERVAL}s)"
cat > /etc/systemd/system/kali-sensor.service <<EOF
[Unit]
Description=🛰️ Honeypot sensor — pull, classify, learn
After=network.target

[Service]
Type=oneshot
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${APP_DIR}/deploy.env
ExecStart=/usr/bin/python3 ${APP_DIR}/sensor.py --once
# Reads honeypot data (untrusted input) — it never runs a tool or applies a fix.
NoNewPrivileges=true
PrivateTmp=true
EOF

cat > /etc/systemd/system/kali-sensor.timer <<EOF
[Unit]
Description=🛰️ Poll the honeypots every ${SENSOR_INTERVAL}s

[Timer]
OnBootSec=90
OnUnitActiveSec=${SENSOR_INTERVAL}
AccuracySec=5s
Unit=kali-sensor.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now kali-sensor.timer
say "timer enabled"

# --- first run --------------------------------------------------------------
say "running one poll now"
systemctl start kali-sensor.service || true
sleep 2
( cd "$APP_DIR" && python3 sensor.py --list ) || true

echo
say "🛰️ sensor is live"
echo
echo "   status : systemctl status kali-sensor.timer"
echo "   logs   : journalctl -u kali-sensor -f"
echo "   pots   : cd ${APP_DIR} && python3 sensor.py --list"
echo "   manual : cd ${APP_DIR} && python3 sensor.py --once"
echo
echo "   Attacks appear in the 🍯 מלכודות screen on kali.dudaei.com."
