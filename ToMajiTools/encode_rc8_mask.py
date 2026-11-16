"""Encode a grayscale Majiro mask as RC8 using literal blocks."""

import argparse
import struct
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with Image.open(args.source) as image:
        grayscale = image.convert("L")
        width, height = grayscale.size
        pixels = grayscale.tobytes()

    # The first pixel is implicit as a one-byte literal. Subsequent literal
    # blocks can contain up to 128 + 65535 pixels.
    payload = bytearray(pixels[:1])
    for offset in range(1, len(pixels), 65663):
        chunk = pixels[offset:offset + 65663]
        if len(chunk) >= 128:
            payload.extend(struct.pack("<BH", 127, len(chunk) - 128))
        else:
            payload.append(len(chunk) - 1)
        payload.extend(chunk)

    palette = bytes(value for value in range(256) for _ in range(3))
    header = struct.pack("<8sIII", b"\x98\x5a\x92\x9a8_00", width, height, len(payload))
    args.output.write_bytes(header + palette + payload)


if __name__ == "__main__":
    main()
