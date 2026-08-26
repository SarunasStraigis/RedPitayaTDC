#!/usr/bin/env python3
"""Model of tdc_axi.v SDR rise encoding: holdoff preload, leftover beat ignore is in the FSM."""

from __future__ import annotations


class EdgeEncode:
    def __init__(self):
        self.q = 0
        self.holdoff = 0
        self.cap_rst = 0
        self.fsm_rst = 0
        self.rise = 0

    def step(self, hit: int) -> None:
        hold = 1 if (self.fsm_rst or self.holdoff) else 0
        if self.cap_rst:
            self.q = 0
            self.rise = 0
        elif hold:
            self.q = hit
            self.rise = 0
        else:
            self.rise = hit & (1 - self.q)
            self.q = hit
        if self.fsm_rst:
            self.holdoff = 3
        elif self.holdoff:
            self.holdoff -= 1


def wait(enc: EdgeEncode, n: int, hit: int) -> int:
    events = 0
    for _ in range(n):
        enc.step(hit)
        if enc.rise:
            events += 1
    return events


def main() -> int:
    enc = EdgeEncode()
    enc.cap_rst = 1
    enc.fsm_rst = 1
    wait(enc, 2, 1)
    enc.cap_rst = 0
    enc.fsm_rst = 0
    if wait(enc, 6, 1) != 0:
        raise AssertionError("idle-high after reset must not emit a rise")
    print("PASS idle-high preload")

    enc.step(0)
    wait(enc, 3, 0)
    enc.step(1)
    if not enc.rise:
        raise AssertionError("0→1 must emit a rise")
    enc.step(1)
    if enc.rise:
        raise AssertionError("held-high after rise must be quiet")
    print("PASS held-high after rise")

    enc.step(0)
    wait(enc, 3, 0)
    enc.step(1)
    if not enc.rise:
        raise AssertionError("second rise must emit")
    print("PASS second rise")

    enc.fsm_rst = 1
    enc.step(1)
    enc.fsm_rst = 0
    if wait(enc, 6, 1) != 0:
        raise AssertionError("pin-change while idle-high must not emit a rise")
    print("PASS pin-change idle-high")
    print("TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
