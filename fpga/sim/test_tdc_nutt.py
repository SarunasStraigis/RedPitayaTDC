#!/usr/bin/env python3
"""Nutt combine + code-density LUT (injected fine codes, no FPGA)."""

from __future__ import annotations

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sw"),
)

from tdc_nutt import (  # noqa: E402
    fine_ps,
    lut_from_hist,
    nutt_dt_ns,
    nutt_dt_ps,
    tclk_ps,
    uniform_lut,
)

CLOCK = 125_000_000
N_TAPS = 512
TCLK = tclk_ps(CLOCK)  # 8000 ps


def main() -> int:
    uni = uniform_lut(N_TAPS, CLOCK)
    if abs(uni[0]) > 1e-9 or abs(uni[N_TAPS] - TCLK) > 1e-6:
        raise AssertionError("uniform LUT endpoints: %r %r" % (uni[0], uni[-1]))
    if abs(uni[N_TAPS // 2] - TCLK / 2) > 1e-3:
        raise AssertionError("uniform midpoint %r" % uni[N_TAPS // 2])
    print("PASS uniform LUT")

    # Same coarse, STOP earlier in the period than START → positive dt.
    dt = nutt_dt_ps(10, 10, 50, 100, CLOCK, N_TAPS, uni)
    expect = fine_ps(100, uni, CLOCK, N_TAPS) - fine_ps(50, uni, CLOCK, N_TAPS)
    if abs(dt - expect) > 1e-6:
        raise AssertionError("same-tick nutt %r expected %r" % (dt, expect))
    print("PASS same-tick interpolator dt=%.3f ps" % dt)

    # One coarse tick, identical fine → exactly Tclk.
    dt = nutt_dt_ps(11, 10, 20, 20, CLOCK, N_TAPS, uni)
    if abs(dt - TCLK) > 1e-6:
        raise AssertionError("one tick %r" % dt)
    print("PASS one coarse tick = %.1f ps" % dt)

    # 1 ms coarse, small fine correction.
    n_1ms = 125000
    dt_ns = nutt_dt_ns(n_1ms, 0, 10, 30, CLOCK, N_TAPS, uni)
    corr = (fine_ps(30, uni, CLOCK, N_TAPS) - fine_ps(10, uni, CLOCK, N_TAPS)) / 1000.0
    if abs(dt_ns - (1e6 + corr)) > 1e-6:
        raise AssertionError("1 ms nutt %r corr %r" % (dt_ns, corr))
    print("PASS 1 ms + fine correction = %.6f ns" % dt_ns)

    hist = [0] * (N_TAPS + 1)
    for i in range(N_TAPS + 1):
        hist[i] = 10
    lut = lut_from_hist(hist, CLOCK)
    if lut is None or abs(lut[-1] - TCLK) > 1e-6:
        raise AssertionError("flat hist LUT %r" % (lut[-1] if lut else None))
    print("PASS code-density LUT span")

    if lut_from_hist([0, 0, 0], CLOCK) is not None:
        raise AssertionError("empty hist must yield None")
    print("PASS empty hist")
    print("TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
