$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Out = Join-Path $PSScriptRoot "tdc.vvp"
& iverilog -g2012 -o $Out (Join-Path $Root "fpga\rtl\tdc_timestamp.v") (Join-Path $Root "fpga\sim\tb_tdc_timestamp.v")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& vvp $Out
exit $LASTEXITCODE
