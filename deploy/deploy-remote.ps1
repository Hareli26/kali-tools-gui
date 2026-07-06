# ============================================================
#  Kali Tools GUI - remote VPS deploy (run from Windows)
#  by Hareli Dudai
#
#  Transfers nothing manually: it SSHes to your VPS, clones the repo,
#  writes deploy.env, and runs the secure installer.
#
#  Requires: key-based SSH already working to the VPS (no password prompt).
#  Test first:  ssh <user>@<host> echo ok
#
#  Example:
#    ./deploy/deploy-remote.ps1 -VpsHost 1.2.3.4 -Domain kali.example.com `
#        -ClientId "xxx.apps.googleusercontent.com" -ClientSecret "GOCSPX-xxx"
# ============================================================
param(
  [Parameter(Mandatory=$true)][string]$VpsHost,
  [string]$VpsUser = "root",
  [Parameter(Mandatory=$true)][string]$Domain,
  [Parameter(Mandatory=$true)][string]$ClientId,
  [Parameter(Mandatory=$true)][string]$ClientSecret,
  [string]$AdminEmail = "hareli26@gmail.com",
  [string]$KeyPath = ""
)
$ErrorActionPreference = "Stop"
$target = "$VpsUser@$VpsHost"
$sshArgs = @("-o","BatchMode=yes","-o","StrictHostKeyChecking=accept-new")
if ($KeyPath) { $sshArgs += @("-i", $KeyPath) }

Write-Host "==> Testing SSH to $target ..." -ForegroundColor Cyan
$probe = & ssh @sshArgs $target "echo connected" 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "SSH failed (need passwordless key auth)." -ForegroundColor Red
  Write-Host "Set it up once with:  ssh-copy-id $target   (or provide -KeyPath)" -ForegroundColor Yellow
  Write-Host "Details: $probe"
  exit 1
}
Write-Host "    OK: $probe" -ForegroundColor Green

$runner = if ($VpsUser -eq "root") { "bash -s" } else { "sudo bash -s" }

$remote = @"
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y git
if [ -d /opt/kali-gui/.git ]; then cd /opt/kali-gui && git pull; else git clone https://github.com/Hareli26/kali-tools-gui.git /opt/kali-gui; fi
cd /opt/kali-gui
cat > deploy/deploy.env <<ENVEOF
DOMAIN="$Domain"
GOOGLE_CLIENT_ID="$ClientId"
GOOGLE_CLIENT_SECRET="$ClientSecret"
ADMIN_EMAIL="$AdminEmail"
APP_DIR="/opt/kali-gui"
OAUTH2_PROXY_VERSION="7.6.0"
KALIGUI_TOKEN=""
ENVEOF
bash deploy/install-vps.sh
"@

Write-Host "==> Running the secure installer on the VPS (a few minutes)..." -ForegroundColor Cyan
$remote | & ssh @sshArgs $target $runner
Write-Host ""
Write-Host "==> Done. Open: https://$Domain" -ForegroundColor Green
Write-Host "    Approve users: edit /opt/kali-gui/deploy/authenticated-emails.txt on the VPS, then: systemctl restart oauth2-proxy" -ForegroundColor DarkGray
