#!/usr/bin/env bash
# ============================================================
#  Kali Tools GUI - secure VPS installer (Ubuntu/Debian)
#  by Hareli Dudai
#
#  Sets up:  Internet -> Caddy(443,TLS) -> oauth2-proxy(Google) -> app(127.0.0.1)
#  The app NEVER binds a public interface. Auth = Google login + email allowlist.
#
#  Usage (as root, from the repo root):
#     cp deploy/deploy.env.example deploy/deploy.env   # then edit it
#     sudo bash deploy/install-vps.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)."; exit 1; }
[ -f "$SCRIPT_DIR/deploy.env" ] || { echo "Missing deploy/deploy.env - copy deploy.env.example and fill it."; exit 1; }
# shellcheck disable=SC1090
source "$SCRIPT_DIR/deploy.env"

echo "==> [1/9] Installing base packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 curl ca-certificates gnupg ufw fail2ban tar debian-keyring debian-archive-keyring apt-transport-https

echo "==> [2/9] Installing a curated set of security tools (best-effort)..."
TOOLS="nmap nikto hydra sqlmap dnsenum dnsrecon whatweb wafw00f dnsutils whois \
nbtscan smbclient john hashcat sslscan wapiti masscan gobuster ffuf exiftool \
binwalk foremost netcat-traditional traceroute iputils-ping wget dirb medusa ncrack crunch"
for t in $TOOLS; do apt-get install -y "$t" >/dev/null 2>&1 || echo "   (skipped: $t)"; done

echo "==> [3/9] Deploying app to $APP_DIR ..."
mkdir -p "$APP_DIR"
if [ "$REPO_ROOT" != "$APP_DIR" ]; then
  cp -rf "$REPO_ROOT/." "$APP_DIR/"
fi
mkdir -p "$APP_DIR/reports"

echo "==> [3b] Setting up MCP server venv (optional)..."
apt-get install -y python3-venv >/dev/null 2>&1 || true
if python3 -m venv "$APP_DIR/.venv" 2>/dev/null; then
  "$APP_DIR/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/mcp/requirements.txt" 2>/dev/null \
    && echo "   MCP venv ready: $APP_DIR/.venv" || echo "   (MCP deps skipped - no internet?)"
fi

echo "==> [4/9] Installing Caddy (auto-HTTPS reverse proxy)..."
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y caddy
fi

echo "==> [5/9] Installing oauth2-proxy v${OAUTH2_PROXY_VERSION}..."
if ! command -v oauth2-proxy >/dev/null 2>&1; then
  cd /tmp
  curl -sSLo o2p.tgz "https://github.com/oauth2-proxy/oauth2-proxy/releases/download/v${OAUTH2_PROXY_VERSION}/oauth2-proxy-v${OAUTH2_PROXY_VERSION}.linux-amd64.tar.gz"
  tar xzf o2p.tgz
  install -m 0755 oauth2-proxy-*/oauth2-proxy /usr/local/bin/oauth2-proxy
  rm -rf /tmp/o2p.tgz /tmp/oauth2-proxy-*
fi

echo "==> [6/9] Writing configuration..."
COOKIE_SECRET="$(python3 -c 'import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
# seed the allowlist with the admin if the file lacks it
touch "$APP_DIR/deploy/authenticated-emails.txt"
grep -qxF "$ADMIN_EMAIL" "$APP_DIR/deploy/authenticated-emails.txt" 2>/dev/null || echo "$ADMIN_EMAIL" >> "$APP_DIR/deploy/authenticated-emails.txt"

cat > /etc/oauth2-proxy.cfg <<EOF
provider = "google"
client_id = "${GOOGLE_CLIENT_ID}"
client_secret = "${GOOGLE_CLIENT_SECRET}"
cookie_secret = "${COOKIE_SECRET}"
redirect_url = "https://${DOMAIN}/oauth2/callback"
authenticated_emails_file = "${APP_DIR}/deploy/authenticated-emails.txt"
http_address = "127.0.0.1:4180"
upstreams = ["http://127.0.0.1:8777"]
reverse_proxy = true
pass_user_headers = true
set_xauthrequest = true
cookie_secure = true
cookie_httponly = true
skip_provider_button = false
EOF
# Dedicated non-root user for oauth2-proxy that owns (and can read) its config
useradd --system --no-create-home --shell /usr/sbin/nologin oauth2-proxy 2>/dev/null || true
chown oauth2-proxy:oauth2-proxy /etc/oauth2-proxy.cfg
chmod 600 /etc/oauth2-proxy.cfg
chmod 644 "$APP_DIR/deploy/authenticated-emails.txt"

cat > /etc/caddy/Caddyfile <<EOF
${DOMAIN} {
    encode gzip
    reverse_proxy 127.0.0.1:4180
    log {
        output file /var/log/caddy/kali-gui-access.log
    }
}
EOF
mkdir -p /var/log/caddy

echo "==> [7/9] Installing systemd services..."
cat > /etc/systemd/system/kali-gui.service <<EOF
[Unit]
Description=Kali Tools GUI backend (localhost only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/python3 ${APP_DIR}/server.py
Environment=KALIGUI_HOST=127.0.0.1
Environment=KALIGUI_PORT=8777
Environment=KALIGUI_TOKEN=${KALIGUI_TOKEN}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/oauth2-proxy.service <<EOF
[Unit]
Description=oauth2-proxy (Google auth in front of Kali Tools GUI)
After=network-online.target kali-gui.service
Wants=network-online.target

[Service]
Type=simple
User=oauth2-proxy
ExecStart=/usr/local/bin/oauth2-proxy --config=/etc/oauth2-proxy.cfg
Restart=on-failure
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now kali-gui.service
systemctl enable --now oauth2-proxy.service
systemctl enable --now caddy
systemctl restart caddy

echo "==> [8/9] Firewall (ufw): allow SSH/HTTP/HTTPS only..."
ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now fail2ban >/dev/null 2>&1 || true

echo "==> [9/9] Health check..."
sleep 3
curl -s http://127.0.0.1:8777/api/health || echo "(app health failed - check: journalctl -u kali-gui)"
echo
echo "============================================================"
echo " Done. Open:  https://${DOMAIN}"
echo " Approve users:  edit ${APP_DIR}/deploy/authenticated-emails.txt"
echo "                 then: systemctl restart oauth2-proxy"
echo " Audit logs:"
echo "   - who ran what : ${APP_DIR}/audit.log"
echo "   - who logged in: journalctl -u oauth2-proxy"
echo "   - access log   : /var/log/caddy/kali-gui-access.log"
echo "============================================================"
