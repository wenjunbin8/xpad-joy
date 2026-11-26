from PIL import Image

im = Image.open(r"D:\project\xpad-joy\harmony\emutest\snap10.jpeg").convert("RGB")
W, H = im.size
ACCENT = (0x3B, 0x82, 0xF6)
LINE = (0x46, 0x53, 0x61)


def near(p, c, tol=26):
    return all(abs(a - b) <= tol for a, b in zip(p, c))


def bbox(region, color):
    xs, ys = [], []
    for y in range(500, 900):
        for x in range(0, W):
            if near(im.getpixel((x, y)), color):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys), (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)


print("image", W, H)
print("蓝色胶囊(Wi-Fi):", bbox(region=None, color=ACCENT))
print("描边胶囊(hdc):", bbox(region=None, color=LINE))
