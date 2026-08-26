#!/usr/bin/env python3
"""Cycle-accurate model of tdc_timestamp.v (125 MHz + 4 ns DDR ticks)."""

from __future__ import annotations

TIMEOUT_TICKS = 2500


class TdcTimestamp:
    def __init__(self):
        self.coarse = 0
        self.state = 0
        self.armed = 0
        self.wait_ticks = 0
        self.t_start_r = 0
        self.seq = 0
        self.timeout_hit_r = 0
        self.result_strobe = 0
        self.result_seq = 0
        self.result_dt_ticks = 0
        self.result_t_start = 0
        self.result_t_stop = 0
        self.result_timeout = 0
        self.result_overflow = 0
        self.result_unmatched_stop = 0
        self.rst = 1
        self.enable = 0
        self.start_rise_r = 0
        self.start_rise_f = 0
        self.stop_rise_r = 0
        self.stop_rise_f = 0
        self.timeout_ticks = 500_000_000

    def _ts(self, rise_r: int, rise_f: int) -> int:
        fine = 0 if rise_r else 1
        return ((self.coarse & 0x7FFFFFFF) << 1) | fine

    def step(self) -> None:
        self.result_strobe = 0
        start_ev = self.start_rise_r or self.start_rise_f
        stop_ev = self.stop_rise_r or self.stop_rise_f
        ts_start = self._ts(self.start_rise_r, self.start_rise_f)
        ts_stop = self._ts(self.stop_rise_r, self.stop_rise_f)
        ts_r = (self.coarse & 0x7FFFFFFF) << 1
        wait_wrap = self.wait_ticks >= 0xFFFFFFFE
        timeout_hit_now = self.timeout_hit_r
        coarse_n = (self.coarse + 1) & 0x7FFFFFFF

        if self.rst:
            self.coarse = 0
            self.state = 0
            self.armed = 0
            self.wait_ticks = 0
            self.t_start_r = 0
            self.seq = 0
            self.timeout_hit_r = 0
            self.result_seq = 0
            self.result_dt_ticks = 0
            self.result_t_start = 0
            self.result_t_stop = 0
            self.result_timeout = 0
            self.result_overflow = 0
            self.result_unmatched_stop = 0
            return

        timeout_hit_next = (
            self.enable
            and self.timeout_ticks != 0
            and self.wait_ticks >= self.timeout_ticks
        )

        if not self.enable:
            self.state = 0
            self.armed = 0
            self.wait_ticks = 0
            self.coarse = coarse_n
            self.timeout_hit_r = timeout_hit_next
            return

        if self.state == 0:
            self.armed = 0
            self.wait_ticks = 0
            if start_ev and stop_ev:
                self._emit((ts_stop - ts_start) & 0xFFFFFFFF, ts_start, ts_stop, 0, 0, 0)
            elif start_ev:
                self.t_start_r = ts_start
                self.wait_ticks = 0
                self.state = 1
                self.armed = 1
            # STOP while idle is ignored (leftover DDR beat must not clobber dt).
        else:
            self.armed = 1
            wait_n = (self.wait_ticks + 2) & 0xFFFFFFFF
            if stop_ev:
                self._emit((ts_stop - self.t_start_r) & 0xFFFFFFFF, self.t_start_r, ts_stop, 0, 0, 0)
                self.state = 0
                self.armed = 0
                self.wait_ticks = 0
            elif start_ev:
                self.t_start_r = ts_start
                self.wait_ticks = 0
            elif timeout_hit_now or wait_wrap:
                self._emit(self.wait_ticks, self.t_start_r, ts_r, int(timeout_hit_now), int(wait_wrap), 0)
                self.state = 0
                self.armed = 0
                self.wait_ticks = 0
            else:
                self.wait_ticks = wait_n

        self.coarse = coarse_n
        self.timeout_hit_r = timeout_hit_next

    def _emit(self, dt, t0, t1, timeout, overflow, unmatch) -> None:
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        self.result_strobe = 1
        self.result_seq = self.seq
        self.result_dt_ticks = dt
        self.result_t_start = t0
        self.result_t_stop = t1
        self.result_timeout = timeout
        self.result_overflow = overflow
        self.result_unmatched_stop = unmatch


def wait_clks(dut: TdcTimestamp, n: int) -> None:
    for _ in range(n):
        dut.step()


def pulse_pair(dut: TdcTimestamp, delay_ticks: int) -> None:
    dut.start_rise_r = 1
    dut.start_rise_f = 0
    dut.stop_rise_r = int(delay_ticks == 0)
    dut.stop_rise_f = int(delay_ticks == 1)
    dut.step()
    dut.start_rise_r = 0
    dut.stop_rise_r = 0
    dut.stop_rise_f = 0
    if delay_ticks >= 2:
        k = delay_ticks // 2
        wait_clks(dut, k - 1)
        dut.stop_rise_r = int(delay_ticks % 2 == 0)
        dut.stop_rise_f = int(delay_ticks % 2 != 0)
        dut.step()
        dut.stop_rise_r = 0
        dut.stop_rise_f = 0


def wait_result(dut: TdcTimestamp, max_cycles: int) -> bool:
    if dut.result_strobe:
        return True
    for _ in range(max_cycles):
        dut.step()
        if dut.result_strobe:
            return True
    return False


def expect_dt(dut: TdcTimestamp, name: str, exp_dt: int, exp_timeout: int, exp_unmatch: int) -> None:
    if not wait_result(dut, 20000):
        raise AssertionError("%s: no result_strobe" % name)
    if dut.result_dt_ticks != exp_dt:
        raise AssertionError("%s: dt=%s expected %s" % (name, dut.result_dt_ticks, exp_dt))
    if dut.result_timeout != exp_timeout:
        raise AssertionError("%s: timeout=%s expected %s" % (name, dut.result_timeout, exp_timeout))
    if dut.result_unmatched_stop != exp_unmatch:
        raise AssertionError("%s: unmatched=%s expected %s" % (name, dut.result_unmatched_stop, exp_unmatch))
    print("PASS %s: dt=%d ticks (%d ns)" % (name, dut.result_dt_ticks, dut.result_dt_ticks * 4))


def main() -> int:
    dut = TdcTimestamp()
    wait_clks(dut, 8)
    dut.rst = 0
    wait_clks(dut, 4)
    dut.enable = 1
    wait_clks(dut, 4)

    print("=== 0 ns ===")
    pulse_pair(dut, 0)
    expect_dt(dut, "0ns", 0, 0, 0)

    print("=== 4 ns ===")
    pulse_pair(dut, 1)
    expect_dt(dut, "4ns", 1, 0, 0)

    print("=== 20 ns ===")
    pulse_pair(dut, 5)
    expect_dt(dut, "20ns", 5, 0, 0)

    print("=== 1 ms ===")
    pulse_pair(dut, 250000)
    expect_dt(dut, "1ms", 250000, 0, 0)

    print("=== 10 ms ===")
    pulse_pair(dut, 2500000)
    expect_dt(dut, "10ms", 2500000, 0, 0)

    print("=== unmatched STOP is ignored ===")
    prev_dt = dut.result_dt_ticks
    prev_seq = dut.result_seq
    dut.stop_rise_r = 1
    dut.step()
    dut.stop_rise_r = 0
    wait_clks(dut, 4)
    if dut.result_strobe:
        raise AssertionError("unmatched STOP must not strobe")
    if dut.result_dt_ticks != prev_dt or dut.result_seq != prev_seq:
        raise AssertionError("unmatched STOP clobbered last dt/seq")
    if dut.result_unmatched_stop:
        raise AssertionError("unmatched flag must stay clear when STOP is ignored")
    print("PASS unmatched ignored: dt=%d seq=%d" % (dut.result_dt_ticks, dut.result_seq))

    print("=== leftover DDR STOP after good pair ===")
    pulse_pair(dut, 5)
    expect_dt(dut, "20ns-before-leftover", 5, 0, 0)
    dut.stop_rise_f = 1
    dut.step()
    dut.stop_rise_f = 0
    wait_clks(dut, 3)
    if dut.result_dt_ticks != 5 or dut.result_unmatched_stop:
        raise AssertionError("leftover STOP beat clobbered dt")
    print("PASS leftover STOP: dt=%d" % dut.result_dt_ticks)

    print("=== timeout ===")
    dut.timeout_ticks = TIMEOUT_TICKS
    wait_clks(dut, 2)
    dut.start_rise_r = 1
    dut.step()
    dut.start_rise_r = 0
    if not wait_result(dut, TIMEOUT_TICKS + 32):
        raise AssertionError("timeout: no strobe")
    if not dut.result_timeout or dut.result_unmatched_stop:
        raise AssertionError("timeout flags wrong")
    print("PASS timeout: dt=%d timeout=1" % dut.result_dt_ticks)
    print("TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
