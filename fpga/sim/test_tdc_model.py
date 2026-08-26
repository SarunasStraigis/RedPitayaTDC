#!/usr/bin/env python3
"""Cycle-accurate model of tdc_timestamp.v (125 MHz coarse + fine bins)."""

from __future__ import annotations

TIMEOUT_TICKS = 2500


class TdcTimestamp:
    def __init__(self):
        self.ts_now = 0
        self.state = 0
        self.armed = 0
        self.wait_ticks = 0
        self.t_start_r = 0
        self.fine_start_r = 0
        self.seq = 0
        self.timeout_hit_r = 0
        self.result_strobe = 0
        self.result_seq = 0
        self.result_dt_ticks = 0
        self.result_t_start = 0
        self.result_t_stop = 0
        self.result_fine_start = 0
        self.result_fine_stop = 0
        self.result_timeout = 0
        self.result_overflow = 0
        self.result_unmatched_stop = 0
        self.rst = 1
        self.enable = 0
        self.start_rise = 0
        self.stop_rise = 0
        self.start_fine = 0
        self.stop_fine = 0
        self.timeout_ticks = 250_000_000

    def step(self) -> None:
        self.result_strobe = 0
        start_ev = self.start_rise
        stop_ev = self.stop_rise
        wait_wrap = self.wait_ticks >= 0xFFFFFFFE
        timeout_hit_now = self.timeout_hit_r
        ts = self.ts_now & 0xFFFFFFFF

        if self.rst:
            self.ts_now = 0
            self.state = 0
            self.armed = 0
            self.wait_ticks = 0
            self.t_start_r = 0
            self.fine_start_r = 0
            self.seq = 0
            self.timeout_hit_r = 0
            self.result_seq = 0
            self.result_dt_ticks = 0
            self.result_t_start = 0
            self.result_t_stop = 0
            self.result_fine_start = 0
            self.result_fine_stop = 0
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
            self.ts_now = (ts + 1) & 0xFFFFFFFF
            self.timeout_hit_r = timeout_hit_next
            return

        if self.state == 0:
            self.armed = 0
            self.wait_ticks = 0
            if start_ev and stop_ev:
                self._emit(0, ts, ts, self.start_fine, self.stop_fine, 0, 0, 0)
            elif start_ev:
                self.t_start_r = ts
                self.fine_start_r = self.start_fine
                self.wait_ticks = 0
                self.state = 1
                self.armed = 1
        else:
            self.armed = 1
            wait_n = (self.wait_ticks + 1) & 0xFFFFFFFF
            if stop_ev:
                self._emit(
                    (ts - self.t_start_r) & 0xFFFFFFFF,
                    self.t_start_r,
                    ts,
                    self.fine_start_r,
                    self.stop_fine,
                    0,
                    0,
                    0,
                )
                self.state = 0
                self.armed = 0
                self.wait_ticks = 0
            elif start_ev:
                self.t_start_r = ts
                self.fine_start_r = self.start_fine
                self.wait_ticks = 0
            elif timeout_hit_now or wait_wrap:
                self._emit(
                    self.wait_ticks,
                    self.t_start_r,
                    ts,
                    self.fine_start_r,
                    0,
                    int(timeout_hit_now),
                    int(wait_wrap),
                    0,
                )
                self.state = 0
                self.armed = 0
                self.wait_ticks = 0
            else:
                self.wait_ticks = wait_n

        self.ts_now = (ts + 1) & 0xFFFFFFFF
        self.timeout_hit_r = timeout_hit_next

    def _emit(self, dt, t0, t1, f0, f1, timeout, overflow, unmatch) -> None:
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        self.result_strobe = 1
        self.result_seq = self.seq
        self.result_dt_ticks = dt
        self.result_t_start = t0
        self.result_t_stop = t1
        self.result_fine_start = f0
        self.result_fine_stop = f1
        self.result_timeout = timeout
        self.result_overflow = overflow
        self.result_unmatched_stop = unmatch


def wait_clks(dut: TdcTimestamp, n: int) -> None:
    for _ in range(n):
        dut.step()


def pulse_pair(dut: TdcTimestamp, delay_ticks: int, f_start: int = 0, f_stop: int = 0) -> None:
    dut.start_rise = 1
    dut.start_fine = f_start
    dut.stop_rise = int(delay_ticks == 0)
    dut.stop_fine = f_stop if delay_ticks == 0 else 0
    dut.step()
    dut.start_rise = 0
    dut.stop_rise = 0
    if delay_ticks >= 1:
        wait_clks(dut, delay_ticks - 1)
        dut.stop_rise = 1
        dut.stop_fine = f_stop
        dut.step()
        dut.stop_rise = 0


def wait_result(dut: TdcTimestamp, max_cycles: int) -> bool:
    if dut.result_strobe:
        return True
    for _ in range(max_cycles):
        dut.step()
        if dut.result_strobe:
            return True
    return False


def expect_dt(
    dut: TdcTimestamp,
    name: str,
    exp_dt: int,
    exp_timeout: int,
    exp_unmatch: int,
    exp_f0: int = 0,
    exp_f1: int = 0,
) -> None:
    if not wait_result(dut, 20000):
        raise AssertionError("%s: no result_strobe" % name)
    if dut.result_dt_ticks != exp_dt:
        raise AssertionError("%s: dt=%s expected %s" % (name, dut.result_dt_ticks, exp_dt))
    if dut.result_timeout != exp_timeout:
        raise AssertionError("%s: timeout=%s expected %s" % (name, dut.result_timeout, exp_timeout))
    if dut.result_unmatched_stop != exp_unmatch:
        raise AssertionError("%s: unmatched=%s expected %s" % (name, dut.result_unmatched_stop, exp_unmatch))
    if dut.result_fine_start != exp_f0 or dut.result_fine_stop != exp_f1:
        raise AssertionError(
            "%s: fine=%s/%s expected %s/%s"
            % (name, dut.result_fine_start, dut.result_fine_stop, exp_f0, exp_f1)
        )
    print("PASS %s: dt=%d ticks (%d ns) fine=%d/%d" % (name, dut.result_dt_ticks, dut.result_dt_ticks * 8, dut.result_fine_start, dut.result_fine_stop))


def main() -> int:
    dut = TdcTimestamp()
    wait_clks(dut, 8)
    dut.rst = 0
    wait_clks(dut, 4)
    dut.enable = 1
    wait_clks(dut, 4)

    print("=== 0 ns ===")
    pulse_pair(dut, 0, 100, 40)
    expect_dt(dut, "0ns", 0, 0, 0, 100, 40)

    print("=== 8 ns ===")
    pulse_pair(dut, 1, 10, 20)
    expect_dt(dut, "8ns", 1, 0, 0, 10, 20)

    print("=== 24 ns ===")
    pulse_pair(dut, 3, 1, 2)
    expect_dt(dut, "24ns", 3, 0, 0, 1, 2)

    print("=== 1 ms ===")
    pulse_pair(dut, 125000, 0, 0)
    expect_dt(dut, "1ms", 125000, 0, 0, 0, 0)

    print("=== 10 ms ===")
    pulse_pair(dut, 1250000, 0, 0)
    expect_dt(dut, "10ms", 1250000, 0, 0, 0, 0)

    print("=== unmatched STOP is ignored ===")
    prev_dt = dut.result_dt_ticks
    prev_seq = dut.result_seq
    dut.stop_rise = 1
    dut.step()
    dut.stop_rise = 0
    wait_clks(dut, 4)
    if dut.result_strobe:
        raise AssertionError("unmatched STOP must not strobe")
    if dut.result_dt_ticks != prev_dt or dut.result_seq != prev_seq:
        raise AssertionError("unmatched STOP clobbered last dt/seq")
    if dut.result_unmatched_stop:
        raise AssertionError("unmatched flag must stay clear when STOP is ignored")
    print("PASS unmatched ignored: dt=%d seq=%d" % (dut.result_dt_ticks, dut.result_seq))

    print("=== leftover STOP after good pair ===")
    pulse_pair(dut, 3, 5, 6)
    expect_dt(dut, "24ns-before-leftover", 3, 0, 0, 5, 6)
    dut.stop_rise = 1
    dut.step()
    dut.stop_rise = 0
    wait_clks(dut, 3)
    if dut.result_dt_ticks != 3 or dut.result_unmatched_stop:
        raise AssertionError("leftover STOP beat clobbered dt")
    print("PASS leftover STOP: dt=%d" % dut.result_dt_ticks)

    print("=== timeout ===")
    dut.timeout_ticks = TIMEOUT_TICKS
    wait_clks(dut, 2)
    dut.start_rise = 1
    dut.start_fine = 9
    dut.step()
    dut.start_rise = 0
    if not wait_result(dut, TIMEOUT_TICKS + 32):
        raise AssertionError("timeout: no strobe")
    if not dut.result_timeout or dut.result_unmatched_stop or dut.result_fine_start != 9:
        raise AssertionError("timeout flags/fine wrong")
    print("PASS timeout: dt=%d timeout=1" % dut.result_dt_ticks)
    print("TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
