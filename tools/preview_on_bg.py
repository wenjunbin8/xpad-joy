#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 icon_master.png 在几种底色上排一遍，看它在深浅背景和小尺寸下长什么样。

跑：  py -3 tools/preview_on_bg.py
产物：assets/preview_on_bg.png
"""

import os
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
SRC = os.path.join(PROJECT, "assets", "icon_master.png")

BG = [(17, 21, 25), (245, 246, 248), (32, 38, 45), (120, 130, 140)]
SIZES = (16, 24, 32, 48, 64, 128, 192, 256)
CELL = max(SIZES) + 40
COLW = 320
ROWH = 320


def main():
    master = Image.open(SRC).convert("RGBA")
    w = COLW * len(BG)
    h = ROWH * len(SIZES)
    canvas_img = Image.new("RGBA", (w, h), (16, 20, 25, 255))

    for r, size in enumerate(SIZES):
        for c, bg in enumerate(BG):
            tile = Image.new("RGBA", (COLW, ROWH), bg + (255,))
            small = master.resize((size, size), Image.LANCZOS)
            x = (COLW - size) // 2
            y = (ROWH - size) // 2
            # 圆角底自带透明角，直接 paste（带 alpha）
            tile.paste(small, (x, y), small)
            canvas_img.paste(tile, (c * COLW, r * ROWH))

    out = os.path.join(PROJECT, "assets", "preview_on_bg.png")
    canvas_img.save(out)
    print("写了 %s（%dx%d，行=尺寸 %s，列=底色 %s）" % (out, w, h, SIZES, BG))


if __name__ == "__main__":
    main()
