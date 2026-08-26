# One-time install of the Pitaya TDC web app onto a STEMlab.
# After this, start/stop is the home-page tile (no SSH).
#
# Usage (from anywhere):
#   powershell -File rp_app\install.ps1 -HostName rp-f0cebb.local
#
# Requires: OpenSSH client (scp/ssh), a built fpga\output\tdc.bit

param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [string]$User = "root"
)

$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $PSScriptRoot
$AppSrc = Join-Path $PSScriptRoot "pitaya_tdc"
$Bit = Join-Path $Repo "fpga\output\tdc.bit"
$Target = "${User}@${HostName}"
$RemoteApps = "/opt/redpitaya/www/apps"
$RemoteApp = "$RemoteApps/pitaya_tdc"

if (-not (Test-Path $Bit)) {
    throw "Missing $Bit. Build first: powershell -File fpga\tcl\build.ps1"
}

foreach ($name in @("tdc_server.py", "tdc_regs.py", "bit_to_bin.py")) {
    $p = Join-Path $Repo "sw\$name"
    if (-not (Test-Path $p)) {
        throw "Missing $p"
    }
}

Write-Host "Remounting /opt/redpitaya read-write on $HostName ..."
ssh $Target "rw >/dev/null 2>&1 || mount -o remount,rw /opt/redpitaya; rm -rf $RemoteApps/femto_tdc; mkdir -p $RemoteApp/fpga $RemoteApp/info $RemoteApp/css $RemoteApp/js $RemoteApp/src"

Write-Host "Copying app, Python server, and bitstream ..."
scp `
    "$AppSrc\index.html" `
    "$AppSrc\nginx.conf" `
    "$AppSrc\Makefile" `
    "$AppSrc\fpga.sh" `
    "$AppSrc\restore_fpga.sh" `
    "${Target}:${RemoteApp}/"
scp -r "$AppSrc\info" "${Target}:${RemoteApp}/"
scp -r "$AppSrc\css" "${Target}:${RemoteApp}/"
scp -r "$AppSrc\js" "${Target}:${RemoteApp}/"
scp -r "$AppSrc\src" "${Target}:${RemoteApp}/"
scp `
    (Join-Path $Repo "sw\tdc_server.py") `
    (Join-Path $Repo "sw\tdc_regs.py") `
    (Join-Path $Repo "sw\bit_to_bin.py") `
    "${Target}:${RemoteApp}/"
scp $Bit "${Target}:${RemoteApp}/fpga/tdc.bit"

Write-Host "Building controllerhf.so and restarting nginx ..."
$remote = @'
set -e
APP=/opt/redpitaya/www/apps/pitaya_tdc
cd "$APP"
sed -i 's/\r$//' fpga.sh restore_fpga.sh Makefile nginx.conf 2>/dev/null || true
chmod +x fpga.sh restore_fpga.sh
make INSTALL_DIR=/opt/redpitaya
if systemctl restart redpitaya_nginx 2>/dev/null; then
    :
elif systemctl restart nginx 2>/dev/null; then
    :
else
    echo "Could not restart nginx; reboot the board if the tile does not appear." >&2
fi
ro >/dev/null 2>&1 || mount -o remount,ro /opt/redpitaya || true
echo "Installed $APP"
'@
$remote | ssh $Target "bash -s"

Write-Host ""
Write-Host "Open http://$HostName/ and click Pitaya TDC."
Write-Host "Scope/SCPI are unavailable only while that app is open."
Write-Host "PC clients can still use http://${HostName}:8080 while the app is running."
