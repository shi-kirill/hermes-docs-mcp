#!/usr/bin/env python3
"""Regenerate the icon assets from a source image.

Run after replacing the artwork:

    python3 scripts/make-icons.py path/to/source.png

`sips` (ships with macOS) does the resampling; the .ico is assembled here,
because sips cannot write one and a single Pillow dependency for one build-time
file is not worth carrying. Modern consumers accept PNG frames inside an ICO.
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "src" / "hermes_docs_mcp" / "assets"
PNG_SIZES = {"icon-16.png": 16, "icon-32.png": 32, "icon-48.png": 48, "icon-128.png": 128}
APPLE_TOUCH = ("apple-touch-icon.png", 180)
ICO_FRAMES = ("icon-16.png", "icon-32.png", "icon-48.png")


def sips(*args: str) -> None:
    subprocess.run(["sips", *args], check=True, capture_output=True)


def squared(source: Path, workdir: Path) -> Path:
    """Pad the artwork to a square so every frame comes out exactly NxN.

    sips preserves the aspect ratio, so a 1772x1799 source would yield 15x16
    frames and an .ico whose directory disagrees with its images.
    """
    read = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(source)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    dimensions = [int(line.split(":")[1]) for line in read.splitlines() if ":" in line.split()[0]]
    side = max(dimensions)
    target = workdir / "square.png"
    sips("-s", "format", "png", str(source), "--out", str(target))
    sips("--padToHeightWidth", str(side), str(side), "--padColor", "FFFFFF", str(target))
    return target


def resample(source: Path, target: Path, size: int) -> None:
    sips("-s", "format", "png", "-Z", str(size), str(source), "--out", str(target))


def build_ico(frames: list[Path], target: Path) -> None:
    payloads = [f.read_bytes() for f in frames]
    header = struct.pack("<HHH", 0, 1, len(payloads))  # reserved, type=icon, count
    offset = len(header) + 16 * len(payloads)
    directory = b""
    for frame, payload in zip(frames, payloads, strict=True):
        side = int(frame.stem.split("-")[1])
        directory += struct.pack(
            "<BBBBHHII",
            side if side < 256 else 0,  # 0 means 256
            side if side < 256 else 0,
            0,  # palette size: none
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel
            len(payload),
            offset,
        )
        offset += len(payload)
    target.write_bytes(header + directory + b"".join(payloads))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    ASSETS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        source = squared(Path(sys.argv[1]), Path(tmp))
        for name, size in PNG_SIZES.items():
            resample(source, ASSETS / name, size)
        resample(source, ASSETS / APPLE_TOUCH[0], APPLE_TOUCH[1])
    build_ico([ASSETS / name for name in ICO_FRAMES], ASSETS / "favicon.ico")
    for path in sorted(ASSETS.iterdir()):
        print(f"{path.name:>22}  {path.stat().st_size:>6} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
