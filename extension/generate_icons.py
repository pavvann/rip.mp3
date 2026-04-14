"""Generate simple PNG icons for the extension using only stdlib."""
import struct
import zlib
import os

def make_png(size, bg=(29, 185, 84), fg=(255, 255, 255)):
    """Create a minimal PNG: green circle with a white download arrow."""
    width = height = size
    img = [[(0, 0, 0, 0)] * width for _ in range(height)]

    cx = cy = size / 2
    r = size / 2

    # Draw filled green circle
    for y in range(height):
        for x in range(width):
            dx = x + 0.5 - cx
            dy = y + 0.5 - cy
            if dx * dx + dy * dy <= r * r:
                img[y][x] = (*bg, 255)

    # Draw down arrow (stem + head)
    stem_w = max(2, size // 8)
    stem_h = size // 3
    head_w = size // 3
    head_h = size // 5

    stem_x1 = int(cx - stem_w / 2)
    stem_x2 = int(cx + stem_w / 2)
    stem_y1 = int(cy - size * 0.28)
    stem_y2 = int(cy + size * 0.02)

    for y in range(stem_y1, stem_y2):
        for x in range(stem_x1, stem_x2):
            if 0 <= x < width and 0 <= y < height:
                img[y][x] = (*fg, 255)

    # Arrowhead as downward triangle
    tip_y = int(cy + size * 0.22)
    base_y = int(cy + size * 0.02)
    for y in range(base_y, tip_y + 1):
        progress = (y - base_y) / max(1, tip_y - base_y)
        half_w = int((head_w / 2) * (1 - progress))
        for x in range(int(cx) - half_w, int(cx) + half_w + 1):
            if 0 <= x < width and 0 <= y < height:
                img[y][x] = (*fg, 255)

    # Bottom bar
    bar_y1 = int(cy + size * 0.28)
    bar_y2 = int(cy + size * 0.36)
    bar_x1 = int(cx - head_w / 2)
    bar_x2 = int(cx + head_w / 2)
    for y in range(bar_y1, bar_y2):
        for x in range(bar_x1, bar_x2):
            if 0 <= x < width and 0 <= y < height:
                img[y][x] = (*fg, 255)

    # Encode as PNG
    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)

    raw = b""
    for row in img:
        raw += b"\x00"
        for r2, g2, b2, a2 in row:
            raw += struct.pack("BBBB", r2, g2, b2, a2)

    compressed = zlib.compress(raw, 9)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    return png


os.makedirs("icons", exist_ok=True)
for size in [16, 48, 128]:
    with open(f"icons/icon{size}.png", "wb") as f:
        f.write(make_png(size))
    print(f"Created icons/icon{size}.png")
