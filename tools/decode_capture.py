#!/usr/bin/env python3
"""Decode an strace dump of the AOOSTAR-X agent into a PNG.

    strace -f -p <pid> -e trace=write -xx -s 300 -o cap.log
    python3 decode_capture.py cap.log out.png

Only the bytes the agent actually sent are reconstructed: the MCU keeps its own
framebuffer, so unchanged rows stay black here. Force a full repaint first if
you want a complete picture.
"""
import ast
import re
import struct
import sys

from PIL import Image

W, H = 960, 376
FRAME = W * H * 2
PAT = re.compile(r'write\((\d+), "(.*?)", (\d+)\)\s+=\s+(-?\d+)')
MAGIC = b"\xaa\x55\xaa\x55"


def load(path):
    chunks = {}
    for line in open(path, "rb").read().decode("utf-8", "replace").splitlines():
        m = PAT.search(line)
        if not m:
            continue
        try:
            data = ast.literal_eval('"' + m.group(2) + '"').encode("latin-1")
        except Exception:
            continue
        chunks.setdefault(m.group(1), bytearray()).extend(data)
    if not chunks:
        return b"", None
    fd = max(chunks, key=lambda k: len(chunks[k]))
    return bytes(chunks[fd]), fd


def decode(buf):
    fb = bytearray(FRAME)
    covered = 0
    i = 0
    while True:
        j = buf.find(MAGIC, i)
        if j < 0 or j + 12 > len(buf):
            break
        cmd, off = struct.unpack("<II", buf[j + 4:j + 12])
        if cmd == 8 and off < FRAME:
            end = min(off + 47, FRAME)
            fb[off:end] = buf[j + 12:j + 12 + (end - off)]
            covered = max(covered, end)
        i = j + 12
    return fb, covered


def to_image(fb):
    data = []
    for k in range(0, FRAME, 2):
        v = fb[k] | (fb[k + 1] << 8)
        data.append((((v >> 11) & 0x1F) << 3, ((v >> 5) & 0x3F) << 2, (v & 0x1F) << 3))
    img = Image.new("RGB", (W, H))
    img.putdata(data)
    return img


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    buf, fd = load(sys.argv[1])
    fb, covered = decode(buf)
    to_image(fb).save(sys.argv[2])
    print(f"fd={fd} bytes={len(buf)} covered={covered}/{FRAME} -> {sys.argv[2]}")
