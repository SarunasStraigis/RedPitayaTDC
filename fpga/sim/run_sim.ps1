$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Sim = Join-Path $Root "fpga\sim"
$Rtl = Join-Path $Root "fpga\rtl"

$TsOut = Join-Path $Sim "tdc_ts.vvp"
& iverilog -g2012 -o $TsOut (Join-Path $Rtl "tdc_timestamp.v") (Join-Path $Sim "tb_tdc_timestamp.v")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& vvp $TsOut
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$EncOut = Join-Path $Sim "tdc_enc.vvp"
& iverilog -g2012 -DSIM -o $EncOut (Join-Path $Rtl "tdc_encoder.v") (Join-Path $Sim "tb_tdc_encoder.v")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& vvp $EncOut
exit $LASTEXITCODE
