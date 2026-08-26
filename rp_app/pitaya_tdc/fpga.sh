#!/bin/sh
# nginx runs rmoverlay.sh before this, which drops v0.94. Restore that overlay
# so GP0 /dev/mem still maps 0x40000000, then replace only the PL with tdc.bin.
# Same method as the working SSH deploy. Unique firmware names force a reload
# (fpga_manager no-ops if the last filename is reused after overlay.sh).

APPDIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
BIT="$APPDIR/fpga/tdc.bit"
BIN="$APPDIR/fpga/tdc.bin"
LOG=/tmp/pitaya_tdc_fpga.log
MGR=/sys/class/fpga_manager/fpga0
PY=/usr/bin/python3
export PATH=/usr/bin:/bin:/sbin:/opt/redpitaya/sbin:/opt/redpitaya/bin:$PATH

{
echo "---- $(date) ----"
echo "APPDIR=$APPDIR pwd=$(pwd) id=$(id)"

verify_id() {
    $PY - <<'PY'
import os, mmap, struct, sys
try:
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    mem = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0x40000000)
    ident = struct.unpack_from("<I", mem, 0)[0]
    mem.close()
    os.close(fd)
except Exception as e:
    print("ID read failed: %s" % e)
    sys.exit(2)
print("ID=0x%08X" % ident)
sys.exit(0 if ident == 0x54444331 else 1)
PY
}

ensure_bin() {
    if [ -f "$BIN" ] && [ -s "$BIN" ]; then
        echo "using existing $BIN ($(wc -c < "$BIN") bytes)"
        return 0
    fi
    if [ ! -f "$BIT" ]; then
        echo "missing $BIN and $BIT"
        return 1
    fi
    echo "converting $BIT -> $BIN"
    $PY "$APPDIR/bit_to_bin.py" "$BIT" "$BIN"
}

restore_v094() {
    if [ -x /opt/redpitaya/sbin/overlay.sh ]; then
        echo "overlay.sh v0.94"
        /opt/redpitaya/sbin/overlay.sh v0.94
        return $?
    fi
    echo "overlay.sh not found"
    return 1
}

load_tdc_sysfs() {
    if [ ! -d "$MGR" ]; then
        echo "no $MGR"
        return 1
    fi
    if [ ! -d /lib/firmware ]; then
        echo "no /lib/firmware"
        return 1
    fi
    rm -f /lib/firmware/tdc_load_*.bin
    name="tdc_load_$$.bin"
    cp "$BIN" /lib/firmware/tdc.bin
    cp "$BIN" "/lib/firmware/$name"
    sync
    echo 0 > "$MGR/flags"
    echo "loading $name ($(wc -c < /lib/firmware/$name) bytes)"
    echo "$name" > "$MGR/firmware"
    i=0
    while [ "$i" -lt 40 ]; do
        st=$(cat "$MGR/state" 2>/dev/null || echo unknown)
        echo "fpga_manager state=$st"
        if [ "$st" = "operating" ]; then
            return 0
        fi
        i=$((i + 1))
        sleep 0.1
    done
    return 1
}

if verify_id; then
    echo "TDC already loaded"
    echo -n "pitaya_tdc" > /tmp/loaded_fpga.inf 2>/dev/null || true
    exit 0
fi

ensure_bin || exit 1
ls -l "$BIN" "$BIT" 2>/dev/null || true

echo "step 1: restore v0.94 after rmoverlay"
restore_v094 || echo "overlay.sh v0.94 failed (continuing)"

echo "step 2: load TDC bitstream (sysfs)"
if ! load_tdc_sysfs; then
    echo "sysfs load failed"
    dmesg | tail -20 || true
    exit 1
fi

sleep 0.4
if verify_id; then
    echo "TDC ID ok"
    echo -n "pitaya_tdc" > /tmp/loaded_fpga.inf 2>/dev/null || true
    exit 0
fi

echo "ID still wrong after sysfs load"
dmesg | tail -20 || true
exit 1
} >>"$LOG" 2>&1
