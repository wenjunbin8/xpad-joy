from PIL import Image

im = Image.open(r"D:\project\xpad-joy\harmony\emutest\snap20.jpeg").convert("RGB")
W, H = im.size
PANEL = (0x23, 0x2A, 0x33)


def near(p, c, tol=12):
    return all(abs(a - b) <= tol for a, b in zip(p, c))


rows = {}
for y in range(350, 1100):
    for x in range(0, W):
        if near(im.getpixel((x, y)), PANEL):
            rows.setdefault(y, []).append(x)

# 把连续的 y 行合并成块，打印每块的 x 范围
blocks = []
cur = None
for y in sorted(rows):
    xs = rows[y]
    if cur is not None and y == cur[0] + 1:
        cur[1] = y
        cur[2] = min(cur[2], min(xs))
        cur[3] = max(cur[3], max(xs))
    else:
        if cur:
            blocks.append(cur)
        cur = [y, y, min(xs), max(xs)]
if cur:
    blocks.append(cur)

for b in blocks:
    y0, y1, x0, x1 = b
    if y1 - y0 >= 30 and x1 - x0 >= 80:
        print("块 y%d-%d x%d-%d 中心(%d,%d)" % (y0, y1, x0, x1, (x0 + x1) // 2, (y0 + y1) // 2))
