# ============================================================
#  Push Kali Tools GUI to GitHub   (by Hareli Dudai)
# ============================================================
#  Run this once. It logs you in to GitHub the first time
#  (opens a browser), then creates the repo and pushes.
#  Safe to re-run: if the repo already exists it just pushes.
# ============================================================
$ErrorActionPreference = "Stop"
$env:PATH += ";C:\Program Files\GitHub CLI;C:\Program Files\Git\cmd"
Set-Location "C:\ClaudeCode\kali-gui"

$RepoName   = "kali-tools-gui"
$Visibility = "public"        # or "private"
$Desc       = "Kali Tools GUI - web console + AI purple-team agents for Kali Linux under WSL2 (by Hareli Dudai)"

# 1) Authenticate (opens browser / device code). Skips if already logged in.
gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Logging in to GitHub (a browser window will open)..." -ForegroundColor Yellow
  gh auth login
}
$me = (gh api user --jq .login).Trim()
Write-Host "Authenticated as: $me" -ForegroundColor Green

# 2) Ensure there is a commit
git rev-parse --verify HEAD *> $null
if ($LASTEXITCODE -ne 0) { git add -A; git commit -m "Initial commit" | Out-Null }

# 3) Create the repo if it doesn't exist yet
$exists = $false
gh repo view "$me/$RepoName" *> $null
if ($LASTEXITCODE -eq 0) { $exists = $true }

if (-not $exists) {
  Write-Host "Creating GitHub repo $me/$RepoName ..." -ForegroundColor Cyan
  gh repo create $RepoName --$Visibility --source "." --remote origin --description $Desc --push
} else {
  Write-Host "Repo already exists - pushing latest..." -ForegroundColor Cyan
  git remote get-url origin *> $null
  if ($LASTEXITCODE -ne 0) { git remote add origin "https://github.com/$me/$RepoName.git" }
  git branch -M main
  git push -u origin main
}

Write-Host ""
Write-Host "Done. Repo URL:" -ForegroundColor Green
gh repo view "$me/$RepoName" --json url --jq .url
