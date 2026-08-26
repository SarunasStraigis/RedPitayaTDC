#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SIM="$ROOT/fpga/sim"
RTL="$ROOT/fpga/rtl"

iverilog -g2012 -o "$SIM/tdc_ts.vvp" \
    "$RTL/tdc_timestamp.v" \
    "$SIM/tb_tdc_timestamp.v"
vvp "$SIM/tdc_ts.vvp"

iverilog -g2012 -DSIM -o "$SIM/tdc_enc.vvp" \
    "$RTL/tdc_encoder.v" \
    "$SIM/tb_tdc_encoder.v"
vvp "$SIM/tdc_enc.vvp"
