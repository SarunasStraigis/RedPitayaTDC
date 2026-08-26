#!/usr/bin/env python3
"""Tiny helper around GET /api/latest (and optional /api/wait)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Poll Red Pitaya TDC REST API")
    p.add_argument("--url", default="http://rp-XXXX.local:8080", help="Server base URL")
    p.add_argument("--wait", action="store_true", help="Use /api/wait instead of /api/latest")
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--health", action="store_true")
    p.add_argument("--loop", action="store_true", help="Print every new seq until Ctrl+C")
    args = p.parse_args(argv)

    base = args.url.rstrip("/")
    if args.health:
        print(json.dumps(get_json(base + "/api/health", 5.0), indent=2))
        return 0

    if args.loop:
        last_seq = None
        try:
            while True:
                q = urllib.parse.urlencode({"timeout_ms": args.timeout_ms})
                snap = get_json("%s/api/wait?%s" % (base, q), args.timeout_ms / 1000.0 + 2.0)
                if snap.get("valid") and snap.get("seq") != last_seq and not snap.get("wait_timed_out"):
                    last_seq = snap.get("seq")
                    print("%(seq)s  %(dt_ns)s ns  flags=%(flags)s" % snap, flush=True)
        except KeyboardInterrupt:
            return 0

    if args.wait:
        q = urllib.parse.urlencode({"timeout_ms": args.timeout_ms})
        path = "/api/wait?" + q
        timeout = args.timeout_ms / 1000.0 + 2.0
    else:
        path = "/api/latest"
        timeout = 5.0

    try:
        snap = get_json(base + path, timeout)
    except urllib.error.URLError as exc:
        print("request failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
