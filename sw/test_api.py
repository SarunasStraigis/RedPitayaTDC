#!/usr/bin/env python3
"""Smoke-test REST + UDP against tdc_server.py --sim."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

HOST = "127.0.0.1"
HTTP_PORT = 18080
UDP_PORT = 18081
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get(path: str, timeout: float = 2.0) -> dict:
    url = "http://%s:%d%s" % (HOST, HTTP_PORT, path)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
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
