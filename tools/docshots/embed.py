#!/usr/bin/env python3
"""Put freshly captured figures into the two guides, in place.

A figure is addressed by the MEDIA PART it already occupies
(`/word/media/imageN.png`), not by its position in the body: paragraphs move
whenever the text is edited, media parts do not. The bytes are replaced and
the drawing's extent is recomputed so the figure keeps its width on the page
and gets the height its new aspect ratio asks for.

    python3 tools/docshots/embed.py --dry-run
    python3 tools/docshots/embed.py
    python3 tools/docshots/embed.py --source docs/user-guide-assets

Writes the .docx files in place; take a copy first if that matters.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS = ROOT / "docs"
EMU_PER_CM = 360000

# media part → the figure that belongs in it.
USER_GUIDE = {
    "image3.png": "09-proje-secimi",
    "image4.png": "01-genel-bakis",
    "image5.png": "06-ag",
    "image6.png": "02-cihazlar",
    "image7.png": "03-ip-atama",
    "image8.png": "04-cihaz-ayarlari",
    "image9.png": "05-yazilim",
    "image10.png": "10-switch-genel",
    "image11.png": "11-adb-genel",
    "image12.png": "07-dogrulama-rapor",
    "image13.png": "08-gecmis",
    # image14 is skipped on purpose: it is the cover photograph, a .jpg that
    # no capture produces. The remote-session figure is image15, after it.
    "image15.png": "12-uzaktan-oturum",
}
DEV_GUIDE = {
    "image4.png": "fig1-architecture",
    "image5.png": "fig2-overview",
    "image6.png": "fig3-frontpanel",
    "image7.png": "fig4-switch",
    "image8.png": "fig5-contextmenu",
    "image9.png": "fig6-adb",
}
GUIDES = [
    ("DABP_Kullanıcı_Kılavuzu.docx", USER_GUIDE, "user-guide-assets"),
    ("DABP_Geliştirici_Kılavuzu.docx", DEV_GUIDE, "dev-guide-assets"),
]


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height of a PNG, from its IHDR."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG (the capture writes PNG)")
    return struct.unpack(">II", data[16:24])


def replace(document, part_name: str, image: Path) -> str:
    """Swap one media part's bytes and fix the drawing that shows it."""
    data = image.read_bytes()
    width, height = png_size(data)
    target = None
    for name, part in document.part.related_parts.items():
        if str(part.partname).endswith("/" + part_name):
            target = (name, part)
            break
    if target is None:
        # Raised, not returned: a mapping key that names no media part is a
        # typo, and it used to print as a bullet in a column of bullets.
        raise ValueError("no such media part in this document")
    rid, part = target
    part._blob = data

    # Every drawing that points at this part keeps its width and is given the
    # height the new picture actually has. Word will not do this for us: the
    # extent is stored, and a 16:9 figure replaced by a 16:10 one is simply
    # squashed until it is corrected here.
    changed = 0
    for blip in document.element.body.findall(".//" + qn("a:blip")):
        if blip.get(qn("r:embed")) != rid:
            continue
        drawing = blip
        while drawing is not None and not drawing.tag.endswith("}drawing"):
            drawing = drawing.getparent()
        if drawing is None:
            continue
        for tag in (qn("wp:extent"), qn("a:ext")):
            for node in drawing.iter(tag):
                cx = int(node.get("cx"))
                node.set("cy", str(round(cx * height / width)))
                changed += 1
    return (f"{part_name} ← {image.name}  {width}×{height}  "
            f"({len(data) // 1024} KB, {changed} extent(s))")


def unclaimed(source: Path) -> list[str]:
    """Captured figures that no media part in either guide claims.

    The mapping above is written by hand, so a figure added to capture.py
    without a line here is captured, copied, looked at — and never reaches a
    guide, silently. That is not hypothetical: the remote-session figure sat
    unclaimed while every run reported nothing but success.
    """
    claimed = {figure for _, mapping, _ in GUIDES
               for figure in mapping.values()}
    return sorted(image.stem for image in source.glob("*.png")
                  # capture.py's own scratch files, mid-run.
                  if not image.name.startswith("_")
                  and image.stem not in claimed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(Path(__file__).parent / "out"),
                        help="directory holding the captured PNGs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source = Path(args.source)

    for filename, mapping, fallback in GUIDES:
        path = DOCS / filename
        print(f"\n{filename}")
        document = Document(path)
        for part_name, figure in mapping.items():
            image = source / f"{figure}.png"
            if not image.is_file():
                image = DOCS / fallback / f"{figure}.png"
            if not image.is_file():
                print(f"  – {part_name}: no {figure}.png anywhere")
                continue
            try:
                print("  ·", replace(document, part_name, image))
            except ValueError as error:
                print(f"  ! {part_name}: {error}")
        if args.dry_run:
            print("  (dry run — not written)")
        else:
            document.save(path)
            print("  saved")

    for figure in unclaimed(source):
        print(f"\n! {figure}.png is captured but no media part claims it — "
              f"add it to USER_GUIDE or DEV_GUIDE, or it stays out of the "
              f"guides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
