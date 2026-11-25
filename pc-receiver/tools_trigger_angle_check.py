import math

def bbox(w, h, deg):
    r = math.radians(deg)
    c, s = abs(math.cos(r)), abs(math.sin(r))
    return w * c + h * s, w * s + h * c

def to_local(x, y, w, h, deg):
    # View bounds = 旋转后的外接框；形状自己占 w×h，居中
    bw, bh = bbox(w, h, deg)
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    dx, dy = x - bw / 2, y - bh / 2
    return w / 2 + dx * c + dy * s, h / 2 - dx * s + dy * c

def value_at(x, y, w, h, deg, anchor_local_y):
    lx, ly = to_local(x, y, w, h, deg)
    span = max(h - anchor_local_y, 0.25 * h)          # Views.kt: max(ownH - anchorY, dp(12))
    depth = max(0.0, min(1.0, (ly - anchor_local_y) / span))
    return round(depth * 255), depth

w, h = 70.0, 120.0          # LT：宽 70dp，高 120dp（ownW/ownH = 不超过 View bounds）
print("角度 | 按下(点一下) | 从按下点拖到最远端 | 拖回反方向")
for deg in (0, 90, 180, 270, 45):
    bw, bh = bbox(w, h, deg)
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    # 按下点：形状中心（屏幕正中）
    tap = to_local(bw / 2, bh / 2, w, h, deg)
    anchor = tap[1]
    tap_value = round(max(0.0, min(1.0, (tap[1] - anchor) / h)) * 255)
    # 最远端（形状自己的远端）在屏幕上的位置
    off = (-s * h / 2, c * h / 2)
    far_x, far_y = bw / 2 + off[0], bh / 2 + off[1]
    far_v, far_d = value_at(far_x, far_y, w, h, deg, anchor)
    # 反方向拖（往近端）
    near_x, near_y = bw / 2 - off[0], bh / 2 - off[1]
    neg_v, _ = value_at(near_x, near_y, w, h, deg, anchor)
    print(f"{deg:>3}° | {tap_value:>13} | {far_v:>18}（depth {far_d:.2f}） | {neg_v:>12}")

print()
print("按下点不在中心时：行程从按下点算，拖到最远端都是 255")
for press_y in (0.0, 30.0, 60.0, 90.0, 110.0):
    span = max(h - press_y, 0.25 * h)
    v = round(min(1.0, (h - press_y) / span) * 255)
    print(f"  按下 y={press_y:>5.0f}（dp）→ 拖到底 {v:>3}；只点一下 0")
