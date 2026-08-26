# One-time install of the Pitaya TDC web app onto a STEMlab.
# After this, Start/Stop is in the web tile (port 80). No SSH per measurement.
#
# Usage:
#   powershell -File rp_app\install.ps1 -HostName rp-f0cebb.local
#
# Requires: OpenSSH client (scp/ssh), a built fpga\output\tdc.bit
# You should be asked for the root password twice (copy, then build).

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

foreach ($name in @("tdc_server.py", "tdc_regs.py", "tdc_nutt.py", "bit_to_bin.py")) {
    $p = Join-Path $Repo "sw\$name"
    if (-not (Test-Path $p)) {
        throw "Missing $p"
    }
}

$stage = Join-Path $env:TEMP "pitaya_tdc"
if (Test-Path $stage) {
    Remove-Item $stage -Recurse -Force
}
Copy-Item $AppSrc $stage -Recurse
Get-ChildItem $stage -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Copy-Item (Join-Path $Repo "sw\tdc_server.py") $stage -Force
Copy-Item (Join-Path $Repo "sw\tdc_regs.py") $stage -Force
Copy-Item (Join-Path $Repo "sw\tdc_nutt.py") $stage -Force
Copy-Item (Join-Path $Repo "sw\bit_to_bin.py") $stage -Force
New-Item -ItemType Directory -Force -Path (Join-Path $stage "fpga") | Out-Null
Copy-Item $Bit (Join-Path $stage "fpga\tdc.bit") -Force
$iconPy = Join-Path $stage "info\make_icon.py"
python $iconPy
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate info/icon/{128,256,512}.png"
}
Copy-Item (Join-Path $stage "info\icon.png") (Join-Path $stage "icon.png") -Force
python (Join-Path $Repo "sw\bit_to_bin.py") $Bit (Join-Path $stage "fpga\tdc.bin")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to convert tdc.bit -> tdc.bin"
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
Get-ChildItem $stage -Recurse -File | Where-Object {
    $_.Extension -match '^\.(sh|py|js|html|css|json|conf|cpp|service|socket)$' -or $_.Name -eq "Makefile"
} | ForEach-Object {
    $text = [System.IO.File]::ReadAllText($_.FullName)
    $text = ($text -replace "`r`n", "`n") -replace "`r", "`n"
    [System.IO.File]::WriteAllText($_.FullName, $text, $utf8)
}

Write-Host "Remounting /opt/redpitaya and replacing $RemoteApp ..."
ssh $Target "rw >/dev/null 2>&1 || mount -o remount,rw /opt/redpitaya; rm -rf $RemoteApp $RemoteApps/femto_tdc; mkdir -p $RemoteApp"

$tar = Join-Path $env:TEMP "pitaya_tdc_deploy.tar.gz"
if (Test-Path $tar) {
    Remove-Item $tar -Force
}
Write-Host "Copying app tree (one tar) ..."
tar -czf $tar -C $stage .
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create $tar"
}
scp $tar "${Target}:/tmp/pitaya_tdc_deploy.tar.gz"

Write-Host "Building controllerhf.so and restarting nginx ..."
$remote = @'
set -e
APP=/opt/redpitaya/www/apps/pitaya_tdc
mkdir -p "$APP"
tar -xzf /tmp/pitaya_tdc_deploy.tar.gz -C "$APP"
cd "$APP"
test -s index.html
test -s control.sh
test -s tdc_control.py
test -s systemd/pitaya-tdc-control.service
test -s nginx.conf
test -s info/info.json
test -s info/icon/128.png
test -s info/icon/256.png
test -s info/icon/512.png
find . -type f ! -name '*.so' ! -name '*.bit' ! -name '*.bin' ! -name '*.png' \
    -exec sed -i 's/\r$//' {} +
find . -type d -exec chmod 755 {} +
find . -type f -exec chmod 644 {} +
chmod +x fpga.sh restore_fpga.sh control.sh
make INSTALL_DIR=/opt/redpitaya
test -s controllerhf.so
test -s tdc_server.py
cp systemd/pitaya-tdc-control.service /etc/systemd/system/
systemctl disable --now pitaya-tdc-control.socket >/dev/null 2>&1 || true
rm -f /etc/systemd/system/pitaya-tdc-control.socket
systemctl daemon-reload
systemctl enable pitaya-tdc-control.service
systemctl restart pitaya-tdc-control.service
if systemctl restart redpitaya_nginx 2>/dev/null; then
    :
elif systemctl restart nginx 2>/dev/null; then
    :
else
    echo "Could not restart nginx; reboot the board if the tile does not appear." >&2
fi
ro >/dev/null 2>&1 || mount -o remount,ro /opt/redpitaya || true
echo "Installed $APP"
ls -l index.html info/icon.png info/icon/128.png info/icon/256.png info/icon/512.png controllerhf.so tdc_server.py fpga/tdc.bit fpga/tdc.bin
'@
$lf = ($remote -replace "`r`n", "`n") -replace "`r", "`n"
$tmp = Join-Path $env:TEMP "pitaya_tdc_install.sh"
[System.IO.File]::WriteAllText($tmp, $lf, $utf8)
scp $tmp "${Target}:/tmp/pitaya_tdc_install.sh"
ssh $Target "sed -i 's/\r`$//' /tmp/pitaya_tdc_install.sh && bash /tmp/pitaya_tdc_install.sh"
if ($LASTEXITCODE -ne 0) {
    throw "Remote install failed (exit $LASTEXITCODE)."
}

Write-Host ""
Write-Host "Open http://$HostName/ , click Pitaya TDC, then press Start."
Write-Host "If the tile has no icon: http://$HostName/pitaya_tdc/info/icon/128.png"
Write-Host "Start/Stop: http://$HostName/pitaya_tdc/control/status"
Write-Host "If health stays offline:"
Write-Host "  ssh $Target `"tail -50 /tmp/pitaya_tdc_fpga.log /tmp/pitaya_tdc.log`""
