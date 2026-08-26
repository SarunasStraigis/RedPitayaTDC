#!/usr/bin/env python3
"""Smoke-test REST + UDP against tdc_server.py --sim."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HOST = "127.0.0.1"
HTTP_PORT = 18080
UDP_PORT = 18081
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get(path: str, timeout: float = 2.0) -> dict:
    url = "http://%s:%d%s" % (HOST, HTTP_PORT, path)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path: str, payload: dict, timeout: float = 5.0) -> tuple:
    url = "http://%s:%d%s" % (HOST, HTTP_PORT, path)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {"error": body}
        return exc.code, parsed


def put(path: str, payload: dict, timeout: float = 2.0) -> tuple:
    url = "http://%s:%d%s" % (HOST, HTTP_PORT, path)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {"error": body}
        return exc.code, parsed


def check_snapshot_fields() -> str | None:
    sys.path.insert(0, os.path.join(ROOT, "sw"))
    from tdc_regs import FLAG_UNMATCHED_STOP, is_good_pair, same_bin_pair
    from tdc_server import pack_snapshot

    if is_good_pair(True, FLAG_UNMATCHED_STOP):
        return "unmatched STOP must not count as a good pair"
    if not is_good_pair(True, 0):
        return "empty flags should be a good pair"
    if not same_bin_pair(True, 0, 40, 40):
        return "identical timestamps should be same_bin"
    if same_bin_pair(True, 0, 40, 41):
        return "different timestamps must not be same_bin"
    if same_bin_pair(True, FLAG_UNMATCHED_STOP, 9, 9):
        return "unmatched STOP must not be same_bin"
    zero = pack_snapshot(
        valid=True,
        seq=3,
        dt_ticks=0,
        t_start=40,
        t_stop=40,
        flags=0,
        age_ms=0.5,
        armed=False,
        clock_hz=125_000_000,
        fine_start=0,
        fine_stop=0,
        fine_bins=512,
    )
    if zero.get("same_bin") is not True or zero.get("dt_ns") != 0.0:
        return "0 ns snapshot should set same_bin and dt_ns=0: %r" % zero
    if zero.get("dt_ps") != 0.0 or zero.get("fine_bins") != 512:
        return "0 ns snapshot should set dt_ps=0 and fine_bins: %r" % zero
    held = pack_snapshot(
        valid=True,
        seq=12,
        dt_ticks=25,
        t_start=1,
        t_stop=26,
        flags=0,
        age_ms=1.5,
        armed=True,
        clock_hz=125_000_000,
        fpga_seq=99,
        latest_flags=FLAG_UNMATCHED_STOP,
        held=True,
        fine_bins=512,
    )
    if held.get("fpga_seq") != 99:
        return "fpga_seq missing/wrong: %r" % held
    if held.get("latest_flags") != ["unmatched_stop"]:
        return "latest_flags missing/wrong: %r" % held
    if held.get("flags"):
        return "held snapshot should keep last-good flags empty: %r" % held
    if held.get("dt_ns") is None or held.get("held") is not True:
        return "held snapshot should publish last-good dt_ns: %r" % held
    if held.get("same_bin"):
        return "held nonzero interval must not be same_bin: %r" % held
    return None


def check_coherent_read() -> str | None:
    sys.path.insert(0, os.path.join(ROOT, "sw"))
    from tdc_regs import (
        ADDR_DT_TICKS,
        ADDR_FINE_START,
        ADDR_FINE_STOP,
        ADDR_FLAGS,
        ADDR_SEQ,
        ADDR_STATUS,
        ADDR_T_START,
        ADDR_T_STOP,
    )
    from tdc_server import coherent_mmio_read

    ev0 = {
        ADDR_SEQ: 10,
        ADDR_STATUS: 1,
        ADDR_DT_TICKS: 1,
        ADDR_T_START: 1000,
        ADDR_T_STOP: 1001,
        ADDR_FLAGS: 0,
        ADDR_FINE_START: 40,
        ADDR_FINE_STOP: 41,
    }
    ev1 = {
        ADDR_SEQ: 11,
        ADDR_STATUS: 1,
        ADDR_DT_TICKS: 1,
        ADDR_T_START: 2250,
        ADDR_T_STOP: 2251,
        ADDR_FLAGS: 0,
        ADDR_FINE_START: 40,
        ADDR_FINE_STOP: 41,
    }
    state = {"cur": dict(ev0), "n": 0}

    def read_u32(off: int) -> int:
        state["n"] += 1
        # After SEQ of the first burst, switch to the next event so T_START
        # is old and T_STOP is new — the old one-retry reader would publish
        # a mixed 10 µs-class interval.
        if state["n"] == 5:
            state["cur"] = dict(ev1)
        return int(state["cur"].get(off, 0)) & 0xFFFFFFFF

    got = coherent_mmio_read(read_u32, max_tries=8)
    if not got.get("coherent"):
        return "coherent read should succeed once SEQ is stable: %r" % got
    if got["t_start"] != ev1[ADDR_T_START] or got["t_stop"] != ev1[ADDR_T_STOP]:
        return "coherent read returned mixed timestamps: %r" % got
    if got["seq"] != ev1[ADDR_SEQ]:
        return "coherent read seq wrong: %r" % got
    if got["t_start"] == ev0[ADDR_T_START] and got["t_stop"] == ev1[ADDR_T_STOP]:
        return "tore start from event 0 and stop from event 1"

    always = {"seq": 10}

    def always_tear(off: int) -> int:
        if off == ADDR_SEQ:
            always["seq"] += 1
            return always["seq"]
        if off == ADDR_T_START:
            return 1000
        if off == ADDR_T_STOP:
            return 2251
        return 1

    try:
        coherent_mmio_read(always_tear, max_tries=4)
        return "persistent SEQ tear must not return a mixed snapshot"
    except RuntimeError:
        pass

    mixed = {
        ADDR_SEQ: 20,
        ADDR_STATUS: 1,
        ADDR_DT_TICKS: 1,
        ADDR_T_START: 1000,
        ADDR_T_STOP: 1000 + 1251,
        ADDR_FLAGS: 0,
        ADDR_FINE_START: 40,
        ADDR_FINE_STOP: 41,
    }

    def stable_but_torn(off: int) -> int:
        return int(mixed.get(off, 0)) & 0xFFFFFFFF

    try:
        coherent_mmio_read(stable_but_torn, max_tries=3)
        return "dt_ticks vs t_stop-t_start mismatch must not be published"
    except RuntimeError:
        pass
    return None


def main() -> int:
    field_err = check_snapshot_fields()
    if field_err:
        print(field_err)
        return 1
    tear_err = check_coherent_read()
    if tear_err:
        print(tear_err)
        return 1

    cal_file = os.path.join(tempfile.gettempdir(), "tdc_cal_test.json")
    try:
        os.remove(cal_file)
    except OSError:
        pass
    cmd = [
        sys.executable,
        os.path.join(ROOT, "sw", "tdc_server.py"),
        "--sim",
        "--host",
        HOST,
        "--port",
        str(HTTP_PORT),
        "--udp-port",
        str(UDP_PORT),
        "--sim-period-ms",
        "20",
        "--sim-dt-ns",
        "1000000",
        "--cal-file",
        cal_file,
    ]
    proc = subprocess.Popen(cmd, cwd=ROOT)
    try:
        deadline = time.time() + 5.0
        health = None
        while time.time() < deadline:
            try:
                health = get("/api/health")
                break
            except OSError:
                time.sleep(0.05)
        if not health or not health.get("ok"):
            print("health failed: %r" % health)
            return 1
        if not health.get("sim"):
            print("expected sim=true")
            return 1

        latest = get("/api/latest")
        if not latest.get("valid"):
            time.sleep(0.05)
            latest = get("/api/latest")
        if not latest.get("valid"):
            print("latest not valid: %r" % latest)
            return 1
        if abs(latest["dt_ns"] - 1_000_000.0) > 1.0:
            print("unexpected dt_ns: %r" % latest)
            return 1
        if latest.get("fine_bins") != 512 or latest.get("dt_ps") is None:
            print("missing interpolator fields: %r" % latest)
            return 1
        if latest.get("calibrated") is not False:
            print("sim should start uncalibrated: %r" % latest)
            return 1
        if latest.get("fpga_seq") != latest.get("seq"):
            print("sim fpga_seq should match seq: %r" % latest)
            return 1
        if "latest_flags" not in latest or latest.get("held") is not False:
            print("missing latest_flags/held on sim latest: %r" % latest)
            return 1
        if latest.get("same_bin"):
            print("sim 1 ms interval should not be same_bin: %r" % latest)
            return 1
        if latest.get("t_stop_ticks") is None:
            print("sim latest missing t_stop_ticks: %r" % latest)
            return 1

        code, cal = post("/api/calibrate", {"n": 5, "timeout_s": 2.0}, timeout=5.0)
        if code != 200 or not cal.get("ok") or cal.get("collected", 0) < 5:
            print("POST /api/calibrate failed: %s %r" % (code, cal))
            return 1
        latest = get("/api/latest")
        if not latest.get("calibrated"):
            print("latest should be calibrated after POST: %r" % latest)
            return 1

        pins = get("/api/pins")
        if pins.get("start", {}).get("index") != 8 or pins.get("stop", {}).get("index") != 9:
            print("default pins should be DIO7 (E1 17/18): %r" % pins)
            return 1
        if pins.get("start", {}).get("label") != "DIO7_P (E1 pin 17)":
            print("pin label missing DIO name and E1 pin: %r" % pins)
            return 1
        code, changed = put("/api/pins", {"start": 0, "stop": "DIO1_P"})
        if code != 200 or changed.get("start", {}).get("index") != 0 or changed.get("stop", {}).get("index") != 2:
            print("PUT /api/pins failed: %s %r" % (code, changed))
            return 1
        code, bad = put("/api/pins", {"start": 3, "stop": 3})
        if code != 400:
            print("expected 400 for identical pins: %s %r" % (code, bad))
            return 1
        health = get("/api/health")
        if health.get("start", {}).get("label") != "DIO0_P (E1 pin 3)":
            print("health start label wrong: %r" % health)
            return 1

        seq0 = latest["seq"]
        waited = get("/api/wait?timeout_ms=500", timeout=2.0)
        if waited.get("seq") == seq0 and not waited.get("wait_timed_out"):
            print("wait did not advance seq: %r" % waited)
            return 1

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        sock.sendto(b"?", (HOST, UDP_PORT))
        data, _addr = sock.recvfrom(4096)
        udp = json.loads(data.decode("utf-8"))
        if "dt_ns" not in udp:
            print("udp payload missing dt_ns: %r" % udp)
            return 1

        print("API smoke test passed")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
