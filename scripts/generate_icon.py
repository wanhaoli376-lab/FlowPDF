from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def generate_icon(output: Path) -> None:
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 255, 255), radius=56, fill="#6D36E8")
    draw.polygon(((69, 47), (152, 47), (187, 82), (187, 210), (69, 210)), fill="white")
    draw.polygon(((152, 47), (152, 82), (187, 82)), fill="#C4B5FD")
    draw.line((88, 108, 157, 108), fill="#7C3AED", width=12)
    draw.line((88, 132, 140, 132), fill="#7C3AED", width=12)
    draw.line(
        ((88, 169), (103, 155), (120, 180), (141, 166), (157, 154), (177, 163)),
        fill="#2563EB",
        width=13,
        joint="curve",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate_icon(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
