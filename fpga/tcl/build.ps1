# Find a local Vivado and run the TDC batch build.
# Usage (from repo root or this folder):
#   powershell -File fpga\tcl\build.ps1

$ErrorActionPreference = "Stop"

$tcl = Join-Path $PSScriptRoot "build.tcl"
if (-not (Test-Path $tcl)) {
    throw "Missing $tcl"
}

$vivadoBat = $null
$candidates = @()
if ($env:XILINX_VIVADO) {
    $candidates += Join-Path $env:XILINX_VIVADO "bin\vivado.bat"
}
$candidates += Get-ChildItem "C:\Xilinx\Vivado" -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "bin\vivado.bat" }

foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) {
        $vivadoBat = $c
        break
    }
}

if (-not $vivadoBat) {
    throw "Vivado not found. Install it or add bin\vivado.bat to PATH. Looked under C:\Xilinx\Vivado\."
}

Write-Host "Using $vivadoBat"
& $vivadoBat -mode batch -source $tcl
exit $LASTEXITCODE
