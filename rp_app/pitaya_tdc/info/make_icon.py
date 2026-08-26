"""Write STEMlab home-page icons.

OS 2.00 desktop loads info/icon/128.png (and 256/512), not info/icon.png.
"""
from __future__ import annotations

import pathlib
import struct
import zlib


def chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def pixel(nx: float, ny: float) -> bytes:
    if min(nx, 1 - nx, ny, 1 - ny) < 0.06:
        return bytes((230, 240, 255))
    high = (0.16 <= nx <= 0.42) or (0.58 <= nx <= 0.84)
    on = ny < 0.38 if high else ny > 0.62
    if on:
        return bytes((61, 184, 255))
    return bytes((11, 46, 74))


def write_png(path: pathlib.Path, size: int) -> None:
    raw = bytearray()
    den = size - 1
    for y in range(size):
        raw.append(0)
        ny = y / den
        for x in range(size):
            raw += pixel(x / den, ny)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    print(path, len(png))


def main() -> None:
    here = pathlib.Path(__file__).resolve().parent
    sizes = (128, 256, 512)
    first = None
    for n in sizes:
        out = here / "icon" / ("%d.png" % n)
        write_png(out, n)
        if first is None:
            first = out
    (here / "icon.png").write_bytes(first.read_bytes())
    print(here / "icon.png", first.stat().st_size)


if __name__ == "__main__":
    main()
