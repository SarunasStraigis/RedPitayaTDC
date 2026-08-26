#!/usr/bin/env python3
"""Poll the latest START/STOP interval from a Red Pitaya TDC (REST + optional UDP)."""

from __future__ import annotations

import argparse
import json
import mmap
import os
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import UDPServer, BaseRequestHandler, ThreadingMixIn
from typing import Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tdc_regs import (
    ADDR_CLOCK_HZ,
    ADDR_CONTROL,
    ADDR_DT_TICKS,
    ADDR_FLAGS,
    ADDR_ID,
    ADDR_PINS,
    ADDR_SEQ,
    ADDR_STATUS,
    ADDR_T_START,
    ADDR_T_STOP,
    ADDR_TIMEOUT,
    CTRL_ENABLE,
    CTRL_SOFT_RESET,
    DEFAULT_BASE,
    DEFAULT_CLOCK_HZ,
    DEFAULT_START_SEL,
    DEFAULT_STOP_SEL,
    ID_VALUE,
    MAP_SIZE,
    STATUS_ARMED,
    STATUS_MMCM_LOCKED,
    STATUS_VALID,
    decode_pins_word,
    encode_pins_word,
    flags_to_names,
    is_good_pair,
    parse_pin_sel,
    pin_info,
    pins_list,
    pins_selectable,
)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class ThreadingUDPServer(ThreadingMixIn, UDPServer):
    daemon_threads = True
    allow_reuse_address = True


def ticks_to_ns(dt_ticks: int, clock_hz: int) -> float:
    if clock_hz <= 0:
        return 0.0
    return dt_ticks * 1e9 / clock_hz


def pack_snapshot(
    *,
    valid: bool,
    seq: int,
    dt_ticks: int,
    t_start: int,
    flags,
    age_ms,
    armed: bool,
    clock_hz: int,
    t_stop: Optional[int] = None,
    fpga_seq: Optional[int] = None,
    latest_flags=None,
    held: bool = False,
) -> dict:
    signed = dt_ticks if dt_ticks < 0x80000000 else dt_ticks - 0x100000000
    if isinstance(flags, int):
        flag_names = flags_to_names(flags)
    else:
        flag_names = list(flags or [])
    if latest_flags is None:
        latest_names = flag_names
    elif isinstance(latest_flags, int):
        latest_names = flags_to_names(latest_flags)
    else:
        latest_names = list(latest_flags)
    out = {
        "valid": bool(valid),
        "seq": int(seq),
        "dt_ticks": signed,
        "dt_ns": ticks_to_ns(signed, clock_hz) if valid else None,
        "t_start_ticks": int(t_start) & 0xFFFFFFFF,
        "clock_hz": clock_hz,
        "flags": flag_names,
        "age_ms": None if age_ms is None else round(age_ms, 3),
        "armed": bool(armed),
        "fpga_seq": int(seq if fpga_seq is None else fpga_seq),
        "latest_flags": latest_names,
        "held": bool(held),
    }
    if t_stop is not None:
        out["t_stop_ticks"] = int(t_stop) & 0xFFFFFFFF
    return out


class TdcDevice:
    def snapshot(self) -> dict:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError

    def pins(self) -> dict:
        raise NotImplementedError

    def set_pins(self, start, stop) -> dict:
        raise NotImplementedError


def pins_payload(start: int, stop: int, selectable: bool = True) -> dict:
    return {
        "selectable": selectable,
        "start": pin_info(start),
        "stop": pin_info(stop),
        "pins": pins_list(),
    }


class SimTdc(TdcDevice):
    """Software stand-in so the REST API can be exercised without a bitstream."""

    def __init__(self, period_s: float = 0.01, dt_ns: float = 1_000_000.0, clock_hz: int = DEFAULT_CLOCK_HZ):
        self.clock_hz = clock_hz
        self._lock = threading.Lock()
        self._seq = 0
        self._valid = False
        self._dt_ticks = 0
        self._t_start = 0
        self._flags = 0
        self._enable = True
        self._latch_mono = time.monotonic()
        self._start_sel = DEFAULT_START_SEL
        self._stop_sel = DEFAULT_STOP_SEL
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(period_s, dt_ns), daemon=True)
        self._thread.start()

    def _run(self, period_s: float, dt_ns: float) -> None:
        dt_ticks = int(round(dt_ns * self.clock_hz / 1e9))
        while not self._stop.wait(period_s):
            with self._lock:
                if not self._enable:
                    continue
                self._seq += 1
                self._valid = True
                self._dt_ticks = dt_ticks
                self._t_start = (self._seq * 1000) & 0xFFFFFFFF
                self._flags = 0
                self._latch_mono = time.monotonic()

    def close(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            age_ms = (time.monotonic() - self._latch_mono) * 1000.0 if self._valid else None
            return pack_snapshot(
                valid=self._valid,
                seq=self._seq,
                dt_ticks=self._dt_ticks,
                t_start=self._t_start,
                flags=self._flags,
                age_ms=age_ms,
                armed=False,
                clock_hz=self.clock_hz,
                fpga_seq=self._seq,
                latest_flags=self._flags,
                held=False,
            )

    def health(self) -> dict:
        with self._lock:
            return {
                "ok": True,
                "id": "TDC1",
                "clock_hz": self.clock_hz,
                "enable": self._enable,
                "mmcm_locked": True,
                "armed": False,
                "valid": self._valid,
                "sim": True,
                "start": pin_info(self._start_sel),
                "stop": pin_info(self._stop_sel),
                "pins_selectable": True,
            }

    def pins(self) -> dict:
        with self._lock:
            return pins_payload(self._start_sel, self._stop_sel, True)

    def set_pins(self, start, stop) -> dict:
        s = parse_pin_sel(start)
        t = parse_pin_sel(stop)
        if s == t:
            raise ValueError("START and STOP must be different pins")
        with self._lock:
            self._start_sel = s
            self._stop_sel = t
            return pins_payload(self._start_sel, self._stop_sel, True)

class FpgaTdc(TdcDevice):
    def __init__(self, base: int = DEFAULT_BASE):
        self.base = base
        self._fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self._mem = mmap.mmap(
            self._fd,
            MAP_SIZE,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
            offset=base,
        )
        ident = self._read_u32(ADDR_ID)
        if ident != ID_VALUE:
            raise RuntimeError(
                "TDC ID register is 0x%08X (expected 0x%08X). Is the bitstream loaded?" % (ident, ID_VALUE)
            )
        self.clock_hz = self._read_u32(ADDR_CLOCK_HZ) or DEFAULT_CLOCK_HZ
        self._last_seq: Optional[int] = None
        self._latch_mono = time.monotonic()
        self._lock = threading.Lock()
        self._last_good: Optional[dict] = None
        self._good_mono = time.monotonic()

    def close(self) -> None:
        try:
            self._mem.close()
        finally:
            os.close(self._fd)

    def _read_u32(self, off: int) -> int:
        return struct.unpack_from("<I", self._mem, off)[0]

    def _read_i32(self, off: int) -> int:
        return struct.unpack_from("<i", self._mem, off)[0]

    def _write_u32(self, off: int, value: int) -> None:
        struct.pack_into("<I", self._mem, off, value & 0xFFFFFFFF)

    def _read_raw(self) -> dict:
        # Read seq first and last so a colliding update is obvious to the caller.
        seq1 = self._read_u32(ADDR_SEQ)
        status = self._read_u32(ADDR_STATUS)
        dt = self._read_i32(ADDR_DT_TICKS)
        t_start = self._read_u32(ADDR_T_START)
        t_stop = self._read_u32(ADDR_T_STOP)
        flags = self._read_u32(ADDR_FLAGS)
        seq2 = self._read_u32(ADDR_SEQ)
        if seq1 != seq2:
            seq1 = self._read_u32(ADDR_SEQ)
            status = self._read_u32(ADDR_STATUS)
            dt = self._read_i32(ADDR_DT_TICKS)
            t_start = self._read_u32(ADDR_T_START)
            t_stop = self._read_u32(ADDR_T_STOP)
            flags = self._read_u32(ADDR_FLAGS)
        return {
            "seq": seq1,
            "status": status,
            "dt": dt,
            "t_start": t_start,
            "t_stop": t_stop,
            "flags": flags,
        }

    def snapshot(self) -> dict:
        raw = self._read_raw()
        valid = bool(raw["status"] & STATUS_VALID)
        flags = raw["flags"]
        if not is_good_pair(valid, flags):
            for _ in range(7):
                raw = self._read_raw()
                valid = bool(raw["status"] & STATUS_VALID)
                flags = raw["flags"]
                if is_good_pair(valid, flags):
                    break

        seq = raw["seq"]
        armed = bool(raw["status"] & STATUS_ARMED)
        now = time.monotonic()
        with self._lock:
            if valid and seq != self._last_seq:
                self._last_seq = seq
                self._latch_mono = now
            age_ms = (now - self._latch_mono) * 1000.0 if valid else None

            if is_good_pair(valid, flags):
                self._last_good = {
                    "seq": seq,
                    "dt_ticks": raw["dt"],
                    "t_start": raw["t_start"],
                    "t_stop": raw["t_stop"],
                    "flags": flags,
                }
                self._good_mono = now
                return pack_snapshot(
                    valid=True,
                    seq=seq,
                    dt_ticks=raw["dt"],
                    t_start=raw["t_start"],
                    t_stop=raw["t_stop"],
                    flags=flags,
                    age_ms=age_ms,
                    armed=armed,
                    clock_hz=self.clock_hz,
                    fpga_seq=seq,
                    latest_flags=flags,
                    held=False,
                )

            if self._last_good is not None:
                g = self._last_good
                return pack_snapshot(
                    valid=True,
                    seq=g["seq"],
                    dt_ticks=g["dt_ticks"],
                    t_start=g["t_start"],
                    t_stop=g["t_stop"],
                    flags=g["flags"],
                    age_ms=(now - self._good_mono) * 1000.0,
                    armed=armed,
                    clock_hz=self.clock_hz,
                    fpga_seq=seq,
                    latest_flags=flags,
                    held=True,
                )

            return pack_snapshot(
                valid=False,
                seq=0,
                dt_ticks=0,
                t_start=raw["t_start"],
                t_stop=raw["t_stop"],
                flags=flags,
                age_ms=None,
                armed=armed,
                clock_hz=self.clock_hz,
                fpga_seq=seq,
                latest_flags=flags,
                held=False,
            )

    def health(self) -> dict:
        ident = self._read_u32(ADDR_ID)
        status = self._read_u32(ADDR_STATUS)
        ctrl = self._read_u32(ADDR_CONTROL)
        timeout = self._read_u32(ADDR_TIMEOUT)
        pins_word = self._read_u32(ADDR_PINS)
        selectable = pins_selectable(pins_word)
        start, stop = decode_pins_word(pins_word) if selectable else (DEFAULT_START_SEL, DEFAULT_STOP_SEL)
        out = {
            "ok": ident == ID_VALUE,
            "id": "TDC1" if ident == ID_VALUE else "0x%08X" % ident,
            "clock_hz": self.clock_hz,
            "enable": bool(ctrl & CTRL_ENABLE),
            "mmcm_locked": bool(status & STATUS_MMCM_LOCKED),
            "armed": bool(status & STATUS_ARMED),
            "valid": bool(status & STATUS_VALID),
            "timeout_ticks": timeout,
            "base": "0x%08X" % self.base,
            "sim": False,
            "pins_selectable": selectable,
        }
        if selectable:
            out["start"] = pin_info(start)
            out["stop"] = pin_info(stop)
        return out

    def pins(self) -> dict:
        word = self._read_u32(ADDR_PINS)
        selectable = pins_selectable(word)
        if not selectable:
            return {
                "selectable": False,
                "error": "this bitstream has no pin mux (rebuild tdc.bit)",
                "pins": pins_list(),
            }
        start, stop = decode_pins_word(word)
        return pins_payload(start, stop, True)

    def set_pins(self, start, stop) -> dict:
        word = self._read_u32(ADDR_PINS)
        if not pins_selectable(word):
            raise ValueError("this bitstream has no pin mux (rebuild tdc.bit)")
        s = parse_pin_sel(start)
        t = parse_pin_sel(stop)
        if s == t:
            raise ValueError("START and STOP must be different pins")
        self._write_u32(ADDR_PINS, encode_pins_word(s, t))
        enable = self._read_u32(ADDR_CONTROL) & CTRL_ENABLE
        self._write_u32(ADDR_CONTROL, enable | CTRL_SOFT_RESET)
        with self._lock:
            self._last_good = None
        return self.pins()


def apply_skew(snap: dict, skew_ns: float) -> dict:
    if snap.get("valid") and snap.get("dt_ns") is not None and skew_ns:
        snap = dict(snap)
        snap["dt_ns"] = snap["dt_ns"] - skew_ns
        snap["skew_ns"] = skew_ns
    return snap


class TdcHttpHandler(BaseHTTPRequestHandler):
    device: TdcDevice
    skew_ns: float = 0.0

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/api/latest":
            self._send_json(200, apply_skew(self.device.snapshot(), self.skew_ns))
            return
        if path == "/api/wait":
            timeout_ms = 1000
            if "timeout_ms" in qs:
                try:
                    timeout_ms = max(0, int(qs["timeout_ms"][0]))
                except ValueError:
                    self._send_json(400, {"error": "timeout_ms must be an integer"})
                    return
            first = self.device.snapshot()
            deadline = time.monotonic() + timeout_ms / 1000.0
            last = first
            while time.monotonic() < deadline:
                last = self.device.snapshot()
                if last.get("valid") and last.get("seq") != first.get("seq"):
                    last = dict(last)
                    last["wait_timed_out"] = False
                    self._send_json(200, apply_skew(last, self.skew_ns))
                    return
                time.sleep(0.001)
            last = dict(last)
            last["wait_timed_out"] = True
            self._send_json(200, apply_skew(last, self.skew_ns))
            return
        if path == "/api/health":
            self._send_json(200, self.device.health())
            return
        if path == "/api/pins":
            self._send_json(200, self.device.pins())
            return
        if path == "/":
            self._send_json(
                200,
                {
                    "service": "tdc",
                    "endpoints": [
                        "/api/latest",
                        "/api/wait?timeout_ms=1000",
                        "/api/health",
                        "/api/pins",
                    ],
                },
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != "/api/pins":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            self._send_json(400, {"error": "invalid JSON"})
            return
        if "start" not in body or "stop" not in body:
            self._send_json(400, {"error": "start and stop are required"})
            return
        try:
            payload = self.device.set_pins(body["start"], body["stop"])
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, payload)


class UdpPollHandler(BaseRequestHandler):
    def handle(self) -> None:
        data, sock = self.request
        snap = apply_skew(self.server.device.snapshot(), self.server.skew_ns)
        sock.sendto(json.dumps(snap, separators=(",", ":")).encode("utf-8"), self.client_address)


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Red Pitaya TDC poll server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--udp-port", type=int, default=8081, help="0 disables UDP poll")
    p.add_argument("--base", default=hex(DEFAULT_BASE), help="FPGA register base (hex or int)")
    p.add_argument("--skew-ns", type=float, default=0.0, help="Subtract splitter calibration (ns)")
    p.add_argument("--sim", action="store_true", help="Serve fake measurements (no FPGA)")
    p.add_argument("--sim-period-ms", type=float, default=10.0)
    p.add_argument("--sim-dt-ns", type=float, default=1_000_000.0)
    return p.parse_args(argv)


def parse_base(text: str) -> int:
    return int(text, 0)


SERVER_LOCK_PATH = "/tmp/pitaya_tdc.server.lock"


def port_in_use(host: str, port: int) -> bool:
    probe = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        return sock.connect_ex((probe, port)) == 0
    finally:
        sock.close()


def acquire_instance_lock() -> Optional[int]:
    try:
        import fcntl
    except ImportError:
        return None
    fd = os.open(SERVER_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        print(
            "tdc_server already running (lock %s)" % SERVER_LOCK_PATH,
            file=sys.stderr,
            flush=True,
        )
        return -1
    os.ftruncate(fd, 0)
    os.write(fd, ("%d\n" % os.getpid()).encode("ascii"))
    os.fsync(fd)
    return fd


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    lock_fd: Optional[int] = None
    if not args.sim:
        if port_in_use(args.host, args.port):
            print(
                "tdc_server already listening on %s:%d" % (args.host, args.port),
                file=sys.stderr,
                flush=True,
            )
            return 1
        lock_fd = acquire_instance_lock()
        if lock_fd == -1:
            return 1
    if args.sim:
        device: TdcDevice = SimTdc(period_s=args.sim_period_ms / 1000.0, dt_ns=args.sim_dt_ns)
    else:
        last_err: Optional[BaseException] = None
        device = None  # type: ignore[assignment]
        for _ in range(30):
            try:
                device = FpgaTdc(base=parse_base(args.base))
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                time.sleep(0.2)
        if last_err is not None:
            print("FPGA open failed: %s" % last_err, file=sys.stderr, flush=True)
            return 1

    TdcHttpHandler.device = device
    TdcHttpHandler.skew_ns = args.skew_ns

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), TdcHttpHandler)
    except OSError as exc:
        print(
            "could not bind %s:%d: %s" % (args.host, args.port, exc),
            file=sys.stderr,
            flush=True,
        )
        return 1
    udp = None
    if args.udp_port:
        udp = ThreadingUDPServer((args.host, args.udp_port), UdpPollHandler)
        udp.device = device
        udp.skew_ns = args.skew_ns
        threading.Thread(target=udp.serve_forever, daemon=True).start()

    mode = "sim" if args.sim else "fpga"
    print(
        "TDC poll server (%s) http://%s:%d/api/latest  udp %s"
        % (mode, args.host, args.port, args.udp_port or "off"),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        httpd.server_close()
        if udp is not None:
            udp.shutdown()
        close = getattr(device, "close", None)
        if close:
            close()
        if lock_fd is not None and lock_fd >= 0:
            os.close(lock_fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
