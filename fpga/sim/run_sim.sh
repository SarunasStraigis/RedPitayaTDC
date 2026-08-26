#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/fpga/sim/tdc.vvp"
iverilog -g2012 -o "$OUT" \
    "$ROOT/fpga/rtl/tdc_timestamp.v" \
    "$ROOT/fpga/sim/tb_tdc_timestamp.v"
vvp "$OUT"
