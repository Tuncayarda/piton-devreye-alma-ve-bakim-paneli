#!/usr/bin/env python3
"""Build the application icons from the Piton logo.

    python3 tools/make_icons.py

Writes `icons/app.png`, `icons/app.icns` and `icons/app.ico`. Those three
files ARE COMMITTED, and this script is how they were made — no build
machine runs it, and CI never needs the tools below.

WHAT THE ICON IS. The logo (`static/piton-logo.svg`) is a wordmark: PITON
above TECHNOLOGY, three times as wide as it is tall. Squeezed into a square
it is unreadable at 32 pixels and pointless at 16. So the icon uses the MARK
alone — the "P" and the two dashes above it, which is what the UI already
uses as its favicon — on the panel's own background colour.

TWO SHAPES, ON PURPOSE:

    rounded, padded     macOS and Linux. A Dock full of squircles with one
                        square tile in it looks like a mistake.
    square, full bleed  Windows. The taskbar and Explorer draw the icon as
                        given, and a rounded PNG there is a small tile with
                        gaps around it.

REQUIREMENTS, all macOS + Homebrew: `rsvg-convert` (SVG), `sips` and
`iconutil` (Apple's own). The `.ico` is written here rather than by a tool,
because nothing on macOS writes a MULTI-SIZE one: Windows picks a different
size for the taskbar, Explorer and the Alt-Tab list, and a single 256 pixel
image scaled down to 16 is mud.
"""
from __future__ import annotations

import base64
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "static" / "piton-logo.svg"
OUT = ROOT / "icons"

# The panel's own window background (see app.py), so the icon and the app
# that opens from it are the same colour.
BACKGROUND = "#101820"
# How much of the square the mark takes. The rest is breathing room; at this
# ratio the mark still reads at 16 pixels.
MARK_RATIO = 0.62
# macOS rounds its own icons; the radius is a proportion of the side.
CORNER = 0.18
# What Windows actually asks for. 256 is the modern one; 16 and 32 are what
# the taskbar and the window corner use, and they are why this is a list.
ICO_SIZES = (16, 32, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)
MASTER = 1024


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


def require(*tools: str) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise SystemExit(f"[ERROR] not installed: {', '.join(missing)}")


# ── the mark, cut out of the wordmark ────────────────────────────────────
def mark_svg() -> str:
    """The logo with the mark's three pieces wrapped in one group.

    The mark is the second `<path>` (the "P" — the glyphs come in reading
    order) and the two rounded `<rect>`s above it. Wrapped rather than
    copied out, so the paths keep the coordinates they were drawn with;
    `rsvg-convert --export-id` then crops to the group's own bounding box
    and no measurement has to be done here.
    """
    text = LOGO.read_text(encoding="utf-8")
    rects = re.findall(r"<rect\b[^>]*/>", text)[:2]
    paths = list(re.finditer(r"<path\b[^>]*/>", text))
    if len(rects) < 2 or len(paths) < 2:
        raise SystemExit("[ERROR] the logo is not shaped as expected; "
                         "check static/piton-logo.svg")
    pieces = "".join(rects) + paths[1].group(0)
    head = text[:text.index(">") + 1]
    return f'{head}<g id="mark">{pieces}</g></svg>'


def cut_out_mark(work: Path) -> Path:
    source = work / "marked.svg"
    source.write_text(mark_svg(), encoding="utf-8")
    mark = work / "mark.png"
    run(["rsvg-convert", "--export-id=mark", "-w", str(MASTER * 2),
         str(source), "-o", str(mark)])
    return mark


def size_of(image: Path) -> tuple[int, int]:
    out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight",
                          str(image)], check=True, capture_output=True,
                         text=True).stdout
    found = dict(re.findall(r"(pixelWidth|pixelHeight):\s*(\d+)", out))
    return int(found["pixelWidth"]), int(found["pixelHeight"])


# ── the square the icon is drawn on ──────────────────────────────────────
def canvas_svg(mark: Path, rounded: bool) -> str:
    """The finished icon, as SVG, with the mark placed in the middle.

    The mark travels as a data URI rather than as paths: it has already been
    cropped to its own bounds by `rsvg-convert`, and re-using that render is
    what keeps this function free of any arithmetic about where the logo's
    glyphs happen to sit.
    """
    width, height = size_of(mark)
    side = MASTER * MARK_RATIO
    scale = min(side / width, side / height)
    draw_w, draw_h = width * scale, height * scale
    encoded = base64.b64encode(mark.read_bytes()).decode("ascii")
    radius = f' rx="{MASTER * CORNER:.0f}"' if rounded else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{MASTER}" height="{MASTER}" '
        f'viewBox="0 0 {MASTER} {MASTER}">'
        f'<rect width="{MASTER}" height="{MASTER}"{radius} '
        f'fill="{BACKGROUND}"/>'
        f'<image x="{(MASTER - draw_w) / 2:.2f}" '
        f'y="{(MASTER - draw_h) / 2:.2f}" '
        f'width="{draw_w:.2f}" height="{draw_h:.2f}" '
        f'xlink:href="data:image/png;base64,{encoded}"/>'
        f'</svg>')


def render(svg: Path, target: Path, size: int) -> Path:
    run(["rsvg-convert", "-w", str(size), "-h", str(size), str(svg),
         "-o", str(target)])
    return target


# ── .ico, written by hand ────────────────────────────────────────────────
def bmp_pixels(path: Path) -> tuple[int, int, bytes]:
    """(width, height, BGRA rows bottom-up) out of a 24- or 32-bit BMP.

    `sips` decodes the PNG for us; only the header has to be understood
    here — and one field of it decides which way up the icon comes out.

    A NEGATIVE HEIGHT MEANS THE ROWS ARE STORED TOP DOWN, which is what
    `sips` writes, while an icon image is always bottom up. Copied across
    without looking, the first attempt produced a perfectly valid .ico of an
    upside-down logo.
    """
    data = path.read_bytes()
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height, _planes, bits = struct.unpack_from("<iihh", data, 18)
    if bits not in (24, 32):
        raise SystemExit(f"[ERROR] unexpected BMP depth: {bits}")
    stride = ((width * bits // 8) + 3) // 4 * 4
    rows = []
    for y in range(abs(height)):
        start = offset + y * stride
        row = data[start:start + width * bits // 8]
        if bits == 24:
            row = b"".join(row[i:i + 3] + b"\xff"
                           for i in range(0, len(row), 3))
        rows.append(row)
    if height < 0:
        rows.reverse()
    return width, abs(height), b"".join(rows)


def ico_image(width: int, height: int, pixels: bytes) -> bytes:
    """One icon image: a DIB with a doubled height and an empty mask.

    THE DOUBLED HEIGHT IS THE FORMAT, not a mistake — the header describes
    the colour rows and the transparency mask together, even when the mask
    is empty. Every one of these icons is opaque, so the mask is zeros; the
    rounded corners live in the PNG and the ICNS, where Windows does not
    look.
    """
    header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0,
                         len(pixels), 0, 0, 0, 0)
    mask_stride = ((width + 31) // 32) * 4
    return header + pixels + b"\x00" * (mask_stride * height)


def write_ico(images: list[tuple[int, bytes]], target: Path) -> None:
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                               1, 32, len(blob), offset)
        offset += len(blob)
        blobs += blob
    target.write_bytes(head + entries + blobs)


def main() -> int:
    require("rsvg-convert", "sips", "iconutil")
    if not LOGO.is_file():
        raise SystemExit(f"[ERROR] no logo at {LOGO}")
    OUT.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dabp-icons-") as temporary:
        work = Path(temporary)
        mark = cut_out_mark(work)

        rounded = work / "rounded.svg"
        rounded.write_text(canvas_svg(mark, rounded=True), encoding="utf-8")
        square = work / "square.svg"
        square.write_text(canvas_svg(mark, rounded=False), encoding="utf-8")

        render(rounded, OUT / "app.png", MASTER)
        print(f"[icons] app.png  {MASTER}x{MASTER}")

        # .icns — Apple's own tool, from the sizes it asks for by name.
        iconset = work / "app.iconset"
        iconset.mkdir()
        for size in ICNS_SIZES:
            render(rounded, iconset / f"icon_{size}x{size}.png", size)
            if size * 2 <= MASTER:
                render(rounded, iconset / f"icon_{size}x{size}@2x.png",
                       size * 2)
        run(["iconutil", "-c", "icns", str(iconset),
             "-o", str(OUT / "app.icns")])
        print(f"[icons] app.icns {', '.join(str(s) for s in ICNS_SIZES)}")

        images = []
        for size in ICO_SIZES:
            png = render(square, work / f"ico-{size}.png", size)
            bmp = work / f"ico-{size}.bmp"
            run(["sips", "-s", "format", "bmp", str(png), "--out", str(bmp)])
            width, height, pixels = bmp_pixels(bmp)
            images.append((size, ico_image(width, height, pixels)))
        write_ico(images, OUT / "app.ico")
        print(f"[icons] app.ico  {', '.join(str(s) for s in ICO_SIZES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
