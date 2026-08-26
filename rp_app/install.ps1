# One-time install of the Pitaya TDC web app onto a STEMlab.
# After this, start/stop is the home-page tile (no SSH).
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

foreach ($name in @("tdc_server.py", "tdc_regs.py", "bit_to_bin.py")) {
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
Copy-Item (Join-Path $Repo "sw\tdc_server.py") $stage -Force
Copy-Item (Join-Path $Repo "sw\tdc_regs.py") $stage -Force
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
    $_.Extension -match '^\.(sh|py|js|html|css|json|conf|cpp)$' -or $_.Name -eq "Makefile"
} | ForEach-Object {
    $text = [System.IO.File]::ReadAllText($_.FullName)
    $text = ($text -replace "`r`n", "`n") -replace "`r", "`n"
    [System.IO.File]::WriteAllText($_.FullName, $text, $utf8)
}

Write-Host "Remounting /opt/redpitaya and replacing $RemoteApp ..."
ssh $Target "rw >/dev/null 2>&1 || mount -o remount,rw /opt/redpitaya; rm -rf $RemoteApp $RemoteApps/femto_tdc"

Write-Host "Copying app tree (one scp) ..."
scp -r $stage "${Target}:${RemoteApp}"

Write-Host "Building controllerhf.so and restarting nginx ..."
$remote = @'
set -e
APP=/opt/redpitaya/www/apps/pitaya_tdc
# Windows OpenSSH scp -r may nest as pitaya_tdc/pitaya_tdc
if [ -d "$APP/pitaya_tdc" ] && [ -f "$APP/pitaya_tdc/index.html" ]; then
    cp -a "$APP/pitaya_tdc/." "$APP/"
    rm -rf "$APP/pitaya_tdc"
fi
cd "$APP"
test -f index.html
test -f info/icon/128.png
test -f info/icon/256.png
test -f info/icon/512.png
find . -type f ! -name '*.so' ! -name '*.bit' ! -name '*.bin' ! -name '*.png' \
    -exec sed -i 's/\r$//' {} +
find . -type d -exec chmod 755 {} +
find . -type f -exec chmod 644 {} +
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
Write-Host "Open http://$HostName/ and click Pitaya TDC."
Write-Host "If the tile has no icon: http://$HostName/pitaya_tdc/info/icon/128.png"
Write-Host "If health stays offline:"
Write-Host "  ssh $Target `"tail -50 /tmp/pitaya_tdc_fpga.log /tmp/pitaya_tdc.log`""
