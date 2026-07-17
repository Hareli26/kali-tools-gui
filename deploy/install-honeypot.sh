#!/usr/bin/env bash
# ============================================================================
# 🍯 Honeypot installer — run this on the SACRIFICIAL host ONLY.
#
#   ⚠️  NEVER run this on kali.dudaei.com (72.62.150.169).
#       This host is one you are inviting people to break into. If it shared a
#       box with production, a successful break-in would land on the machine
#       holding the DB, the audit log and the OAuth config.
#
# Installs: web_pot (public bait) + collector (token-protected pull endpoint),
# as two separate hardened systemd units, optionally behind Caddy for HTTPS.
#
# Prerequisites: python3 only. The pots are standard-library-only by design —
# no pip, no apt packages, nothing to install. That is deliberate: this box's
# apt is broken (half-migrated Ubuntu/Kali), and a honeypot you cannot deploy
# is a honeypot you do not have.
#
# Usage:
#   sudo ./install-honeypot.sh
#   sudo HP_TOKEN=<token> HP_DOMAIN=web.dudaei.com HP_PROD_IP=72.62.150.169 \
#        ./install-honeypot.sh
# ============================================================================
set -euo pipefail

HP_DIR="${HP_DIR:-/opt/honeypot}"
HP_LOG_DIR="${HP_LOG_DIR:-/var/log/honeypot}"
HP_PORT="${HP_PORT:-8080}"
HP_COL_PORT="${HP_COL_PORT:-8081}"
HP_DOMAIN="${HP_DOMAIN:-}"
HP_PROD_IP="${HP_PROD_IP:-}"
HP_SITE="${HP_SITE:-Dudaei Logistics Ltd}"
HP_TOKEN="${HP_TOKEN:-}"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m/!\\\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (sudo)"

# --- guard: refuse to install on the production box -------------------------
# A honeypot on production defeats the entire point of the separation.
if [ "${HP_FORCE:-0}" != "1" ] &&
   { [ -d /opt/kali-gui ] || systemctl list-units --all 2>/dev/null | grep -q kali-gui; }; then
  die "kali-gui is installed here — this looks like PRODUCTION.
     Run this on the sacrificial host only. If you are certain, re-run with HP_FORCE=1."
fi

# --- prerequisites ----------------------------------------------------------
say "checking prerequisites"
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — attempting to install"
  if command -v apt-get >/dev/null 2>&1; then
    # This box's apt may be broken; try, but do not let it abort the script.
    apt-get update -qq  || warn "apt update failed (expected on this host) — continuing"
    apt-get install -y --no-install-recommends python3 \
      || die "could not install python3 via apt. Install it manually, then re-run.
     The pots need nothing else — standard library only."
  else
    die "no python3 and no apt-get. Install python3 manually, then re-run."
  fi
fi
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
say "python3 ${PYV} present — no other packages required (stdlib only)"
python3 - <<'EOF' || exit 1
import sys
if sys.version_info < (3, 7):
    sys.exit("FATAL: python 3.7+ required (uses stream.reconfigure)")
EOF

# --- token ------------------------------------------------------------------
if [ -z "$HP_TOKEN" ]; then
  HP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  say "generated a collector token"
fi
[ "${#HP_TOKEN}" -ge 20 ] || die "HP_TOKEN too short (${#HP_TOKEN}) — use 32+ random chars"

# --- files ------------------------------------------------------------------
say "installing to ${HP_DIR}"
mkdir -p "$HP_DIR" "$HP_LOG_DIR"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for f in web_pot.py collector.py; do
  [ -f "$SRC/honeypot/$f" ] || die "missing $SRC/honeypot/$f"
  install -m 0644 "$SRC/honeypot/$f" "$HP_DIR/$f"
done
# The pot runs as nobody and must only ever write its event log.
touch "$HP_LOG_DIR/web.jsonl"
chown -R nobody:nogroup "$HP_LOG_DIR" 2>/dev/null || chown -R nobody:nobody "$HP_LOG_DIR"
chmod 0755 "$HP_LOG_DIR"

# --- systemd: the bait ------------------------------------------------------
say "writing systemd units"
cat > /etc/systemd/system/web-pot.service <<EOF
[Unit]
Description=🍯 Web honeypot (low-interaction bait)
After=network.target

[Service]
Type=simple
User=nobody
Environment=HP_PORT=${HP_PORT}
Environment=HP_EVENTS=${HP_LOG_DIR}/web.jsonl
Environment=HP_SITE=${HP_SITE}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 ${HP_DIR}/web_pot.py
Restart=always
RestartSec=3
# This process is internet-exposed by design — give it nothing to work with.
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
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

# --- systemd: the management channel ---------------------------------------
# Separate unit from the bait on purpose: the bait is touched by attackers,
# this is not. Independent bind, firewall and restart.
cat > /etc/systemd/system/hp-collector.service <<EOF
[Unit]
Description=📡 Honeypot collector (token-protected pull endpoint)
After=network.target

[Service]
Type=simple
User=nobody
Environment=HP_COL_PORT=${HP_COL_PORT}
Environment=HP_EVENTS=${HP_LOG_DIR}/web.jsonl
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
# The token sits in this unit file — keep it out of other users' reach.
chmod 0600 /etc/systemd/system/hp-collector.service

systemctl daemon-reload
systemctl enable --now web-pot hp-collector
sleep 2
systemctl is-active --quiet web-pot     || die "web-pot failed to start: journalctl -u web-pot -n 30"
systemctl is-active --quiet hp-collector || die "collector failed: journalctl -u hp-collector -n 30"
say "both services are running"

# --- firewall ---------------------------------------------------------------
# The bait must be reachable by everyone; the collector by production only.
if [ -n "$HP_PROD_IP" ] && command -v ufw >/dev/null 2>&1; then
  say "restricting collector port ${HP_COL_PORT} to ${HP_PROD_IP}"
  ufw allow "${HP_PORT}/tcp"                          >/dev/null 2>&1 || true
  ufw allow 80/tcp && ufw allow 443/tcp               >/dev/null 2>&1 || true
  ufw allow from "$HP_PROD_IP" to any port "$HP_COL_PORT" proto tcp >/dev/null 2>&1 || true
  ufw deny "${HP_COL_PORT}/tcp"                       >/dev/null 2>&1 || true
elif [ -n "$HP_PROD_IP" ]; then
  warn "ufw not present — restrict port ${HP_COL_PORT} to ${HP_PROD_IP} yourself:"
  echo "     iptables -A INPUT -p tcp --dport ${HP_COL_PORT} -s ${HP_PROD_IP} -j ACCEPT"
  echo "     iptables -A INPUT -p tcp --dport ${HP_COL_PORT} -j DROP"
else
  warn "HP_PROD_IP not set — the collector port is open to the world."
  warn "It is token-protected, but restrict it to production anyway."
fi

# --- Caddy (optional) -------------------------------------------------------
if [ -n "$HP_DOMAIN" ]; then
  if command -v caddy >/dev/null 2>&1; then
    say "configuring Caddy for ${HP_DOMAIN}"
    cat > /etc/caddy/Caddyfile <<EOF
${HP_DOMAIN} {
    reverse_proxy 127.0.0.1:${HP_PORT}
}
EOF
    systemctl reload caddy || systemctl restart caddy || warn "reload Caddy manually"
  else
    warn "caddy not installed — the pot is served on :${HP_PORT} over plain HTTP."
    warn "That is fine for a honeypot; install caddy if you want HTTPS on ${HP_DOMAIN}."
  fi
fi

# --- done -------------------------------------------------------------------
echo
say "🍯 honeypot is live"
echo
echo "   bait      : http://$(hostname -I | awk '{print $1}'):${HP_PORT}/   (public — that's the point)"
echo "   collector : http://$(hostname -I | awk '{print $1}'):${HP_COL_PORT}/events  (token required)"
echo "   events    : ${HP_LOG_DIR}/web.jsonl"
echo
printf '\033[1;33m   COLLECTOR TOKEN — copy this into kali.dudaei.com now:\033[0m\n'
printf '\033[1;37m   %s\033[0m\n' "$HP_TOKEN"
echo
echo "   Next, on PRODUCTION (kali.dudaei.com):"
echo "     open the 🍯 מלכודות screen -> ➕ הוסף מלכודת"
echo "       id    : web"
echo "       url   : http://${HP_DOMAIN:-$(hostname -I | awk '{print $1}')}:${HP_COL_PORT}"
echo "       token : (the token above)"
echo "     or:  cd /opt/kali-gui && python3 sensor.py --add web http://...:${HP_COL_PORT} <token>"
echo
echo "   Verify:  curl -s localhost:${HP_COL_PORT}/health"
echo "   Watch :  tail -f ${HP_LOG_DIR}/web.jsonl"
echo "   Logs  :  journalctl -u web-pot -f"
