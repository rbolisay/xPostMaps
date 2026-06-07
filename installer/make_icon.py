"""Build a multi-size .ico from TierMaps.png for NSIS and Windows shortcuts."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required: pip install pillow") from exc


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: make_icon.py <source.png> <dest.ico>")
        return 1

    source = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    if not source.is_file():
        print(f"Source image not found: {source}")
        return 1

    image = Image.open(source).convert("RGBA")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    image.save(dest, format="ICO", sizes=sizes)
    print(f"Wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
