"""Generate the Klatsch app icon as .ico + .png files.

Run once:  python generate_icon.py
Outputs:   klatsch.ico, klatsch.png (256x256)
"""

from PIL import Image, ImageDraw, ImageFont
import math, os

SIZE = 256
PAD = 24

def draw_icon(size=SIZE):
    """Create a speech-bubble + paw icon for Klatsch."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size  # shorthand

    # --- Speech bubble (rounded rect) ---
    bx0, by0 = int(s * 0.08), int(s * 0.06)
    bx1, by1 = int(s * 0.92), int(s * 0.72)
    radius = int(s * 0.15)
    # Gradient-like fill: solid teal
    bubble_color = (0, 180, 160)  # teal
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=radius, fill=bubble_color)

    # --- Speech bubble tail (triangle pointing bottom-left) ---
    tx = int(s * 0.22)
    ty = by1
    tail = [
        (tx, ty - 2),
        (tx - int(s * 0.06), ty + int(s * 0.14)),
        (tx + int(s * 0.14), ty - 2),
    ]
    d.polygon(tail, fill=bubble_color)

    # --- Paw print (inside bubble) ---
    cx, cy = s // 2, int(s * 0.36)  # center of paw area
    paw_color = (255, 255, 255)  # white

    # Main pad (large oval)
    pad_w, pad_h = int(s * 0.14), int(s * 0.11)
    d.ellipse([cx - pad_w, cy - pad_h + int(s*0.06),
               cx + pad_w, cy + pad_h + int(s*0.06)], fill=paw_color)

    # Toe beans (4 small circles)
    toe_r = int(s * 0.055)
    toe_positions = [
        (cx - int(s * 0.12), cy - int(s * 0.04)),
        (cx - int(s * 0.04), cy - int(s * 0.10)),
        (cx + int(s * 0.04), cy - int(s * 0.10)),
        (cx + int(s * 0.12), cy - int(s * 0.04)),
    ]
    for tx, ty in toe_positions:
        d.ellipse([tx - toe_r, ty - toe_r, tx + toe_r, ty + toe_r], fill=paw_color)

    # --- "Klatsch" text below bubble ---
    text = "Klatsch"
    # Try to use a nice font, fall back to default
    font = None
    font_size = int(s * 0.14)
    for font_name in ["segoeuib.ttf", "segoeui.ttf", "arial.ttf", "arialbd.ttf"]:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    text_color = (60, 60, 60)  # dark gray
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (s - tw) // 2
    ty = int(s * 0.78)
    d.text((tx, ty), text, fill=text_color, font=font)

    return img


def main():
    base = os.path.dirname(os.path.abspath(__file__))

    # Create 256x256 master
    icon_256 = draw_icon(256)
    icon_256.save(os.path.join(base, "klatsch.png"))
    print("Created: klatsch.png (256x256)")

    # Create multi-size ICO
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icons = []
    for sz in sizes:
        if sz == 256:
            icons.append(icon_256)
        else:
            icons.append(icon_256.resize((sz, sz), Image.LANCZOS))

    ico_path = os.path.join(base, "klatsch.ico")
    icons[0].save(ico_path, format="ICO", sizes=[(sz, sz) for sz in sizes],
                  append_images=icons[1:])
    print(f"Created: klatsch.ico ({len(sizes)} sizes)")


if __name__ == "__main__":
    main()
