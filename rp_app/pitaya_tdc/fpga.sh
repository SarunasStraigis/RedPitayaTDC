#!/bin/sh
# Load the TDC overlay. Called by nginx before rp_app_init.
# STEMlab fpga_manager wants a 32-bit byte-swapped .bin, not a raw Vivado .bit.

set -e
APPDIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
BIT="$APPDIR/fpga/tdc.bit"
BIN="$APPDIR/fpga/tdc.bin"
MGR=/sys/class/fpga_manager/fpga0

if [ ! -f "$BIN" ]; then
    if [ ! -f "$BIT" ]; then
        echo "pitaya_tdc: missing $BIN and $BIT" >&2
        exit 1
    fi
    python3 "$APPDIR/bit_to_bin.py" "$BIT" "$BIN"
fi

cp "$BIN" /lib/firmware/tdc.bin

if [ -d "$MGR" ]; then
    echo 0 > "$MGR/flags"
    echo tdc.bin > "$MGR/firmware"
    i=0
    while [ "$i" -lt 25 ]; do
        st=$(cat "$MGR/state" 2>/dev/null || echo unknown)
        if [ "$st" = "operating" ]; then
            exit 0
        fi
        i=$((i + 1))
        sleep 0.1
    done
    echo "pitaya_tdc: fpga_manager state=$st" >&2
    exit 1
fi

if command -v fpgautil >/dev/null 2>&1; then
    fpgautil -b "$BIN"
    exit $?
fi

echo "pitaya_tdc: no fpga_manager and no fpgautil" >&2
exit 1
