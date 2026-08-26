"""Nutt interpolation: combine coarse ticks with calibrated delay-line bins."""

from __future__ import annotations

import json
import os
from typing import Iterable, List, Optional


def tclk_ps(clock_hz: int) -> float:
    if clock_hz <= 0:
        return 0.0
    return 1e12 / float(clock_hz)


def uniform_lut(n_taps: int, clock_hz: int) -> List[float]:
    """lut[k] = time-from-hit-to-clock for ones-count k, assuming equal taps."""
    period = tclk_ps(clock_hz)
    if n_taps <= 0:
        return [0.0]
    return [period * k / float(n_taps) for k in range(n_taps + 1)]


def lut_from_hist(hist: Iterable[int], clock_hz: int) -> Optional[List[float]]:
    """Code-density LUT: lut[k] is time-from-hit-to-clock for ones-count k."""
    counts = [max(0, int(c)) for c in hist]
    total = sum(counts)
    if total <= 0 or len(counts) < 2:
        return None
    period = tclk_ps(clock_hz)
    lut = [0.0]
    acc = 0.0
    for c in counts[:-1]:
        acc += (c / float(total)) * period
        lut.append(acc)
    lut[-1] = period
    return lut


def fine_ps(bin_index: int, lut: Optional[List[float]], clock_hz: int, n_taps: int) -> float:
    idx = int(bin_index)
    if idx < 0:
        idx = 0
    if lut:
        if idx >= len(lut):
            idx = len(lut) - 1
        return float(lut[idx])
    uni = uniform_lut(n_taps, clock_hz)
    if idx >= len(uni):
        idx = len(uni) - 1
    return uni[idx]


def signed32(value: int) -> int:
    v = int(value) & 0xFFFFFFFF
    if v >= 0x80000000:
        return v - 0x100000000
    return v


def nutt_dt_ps(
    t_stop: int,
    t_start: int,
    fine_stop: int,
    fine_start: int,
    clock_hz: int,
    n_taps: int,
    lut: Optional[List[float]] = None,
) -> float:
    """dt = (N_stop - N_start)*Tclk - (t_fine_stop - t_fine_start)."""
    dn = signed32((int(t_stop) - int(t_start)) & 0xFFFFFFFF)
    period = tclk_ps(clock_hz)
    fs = fine_ps(fine_start, lut, clock_hz, n_taps)
    ft = fine_ps(fine_stop, lut, clock_hz, n_taps)
    return dn * period - (ft - fs)


def nutt_dt_ns(
    t_stop: int,
    t_start: int,
    fine_stop: int,
    fine_start: int,
    clock_hz: int,
    n_taps: int,
    lut: Optional[List[float]] = None,
) -> float:
    return nutt_dt_ps(t_stop, t_start, fine_stop, fine_start, clock_hz, n_taps, lut) / 1000.0


def empty_hist(n_taps: int) -> List[int]:
    return [0] * (max(0, int(n_taps)) + 1)


def accumulate_hist(hist: List[int], *bins: int) -> None:
    last = len(hist) - 1
    if last < 0:
        return
    for b in bins:
        i = int(b)
        if i < 0:
            i = 0
        if i > last:
            i = last
        hist[i] += 1


class FineCal:
    """Code-density calibration persisted as JSON."""

    def __init__(self, path: str, n_taps: int, clock_hz: int):
        self.path = path
        self.n_taps = int(n_taps)
        self.clock_hz = int(clock_hz)
        self.lut: Optional[List[float]] = None
        self.hist: List[int] = empty_hist(self.n_taps)
        self.events = 0
        self.load()

    @property
    def calibrated(self) -> bool:
        return self.lut is not None and len(self.lut) > 1

    def load(self) -> bool:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False
        lut = data.get("lut_ps")
        n_taps = int(data.get("n_taps", self.n_taps) or self.n_taps)
        if not isinstance(lut, list) or len(lut) < 2:
            return False
        self.n_taps = n_taps
        self.lut = [float(x) for x in lut]
        hist = data.get("hist")
        if isinstance(hist, list) and hist:
            self.hist = [int(x) for x in hist]
        self.events = int(data.get("events", 0) or 0)
        return True

    def save(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError:
                pass
        payload = {
            "n_taps": self.n_taps,
            "clock_hz": self.clock_hz,
            "events": self.events,
            "lut_ps": self.lut,
            "hist": self.hist,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, self.path)

    def apply_hist(self, hist: List[int], events: int) -> bool:
        lut = lut_from_hist(hist, self.clock_hz)
        if lut is None:
            return False
        self.hist = list(hist)
        self.events = int(events)
        self.n_taps = max(0, len(hist) - 1)
        self.lut = lut
        self.save()
        return True

    def status(self) -> dict:
        return {
            "calibrated": self.calibrated,
            "n_taps": self.n_taps,
            "events": self.events,
            "path": self.path,
        }


def default_cal_path() -> str:
    if os.path.isdir("/root/tdc"):
        return "/root/tdc/cal.json"
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "tdc_cal.json")
