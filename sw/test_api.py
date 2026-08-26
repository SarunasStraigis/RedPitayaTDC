#!/usr/bin/env python3
"""Smoke-test REST + UDP against tdc_server.py --sim."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
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
    from tdc_regs import FLAG_UNMATCHED_STOP, is_good_pair
    from tdc_server import pack_snapshot

    if is_good_pair(True, FLAG_UNMATCHED_STOP):
        return "unmatched STOP must not count as a good pair"
    if not is_good_pair(True, 0):
        return "empty flags should be a good pair"
    held = pack_snapshot(
        valid=True,
        seq=12,
        dt_ticks=25,
        t_start=1,
        t_stop=26,
        flags=0,
        age_ms=1.5,
        armed=True,
        clock_hz=250_000_000,
        fpga_seq=99,
        latest_flags=FLAG_UNMATCHED_STOP,
        held=True,
    )
    if held.get("fpga_seq") != 99:
        return "fpga_seq missing/wrong: %r" % held
    if held.get("latest_flags") != ["unmatched_stop"]:
        return "latest_flags missing/wrong: %r" % held
    if held.get("flags"):
        return "held snapshot should keep last-good flags empty: %r" % held
    if held.get("dt_ns") is None or held.get("held") is not True:
        return "held snapshot should publish last-good dt_ns: %r" % held
    return None


def main() -> int:
    field_err = check_snapshot_fields()
    if field_err:
        print(field_err)
        return 1

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
        if latest.get("fpga_seq") != latest.get("seq"):
            print("sim fpga_seq should match seq: %r" % latest)
            return 1
        if "latest_flags" not in latest or latest.get("held") is not False:
            print("missing latest_flags/held on sim latest: %r" % latest)
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
