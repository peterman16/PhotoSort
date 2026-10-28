"""Draws PhotoSort's icon (photosort/resources/photosort.ico). Run by setup.bat.

Three concepts were sketched; CONCEPT is the one in use.
`python tools/make_icon.py --preview out.png` draws all three side by side.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

CONCEPT = "film"  # the one in use; others: "aperture", "stack"

OUT = Path(__file__).resolve().parent.parent / "photosort" / "resources" / "photosort.ico"
S = 1024  # drawn large, then shrunk for smooth edges
BACKGROUND = (30, 42, 56)
LIGHT = (225, 230, 236)
MID = (120, 135, 150)
GREEN = (60, 200, 90)


def base():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((32, 32, S - 32, S - 32), radius=200, fill=BACKGROUND)
    return im


def check_badge(d):
    cx, cy, r = 740, 740, 190
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GREEN, outline=BACKGROUND, width=36)
    d.line([(cx - 95, cy + 5), (cx - 25, cy + 80), (cx + 105, cy - 75)], fill="white", width=58, joint="curve")


def aperture():
    im = base()
    d = ImageDraw.Draw(im)
    cx, cy, r = 450, 450, 330
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=LIGHT)
    blades, hole = 6, 120
    for k in range(blades):  # each blade: a line from the hole's edge out to the rim
        a = 2 * math.pi * k / blades
        x1, y1 = cx + hole * math.cos(a), cy + hole * math.sin(a)
        x2, y2 = cx + r * math.cos(a + 1.0), cy + r * math.sin(a + 1.0)
        d.line([(x1, y1), (x2, y2)], fill=MID, width=26)
    pts = [(cx + hole * math.cos(2 * math.pi * k / blades), cy + hole * math.sin(2 * math.pi * k / blades))
           for k in range(blades)]
    d.polygon(pts, fill=BACKGROUND)
    check_badge(d)
    return im


FILM_TILE = (43, 43, 43)      # #2b2b2b
FILM_BLACK = (0, 0, 0)
FILM_YELLOW = (255, 210, 0)   # #ffd200, the cull view's yellow


def film():
    """Flat and chunky so it still reads at 16 px: a black film frame with sprocket holes down
    both sides, holding a yellow frame with a thick black check."""
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=200, fill=FILM_TILE)
    d.rounded_rectangle((170, 110, 854, 914), radius=48, fill=FILM_BLACK)
    for y in range(170, 860, 140):  # sprocket holes, left and right
        d.rounded_rectangle((210, y, 280, y + 70), radius=14, fill=FILM_TILE)
        d.rounded_rectangle((744, y, 814, y + 70), radius=14, fill=FILM_TILE)
    d.rounded_rectangle((320, 230, 704, 794), radius=24, fill=FILM_YELLOW)
    d.line([(390, 520), (480, 620), (640, 400)], fill=FILM_BLACK, width=80, joint="curve")
    return im


def stack():
    im = base()
    d = ImageDraw.Draw(im)
    for k, colour in enumerate((MID, (170, 182, 195), LIGHT)):  # back to front
        o = 70 * (2 - k)  # back photos sit up and to the right
        d.rounded_rectangle((130 + o, 250 - o, 660 + o, 660 - o), radius=36,
                            fill=colour, outline=BACKGROUND, width=18)
    d.polygon([(170, 620), (330, 430), (440, 540), (520, 470), (620, 620)], fill=BACKGROUND)
    d.ellipse((470, 320, 550, 400), fill=BACKGROUND)  # sun
    check_badge(d)
    return im


CONCEPTS = {"aperture": aperture, "film": film, "stack": stack}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        sheet = Image.new("RGBA", (3 * 300, 300), (245, 245, 245, 255))
        for k, draw in enumerate(CONCEPTS.values()):
            sheet.alpha_composite(draw().resize((256, 256), Image.LANCZOS), (22 + 300 * k, 22))
        sheet.save(sys.argv[2])
        return
    OUT.parent.mkdir(exist_ok=True)
    icon = CONCEPTS[CONCEPT]().resize((256, 256), Image.LANCZOS)
    icon.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"  wrote {OUT}")


if __name__ == "__main__":
    main()
