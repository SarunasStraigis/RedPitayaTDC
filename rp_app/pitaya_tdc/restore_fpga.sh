#!/bin/sh
# Put the stock v0.94 overlay back so Scope / SCPI work after Stop.
# Shares the FPGA lock with fpga.sh so Start after Stop does not collide.
# If Start already ran again (.want), skip — do not overwrite TDC.

exec 8>/tmp/pitaya_tdc.fpga.lock
flock 8

if [ -f /tmp/pitaya_tdc.want ]; then
    echo "skip restore: TDC start requested"
    exit 0
fi

if [ ! -x /opt/redpitaya/sbin/overlay.sh ]; then
    echo "overlay.sh not found" >&2
    exit 1
fi
if command -v timeout >/dev/null 2>&1; then
    timeout 30 /opt/redpitaya/sbin/overlay.sh v0.94
    exit $?
fi
/opt/redpitaya/sbin/overlay.sh v0.94

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
