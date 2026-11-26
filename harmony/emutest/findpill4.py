from PIL import Image

im = Image.open(r"D:\project\xpad-joy\harmony\emutest\snap17.jpeg").convert("RGB")
W, H = im.size
ACCENT = (0x3B, 0x82, 0xF6)


def near(p, c, tol=24):
    return all(abs(a - b) <= tol for a, b in zip(p, c))


def bbox(y0, y1, x0, x1, color):
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if near(im.getpixel((x, y)), color):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys), (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)


print("体感胶囊:", bbox(1900, 2400, 0, 700, ACCENT))
print("紧凑包胶囊:", bbox(2400, 2848, 0, 700, ACCENT))
print("扫码连接按钮:", bbox(600, 900, 900, W, ACCENT))
print("进入手柄:", bbox(1800, 2000, 0, 400, ACCENT))
