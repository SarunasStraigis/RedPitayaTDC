#!/bin/sh
# Put the stock v0.94 overlay back so Scope / SCPI work after this app exits.

if [ -x /opt/redpitaya/sbin/overlay.sh ]; then
    /opt/redpitaya/sbin/overlay.sh v0.94
    exit $?
fi

MODEL=$(/opt/redpitaya/bin/profiles -f 2>/dev/null || true)
STOCK="/opt/redpitaya/fpga/${MODEL}/v0.94/fpga.bin"
MGR=/sys/class/fpga_manager/fpga0

if [ -n "$MODEL" ] && [ -f "$STOCK" ] && [ -d "$MGR" ]; then
    cp "$STOCK" /lib/firmware/rp_v094.bin
    echo 0 > "$MGR/flags"
    echo rp_v094.bin > "$MGR/firmware"
    exit 0
fi

if command -v fpgautil >/dev/null 2>&1 && [ -f "$STOCK" ]; then
    fpgautil -b "$STOCK"
    exit $?
fi

echo "pitaya_tdc: could not restore v0.94 (reboot to get Scope back)" >&2
exit 1
