# Kali Tools GUI - launcher (Windows)
# Starts the Python backend INSIDE Kali WSL as ROOT (passwordless via -u root)
# so all tools (nmap -sS, tcpdump, masscan, ...) and apt installs work.
$ErrorActionPreference = "Stop"
$port = 8777
Write-Host "Starting Kali Tools GUI backend inside WSL (kali-linux, root)..." -ForegroundColor Green
# Launch server in a new window; WSL2 forwards localhost automatically.
Start-Process -FilePath "wsl.exe" -ArgumentList @(
  "-d", "kali-linux", "-u", "root", "--",
  "python3", "/mnt/c/ClaudeCode/kali-gui/server.py"
)
Start-Sleep -Seconds 2
Write-Host "Opening http://localhost:$port ..." -ForegroundColor Green
Start-Process "http://localhost:$port"
Write-Host ""
Write-Host "To stop: close the WSL window, or run:  wsl -d kali-linux -- pkill -f server.py" -ForegroundColor Yellow
