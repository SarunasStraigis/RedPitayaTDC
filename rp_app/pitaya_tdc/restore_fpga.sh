#!/bin/sh
# Restore stock v0.94 bitstream via sysfs (same as Start). overlay.sh is
# what hangs/reboots the board after TDC.
# Shares the FPGA lock with fpga.sh. Skip if Start already ran again.

exec 8>/tmp/pitaya_tdc.fpga.lock
flock 8

if [ -f /tmp/pitaya_tdc.want ]; then
    echo "skip restore: TDC start requested"
    exit 0
fi

MODEL=$(/opt/redpitaya/bin/profiles -f 2>/dev/null || true)
STOCK="/opt/redpitaya/fpga/${MODEL}/v0.94/fpga.bin"
MGR=/sys/class/fpga_manager/fpga0

if [ -z "$MODEL" ] || [ ! -f "$STOCK" ] || [ ! -d "$MGR" ]; then
    echo "stock bitstream not found (MODEL=$MODEL STOCK=$STOCK)" >&2
    exit 1
fi

name="v094_load_$$.bin"
cp "$STOCK" "/lib/firmware/$name"
sync
echo 0 > "$MGR/flags"
echo "loading $name ($(wc -c < /lib/firmware/$name) bytes)"
echo "$name" > "$MGR/firmware"
i=0
while [ "$i" -lt 40 ]; do
    st=$(cat "$MGR/state" 2>/dev/null || echo unknown)
    echo "fpga_manager state=$st"
    if [ "$st" = "operating" ]; then
        exit 0
    fi
    i=$((i + 1))
    sleep 0.1
done
echo "v0.94 sysfs load did not reach operating" >&2
exit 1
