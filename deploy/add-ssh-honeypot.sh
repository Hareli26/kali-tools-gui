#!/usr/bin/env bash
# ============================================================================
# 🍯 SSH honeypot add-on — run on the SACRIFICIAL host.
#
#   ⚠️  NEVER on kali.dudaei.com. Same rule as the other pots.
#
# Captures the credentials brute-force bots try against port 22, and always
# rejects them (no shell, ever). Adds a third collector (8083) for the SSH
# events.
#
# ── THE PORT 22 PROBLEM ─────────────────────────────────────────────────────
# Port 22 is where your REAL sshd listens — the way you log in (root+password).
# The honeypot wants 22 too (that's where the attacks are). This script will
# NOT touch your sshd: moving SSH is exactly the kind of change that locks you
# out, so it stays manual. If port 22 is busy, the script installs everything,
# leaves the pot stopped, and prints the safe migration procedure.
#
# Dependency: paramiko — installed into a venv on THIS host only. SSH encrypts
# with AES, which Python's stdlib lacks, so credential capture can't be pure
# stdlib. Production stays stdlib-only.
#
# Usage:
#   sudo HP_PROD_IP=72.62.150.169 ./deploy/add-ssh-honeypot.sh
#   sudo HP_SSH_PORT=2222 HP_PROD_IP=72.62.150.169 ./deploy/add-ssh-honeypot.sh  # test port
# ============================================================================
set -euo pipefail

HP_DIR="${HP_DIR:-/opt/honeypot}"
HP_LOG_DIR="${HP_LOG_DIR:-/var/log/honeypot}"
HP_SSH_PORT="${HP_SSH_PORT:-22}"
HP_SSH_COL_PORT="${HP_SSH_COL_PORT:-8083}"
HP_PROD_IP="${HP_PROD_IP:-}"
HP_TOKEN="${HP_TOKEN:-}"
VENV="$HP_DIR/.venv"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m/!\\\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (sudo)"

if [ "${HP_FORCE:-0}" != "1" ] &&
   { [ -d /opt/kali-gui ] || systemctl list-units --all 2>/dev/null | grep -q kali-gui; }; then
  die "kali-gui is installed here — this looks like PRODUCTION.
     Run this on the sacrificial host only. If you are certain, re-run with HP_FORCE=1."
fi

command -v python3 >/dev/null 2>&1 || die "python3 not found."

# --- token ------------------------------------------------------------------
if [ -z "$HP_TOKEN" ]; then
  HP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  say "generated a token for the SSH collector"
fi
[ "${#HP_TOKEN}" -ge 20 ] || die "HP_TOKEN too short — use 32+ random chars"

# --- paramiko (this host only) ----------------------------------------------
# Prefer the distro package: on Ubuntu `python3 -m venv` silently produces a
# venv WITHOUT pip unless python3-venv is installed, which is exactly what bit
# us. apt's python3-paramiko needs no venv and no pip, and runs under the
# system interpreter. Fall back to a venv only if apt can't provide it.
say "ensuring paramiko is available"
PYBIN=/usr/bin/python3
if python3 -c 'import paramiko' 2>/dev/null; then
  say "paramiko already present (system)"
elif { apt-get install -y python3-paramiko >/dev/null 2>&1 || \
       { apt-get update -qq && apt-get install -y python3-paramiko >/dev/null 2>&1; }; } \
     && python3 -c 'import paramiko' 2>/dev/null; then
  say "installed python3-paramiko via apt"
else
  warn "apt could not provide python3-paramiko — falling back to a venv"
  apt-get install -y python3-venv >/dev/null 2>&1 || true
  rm -rf "$VENV"
  python3 -m venv "$VENV" || die "venv creation failed (apt-get install -y python3-venv)"
  "$VENV/bin/pip" install --quiet paramiko || die "pip install paramiko failed"
  PYBIN="$VENV/bin/python"
fi
say "paramiko $("$PYBIN" -c 'import paramiko; print(paramiko.__version__)') ready via ${PYBIN}"

# --- files ------------------------------------------------------------------
mkdir -p "$HP_DIR" "$HP_LOG_DIR"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$SRC/honeypot/ssh_pot.py" ] || die "missing $SRC/honeypot/ssh_pot.py"
install -m 0644 "$SRC/honeypot/ssh_pot.py" "$HP_DIR/ssh_pot.py"
[ -f "$HP_DIR/collector.py" ] || install -m 0644 "$SRC/honeypot/collector.py" "$HP_DIR/collector.py"

# Pre-generate a stable host key (owned by the pot user; the pot only reads it).
KEYF="$HP_DIR/ssh_host_rsa_key"
if [ ! -f "$KEYF" ]; then
  say "generating a stable SSH host key"
  "$PYBIN" -c "import paramiko; paramiko.RSAKey.generate(2048).write_private_key_file('$KEYF')"
fi
touch "$HP_LOG_DIR/ssh.jsonl"
chown nobody:nogroup "$KEYF" "$HP_LOG_DIR/ssh.jsonl" 2>/dev/null || \
  chown nobody:nobody "$KEYF" "$HP_LOG_DIR/ssh.jsonl"
chmod 600 "$KEYF"

# --- systemd units ----------------------------------------------------------
say "writing systemd units"
# Port <1024 as an unprivileged user needs the bind capability.
cat > /etc/systemd/system/ssh-pot.service <<EOF
[Unit]
Description=🍯 SSH honeypot (credential harvesting, no shell)
After=network.target

[Service]
Type=simple
User=nobody
AmbientCapabilities=CAP_NET_BIND_SERVICE
Environment=HP_SSH_PORT=${HP_SSH_PORT}
Environment=HP_SSH_EVENTS=${HP_LOG_DIR}/ssh.jsonl
Environment=HP_SSH_HOSTKEY=${KEYF}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PYBIN} ${HP_DIR}/ssh_pot.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=${HP_LOG_DIR}

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/hp-collector-ssh.service <<EOF
[Unit]
Description=📡 Honeypot collector — SSH events (token-protected)
After=network.target

[Service]
Type=simple
User=nobody
Environment=HP_COL_PORT=${HP_SSH_COL_PORT}
Environment=HP_EVENTS=${HP_LOG_DIR}/ssh.jsonl
Environment=HP_TOKEN=${HP_TOKEN}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 ${HP_DIR}/collector.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF
chmod 0600 /etc/systemd/system/hp-collector-ssh.service

systemctl daemon-reload
systemctl enable --now hp-collector-ssh
sleep 1
systemctl is-active --quiet hp-collector-ssh || die "ssh collector failed: journalctl -u hp-collector-ssh -n 30"

# --- firewall ---------------------------------------------------------------
if [ -n "$HP_PROD_IP" ] && command -v ufw >/dev/null 2>&1; then
  say "firewall: ${HP_SSH_PORT} public, ${HP_SSH_COL_PORT} -> ${HP_PROD_IP} only"
  ufw allow "${HP_SSH_PORT}/tcp"                                        >/dev/null 2>&1 || true
  ufw allow from "$HP_PROD_IP" to any port "$HP_SSH_COL_PORT" proto tcp >/dev/null 2>&1 || true
  ufw deny "${HP_SSH_COL_PORT}/tcp"                                     >/dev/null 2>&1 || true
  if ! ufw status 2>/dev/null | grep -q "Status: active"; then
    ADM=$(echo "${SSH_CONNECTION:-}" | awk '{print $4}'); ADM=${ADM:-22}
    ufw allow "${ADM}/tcp" >/dev/null 2>&1 || true
    warn "ufw INACTIVE — rules stored, not enforced. Your admin SSH port ${ADM} is allowed."
    warn "enforce with:  ufw --force enable"
  fi
fi

IP="$(hostname -I | awk '{print $1}')"

# --- can we take port 22? ---------------------------------------------------
# If a real sshd holds the port, DO NOT touch it. Install is done; leave the pot
# stopped and hand the user a safe, verify-before-you-commit migration.
PORT_BUSY=0
ss -ltn 2>/dev/null | grep -q ":${HP_SSH_PORT}\b" && PORT_BUSY=1

echo
if [ "$PORT_BUSY" = "1" ]; then
  systemctl stop ssh-pot 2>/dev/null || true
  systemctl disable ssh-pot 2>/dev/null || true
  warn "port ${HP_SSH_PORT} is IN USE (your real sshd). The pot is installed but NOT started."
  echo
  printf '\033[1;37m   Move your admin SSH off 22 SAFELY, then start the pot:\033[0m\n'
  cat <<GUIDE

   Uses an isolated drop-in file so a mistake is one 'rm' away from full revert.
   NEVER close your current session until step 2 confirms the new port works.

   1) Listen on BOTH 22 and 2222 (a bare 'Port 2222' would DROP 22 — this keeps it):
        ufw allow 2222/tcp 2>/dev/null
        printf 'Port 22\\nPort 2222\\n' > /etc/ssh/sshd_config.d/99-hp-migration.conf
        sshd -t && systemctl reload ssh          # sshd -t validates BEFORE reload

   2) In a NEW terminal, CONFIRM the new port before touching anything else:
        ssh -p 2222 root@${IP}

   3) ONLY after that logs in — switch to 2222 only, freeing 22:
        printf 'Port 2222\\n' > /etc/ssh/sshd_config.d/99-hp-migration.conf
        sshd -t && systemctl reload ssh
        ss -ltn | grep ':22 ' || echo 'port 22 is free'

   4) Start the honeypot on the now-free port 22:
        systemctl enable --now ssh-pot
        systemctl status ssh-pot --no-pager | head -5

   Full revert at any point:  rm /etc/ssh/sshd_config.d/99-hp-migration.conf && systemctl reload ssh
GUIDE
else
  systemctl enable --now ssh-pot
  sleep 2
  systemctl is-active --quiet ssh-pot || die "ssh-pot failed: journalctl -u ssh-pot -n 30"
  say "🍯 SSH honeypot is live on ${IP}:${HP_SSH_PORT}"
fi

echo
echo "   collector : ${IP}:${HP_SSH_COL_PORT}/events  (token required)"
echo "   events    : ${HP_LOG_DIR}/ssh.jsonl"
echo
printf '\033[1;33m   SSH COLLECTOR TOKEN — copy into kali.dudaei.com:\033[0m\n'
printf '\033[1;37m   %s\033[0m\n' "$HP_TOKEN"
echo
echo "   On PRODUCTION, register the SSH pot as a THIRD pot:"
echo "     cd /opt/kali-gui && python3 sensor.py --add ssh http://${IP}:${HP_SSH_COL_PORT} <token>"
echo
echo "   Watch: tail -f ${HP_LOG_DIR}/ssh.jsonl   ·   Logs: journalctl -u ssh-pot -f"
