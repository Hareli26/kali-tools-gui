# ============================================================
#  Kali Tools GUI — Full Installer
#  Author: Hareli D.  (hareli26@gmail.com)
# ============================================================
#  Installs the app as an always-on service inside Kali WSL:
#   1. verifies WSL + Kali + Python
#   2. fixes WSL DNS (so external targets resolve)
#   3. installs the systemd service (auto-start + auto-restart)
#   4. registers a Windows logon task (boots WSL after sign-in)
#   5. health-checks and opens the browser
# ============================================================
$ErrorActionPreference = "Stop"
$Distro  = "kali-linux"
$Root    = "/mnt/c/ClaudeCode/kali-gui"
$Port    = 8777

function Info($m){ Write-Host $m -ForegroundColor Cyan }
function Ok($m){ Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "  [!] $m" -ForegroundColor Yellow }
function Fail($m){ Write-Host "  [X] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "==================================================" -ForegroundColor Magenta
Write-Host "   Kali Tools GUI - Installer  (by Hareli D.)"       -ForegroundColor Magenta
Write-Host "==================================================" -ForegroundColor Magenta
Write-Host ""

# --- 1. prerequisites -------------------------------------------------------
Info "1/5  Checking prerequisites..."
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
  Fail "WSL is not installed. Run:  wsl --install  then reboot and re-run this."
  exit 1
}
$distros = (wsl.exe -l -q) -replace "`0",""
if ($distros -notmatch $Distro) {
  Fail "'$Distro' distro not found. Install it:  wsl --install -d $Distro"
  exit 1
}
Ok "WSL + $Distro present"
$py = (wsl.exe -d $Distro -u root -- bash -lc "command -v python3 || true").Trim()
if (-not $py) {
  Warn "python3 not found; installing..."
  wsl.exe -d $Distro -u root -- bash -lc "apt-get update -qq && apt-get install -y python3"
}
Ok "python3 available"

# --- 2. DNS fix -------------------------------------------------------------
Info "2/5  Ensuring WSL DNS resolves external targets..."
wsl.exe -d $Distro -u root -- bash -lc "grep -q 'generateResolvConf = false' /etc/wsl.conf 2>/dev/null || printf '[network]\ngenerateResolvConf = false\n' > /etc/wsl.conf; if ! grep -q '8.8.8.8' /etc/resolv.conf 2>/dev/null; then rm -f /etc/resolv.conf; printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' > /etc/resolv.conf; fi"
Ok "DNS configured"

# --- 3. systemd service -----------------------------------------------------
Info "3/5  Installing the systemd service..."
wsl.exe -d $Distro -u root -- bash "$Root/install-service.sh"

# --- 4. Windows logon task --------------------------------------------------
Info "4/5  Registering Windows logon task (boots WSL at sign-in)..."
$taskName = "KaliToolsGUI-Boot"
try {
  $action   = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $Distro -u root -- systemctl start kali-gui"
  $trigger  = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Ok "Logon task '$taskName' registered"
} catch {
  Warn "Could not register logon task (run as Administrator for boot persistence)."
}

# --- 5. verify --------------------------------------------------------------
Info "5/5  Verifying..."
Start-Sleep -Seconds 2
try {
  $h = (Invoke-WebRequest "http://localhost:$Port/api/health" -UseBasicParsing -TimeoutSec 8).Content
  Ok "Service healthy: $h"
  Start-Process "http://localhost:$Port"
} catch {
  Fail "Health check failed. Check logs:  wsl -d $Distro -u root -- journalctl -u kali-gui -n 50"
}

Write-Host ""
Write-Host "Done. Open:  http://localhost:$Port" -ForegroundColor Green
Write-Host "Manage:  wsl -d $Distro -u root -- systemctl {status|restart|stop} kali-gui" -ForegroundColor DarkGray
Write-Host ""
