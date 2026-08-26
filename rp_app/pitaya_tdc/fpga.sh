#!/bin/sh
# Called by Bazaar on tile open (after rmoverlay.sh) and by control.sh start.
# Load tdc.bin only if TDC was started (.want / server). Otherwise restore v0.94.

APPDIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
BIT="$APPDIR/fpga/tdc.bit"
BIN="$APPDIR/fpga/tdc.bin"
LOG=/tmp/pitaya_tdc_fpga.log
MGR=/sys/class/fpga_manager/fpga0
PY=/usr/bin/python3
export PATH=/usr/bin:/bin:/sbin:/opt/redpitaya/sbin:/opt/redpitaya/bin:$PATH

exec 8>/tmp/pitaya_tdc.fpga.lock
if flock -w 45 8; then
    :
else
    echo "fpga lock timeout (another overlay still running)" >&2
    exit 1
fi

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
    if [ ! -x /opt/redpitaya/sbin/overlay.sh ]; then
        echo "overlay.sh not found"
        return 1
    fi
    echo "overlay.sh v0.94"
    if command -v timeout >/dev/null 2>&1; then
        timeout 30 /opt/redpitaya/sbin/overlay.sh v0.94
        return $?
    fi
    /opt/redpitaya/sbin/overlay.sh v0.94
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

tdc_wanted() {
    if [ -f /tmp/pitaya_tdc.want ]; then
        echo "want file present"
        return 0
    fi
    if [ -f /tmp/pitaya_tdc.pid ]; then
        pid=$(tr -dc '0-9' < /tmp/pitaya_tdc.pid 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "tdc_server pid $pid alive"
            return 0
        fi
    fi
    if pgrep -f '/opt/redpitaya/www/apps/pitaya_tdc/tdc_server.py' >/dev/null 2>&1; then
        echo "tdc_server.py process present"
        return 0
    fi
    $PY - <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=0.3) as resp:
        data = json.loads(resp.read().decode("utf-8"))
except Exception:
    sys.exit(1)
sys.exit(0 if data.get("ok") and str(data.get("id") or "") in ("TDC1", "0x54444331") else 1)
PY
}

verify_id
id_rc=$?
if [ "$id_rc" -eq 0 ]; then
    echo "TDC already loaded"
    echo -n "pitaya_tdc" > /tmp/loaded_fpga.inf 2>/dev/null || true
    exit 0
fi

if ! tdc_wanted; then
    echo "TDC not requested; restore v0.94 after rmoverlay"
    restore_v094 || echo "overlay.sh v0.94 failed"
    exit 0
fi

ensure_bin || exit 1
ls -l "$BIN" "$BIT" 2>/dev/null || true

mgr_state=$(cat "$MGR/state" 2>/dev/null || echo missing)
echo "fpga_manager state=$mgr_state id_rc=$id_rc"

# overlay.sh while the manager is already operating is what hangs Start
# after Stop. Only restore the DT when the PL is actually down.
if [ "$mgr_state" != "operating" ]; then
    echo "step 1: manager not operating, restore v0.94"
    restore_v094 || echo "overlay.sh v0.94 failed (continuing)"
else
    echo "step 1: skip overlay.sh (fpga_manager operating) — load bitstream only"
fi

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
