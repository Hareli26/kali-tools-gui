#!/usr/bin/env bash
# ============================================================================
# 🍯 SQL honeypot add-on — run on the SACRIFICIAL host, alongside the web pot.
#
#   ⚠️  NEVER on kali.dudaei.com. Same rule as install-honeypot.sh.
#
# Adds a fake MySQL on port 3306 plus a SECOND collector (port 8082) that serves
# the SQL events. Why a second collector rather than sharing the web one: two
# pot processes appending to one JSONL file would interleave and tear lines
# under load. Separate files, separate collectors — each pot is independent,
# and the sensor already handles any number of pots.
#
# Prerequisite: python3 only. The pot is standard-library-only by design.
#
# Usage (on 187.124.189.97, after install-honeypot.sh):
#   sudo HP_PROD_IP=72.62.150.169 ./deploy/add-sql-honeypot.sh
#   sudo HP_TOKEN=<token> HP_PROD_IP=72.62.150.169 ./deploy/add-sql-honeypot.sh
# ============================================================================
set -euo pipefail

HP_DIR="${HP_DIR:-/opt/honeypot}"
HP_LOG_DIR="${HP_LOG_DIR:-/var/log/honeypot}"
HP_SQL_PORT="${HP_SQL_PORT:-3306}"
HP_SQL_COL_PORT="${HP_SQL_COL_PORT:-8082}"
HP_PROD_IP="${HP_PROD_IP:-}"
HP_TOKEN="${HP_TOKEN:-}"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m/!\\\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (sudo)"

if [ "${HP_FORCE:-0}" != "1" ] &&
   { [ -d /opt/kali-gui ] || systemctl list-units --all 2>/dev/null | grep -q kali-gui; }; then
  die "kali-gui is installed here — this looks like PRODUCTION.
     Run this on the sacrificial host only. If you are certain, re-run with HP_FORCE=1."
fi

command -v python3 >/dev/null 2>&1 || die "python3 not found — install it, then re-run."

# Is 3306 already taken (e.g. a real MySQL)? A honeypot must own the port.
if ss -ltn 2>/dev/null | grep -q ":${HP_SQL_PORT}\b"; then
  die "port ${HP_SQL_PORT} is already in use. A real DB must NOT run on the pot host.
     Stop/remove it (e.g. systemctl disable --now mysql) and re-run."
fi

if [ -z "$HP_TOKEN" ]; then
  HP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  say "generated a token for the SQL collector"
fi
[ "${#HP_TOKEN}" -ge 20 ] || die "HP_TOKEN too short (${#HP_TOKEN}) — use 32+ random chars"

say "installing sql_pot to ${HP_DIR}"
mkdir -p "$HP_DIR" "$HP_LOG_DIR"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$SRC/honeypot/sql_pot.py" ] || die "missing $SRC/honeypot/sql_pot.py"
install -m 0644 "$SRC/honeypot/sql_pot.py" "$HP_DIR/sql_pot.py"
[ -f "$HP_DIR/collector.py" ] || install -m 0644 "$SRC/honeypot/collector.py" "$HP_DIR/collector.py"
touch "$HP_LOG_DIR/sql.jsonl"
chown -R nobody:nogroup "$HP_LOG_DIR" 2>/dev/null || chown -R nobody:nobody "$HP_LOG_DIR"

say "writing systemd units"
cat > /etc/systemd/system/sql-pot.service <<EOF
[Unit]
Description=🍯 MySQL honeypot (fake DB, low-interaction bait)
After=network.target

[Service]
Type=simple
User=nobody
Environment=HP_SQL_PORT=${HP_SQL_PORT}
Environment=HP_SQL_EVENTS=${HP_LOG_DIR}/sql.jsonl
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 ${HP_DIR}/sql_pot.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
ReadWritePaths=${HP_LOG_DIR}

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/hp-collector-sql.service <<EOF
[Unit]
Description=📡 Honeypot collector — SQL events (token-protected)
After=network.target

[Service]
Type=simple
User=nobody
Environment=HP_COL_PORT=${HP_SQL_COL_PORT}
Environment=HP_EVENTS=${HP_LOG_DIR}/sql.jsonl
Environment=HP_TOKEN=${HP_TOKEN}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 ${HP_DIR}/collector.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF
chmod 0600 /etc/systemd/system/hp-collector-sql.service

systemctl daemon-reload
systemctl enable --now sql-pot hp-collector-sql
sleep 2
systemctl is-active --quiet sql-pot         || die "sql-pot failed: journalctl -u sql-pot -n 30"
systemctl is-active --quiet hp-collector-sql || die "sql collector failed: journalctl -u hp-collector-sql -n 30"
say "both SQL services are running"

# Firewall: 3306 open to the world (bait), 8082 to production only.
if [ -n "$HP_PROD_IP" ] && command -v ufw >/dev/null 2>&1; then
  say "firewall: 3306 public, ${HP_SQL_COL_PORT} -> ${HP_PROD_IP} only"
  ufw allow "${HP_SQL_PORT}/tcp"                                          >/dev/null 2>&1 || true
  ufw allow from "$HP_PROD_IP" to any port "$HP_SQL_COL_PORT" proto tcp   >/dev/null 2>&1 || true
  ufw deny "${HP_SQL_COL_PORT}/tcp"                                       >/dev/null 2>&1 || true
elif [ -n "$HP_PROD_IP" ]; then
  warn "ufw not present — restrict port ${HP_SQL_COL_PORT} to ${HP_PROD_IP} yourself."
else
  warn "HP_PROD_IP not set — the SQL collector port is world-open (token-protected, but restrict it)."
fi

IP="$(hostname -I | awk '{print $1}')"
echo
say "🍯 SQL honeypot is live"
echo
echo "   bait      : ${IP}:${HP_SQL_PORT}  (fake MySQL — public, that's the point)"
echo "   collector : ${IP}:${HP_SQL_COL_PORT}/events  (token required)"
echo "   events    : ${HP_LOG_DIR}/sql.jsonl"
echo
printf '\033[1;33m   SQL COLLECTOR TOKEN — copy into kali.dudaei.com:\033[0m\n'
printf '\033[1;37m   %s\033[0m\n' "$HP_TOKEN"
echo
echo "   On PRODUCTION, register the SQL pot as a SECOND pot:"
echo "     cd /opt/kali-gui && python3 sensor.py --add sql http://${IP}:${HP_SQL_COL_PORT} <token>"
echo "   or the 🍯 screen -> ➕ הוסף מלכודת (id: sql)."
echo
echo "   Test:  mysql --skip-ssl -h ${IP} -P ${HP_SQL_PORT} -u root -ptest -e 'show databases;'"
echo "   Watch: tail -f ${HP_LOG_DIR}/sql.jsonl"
