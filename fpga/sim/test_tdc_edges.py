#!/usr/bin/env python3
"""Model of tdc_axi.v IDDR rise encoding: leftover beat suppress + reset preload."""

from __future__ import annotations


class EdgeEncode:
    def __init__(self):
        self.q1 = 0
        self.q2 = 0
        self.q1_d = 0
        self.q2_d = 0
        self.ev_d = 0
        self.holdoff = 0
        self.iddr_rst = 0
        self.fsm_rst = 0
        self.rise_r = 0
        self.rise_f = 0

    def step(self, q1: int, q2: int) -> None:
        if self.iddr_rst:
            self.q1_d = 0
            self.q2_d = 0
        else:
            self.q1_d = self.q1
            self.q2_d = self.q2
        self.q1 = q1
        self.q2 = q2
        raw_r = self.q1 & (1 - self.q1_d)
        raw_f = self.q2 & (1 - self.q2_d)
        hold = 1 if (self.fsm_rst or self.holdoff) else 0
        self.rise_r = raw_r & (1 - self.ev_d) & (1 - hold)
        self.rise_f = raw_f & (1 - self.ev_d) & (1 - hold)
        if self.fsm_rst:
            self.ev_d = 0
            self.holdoff = 3
        else:
            self.ev_d = self.rise_r | self.rise_f
            if self.holdoff:
                self.holdoff -= 1


def wait(enc: EdgeEncode, n: int, q1: int, q2: int) -> int:
    events = 0
    for _ in range(n):
        enc.step(q1, q2)
        if enc.rise_r or enc.rise_f:
            events += 1
    return events


def main() -> int:
    enc = EdgeEncode()
    enc.iddr_rst = 1
    enc.fsm_rst = 1
    wait(enc, 2, 1, 1)
    enc.iddr_rst = 0
    enc.fsm_rst = 0
    if wait(enc, 6, 1, 1) != 0:
        raise AssertionError("idle-high after reset must not emit a rise")
    print("PASS idle-high preload")

    enc.step(0, 0)
    wait(enc, 3, 0, 0)
    enc.step(0, 1)
    if not enc.rise_f or enc.rise_r:
        raise AssertionError("odd-bin rise should be rise_f only")
    enc.step(1, 1)
    if enc.rise_r or enc.rise_f:
        raise AssertionError("leftover even-bin beat must be suppressed")
    print("PASS leftover DDR beat suppressed")

    enc.step(0, 0)
    wait(enc, 3, 0, 0)
    enc.step(1, 1)
    if not (enc.rise_r or enc.rise_f):
        raise AssertionError("same-cycle even+odd rise should emit once")
    first = (enc.rise_r, enc.rise_f)
    enc.step(1, 1)
    if enc.rise_r or enc.rise_f:
        raise AssertionError("held-high after same-cycle rise must be quiet, got %s then extra" % (first,))
    print("PASS same-cycle rise is one event")

    enc.fsm_rst = 1
    enc.step(1, 1)
    enc.fsm_rst = 0
    if wait(enc, 6, 1, 1) != 0:
        raise AssertionError("pin-change while idle-high must not emit a rise")
    print("PASS pin-change idle-high")
    print("TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
