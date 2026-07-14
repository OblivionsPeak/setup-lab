"""Generate icon.ico — gold gauge on dark, matching the Setup Lab UI theme."""
import math

from PIL import Image, ImageDraw

BG = (13, 17, 23, 255)        # --bg
PANEL = (28, 35, 48, 255)     # --panel2
GOLD = (240, 180, 41, 255)    # --accent
RED = (248, 81, 73, 255)      # --bad
DIM = (139, 148, 158, 255)    # --dim


def draw_icon(size):
    S = 16                                       # supersample factor
    W = size * S
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # rounded dark tile with a subtle gold rim
    r = W * 0.22
    d.rounded_rectangle([0, 0, W - 1, W - 1], radius=r, fill=BG,
                        outline=GOLD, width=max(1, W // 32))

    # gauge: 240° arc, open at the bottom
    cx, cy = W / 2, W * 0.54
    R = W * 0.34
    box = [cx - R, cy - R, cx + R, cy + R]
    d.arc(box, start=150, end=390, fill=PANEL, width=int(W * 0.10))
    # gold "healthy" sweep
    d.arc(box, start=150, end=330, fill=GOLD, width=int(W * 0.10))
    # redline segment
    d.arc(box, start=330, end=390, fill=RED, width=int(W * 0.10))

    # tick marks
    for ang in (150, 210, 270, 330, 390):
        a = math.radians(ang)
        r1, r2 = R * 0.70, R * 0.52
        d.line([cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a)],
               fill=DIM, width=max(1, int(W * 0.02)))

    # needle pointing into the gold zone
    a = math.radians(295)
    d.line([cx - R * 0.18 * math.cos(a), cy - R * 0.18 * math.sin(a),
            cx + R * 0.62 * math.cos(a), cy + R * 0.62 * math.sin(a)],
           fill=(230, 237, 243, 255), width=max(2, int(W * 0.045)))
    hub = W * 0.055
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=GOLD)

    return img.resize((size, size), Image.LANCZOS)


sizes = [256, 128, 64, 48, 32, 16]
frames = [draw_icon(s) for s in sizes]
frames[0].save('icon.ico', sizes=[(s, s) for s in sizes],
               append_images=frames[1:])
frames[0].save('icon-256.png')
print('wrote icon.ico + icon-256.png')
