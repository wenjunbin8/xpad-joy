#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xpad-joy 图标生成（Pillow，纯代码画，不联网、不下载素材）

跑：  py -3 tools/make_icon.py   （要 Pillow；本机用打包运行时里的 Pillow 跑通过）

设计：深蓝黑圆角底 + 亮蓝手柄剪影（十字键、四个按键、两个摇杆挖空成深色孔），
右上三... 手柄在中间、电波在右上。图形要能缩到 16 px 还认得出：所以只保留剪影 + 三个孔。

产物：
  assets/icon_master.png      1024 主图（带圆角底，给 Windows 图标用）
  assets/icon_glyph.png       1024 只有图形（透明底，给 Android 自适应图标的前景层用）
  assets/preview_small.png    一排小尺寸预览（16/32/48/72/96/192），看小尺寸还认不认得出
  pc-receiver/icon.ico        Windows 多尺寸图标（16/24/32/48/64/128/256）
  android/.../res/mipmap-*/ic_launcher.png 和 ic_launcher_round.png（48/72/96/144/192）
  android/.../res/drawable-*/ic_launcher_foreground.png（108dp 画布，图形在 66dp 安全区里）
"""

import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
S = 2048                      # 先按 2048 画再缩到 1024，边缘更干净
U = S / 1024.0                # 1 个"1024 单位"等于多少像素

BG_TOP = (24, 35, 47)         # 底上
BG_BOTTOM = (14, 19, 23)      # 底下
ACCENT = (59, 130, 246)       # #3B82F6
ACCENT_LIGHT = (133, 184, 255)
HOLE = (13, 18, 23)           # 挖空（比底更暗）


def canvas():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def gradient(draw, top, bottom):
    for i in range(S):
        t = i / float(S)
        c = tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3))
        draw.line([(0, i), (S, i)], fill=c + (255,))


def circle(draw, cx, cy, r, fill):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def cross(draw, cx, cy, arm, length, fill):
    draw.polygon([
        (cx - arm, cy - length), (cx + arm, cy - length), (cx + arm, cy - arm),
        (cx + length, cy - arm), (cx + length, cy + arm), (cx + arm, cy + arm),
        (cx + arm, cy + length), (cx - arm, cy + length), (cx - arm, cy + arm),
        (cx - length, cy + arm), (cx - length, cy - arm), (cx - arm, cy - arm),
    ], fill=fill)


def gamepad(draw, cx, cy, scale, detail=True):
    """手柄剪影：机身 + 两个握把；detail=True 时画十字键、四个按键、两个摇杆孔。"""
    bw, bh = int(600 * scale * U), int(300 * scale * U)
    br = int(120 * scale * U)
    x0, y0 = cx - bw // 2, cy - bh // 2
    draw.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=br, fill=ACCENT)

    grip_r = int(150 * scale * U)
    drop = int(45 * scale * U)
    gx1, gx2 = x0 + int(bw * 0.17), x0 + bw - int(bw * 0.17)
    gy = y0 + bh // 2 + drop
    circle(draw, gx1, gy, grip_r, ACCENT)
    circle(draw, gx2, gy, grip_r, ACCENT)

    if not detail:
        return

    # 十字键（左）、四个按键菱形（右）：都在机身上半部
    arm, length = int(20 * scale * U), int(52 * scale * U)
    cross(draw, x0 + int(bw * 0.17), y0 + int(bh * 0.30), arm, length, HOLE)
    btn = int(22 * scale * U)
    sp = int(46 * scale * U)
    bx, by = x0 + int(bw * 0.83), y0 + int(bh * 0.30)
    for dx, dy in ((0, -sp), (sp, 0), (0, sp), (-sp, 0)):
        circle(draw, bx + dx, by + dy, btn, HOLE)

    # 摇杆：机身后半部，对称；深色孔 + 浅蓝小帽（小尺寸时只剩这两个孔，所以别太大）
    sr = int(44 * scale * U)
    for sx in (x0 + int(bw * 0.36), x0 + int(bw * 0.64)):
        sy = y0 + bh - int(bh * 0.18)
        circle(draw, sx, sy, sr, HOLE)
        circle(draw, sx, sy - int(12 * scale * U), int(18 * scale * U), ACCENT_LIGHT)


def waves(draw, cx, cy, scale, color=ACCENT_LIGHT):
    """右上角三道电波（手机把键值传到电脑）。"""
    w = int(max(6, int(13 * scale * U)))
    for i, r in enumerate((int(120 * scale * U), int(84 * scale * U), int(48 * scale * U))):
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=195, end=285, fill=color, width=w)


def master_icon():
    img, draw = canvas()
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    gradient(gd, BG_TOP, BG_BOTTOM)
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(170 * U), fill=255)
    img.paste(grad, (0, 0), mask)

    draw2 = ImageDraw.Draw(img)
    gamepad(draw2, int(S * 0.50), int(S * 0.55), 0.95)
    waves(draw2, int(S * 0.76), int(S * 0.25), 0.95)
    return img


def glyph_only():
    """Android 自适应图标的前景层：108dp 画布，图形必须在中间 66dp（约 61%）里。"""
    img, draw = canvas()
    scale = 0.55
    gamepad(draw, int(S * 0.50), int(S * 0.55), scale)
    waves(draw, int(S * 0.72), int(S * 0.29), scale)
    return img


def save(img, path, size=None):
    if size:
        img = img.resize((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("写了 %s（%dx%d）" % (path, img.width, img.height))


def rounded_round(img, size, path):
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.save(path)
    print("写了 %s（%dx%d）" % (path, size, size))


def preview(master, path):
    """把同一张图按小尺寸排一排，看还能不能认出手柄。"""
    sizes = (16, 24, 32, 48, 64, 96, 128, 192)
    h = 200
    cell = max(sizes) + 24
    out = Image.new("RGBA", (cell * len(sizes), h), (16, 20, 25, 255))
    d = ImageDraw.Draw(out)
    for i, s in enumerate(sizes):
        small = master.resize((s, s), Image.LANCZOS)
        x = i * cell + (cell - s) // 2
        d.text((i * cell + 8, h - 24), str(s), fill=(231, 236, 243, 255))
        out.paste(small, (x, (cell - s) // 2))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.save(path)
    print("写了 %s" % path)


def main():
    assets = os.path.join(PROJECT, "assets")
    master = master_icon()
    glyph = glyph_only()
    save(master, os.path.join(assets, "icon_master.png"), 1024)
    save(glyph, os.path.join(assets, "icon_glyph.png"), 1024)
    preview(master, os.path.join(assets, "preview_small.png"))

    ico = os.path.join(PROJECT, "pc-receiver", "icon.ico")
    master.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("写了 %s" % ico)

    res = os.path.join(PROJECT, "android", "app", "src", "main", "res")
    for name, size in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        d = os.path.join(res, "mipmap-" + name)
        save(master, os.path.join(d, "ic_launcher.png"), size)
        rounded_round(master, size, os.path.join(d, "ic_launcher_round.png"))
    for name, size in (("mdpi", 108), ("hdpi", 162), ("xhdpi", 216), ("xxhdpi", 324), ("xxxhdpi", 432)):
        save(glyph, os.path.join(res, "drawable-" + name, "ic_launcher_foreground.png"), size)


if __name__ == "__main__":
    main()
