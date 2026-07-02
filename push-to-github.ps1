# Push Kali Tools GUI to GitHub.
# Run once. It will prompt you to log in to GitHub the first time (browser).
$ErrorActionPreference = "Stop"
$env:PATH += ";C:\Program Files\GitHub CLI;C:\Program Files\Git\cmd"
Set-Location "C:\ClaudeCode\kali-gui"

# 1) Authenticate (opens browser / device code). Skips if already logged in.
gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Logging in to GitHub..." -ForegroundColor Yellow
  gh auth login
}

# 2) Create the GitHub repo from this folder and push.
#    Change the name/visibility as you like.
$RepoName    = "kali-tools-gui"
$Visibility  = "--public"       # or "--private"
$Description  = "Kali Tools GUI - web interface + AI agent layer for Kali Linux tools under WSL2"

gh repo create $RepoName $Visibility --source "." --remote "origin" --description $Description --push

Write-Host ""
Write-Host "Done. Repo URL:" -ForegroundColor Green
gh repo view --json url --jq .url
