from PIL import Image

im = Image.open(r"D:\project\xpad-joy\harmony\emutest\snap11.jpeg").convert("RGB")
W, H = im.size
ACCENT = (0x3B, 0x82, 0xF6)
LINE = (0x46, 0x53, 0x61)


def near(p, c, tol=24):
    return all(abs(a - b) <= tol for a, b in zip(p, c))


def bbox(y0, y1, color):
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(W):
            if near(im.getpixel((x, y)), color):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys), (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)


print("蓝色(选中胶囊/按钮) y450-650:", bbox(450, 650, ACCENT))
print("描边胶囊 y450-650:", bbox(450, 650, LINE))
print("顶部蓝色按钮 y100-450:", bbox(100, 450, ACCENT))
