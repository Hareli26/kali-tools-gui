#!/bin/bash
# Install Kali Tools GUI as a systemd service (run as root inside Kali WSL).
#   wsl -d kali-linux -u root -- bash /mnt/c/ClaudeCode/kali-gui/install-service.sh
set -e
UNIT=/etc/systemd/system/kali-gui.service
SRC=/mnt/c/ClaudeCode/kali-gui/docs/kali-gui.service

echo "[*] Stopping any ad-hoc server on port 8777..."
pkill -f "kali-gui/server.py" 2>/dev/null || true
sleep 1

echo "[*] Installing unit -> $UNIT"
cp "$SRC" "$UNIT"

echo "[*] Reloading systemd and enabling service..."
systemctl daemon-reload
systemctl enable kali-gui
systemctl restart kali-gui
sleep 2

echo "[*] Status:"
systemctl --no-pager --full status kali-gui | head -14 || true
echo
echo "[*] Health:"
curl -s http://127.0.0.1:8777/api/health || echo "(health check failed)"
echo
echo "[✓] Done. The service will now start automatically whenever Kali WSL boots."
