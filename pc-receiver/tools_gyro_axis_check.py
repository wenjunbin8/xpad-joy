import math

def mul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

def tr(A):
    return [[A[i][j] for i in range(3)] for j in range(3)]

def rot(axis, deg):
    n = math.sqrt(sum(v * v for v in axis))
    x, y, z = [v / n for v in axis]
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ]

def antisym(M):
    return [(M[2][1] - M[1][2]) / 2.0, (M[0][2] - M[2][0]) / 2.0, (M[1][0] - M[0][1]) / 2.0]

def kotlin_angle(M, axis):
    """Kotlin 里算的是 M = R1·R0ᵀ 或 Wᵀ（转置形式），所以取分量时要交换减序 = 物理角"""
    v = antisym(M)
    s = -sum(axis[i] * v[i] for i in range(3))
    c = (M[0][0] + M[1][1] + M[2][2] - 1.0) / 2.0
    return math.degrees(math.atan2(s, c))

SIGN = -1.0          # Kotlin ORIENTATION_SIGN
RANGE = 8.0          # 第一屏滑块
theta = 6.0          # 向左转 6°（从上看逆时针）→ 摇杆应该是负数

poses = [
    ("横屏、平放桌上（屏幕朝上）", [[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
    ("横屏、竖着拿（屏幕对自己）", [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]),
    ("竖屏、竖着拿（屏幕对自己）", [[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
    ("横屏、竖着拿但反手（屏幕对自己）", [[0, 0, -1], [0, 1, 0], [1, 0, 0]]),
]

print("同一个动作：向左转 %.0f°（从上看逆时针）。摇杆应该 = 负（左）：" % theta)
for name, R0 in poses:
    W = rot((0, 0, 1), theta)                 # 绕世界竖直转
    # Kotlin AXIS_AUTO: worldRelative = R0ᵀ · M · R0，其中 M = R1·R0ᵀ = R0·Wᵀ·R0ᵀ
    M = mul(mul(R0, tr(W)), tr(R0))
    Wm = tr(W)
    # 这条动作在世界里是绕竖直转；用 device 坐标看它落在哪条机身轴上
    up_in_device = [R0[0][2], R0[1][2], R0[2][2]]
    stick = kotlin_angle(Wm, (0, 0, 1)) / RANGE * 127 * SIGN
    stick = max(-127, min(127, stick))
    stick_fixed = kotlin_angle(M, up_in_device) / RANGE * 127 * SIGN
    stick_fixed = max(-127, min(127, stick_fixed))
    print("  %-34s AXIS_AUTO → 摇杆 %6.1f   固定机身竖直轴 → 摇杆 %6.1f" % (name, stick, stick_fixed))
