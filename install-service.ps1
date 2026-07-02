# Production install for Kali Tools GUI (run in PowerShell).
# 1) Installs the systemd service inside Kali WSL (auto-start + auto-restart).
# 2) Registers a Windows logon task that boots WSL, so the service is up
#    after every Windows sign-in (systemd then starts the enabled service).
$ErrorActionPreference = "Stop"

Write-Host "==> Installing systemd service inside Kali WSL..." -ForegroundColor Cyan
wsl.exe -d kali-linux -u root -- bash /mnt/c/ClaudeCode/kali-gui/install-service.sh

Write-Host ""
Write-Host "==> Registering Windows logon task to boot WSL at sign-in..." -ForegroundColor Cyan
$taskName = "KaliToolsGUI-Boot"
$action   = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d kali-linux -u root -- systemctl start kali-gui"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
try {
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Write-Host "    Registered scheduled task '$taskName'." -ForegroundColor Green
} catch {
  Write-Host "    Could not register task (need elevated PowerShell?). You can add it manually." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==> Done. Open http://localhost:8777" -ForegroundColor Green
Write-Host "    Manage:  wsl -d kali-linux -u root -- systemctl {status|restart|stop} kali-gui" -ForegroundColor DarkGray
Write-Host "    Logs:    wsl -d kali-linux -u root -- journalctl -u kali-gui -n 50 --no-pager" -ForegroundColor DarkGray
