#!/usr/bin/env python3
"""Convert Vivado .bit -> byte-swapped .bin for Zynq fpga_manager."""

from __future__ import annotations

import argparse
import struct
import sys


def extract_payload(data: bytes) -> bytes:
    if len(data) < 20:
        raise ValueError("file too small")

    # Standard Xilinx .bit: 13-byte preamble, then a/b/c/d/e records.
    p = 13
    payload = None
    while p < len(data):
        key = data[p]
        p += 1
        if key == ord("e"):
            (n,) = struct.unpack(">I", data[p : p + 4])
            p += 4
            payload = data[p : p + n]
            if len(payload) != n:
                raise ValueError("truncated e-record")
            break
        if p + 2 > len(data):
            break
        (n,) = struct.unpack(">H", data[p : p + 2])
        p += 2 + n

    if payload is None:
        sync = bytes([0xAA, 0x99, 0x55, 0x66])
        i = data.find(sync)
        if i < 0:
            raise ValueError("no bitstream payload")
        payload = data[max(0, i - 32) :]
    return payload


def swab32(payload: bytes) -> bytes:
    if len(payload) % 4:
        payload = payload + b"\x00" * (4 - len(payload) % 4)
    out = bytearray(len(payload))
    for i in range(0, len(payload), 4):
        out[i : i + 4] = payload[i : i + 4][::-1]
    return bytes(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("bitfile")
    p.add_argument("binfile")
    p.add_argument("--no-swap", action="store_true", help="keep native endian (not for RP fpga_manager)")
    args = p.parse_args(argv)
    with open(args.bitfile, "rb") as f:
        payload = extract_payload(f.read())
    out = payload if args.no_swap else swab32(payload)
    with open(args.binfile, "wb") as f:
        f.write(out)
    sync = out.find(bytes([0x66, 0x55, 0x99, 0xAA]))
    print("Wrote %s (%d bytes, swapped_sync_at=%s)" % (args.binfile, len(out), sync))
    if not args.no_swap and sync < 0:
        print("warning: swapped sync word 66 55 99 aa not found", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
