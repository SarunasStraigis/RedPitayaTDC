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

from tdc_nutt import FineCal, default_cal_path, empty_hist, accumulate_hist, nutt_dt_ps
from tdc_regs import (
    ADDR_CLOCK_HZ,
    ADDR_CONTROL,
    ADDR_DT_TICKS,
    ADDR_FINE_BINS,
    ADDR_FINE_START,
    ADDR_FINE_STOP,
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
    DEFAULT_FINE_BINS,
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


READ_RAW_MAX_TRIES = 128
# STATUS (0x08) .. FINE_STOP (0x30) as one /dev/mem copy — 9 Python AXI
# beats are slower than a 10 µs 100 kHz period, so SEQ always moved.
_RESULT_BLOCK_OFF = ADDR_STATUS
_RESULT_BLOCK_N = ((ADDR_FINE_STOP - ADDR_STATUS) // 4) + 1


def _as_i32(u32: int) -> int:
    v = int(u32) & 0xFFFFFFFF
    if v >= 0x80000000:
        return v - 0x100000000
    return v


def _result_from_words(seq: int, words) -> dict:
    return {
        "seq": seq,
        "status": int(words[0]) & 0xFFFFFFFF,
        "dt": _as_i32(words[2]),
        "t_start": int(words[3]) & 0xFFFFFFFF,
        "t_stop": int(words[4]) & 0xFFFFFFFF,
        "flags": int(words[5]) & 0xFFFFFFFF,
        "fine_start": int(words[9]) & 0xFFFFFFFF,
        "fine_stop": int(words[10]) & 0xFFFFFFFF,
        "coherent": True,
    }


def coherent_mmio_read(read_u32, max_tries: int = READ_RAW_MAX_TRIES, read_block=None) -> dict:
    """Read the latest-result block only if SEQ is unchanged across the burst.

    At 100 kHz a new FPGA result can land between AXI-Lite beats. One retry is
    not enough; keep looping until the bookend SEQ values match. Prefer one
    multi-word copy of the result window so the burst fits inside one period.
    """
    def _block(off: int, n: int):
        if read_block is not None:
            return read_block(off, n)
        return [read_u32(off + 4 * i) & 0xFFFFFFFF for i in range(n)]

    for _ in range(max(1, int(max_tries))):
        seq1 = read_u32(ADDR_SEQ) & 0xFFFFFFFF
        seq_quiet = read_u32(ADDR_SEQ) & 0xFFFFFFFF
        if seq_quiet != seq1:
            continue
        words = _block(_RESULT_BLOCK_OFF, _RESULT_BLOCK_N)
        seq2 = read_u32(ADDR_SEQ) & 0xFFFFFFFF
        seq_mid = int(words[1]) & 0xFFFFFFFF
        if seq1 == seq2 == seq_mid:
            dt_reg = int(words[2]) & 0xFFFFFFFF
            dt_from_ts = (int(words[4]) - int(words[3])) & 0xFFFFFFFF
            if dt_reg != dt_from_ts:
                continue
            return _result_from_words(seq2, words)
    raise RuntimeError(
        "coherent_mmio_read: SEQ changed on every try (%d); refusing torn snapshot"
        % max(1, int(max_tries))
    )


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
    fine_start: int = 0,
    fine_stop: int = 0,
    fine_bins: int = 0,
    lut=None,
    calibrated: bool = False,
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
    t_stop_u = None if t_stop is None else (int(t_stop) & 0xFFFFFFFF)
    t_start_u = int(t_start) & 0xFFFFFFFF
    n_taps = int(fine_bins or 0)
    dt_ns = None
    dt_ps = None
    if valid:
        if n_taps > 0:
            stop_for_nutt = t_start_u + signed if t_stop_u is None else t_stop_u
            dt_ps = nutt_dt_ps(
                stop_for_nutt,
                t_start_u,
                int(fine_stop),
                int(fine_start),
                clock_hz,
                n_taps,
                lut,
            )
            dt_ns = dt_ps / 1000.0
        else:
            dt_ns = ticks_to_ns(signed, clock_hz)
            dt_ps = dt_ns * 1000.0
    out = {
        "valid": bool(valid),
        "seq": int(seq),
        "dt_ticks": signed,
        "dt_ns": dt_ns,
        "dt_ps": dt_ps,
        "t_start_ticks": t_start_u,
        "clock_hz": clock_hz,
        "flags": flag_names,
        "age_ms": None if age_ms is None else round(age_ms, 3),
        "armed": bool(armed),
        "fpga_seq": int(seq if fpga_seq is None else fpga_seq),
        "latest_flags": latest_names,
        "held": bool(held),
        "fine_start": int(fine_start),
        "fine_stop": int(fine_stop),
        "fine_bins": n_taps,
        "calibrated": bool(calibrated),
    }
    if t_stop_u is not None:
        out["t_stop_ticks"] = t_stop_u
    out["same_bin"] = bool(
        valid
        and not flag_names
        and t_stop_u is not None
        and t_start_u == t_stop_u
        and int(fine_start) == int(fine_stop)
    )
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

    def cal_status(self) -> dict:
        raise NotImplementedError

    def calibrate(self, n: int, timeout_s: float) -> dict:
        raise NotImplementedError


def pins_payload(start: int, stop: int, selectable: bool = True) -> dict:
    return {
        "selectable": selectable,
        "start": pin_info(start),
        "stop": pin_info(stop),
        "pins": pins_list(),
    }


def collect_calibration(device: TdcDevice, cal: FineCal, n: int, timeout_s: float, n_taps: int) -> dict:
    want = max(1, int(n))
    hist = empty_hist(n_taps)
    first = device.snapshot()
    last_seq = first.get("seq")
    collected = 0
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while collected < want and time.monotonic() < deadline:
        snap = device.snapshot()
        seq = snap.get("seq")
        flags = snap.get("flags") or []
        if (
            snap.get("valid")
            and not snap.get("held")
            and seq != last_seq
            and "timeout" not in flags
            and "overflow" not in flags
        ):
            last_seq = seq
            accumulate_hist(hist, int(snap.get("fine_start") or 0), int(snap.get("fine_stop") or 0))
            collected += 1
        else:
            time.sleep(0.001)
    ok = collected > 0 and cal.apply_hist(hist, collected)
    out = cal.status()
    out["ok"] = bool(ok)
    out["collected"] = collected
    out["requested"] = want
    if not ok:
        out["error"] = "not enough events" if collected == 0 else "could not build LUT"
    return out


class SimTdc(TdcDevice):
    """Software stand-in so the REST API can be exercised without a bitstream."""

    def __init__(
        self,
        period_s: float = 0.01,
        dt_ns: float = 1_000_000.0,
        clock_hz: int = DEFAULT_CLOCK_HZ,
        cal: Optional[FineCal] = None,
    ):
        self.clock_hz = clock_hz
        self.fine_bins = DEFAULT_FINE_BINS
        self.cal = cal or FineCal(default_cal_path(), self.fine_bins, clock_hz)
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
                t_stop=(self._t_start + self._dt_ticks) & 0xFFFFFFFF,
                flags=self._flags,
                age_ms=age_ms,
                armed=False,
                clock_hz=self.clock_hz,
                fpga_seq=self._seq,
                latest_flags=self._flags,
                held=False,
                fine_start=0,
                fine_stop=0,
                fine_bins=self.fine_bins,
                lut=self.cal.lut,
                calibrated=self.cal.calibrated,
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
                "fine_bins": self.fine_bins,
                "calibrated": self.cal.calibrated,
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

    def cal_status(self) -> dict:
        st = self.cal.status()
        st["ok"] = True
        return st

    def calibrate(self, n: int, timeout_s: float) -> dict:
        return collect_calibration(self, self.cal, n, timeout_s, self.fine_bins)

class FpgaTdc(TdcDevice):
    def __init__(self, base: int = DEFAULT_BASE, cal_path: Optional[str] = None):
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
        self.fine_bins = self._read_u32(ADDR_FINE_BINS)
        if self.fine_bins <= 0 or self.fine_bins > 4096:
            self.fine_bins = 0
        self.cal = FineCal(cal_path or default_cal_path(), self.fine_bins or DEFAULT_FINE_BINS, self.clock_hz)
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

    def _read_block(self, off: int, n: int):
        return struct.unpack_from("<%dI" % int(n), self._mem, off)

    def _read_i32(self, off: int) -> int:
        return struct.unpack_from("<i", self._mem, off)[0]

    def _write_u32(self, off: int, value: int) -> None:
        struct.pack_into("<I", self._mem, off, value & 0xFFFFFFFF)

    def _read_raw(self) -> dict:
        return coherent_mmio_read(self._read_u32, read_block=self._read_block)

    def snapshot(self) -> dict:
        try:
            raw = self._read_raw()
        except RuntimeError:
            now = time.monotonic()
            with self._lock:
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
                        armed=False,
                        clock_hz=self.clock_hz,
                        fpga_seq=g["seq"],
                        latest_flags=g["flags"],
                        held=True,
                        fine_start=g.get("fine_start", 0),
                        fine_stop=g.get("fine_stop", 0),
                        fine_bins=self.fine_bins,
                        lut=self.cal.lut,
                        calibrated=self.cal.calibrated,
                    )
            return pack_snapshot(
                valid=False,
                seq=0,
                dt_ticks=0,
                t_start=0,
                t_stop=0,
                flags=0,
                age_ms=None,
                armed=False,
                clock_hz=self.clock_hz,
                fpga_seq=0,
                latest_flags=0,
                held=False,
                fine_start=0,
                fine_stop=0,
                fine_bins=self.fine_bins,
                lut=self.cal.lut,
                calibrated=self.cal.calibrated,
            )
        valid = bool(raw["status"] & STATUS_VALID)
        flags = raw["flags"]
        if not is_good_pair(valid, flags):
            for _ in range(7):
                try:
                    raw = self._read_raw()
                except RuntimeError:
                    break
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
                if raw["dt"] != 0:
                    self._last_good = {
                        "seq": seq,
                        "dt_ticks": raw["dt"],
                        "t_start": raw["t_start"],
                        "t_stop": raw["t_stop"],
                        "flags": flags,
                        "fine_start": raw.get("fine_start", 0),
                        "fine_stop": raw.get("fine_stop", 0),
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
                    fine_start=raw.get("fine_start", 0),
                    fine_stop=raw.get("fine_stop", 0),
                    fine_bins=self.fine_bins,
                    lut=self.cal.lut,
                    calibrated=self.cal.calibrated,
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
                    fine_start=g.get("fine_start", 0),
                    fine_stop=g.get("fine_stop", 0),
                    fine_bins=self.fine_bins,
                    lut=self.cal.lut,
                    calibrated=self.cal.calibrated,
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
                fine_start=raw.get("fine_start", 0),
                fine_stop=raw.get("fine_stop", 0),
                fine_bins=self.fine_bins,
                lut=self.cal.lut,
                calibrated=self.cal.calibrated,
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
            "fine_bins": self.fine_bins,
            "calibrated": self.cal.calibrated,
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

    def cal_status(self) -> dict:
        st = self.cal.status()
        st["ok"] = True
        st["fine_bins"] = self.fine_bins
        return st

    def calibrate(self, n: int, timeout_s: float) -> dict:
        if self.fine_bins <= 0:
            return {"ok": False, "error": "this bitstream has no interpolator", "calibrated": False}
        return collect_calibration(self, self.cal, n, timeout_s, self.fine_bins)


def apply_skew(snap: dict, skew_ns: float) -> dict:
    if snap.get("valid") and snap.get("dt_ns") is not None and skew_ns:
        snap = dict(snap)
        snap["dt_ns"] = snap["dt_ns"] - skew_ns
        if snap.get("dt_ps") is not None:
            snap["dt_ps"] = snap["dt_ps"] - skew_ns * 1000.0
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
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
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
        if path == "/api/calibrate":
            self._send_json(200, self.device.cal_status())
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
                        "/api/calibrate",
                    ],
                },
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != "/api/calibrate":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        n = body.get("n", 5000)
        timeout_s = body.get("timeout_s", 30.0)
        try:
            n = int(n)
            timeout_s = float(timeout_s)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "n and timeout_s must be numbers"})
            return
        payload = self.device.calibrate(n, timeout_s)
        self._send_json(200 if payload.get("ok") else 408, payload)

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
    p.add_argument("--cal-file", default=None, help="Code-density LUT JSON (default /root/tdc/cal.json)")
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
        device: TdcDevice = SimTdc(
            period_s=args.sim_period_ms / 1000.0,
            dt_ns=args.sim_dt_ns,
            cal=FineCal(args.cal_file or default_cal_path(), DEFAULT_FINE_BINS, DEFAULT_CLOCK_HZ),
        )
    else:
        last_err: Optional[BaseException] = None
        device = None  # type: ignore[assignment]
        for _ in range(30):
            try:
                device = FpgaTdc(base=parse_base(args.base), cal_path=args.cal_file)
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
