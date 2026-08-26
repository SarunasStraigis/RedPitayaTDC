#!/bin/sh
# Single-instance TDC start/stop. Serialized with flock.
# Usage: control.sh start|stop|status

APPDIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PIDFILE=/tmp/pitaya_tdc.pid
WANT=/tmp/pitaya_tdc.want
LOCK=/tmp/pitaya_tdc.lock
LOG=/tmp/pitaya_tdc.log
SERVER="$APPDIR/tdc_server.py"
PY=/usr/bin/python3
export PATH=/usr/bin:/bin:/sbin:/opt/redpitaya/sbin:/opt/redpitaya/bin:$PATH

if [ ! -x "$PY" ]; then
    PY=python3
fi

health_ok() {
    $PY - <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=0.5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
except Exception:
    sys.exit(1)
ok = bool(data.get("ok"))
ident = str(data.get("id") or "")
sys.exit(0 if ok and ident in ("TDC1", "0x54444331") else 1)
PY
}

read_pid() {
    if [ ! -f "$PIDFILE" ]; then
        echo ""
        return
    fi
    pid=$(tr -dc '0-9' < "$PIDFILE" 2>/dev/null || true)
    echo "$pid"
}

pid_alive() {
    pid=$1
    if [ -z "$pid" ] || [ "$pid" -lt 2 ] 2>/dev/null; then
        return 1
    fi
    kill -0 "$pid" 2>/dev/null
}

print_status() {
    $PY - "$PIDFILE" "$WANT" <<'PY'
import json, os, sys, urllib.request

pidfile, want = sys.argv[1], sys.argv[2]
pid = None
try:
    with open(pidfile, "r") as f:
        text = "".join(c for c in f.read() if c.isdigit())
        if text:
            pid = int(text)
except Exception:
    pid = None

alive = False
if pid and pid > 1:
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False

http_ok = False
health = None
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=0.5) as resp:
        health = json.loads(resp.read().decode("utf-8"))
        http_ok = True
except Exception:
    pass

fpga_id = None
if health and health.get("id"):
    fpga_id = health.get("id")

running = bool(http_ok and health and health.get("ok") and str(health.get("id") or "") in ("TDC1", "0x54444331"))
if running:
    state = "running"
elif os.path.isfile(want):
    state = "starting"
else:
    state = "stopped"
out = {
    "state": state,
    "pid": pid if alive else None,
    "http": http_ok,
    "fpga_id": fpga_id,
    "want": os.path.isfile(want),
}
if health:
    out["health"] = {"ok": bool(health.get("ok")), "id": health.get("id")}
print(json.dumps(out, separators=(",", ":")))
PY
}

do_start() {
    if health_ok; then
        touch "$WANT"
        print_status
        return 0
    fi

    touch "$WANT"
    if ! /bin/sh "$APPDIR/fpga.sh"; then
        rm -f "$WANT"
        echo '{"state":"error","error":"fpga.sh failed — see /tmp/pitaya_tdc_fpga.log"}'
        return 1
    fi

    if [ ! -f "$WANT" ]; then
        echo '{"state":"stopped","error":"start cancelled"}'
        return 1
    fi

    if health_ok; then
        print_status
        return 0
    fi

    pid=$(read_pid)
    if pid_alive "$pid"; then
        kill "$pid" 2>/dev/null || true
        sleep 0.1
    fi
    pkill -f '/opt/redpitaya/www/apps/pitaya_tdc/tdc_server.py' >/dev/null 2>&1 || true
    sleep 0.1

    mkdir -p "$APPDIR"
    : >> "$LOG"
    (
        cd "$APPDIR" || exit 127
        exec 9>&-
        exec 8>&-
        exec >>"$LOG" 2>&1
        exec "$PY" "$SERVER" --host 0.0.0.0 --port 8080 --udp-port 0
    ) &
    echo $! > "$PIDFILE"

    i=0
    while [ "$i" -lt 50 ]; do
        if health_ok; then
            print_status
            return 0
        fi
        i=$((i + 1))
        sleep 0.2
    done

    echo '{"state":"error","error":"tdc_server.py did not become healthy — see /tmp/pitaya_tdc.log"}'
    return 1
}

do_stop() {
    had_want=0
    [ -f "$WANT" ] && had_want=1
    pid=$(read_pid)
    had_pid=0
    pid_alive "$pid" && had_pid=1
    had_http=0
    health_ok && had_http=1

    rm -f "$WANT"
    if pid_alive "$pid"; then
        kill "$pid" 2>/dev/null || true
        i=0
        while [ "$i" -lt 10 ]; do
            if ! pid_alive "$pid"; then
                break
            fi
            i=$((i + 1))
            sleep 0.05
        done
        if pid_alive "$pid"; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    rm -f "$PIDFILE"
    pkill -f '/opt/redpitaya/www/apps/pitaya_tdc/tdc_server.py' >/dev/null 2>&1 || true
    if [ "$had_http" -eq 0 ]; then
        echo "skip restore: TDC was not running" >&2
        print_status
        return 0
    fi
    (
        /bin/sh "$APPDIR/restore_fpga.sh"
    ) >/tmp/pitaya_tdc_restore.log 2>&1 &
    print_status
    return 0
}

cmd=${1:-}
case "$cmd" in
    status)
        print_status
        exit 0
        ;;
    stop)
        do_stop
        exit $?
        ;;
    start)
        if health_ok; then
            touch "$WANT"
            print_status
            exit 0
        fi
        ;;
    *)
        echo '{"state":"error","error":"usage: control.sh start|stop|status"}'
        exit 2
        ;;
esac

exec 9>"$LOCK"
if flock -w 55 9; then
    :
else
    echo '{"state":"error","error":"start already in progress"}'
    exit 1
fi
do_start
exit $?

