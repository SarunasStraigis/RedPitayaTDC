#!/usr/bin/env python3
"""Live TDC monitor: polls /api/health and /api/latest and shows a small GUI."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import urllib.error
import urllib.request

DEFAULT_URL = "http://rp-f0cebb.local:8080"
POLL_MS = 100


def get_json(url: str, timeout: float = 1.5) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def put_json(url: str, payload: dict, timeout: float = 2.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt_ns(dt_ns) -> str:
    if dt_ns is None:
        return "—"
    try:
        v = float(dt_ns)
    except (TypeError, ValueError):
        return str(dt_ns)
    av = abs(v)
    if av >= 1e6:
        return "%.6f ms" % (v / 1e6)
    if av >= 1e3:
        return "%.3f µs" % (v / 1e3)
    return "%.3f ns" % v


BAD_FLAGS = ("unmatched_stop", "timeout", "overflow")


def latest_flags(latest: dict) -> list:
    if latest.get("latest_flags") is not None:
        return list(latest.get("latest_flags") or [])
    return list(latest.get("flags") or [])


def fpga_seq_of(latest: dict):
    if latest.get("fpga_seq") is not None:
        return int(latest["fpga_seq"])
    if latest.get("seq") is not None:
        return int(latest["seq"])
    return None


def is_raw_good(latest: dict) -> bool:
    if not latest or latest.get("held"):
        return False
    if not latest.get("valid"):
        return False
    flags = latest_flags(latest)
    return not any(f in flags for f in BAD_FLAGS)


def meaning(flags, valid, armed) -> str:
    flags = flags or []
    if not valid:
        return "No completed pair yet. Waiting for START, then STOP."
    if "unmatched_stop" in flags:
        return "STOP rose while idle (no START first). Not a delay."
    if "timeout" in flags:
        return "START seen, STOP never arrived (timeout)."
    if "overflow" in flags:
        return "Wait counter wrapped. Interval too long."
    if armed:
        return "Good last pair. Currently armed — waiting for STOP."
    return "Good START→STOP pair."


class Monitor(tk.Tk):
    def __init__(self, url: str):
        super().__init__()
        self.title("Pitaya TDC")
        self.geometry("640x520")
        self.minsize(520, 420)

        self.url = tk.StringVar(value=url.rstrip("/"))
        self.status = tk.StringVar(value="Disconnected")
        self.dt = tk.StringVar(value="—")
        self.seq = tk.StringVar(value="—")
        self.fpga_seq = tk.StringVar(value="—")
        self.flags = tk.StringVar(value="—")
        self.latest_flags = tk.StringVar(value="—")
        self.held = tk.StringVar(value="—")
        self.same_bin = tk.StringVar(value="—")
        self.t_start = tk.StringVar(value="—")
        self.t_stop = tk.StringVar(value="—")
        self.armed = tk.StringVar(value="—")
        self.age = tk.StringVar(value="—")
        self.rate = tk.StringVar(value="—")
        self.meaning = tk.StringVar(value="Enter Pitaya URL and click Start.")
        self.health = tk.StringVar(value="—")
        self.wiring = tk.StringVar(
            value="Default START is DIO7_P (E1 pin 17), STOP is DIO7_N (E1 pin 18)."
        )
        self.start_pin = tk.StringVar()
        self.stop_pin = tk.StringVar()

        self.valid_only = tk.BooleanVar(value=True)
        self._running = False
        self._last_seq = None
        self._seq_window = []  # (t, seq)
        self._last_good = None
        self._lock = threading.Lock()
        self._pending = None
        self._pin_by_label = {}
        self._filling_pins = False
        self._pins_loaded = False

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._drain)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self)
        top.pack(fill=tk.X, **pad)
        ttk.Label(top, text="Server").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.url).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.btn = ttk.Button(top, text="Start", command=self._toggle)
        self.btn.pack(side=tk.LEFT)

        ttk.Label(self, textvariable=self.status, font=("Segoe UI", 10)).pack(anchor=tk.W, **pad)

        big = ttk.Frame(self)
        big.pack(fill=tk.X, **pad)
        ttk.Label(big, text="Interval", font=("Segoe UI", 11)).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(big, textvariable=self.dt, font=("Consolas", 28)).grid(row=1, column=0, sticky=tk.W)

        pins = ttk.Frame(self)
        pins.pack(fill=tk.X, **pad)
        ttk.Label(pins, text="START").pack(side=tk.LEFT)
        self.start_combo = ttk.Combobox(
            pins, textvariable=self.start_pin, state="readonly", width=28
        )
        self.start_combo.pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(pins, text="STOP").pack(side=tk.LEFT)
        self.stop_combo = ttk.Combobox(
            pins, textvariable=self.stop_pin, state="readonly", width=28
        )
        self.stop_combo.pack(side=tk.LEFT, padx=6)
        self.start_combo.bind("<<ComboboxSelected>>", self._on_pin_change)
        self.stop_combo.bind("<<ComboboxSelected>>", self._on_pin_change)

        grid = ttk.Frame(self)
        grid.pack(fill=tk.X, **pad)
        rows = [
            ("seq", self.seq),
            ("fpga seq", self.fpga_seq),
            ("flags", self.flags),
            ("latest flags", self.latest_flags),
            ("held", self.held),
            ("same bin", self.same_bin),
            ("t_start", self.t_start),
            ("t_stop", self.t_stop),
            ("armed", self.armed),
            ("age", self.age),
            ("event rate", self.rate),
            ("health", self.health),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky=tk.W, padx=(0, 12), pady=1)
            ttk.Label(grid, textvariable=var, font=("Consolas", 11)).grid(row=i, column=1, sticky=tk.W)

        ttk.Label(self, textvariable=self.meaning, wraplength=600, justify=tk.LEFT).pack(
            anchor=tk.W, **pad
        )
        ttk.Label(self, textvariable=self.wiring, wraplength=600, foreground="#666").pack(
            anchor=tk.W, **pad
        )

        log_hdr = ttk.Frame(self)
        log_hdr.pack(fill=tk.X, padx=8)
        ttk.Label(log_hdr, text="New measurements (seq changed)").pack(side=tk.LEFT)
        ttk.Checkbutton(
            log_hdr,
            text="Valid only",
            variable=self.valid_only,
        ).pack(side=tk.RIGHT)
        self.log = tk.Text(self, height=12, font=("Consolas", 10), state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    def _toggle(self) -> None:
        if self._running:
            self._running = False
            self.btn.config(text="Start")
            self.status.set("Stopped")
            return
        self._running = True
        self.btn.config(text="Stop")
        self.status.set("Polling…")
        self._pins_loaded = False
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self) -> None:
        while self._running:
            base = self.url.get().rstrip("/")
            err = None
            health = None
            latest = None
            pins = None
            try:
                health = get_json(base + "/api/health")
                latest = get_json(base + "/api/latest")
            except Exception as exc:
                err = str(exc)
            if err is None and not self._pins_loaded:
                try:
                    pins = get_json(base + "/api/pins")
                except Exception:
                    pins = None
            with self._lock:
                self._pending = (time.time(), err, health, latest, pins)
            time.sleep(POLL_MS / 1000.0)

    def _drain(self) -> None:
        item = None
        with self._lock:
            if self._pending is not None:
                item = self._pending
                self._pending = None
        if item:
            self._apply(*item)
        self.after(50, self._drain)

    def _apply_pins(self, payload) -> None:
        if not payload:
            return
        entries = payload.get("pins") or []
        if not entries:
            return
        labels = [p.get("label") or p.get("name") for p in entries]
        self._pin_by_label = {p.get("label") or p.get("name"): p["index"] for p in entries}
        self._filling_pins = True
        self.start_combo["values"] = labels
        self.stop_combo["values"] = labels
        if payload.get("start"):
            self.start_pin.set(payload["start"].get("label") or "")
        if payload.get("stop"):
            self.stop_pin.set(payload["stop"].get("label") or "")
        selectable = bool(payload.get("selectable"))
        state = "readonly" if selectable else "disabled"
        self.start_combo.config(state=state)
        self.stop_combo.config(state=state)
        self._filling_pins = False
        self._pins_loaded = True
        s = (payload.get("start") or {}).get("label")
        t = (payload.get("stop") or {}).get("label")
        if not selectable:
            self.wiring.set(
                payload.get("error")
                or "Pin mux not in this bitstream. Rebuild tdc.bit. Default is DIO7_P (E1 pin 17) / DIO7_N (E1 pin 18)."
            )
        elif s and t:
            self.wiring.set("START = %s, STOP = %s (3.3 V TTL rising edge)." % (s, t))

    def _on_pin_change(self, _event=None) -> None:
        if self._filling_pins or not self._running:
            return
        start = self._pin_by_label.get(self.start_pin.get())
        stop = self._pin_by_label.get(self.stop_pin.get())
        if start is None or stop is None:
            return
        if start == stop:
            self.meaning.set("START and STOP must be different pins.")
            return
        self._last_good = None
        base = self.url.get().rstrip("/")

        def worker():
            try:
                payload = put_json(base + "/api/pins", {"start": start, "stop": stop})
                self.after(0, lambda: self._apply_pins(payload))
            except Exception as exc:
                self.after(0, lambda: self.meaning.set(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _apply(self, now: float, err, health, latest, pins=None) -> None:
        if err:
            self.status.set("Error: " + err)
            self.health.set("offline")
            self.meaning.set("Cannot reach the Pitaya. Is tdc_server.py running?")
            return

        ok = bool(health and health.get("ok"))
        hid = (health or {}).get("id", "?")
        en = (health or {}).get("enable")
        locked = (health or {}).get("mmcm_locked")
        self.health.set("id=%s  enable=%s  mmcm=%s" % (hid, en, locked))
        self.status.set("Connected" if ok else "FPGA ID mismatch — is tdc.bin loaded?")
        if pins:
            self._apply_pins(pins)

        latest = latest or {}
        valid = bool(latest.get("valid"))
        seq = latest.get("seq")
        flags = latest_flags(latest)
        armed = bool(latest.get("armed"))
        raw_good = is_raw_good(latest)
        fpga_seq = fpga_seq_of(latest)
        if (raw_good or (latest.get("held") and latest.get("valid"))) and latest.get("dt_ns") != 0:
            self._last_good = dict(latest)
            self._last_good["_seen"] = now

        show = latest
        if self.valid_only.get() and not raw_good and not latest.get("held"):
            show = self._last_good
        shown_valid = bool(show and show.get("valid"))
        shown_flags = latest_flags(show) if show else []
        if show is latest:
            shown_flags = flags
        shown_seq = show.get("seq") if show else None
        dt_ns = show.get("dt_ns") if show and shown_valid else None

        self.dt.set(fmt_ns(dt_ns) if shown_valid else "—")
        self.seq.set(str(shown_seq) if shown_seq is not None else "—")
        self.fpga_seq.set(str(fpga_seq) if fpga_seq is not None else "—")
        self.flags.set(", ".join(shown_flags) if shown_flags else "(none)")
        self.latest_flags.set(", ".join(flags) if flags else "(none)")
        self.held.set("yes" if latest.get("held") else "no")
        self.same_bin.set("yes" if show and show.get("same_bin") else "no")
        t0 = show.get("t_start_ticks") if show else None
        t1 = show.get("t_stop_ticks") if show else None
        self.t_start.set(str(t0) if t0 is not None else "—")
        self.t_stop.set(str(t1) if t1 is not None else "—")
        self.armed.set("yes — waiting for STOP" if armed else "no")
        age = show.get("age_ms") if show else None
        if show is self._last_good and show is not latest and isinstance(show.get("_seen"), float):
            age = (now - show["_seen"]) * 1000.0
        self.age.set("%.1f ms" % age if isinstance(age, (int, float)) else "—")
        if (
            show
            and show.get("same_bin")
            and show.get("dt_ns") == 0
            and not show.get("held")
        ):
            self.meaning.set("START and STOP in the same coarse tick and interpolator bin (true 0 ns, or crosstalk).")
        elif latest.get("held") or (self.valid_only.get() and not raw_good):
            if self._last_good is None and not latest.get("held"):
                self.meaning.set("Waiting for a valid START→STOP pair.")
            else:
                self.meaning.set("Holding last valid pair. Latest FPGA result was not a delay.")
        else:
            self.meaning.set(meaning(flags, valid, armed))

        if fpga_seq is not None:
            self._seq_window.append((now, fpga_seq))
            cutoff = now - 1.0
            self._seq_window = [(t, s) for t, s in self._seq_window if t >= cutoff]
            if len(self._seq_window) >= 2:
                dt = self._seq_window[-1][0] - self._seq_window[0][0]
                ds = self._seq_window[-1][1] - self._seq_window[0][1]
                hz = ds / dt if dt > 0 else 0.0
                self.rate.set("%.0f events/s" % hz if hz >= 1 else "%.2f events/s" % hz)
            else:
                self.rate.set("—")

            if self._last_seq is not None and fpga_seq != self._last_seq:
                if (not self.valid_only.get()) or raw_good:
                    line = "%s  seq=%s  %s  flags=%s  latest=%s  held=%s  same_bin=%s  t=%s..%s  armed=%s\n" % (
                        time.strftime("%H:%M:%S"),
                        seq if seq is not None else fpga_seq,
                        fmt_ns(dt_ns if shown_valid else None),
                        ",".join(shown_flags) if shown_flags else "-",
                        ",".join(flags) if flags else "-",
                        bool(latest.get("held")),
                        bool(show.get("same_bin") if show else False),
                        latest.get("t_start_ticks", "-"),
                        latest.get("t_stop_ticks", "-"),
                        armed,
                    )
                    self.log.config(state=tk.NORMAL)
                    self.log.insert(tk.END, line)
                    self.log.see(tk.END)
                    self.log.config(state=tk.DISABLED)
            self._last_seq = fpga_seq

    def _on_close(self) -> None:
        self._running = False
        self.destroy()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Live GUI for the Red Pitaya TDC poll API")
    p.add_argument("--url", default=DEFAULT_URL)
    args = p.parse_args(argv)
    try:
        app = Monitor(args.url)
    except tk.TclError as exc:
        print("tkinter UI failed (%s). Use: python sw/tdc_poll.py --loop --url ..." % exc, file=sys.stderr)
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
