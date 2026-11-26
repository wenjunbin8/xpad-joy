#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC 端（Windows）接收程序：接收安卓手机发来的游戏手柄状态（Wi-Fi 走 UDP，USB 走 ADB 隧道的 TCP），
并映射为「虚拟 Xbox 360 手柄」（XInput，通过 vgamepad + ViGEmBus 驱动）。

用法示例:
    python receiver.py
    python receiver.py --port 27042
    python receiver.py --console          # 输出走命令行（仍然会创建虚拟手柄，Steam 能认到）
    python receiver.py --no-pad           # 只看打印、不建虚拟手柄（Steam 就看不到手柄）
    python receiver.py --backend x360     # 虚拟手柄后端：x360（默认）或 ds4；X360 验证不过会自动退到 DS4
    python receiver.py --timeout 10
    python receiver.py --status-interval 2    # 运行信息（按键/摇杆/扳机/收包数）显示在这里
    python receiver.py --no-tcp               # 只留 UDP（关掉 ADB 隧道的 TCP 监听）
    pip install vgamepad

两条收包路径（协议字段完全不变，两条可以同时用）:
  Wi-Fi : UDP，一个数据报一个包（原来那条，逻辑一行没改）。
  ADB   : USB 这条改成 ADB 隧道，ADB 只能转发 TCP —— 电脑上先 `adb reverse tcp:27042 tcp:27042`，
          手机连 127.0.0.1:27042。TCP 上按帧读写：2 字节大端长度 + 原始包字节，
          payload 就是原来 UDP 数据报的内容（20 字节紧凑包 / JSON / XACK），一个字节都不能改。

协议（与安卓端完全一致，字段名不得改动）:
  状态包（手机 -> PC），JSON / UTF-8，一个 UDP 数据报一个 JSON：
    {"t":"state","buttons":<int 0..2047>,"hat":<int 0..8>,
     "lx":<int -128..127>,"ly":<int -128..127>,
     "rx":<int -128..127>,"ry":<int -128..127>,
     "lt":<int 0..255>,"rt":<int 0..255>}

  buttons 位定义（从 bit0 起）：
    0=A, 1=B, 2=X, 3=Y, 4=LB(左肩键), 5=RB, 6=BACK(选择),
    7=START, 8=GUIDE(Xbox 按钮), 9=L3, 10=R3

  hat（十字键，8 方向 + 中立）：
    0=上, 1=右上, 2=右, 3=右下, 4=下, 5=左下, 6=左, 7=左上, 8=中立(未按下)

  震动包（PC -> 手机），发往最近一次收到状态包的来源地址：
    {"t":"rumble","left":0-255,"right":0-255}
  震动值来自 ViGEmBus 的回调（游戏对虚拟手柄发震动时才会来），回调在驱动线程上跑，
  所以只入队、由主循环发（同一条连接不能两个线程同时写帧）。同一强度最多每 120ms 发一次。

重要说明（符号）：
  ly / ry 的符号：游戏里通常 y 轴向下为正（XInput 的 left_y / right_y 也是向下为正），
  因此直接把 ly 赋值给 vgamepad 的 left_y、把 ry 赋值给 right_y，不做任何取反。
"""

import argparse
import gc
import json
import select
import signal
import socket
import sys
import threading
import time

# 虚拟手柄这一层单独放在 pads.py（两个后端 + 验证）：pads.py 自己 try/except 导入 vgamepad，
# 这里也包一层，保证 python -m py_compile 等静态校验不会失败。
try:
    import pads
except Exception:
    pads = None

# vgamepad 依赖 Windows 的 ViGEmBus 驱动；未安装库时导入会失败，
# 这里必须放在 try/except 中，保证 python -m py_compile 等静态校验不会失败。
try:
    import vgamepad as vg
except Exception:
    vg = None

DEFAULT_PORT = 27042
DEFAULT_TIMEOUT = 10.0  # 秒：连续无数据则打印超时提示，但程序继续运行

MAX_FRAME_BYTES = 4096        # TCP 帧里包长度的上限（和 UDP 的 recvfrom(4096) 一致）
MAX_FRAMES_PER_CONN = 1000    # 单条 TCP 连接一次最多攒这么多帧，超了直接断连


def xinput_connected(slot):
    """查这个玩家位上 XInput 是不是真能看到设备（虚拟手柄没真正插上时会返回 False）。

    读不到（非 Windows、没有 xinput dll）返回 None，不报假消息。
    返回码 0 = 有设备；1167 = ERROR_DEVICE_NOT_CONNECTED。
    """
    return pads.xinput_visible(slot) if pads else None

# ---------------------------------------------------------------------------
# buttons 位定义：bit -> 显示名称。
# 属性名按版本前缀生成：新版 vgamepad 是 XUSB_BUTTON 类里的 XUSB_GAMEPAD_*，
# 老版本是模块级的 XBOX_BUTTON_*，两种都试。
# ---------------------------------------------------------------------------
BUTTON_BITS = [
    (0, "A"), (1, "B"), (2, "X"), (3, "Y"), (4, "LB"), (5, "RB"),
    (6, "BACK"), (7, "START"), (8, "GUIDE"), (9, "L3"), (10, "R3"),
]
BUTTON_NAME_CANDIDATES = {
    "A": ("A",), "B": ("B",), "X": ("X",), "Y": ("Y",),
    "LB": ("LB", "LEFT_SHOULDER"), "RB": ("RB", "RIGHT_SHOULDER"),
    "BACK": ("BACK", "SELECT"), "START": ("START",), "GUIDE": ("GUIDE",),
    "L3": ("L3", "LEFT_THUMB"), "R3": ("R3", "RIGHT_THUMB"),
}

BUTTON_PREFIXES = ("XUSB_GAMEPAD_", "XBOX_BUTTON_")
DPAD_PREFIXES = ("XUSB_GAMEPAD_", "XBOX_BUTTON_")
DPAD_KEYS = ("DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")

# 不同 vgamepad 版本的手柄类名：ViGamepad（某些版本）/ XUSB（老版）/ VX360Gamepad（0.1+）
GAMEPAD_CLASS_CANDIDATES = ("ViGamepad", "XUSB", "VX360Gamepad", "VGamepad")

# hat 值 -> 需要按下的十字键（8 方向映射为组合方向，例如 hat=1 -> DPadUp+DPadRight）
HAT_DPAD = {
    0: ("DPAD_UP",),
    1: ("DPAD_UP", "DPAD_RIGHT"),
    2: ("DPAD_RIGHT",),
    3: ("DPAD_DOWN", "DPAD_RIGHT"),
    4: ("DPAD_DOWN",),
    5: ("DPAD_DOWN", "DPAD_LEFT"),
    6: ("DPAD_LEFT",),
    7: ("DPAD_UP", "DPAD_LEFT"),
    8: (),  # 中立：所有十字键 release
}


STICK_FIELDS = ("lx", "ly", "rx", "ry")
TRIGGER_FIELDS = ("lt", "rt")


def enum_containers():
    """枚举可能放在模块级（老版本），也可能放在 XUSB_BUTTON 这类枚举类里（新版本）。"""
    if vg is None:
        return []
    containers = [vg]
    for holder in ("XUSB_BUTTON", "XBOX_BUTTON", "DS4_BUTTONS"):
        obj = getattr(vg, holder, None)
        if isinstance(obj, type):
            containers.append(obj)
    return containers


def resolve_attr(prefixes, names):
    """按前缀 + 名称找按钮值（两种版本的命名都试）；找不到返回 None。"""
    containers = enum_containers()
    if not containers:
        return None
    candidates = [p + n for p in prefixes for n in names]
    for container in containers:
        for n in candidates:
            v = getattr(container, n, None)
            if v is not None:
                return v
    return None


def p(msg):
    """统一输出（flush=True）：重定向/管道时调试信息也能及时出现。
    打包成 --windowed 的 exe 时没有控制台（sys.stdout 是 None）：这时只走 client.py 的 emit（写日志文件）。"""
    if sys.stdout is None:
        return
    try:
        sys.stdout.write(str(msg) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def fmt_addr(addr):
    """来源地址写成 ip:port；TCP 连接上就是 getpeername()。"""
    try:
        return "%s:%d" % (addr[0], addr[1])
    except Exception:
        return str(addr)


def frame(payload):
    """TCP 帧：2 字节大端长度 + 原始包字节（payload 就是原来 UDP 数据报的内容，一个字节都不能改）。"""
    return len(payload).to_bytes(2, "big") + payload


def clamp(v, lo, hi):
    """把字段值夹到协议规定的范围内，避免异常数据把虚拟手柄搞坏。"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, v))


def parse_state(data):
    """解析并校验一个状态包；不合法返回 None（调用方计数并忽略）。"""
    try:
        obj = json.loads(data.decode("utf-8", errors="strict"))
    except Exception:
        return None
    if not isinstance(obj, dict) or obj.get("t") != "state":
        return None

    state = {}
    spec = {"buttons": (0, 2047), "hat": (0, 8)}
    for f in STICK_FIELDS:
        spec[f] = (-128, 127)
    for f in TRIGGER_FIELDS:
        spec[f] = (0, 255)

    for f, (lo, hi) in spec.items():
        if f not in obj:
            return None
        v = clamp(obj[f], lo, hi)
        if v is None:
            return None
        state[f] = v
    return state


def parse_compact(data):
    """紧凑包（手机发的 20 字节）：'X' + buttons(2) + hat + lx,ly,rx,ry + lt,rt + ts(8) + srtt(2)，全大端。
    返回 (state, ts, srtt)，srtt = -1 表示手机没测到。"""
    if len(data) < 20 or data[0:1] != b"X":
        return None

    def signed(v):
        return v - 256 if v > 127 else v

    state = {
        "buttons": ((data[1] << 8) | data[2]) & 2047,
        "hat": min(data[3], 8),
        "lx": signed(data[4]), "ly": signed(data[5]),
        "rx": signed(data[6]), "ry": signed(data[7]),
        "lt": data[8], "rt": data[9],
    }
    ts = int.from_bytes(data[10:18], "big")
    raw = int.from_bytes(data[18:20], "big")
    return state, ts, (raw if raw < 0xFFFF else -1)


def fmt_state(state):
    """控制台模式下用于打印状态变化的一行摘要。"""
    b = state["buttons"]
    on = [BUTTON_BITS[i][1] for i in range(11) if (b >> i) & 1]
    return "buttons=%d [%s] hat=%d sticks=(%d,%d,%d,%d) triggers=(%d,%d)" % (
        b, ",".join(on) if on else "-", state["hat"],
        state["lx"], state["ly"], state["rx"], state["ry"],
        state["lt"], state["rt"],
    )


class Conn:
    """一条已接受的 TCP 连接（走 ADB 隧道）：帧缓冲 + 本次攒了多少帧。"""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.buf = bytearray()   # 半包留在这里，下次再读
        self.frames = 0          # 本次读到的帧数（用于 1000 帧上限）


class Receiver:
    """核心：收包 -> 与上一帧比较 -> 只在变化时设置虚拟手柄 / 打印。"""

    def __init__(self, port, force_console, timeout, no_pad=False, prefer_backend="x360"):
        self.port = port
        self.timeout = timeout
        self.no_pad = no_pad             # True：只打印，不创建虚拟手柄（--no-pad）
        self.prefer_backend = prefer_backend   # x360 / ds4；pads.pick_backend 按这个顺序试
        self.backend = None              # 当前用的虚拟手柄后端（pads.Backend 对象）
        self.backend_notes = []          # 建失败/验证失败的说明，打印用
        self.invalid_count = 0
        self.packet_count = 0
        self.last_sender = None          # 最近一次状态包来源地址（震动包回送目标）
        self.prev = None                 # 上一帧状态
        self.pad = None                  # 虚拟手柄（None 表示控制台模式）
        self.console_mode = force_console or vg is None
        self.button_objs = {}
        self.rumble_count = 0
        # 震动包要在主循环里发：ViGEmBus 的回调是驱动线程，和收包线程同时往同一条连接写字节
        # 会把"2 字节长度 + 正文"的帧写乱（手机那边就是解不出 JSON、不震动）。
        self._rumble_q = []
        self._rumble_lock = threading.Lock()
        self._last_rumble_vals = (0, 0)
        self._last_rumble_at = 0.0
        self.rumble_min_interval_ms = 120   # 同一个强度最多每 120ms 发一次（游戏每帧都发，手机那边也会被限流）
        self.status_interval = 1.0        # 秒：运行信息刷新间隔（0 = 关闭）
        self._last_status_at = 0.0
        self._last_printed = None
        self._last_printed_ping = 0
        self.phone_rtt = -1              # 手机上报的最后一次 ping→pong 往返延迟（ms）
        self.rtt_min = -1                # 同一连接内的 RTT 统计
        self.rtt_max = -1
        self.rtt_avg = -1.0
        self.handle_ms = 0.0             # 电脑端处理一个 state 包耗时（ms）：用来判断瓶颈在网络还是本机
        self.ack_enabled = True          # 每个带 ts 的包回 ack；--no-ack 关掉就少一半回包
        self.packet_format = "-"         # 手机实际在用哪种包：紧凑包（20B）或 JSON
        self.input_rtt = -1              # 手机上报的"输入路径往返"（state → 电脑 → 手机）
        self.lazy_pad = False            # True：收到第一帧才创建虚拟手柄（Steam 不会一开客户端就显示手柄）
        self.ping_count = 0
        self.last_gap_ms = 0.0
        self.min_gap_ms = 0.0
        self.avg_gap_ms = 0.0
        self.max_gap_ms = 0.0
        self.rx_rate = 0.0               # 收包速率（包/秒，指数平滑）
        self._last_rx_time = 0.0
        self.events = []
        self.self_test = None
        self.dpad_objs = {}
        self.running = True
        self._warned_timeout = False
        # -- ADB 隧道（只能转发 TCP）：Wi-Fi 的 UDP 路径完全不变，两条可以同时用 --
        self.tcp_enabled = True
        self.tcp_socket = None
        self.conns = []          # 已接受的 TCP 连接（Conn 对象）
        self.via = "UDP"         # 当前这条包是从哪条路收的：UDP 或 TCP(adb)
        self.reply_conn = None   # 回包要写回的 TCP 连接；None = UDP（照旧 sendto）

    # -- 虚拟手柄初始化 ---------------------------------------------------
    def pad_index(self):
        """新版用 get_index()，老版用 player_index。"""
        if self.backend is not None:
            return self.backend.index()
        idx = getattr(self.pad, "player_index", None)
        if idx is None and hasattr(self.pad, "get_index"):
            try:
                idx = self.pad.get_index()
            except Exception:
                idx = None
        return idx if idx is not None else "?"

    def init_gamepad(self):
        # 注意：--console 只是"输出走命令行"，不该顺手关掉虚拟手柄 —— Steam 认的就是这个手柄。
        # 要只看打印不建手柄，用 --no-pad。
        if self.no_pad:
            p("[模式] 只打印（--no-pad：不创建虚拟手柄）")
            return False
        if pads is None or getattr(pads, "vg", None) is None:
            p("[模式] 不建虚拟手柄：没有 vgamepad（打包版要用 --add-data 把 ViGEmClient.dll 打进包，"
              "或这个 Python 没装 vgamepad）")
            p("        原因：%s" % (getattr(pads, "VG_IMPORT_ERROR", "") or "pads 模块没读到"))
            self.console_mode = True
            return False

        backend, notes = pads.pick_backend(p, self.prefer_backend)
        self.backend_notes = list(notes)
        if backend is None:
            for n in notes:
                p("[警告] " + n)
            self.console_mode = True
            return False

        for n in notes:
            p("[提示] " + n)
        self.backend = backend
        self.pad = backend.pad
        self.button_objs = backend.buttons

        if backend.verified is True:
            p("[后端] %s —— 验证通过：Windows 和 Steam 都能看到这个设备" % backend.label())
        else:
            p("[警告] 用 %s 建了 target（玩家 %s），验证结果 = %s：设备其实没插上去，"
              "Steam 和游戏都读不到这个手柄" % (backend.display, backend.index(), backend.verified))
            p("        这种情况客户端看着一切正常（包照收、打印照刷），但 Steam 认不到。修驱动侧：")
            p("        1) 装 Nefarius ViGEmBus（建议 1.22+，和 vgamepad 自带的 ViGEmClient 配套）；")
            p("        2) 管理员执行 sc config ViGEmBus start= demand 然后重启；")
            p("        3) 设备管理器里 ViGEmBus 总线节点不能报 Problem 31；")
            p("        4) 虚拟设备要能绑上 XnaComposite 类驱动包（缺包时管理员执行："
              "pnputil /add-driver C:\\Windows\\INF\\xusb22.inf /install）")
        for n in backend.notes:
            p("[提示] " + n)
        self.register_vibration()
        return True

    # -- 震动回调 -----------------------------------------------------------
    def _motors(self, args):
        """老版回调收到一个 vibration 对象；新版收到 (client, target, large, small, led, user_data)。"""
        if len(args) == 1:
            return _motor_values(args[0])
        if len(args) >= 4:
            try:
                return int(args[2]), int(args[3])
            except (TypeError, ValueError):
                return 0, 0
        return 0, 0

    def register_vibration(self):
        """新版是 register_notification，老版是 register_vibration_callback；两种都试。"""
        if self.backend is None:
            return
        self.backend.register_rumble(lambda left, right: self.queue_rumble(left, right, "游戏"))

    def queue_rumble(self, left, right, source="手动"):
        """游戏发给虚拟手柄的震动（ViGEmBus 回调）或界面上的测试按钮：这里只入队。"""
        try:
            left = max(0, min(255, int(left)))
            right = max(0, min(255, int(right)))
        except (TypeError, ValueError):
            return
        if left <= 0 and right <= 0:
            return
        with self._rumble_lock:
            now = time.time()
            changed = (left, right) != self._last_rumble_vals
            if not changed and (now - self._last_rumble_at) * 1000.0 < self.rumble_min_interval_ms:
                return
            self._last_rumble_vals = (left, right)
            self._last_rumble_at = now
            self._rumble_q.append((left, right, source))

    def drain_rumble(self):
        """把排队的震动包发回手机：只在收包线程（主循环）里跑，一条连接只有一个线程在写。"""
        while True:
            with self._rumble_lock:
                if not self._rumble_q:
                    return
                left, right, source = self._rumble_q.pop(0)
            if self.last_sender is None:
                self.note("[震动] 没地方可回：手机还没发过状态包（left=%d right=%d）" % (left, right))
                continue
            payload = json.dumps({"t": "rumble", "left": left, "right": right}).encode("utf-8")
            try:
                self.reply(payload, self.last_sender)
                self.rumble_count += 1
                p("[%s震动] left=%d right=%d -> %s（走 %s）"
                  % (source, left, right, fmt_addr(self.last_sender), self.via))
            except Exception as exc:
                p("[震动发送失败] %s" % exc)

    # -- 处理一个状态包 ---------------------------------------------------
    def handle_state(self, state, addr):
        self.packet_count += 1
        self.last_sender = addr
        self._warned_timeout = False
        if self.lazy_pad and self.backend is None and not self.no_pad and getattr(pads, "vg", None) is not None:
            # 收到第一帧才创建虚拟手柄：否则 Steam 一开客户端就显示「手柄已连接」
            self.init_gamepad()
        now = time.time()
        if self._last_rx_time:
            gap = now - self._last_rx_time
            if gap > 0:
                self.last_gap_ms = gap * 1000.0
                if self.min_gap_ms == 0 or self.last_gap_ms < self.min_gap_ms:
                    self.min_gap_ms = self.last_gap_ms
                self.avg_gap_ms = self.last_gap_ms if self.avg_gap_ms == 0 else self.avg_gap_ms * 0.8 + self.last_gap_ms * 0.2
                self.max_gap_ms = max(self.max_gap_ms, self.last_gap_ms)
                self.rx_rate = 1.0 / gap if self.rx_rate == 0 else self.rx_rate * 0.8 + (1.0 / gap) * 0.2
        self._last_rx_time = now

        if self.prev is None:
            p("[首包] %s -> %s" % (addr, fmt_state(state)))
            self.prev = dict(state)
            self._apply(state, None, None)
            return

        old = dict(self.prev)
        changed = {k: state[k] for k in state if old.get(k) != state[k]}
        self.prev = dict(state)
        if not changed:
            return  # 无变化：不打印、不重复设置，避免刷屏
        p("[变化] %s" % _fmt_changed(changed))
        self._apply(state, changed, old)

    def maybe_print_status(self):
        """运行信息（安卓端第一屏已删掉，改在这里显示）：最多每 status_interval 秒打印一次。"""
        if self.status_interval <= 0:
            return
        # 只有 ping 的时候也要打印：这样能看到手机是不是把包发进来了
        if self.prev is None and self.ping_count == 0:
            return
        now = time.time()
        if now - self._last_status_at < self.status_interval:
            return
        if self.prev is not None and self.prev == self._last_printed:
            return
        self._last_status_at = now
        if self.prev is not None:
            self._last_printed = dict(self.prev)

        src = fmt_addr(self.last_sender) if self.last_sender else "-"
        if self.backend is not None:
            mode = "虚拟手柄 %s(玩家 %s)%s" % (self.backend.kind, self.pad_index(),
                                              "" if self.backend.verified is True else "(设备没插上，Steam 读不到)")
        else:
            mode = ("只打印(--no-pad)" if self.no_pad else "未建手柄")
        if self.prev is None:
            # 只有 ping：只在数字变化时打印一次，避免每秒刷屏
            if self.ping_count == self._last_printed_ping:
                return
            self._last_printed_ping = self.ping_count
            p("[运行信息] 还没收到 state 包（只有 ping）")
        else:
            p("[运行信息] %s" % fmt_state(self.prev))
        p("           来源=%s（走 %s）  收包=%d  无效=%d  震动=%d  模式=%s"
          % (src, self.via, self.packet_count, self.invalid_count, self.rumble_count, mode))
        p("           延迟 RTT=%s（min %s avg %.1f max %s）单程≈%.1fms  处理=%.1fms"
          % ("%dms" % self.phone_rtt if self.phone_rtt >= 0 else "-",
             self.rtt_min if self.rtt_min >= 0 else "-", self.rtt_avg,
             self.rtt_max if self.rtt_max >= 0 else "-",
             self.phone_rtt / 2.0 if self.phone_rtt >= 0 else -1.0, self.handle_ms))
        p("           输入路径往返=%s（手机发包→电脑处理→手机收到，手机侧排队也算进去）"
          % ("%dms" % self.input_rtt if self.input_rtt >= 0 else "-"))
        p("           收包速率=%.1f/s  包间隔 min=%.0f avg=%.0f max=%.0f ms  ping=%d"
          % (self.rx_rate, self.min_gap_ms, self.avg_gap_ms, self.max_gap_ms, self.ping_count))

    def note(self, msg):
        """记录一条事件（GUI 客户端会显示最近几条）。"""
        self.events.append(msg)
        if len(self.events) > 8:
            del self.events[0]

    def reply(self, payload, addr):
        """回包（XACK / pong / ack / rumble）统一走这里：
        self.reply_conn 不是 None（这条包来自 TCP 连接）就按帧格式写回那条连接；
        是 None（来自 UDP）就照旧 sendto。payload 一个字节都不改。"""
        conn = self.reply_conn
        if conn is None:
            self.sock.sendto(payload, addr)
            return
        try:
            conn.sock.sendall(frame(payload))
        except Exception as exc:
            self.note("回包失败（TCP %s）: %s" % (fmt_addr(conn.addr), exc))

    def handle_data(self, data, addr):
        """一个数据报：state 包走映射，其它（例如 ping）走 handle_other。"""
        if data[:1] == b"X" and len(data) >= 20:
            # 紧凑包：不用 JSON，18~20 字节，解析就是一次取字节
            parsed = parse_compact(data)
            if parsed is None:
                self.invalid_count += 1
                return
            state, ts, srtt = parsed
            self.last_sender = addr
            self.packet_format = "紧凑包 20B"
            started = time.perf_counter()
            self.handle_state(state, addr)
            self.handle_ms = (time.perf_counter() - started) * 1000.0
            if srtt >= 0:
                self.input_rtt = srtt
            if self.ack_enabled and ts > 0:
                try:
                    self.reply(b"XACK" + ts.to_bytes(8, "big"), addr)
                except Exception as exc:
                    self.note("ack 发送失败: %s" % exc)
            return
        try:
            obj = json.loads(data.decode("utf-8", errors="strict"))
        except Exception:
            obj = None
        if not isinstance(obj, dict):
            self.invalid_count += 1
            return
        # 任何合法 JSON 包都记下来源地址：这样只有 ping 的时候界面也能看到手机
        self.last_sender = addr
        if obj.get("t") == "state":
            state = parse_state(data)
            if state is None:
                self.invalid_count += 1
                if self.invalid_count == 1 or self.invalid_count % 10 == 0:
                    p("[无效包] 已忽略 %d 个（非 JSON 或字段不合法）" % self.invalid_count)
                return
            self.packet_format = "JSON"
            if isinstance(obj.get("rtt"), int):
                value = max(0, obj["rtt"])
                self.phone_rtt = value
                if self.rtt_min < 0 or value < self.rtt_min:
                    self.rtt_min = value
                if value > self.rtt_max:
                    self.rtt_max = value
                self.rtt_avg = float(value) if self.rtt_avg < 0 else self.rtt_avg * 0.8 + value * 0.2
            started = time.perf_counter()
            self.handle_state(state, addr)
            self.handle_ms = (time.perf_counter() - started) * 1000.0
            if isinstance(obj.get("srtt"), int):
                self.input_rtt = max(0, obj["srtt"])
            ts = obj.get("ts")
            if isinstance(ts, (int, float)) and ts > 0:
                # 回 ack：手机据此算"输入路径往返"（手机发包 → 电脑处理 → 手机收到）
                try:
                    self.reply(json.dumps({"t": "ack", "ts": ts}).encode("utf-8"), addr)
                except Exception as exc:
                    self.note("ack 发送失败: %s" % exc)
        else:
            self.handle_other(obj, addr)

    def handle_other(self, obj, addr):
        """ping → pong：手机据此算往返延迟（RTT），电脑端运行信息显示它。"""
        if obj.get("t") == "selftest":
            # 客户端自己发的回环测试包：只证明监听正常，不计入收包统计
            try:
                self.reply(json.dumps({"t": "pong", "ts": obj.get("ts")}).encode("utf-8"), addr)
            except Exception as exc:
                self.note("pong 发送失败: %s" % exc)
            self.self_test = True
            return
        if obj.get("t") == "ping":
            self.ping_count += 1
            try:
                self.reply(json.dumps({"t": "pong", "ts": obj.get("ts")}).encode("utf-8"), addr)
            except Exception as exc:
                self.note("pong 发送失败: %s" % exc)
        else:
            self.invalid_count += 1

    def _apply(self, state, changed, old=None):
        """把状态写入虚拟手柄；changed=None 表示全量设置。"""
        if self.backend is not None:
            return self.backend.apply(state, changed)
        if self.pad is None:
            return

        # 只处理发生变化的 bit（changed=None 时全量处理）
        changed_bits = None
        if changed is not None and "buttons" in changed:
            old_buttons = (old or {}).get("buttons", 0)
            changed_bits = {b for b in range(11)
                            if ((changed["buttons"] >> b) & 1) != ((old_buttons >> b) & 1)}
        dirty = False

        for bit, _label in BUTTON_BITS:
            obj = self.button_objs.get(bit)
            if obj is None:
                continue
            on = (state["buttons"] >> bit) & 1
            # 只处理变化的 bit（changed_bits 为 None 时全量处理）
            if changed_bits is not None and bit not in changed_bits:
                continue
            if on:
                self.pad.press_button(obj)
            else:
                self.pad.release_button(obj)
            dirty = True

        if changed is None or "hat" in changed:
            hat = state["hat"]
            if hat == 8:
                # 中立：所有十字键 release
                for key in DPAD_KEYS:
                    obj = self.dpad_objs.get(key)
                    if obj is not None:
                        self.pad.release_button(obj)
            else:
                for key in DPAD_KEYS:
                    obj = self.dpad_objs.get(key)
                    if obj is not None:
                        self.pad.release_button(obj)
                for key in HAT_DPAD[hat]:
                    obj = self.dpad_objs.get(key)
                    if obj is not None:
                        self.pad.press_button(obj)
            dirty = True

        if changed is None or any(f in changed for f in STICK_FIELDS):
            # 协议里摇杆是 -128..127；vgamepad 的 XInput 摇杆是 -32768..32767，
            # 直接赋小数值会被当作接近 0（Steam 的死区一下就吞掉），所以要放大 256 倍。
            # 另外这个版本的 vgamepad 用方法 left_joystick(x, y)，不是属性 left_x：
            # 写成属性赋值只会凭空多一个属性，报告里一直是 0，Steam 测试自然没反应。
            def scale(value):
                v = int(value) * 256
                return max(-32768, min(32767, v))

            lx, ly = scale(state["lx"]), scale(state["ly"])
            rx, ry = scale(state["rx"]), scale(state["ry"])
            try:
                if callable(getattr(self.pad, "left_joystick", None)):
                    self.pad.left_joystick(lx, ly)
                    self.pad.right_joystick(rx, ry)
                else:
                    # 老版本（0.3 之前）是属性，且用的就是 -128..127
                    self.pad.left_x = state["lx"]
                    self.pad.left_y = state["ly"]
                    self.pad.right_x = state["rx"]
                    self.pad.right_y = state["ry"]
            except Exception as exc:
                p("[摇杆映射失败] %s" % exc)
            dirty = True

        if changed is None or any(f in changed for f in TRIGGER_FIELDS):
            lt, rt = int(state["lt"]), int(state["rt"])
            try:
                if callable(getattr(self.pad, "left_trigger", None)):
                    self.pad.left_trigger(lt)
                    self.pad.right_trigger(rt)
                else:
                    self.pad.left_trigger = lt
                    self.pad.right_trigger = rt
            except Exception as exc:
                p("[扳机映射失败] %s" % exc)
            dirty = True

        if dirty:
            try:
                self.pad.update()
            except Exception as exc:
                p("[虚拟手柄 update 失败] %s" % exc)

    # -- TCP（ADB 隧道）收帧 ------------------------------------------------
    def accept_conn(self):
        """接受一条 TCP 连接（ADB 只能转发 TCP），设 TCP_NODELAY。"""
        try:
            c, addr = self.tcp_socket.accept()
        except OSError as exc:
            p("[TCP] accept 失败: %s" % exc)
            return None
        try:
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as exc:
            p("[TCP] TCP_NODELAY 设不上: %s" % exc)
        conn = Conn(c, addr)
        self.conns.append(conn)
        p("[TCP] 手机连上来了 %s（ADB 隧道）" % fmt_addr(addr))
        self.note("TCP 连接 %s" % fmt_addr(addr))
        return conn

    def conn_of(self, fd):
        """select 返回的 socket -> 对应的 Conn。"""
        for c in self.conns:
            if c.sock is fd:
                return c
        return None

    def close_conn(self, conn, why="连接断开"):
        """从 conns 移除并打印（连接断开时调用）。"""
        try:
            self.conns.remove(conn)
        except ValueError:
            pass
        try:
            conn.sock.close()
        except Exception:
            pass
        p("[TCP] %s：%s（还剩 %d 条）" % (why, fmt_addr(conn.addr), len(self.conns)))
        self.note("TCP %s（%s）" % (why, fmt_addr(conn.addr)))

    def read_frames(self, conn):
        """按帧格式读：先读满 2 字节大端长度，再读满 N 字节（半包留在缓冲里下次再读）。
        N 上限 MAX_FRAME_BYTES；单连接一次最多攒 MAX_FRAMES_PER_CONN 帧，超了直接断连。
        返回 False 表示这条连接该关。"""
        try:
            chunk = conn.sock.recv(MAX_FRAME_BYTES + 2)
        except BlockingIOError:
            return True
        except (ConnectionResetError, ConnectionAbortedError):
            return False
        except OSError as exc:
            p("[TCP] 读 %s 失败: %s" % (fmt_addr(conn.addr), exc))
            return False
        if not chunk:
            return False  # 对端关闭
        conn.buf.extend(chunk)
        conn.frames = 0
        while len(conn.buf) >= 2:
            n = int.from_bytes(conn.buf[:2], "big")
            if n > MAX_FRAME_BYTES:
                p("[TCP] %s 帧长度 %d 超上限 %d，断连" % (fmt_addr(conn.addr), n, MAX_FRAME_BYTES))
                return False
            if len(conn.buf) < 2 + n:
                break  # 半包：等下次 recv
            payload = bytes(conn.buf[2:2 + n])
            del conn.buf[:2 + n]
            conn.frames += 1
            if conn.frames > MAX_FRAMES_PER_CONN:
                p("[TCP] %s 一次攒了 %d 帧（上限 %d），断连" % (fmt_addr(conn.addr), conn.frames, MAX_FRAMES_PER_CONN))
                return False
            # 走同一个 handle_data：收包数、无效包、包间隔、RTT、输入路径往返这些统计全部不动
            self.via = "TCP(adb)"
            self.reply_conn = conn
            self.handle_data(payload, conn.addr)
        return True

    # -- 主循环 -------------------------------------------------------------
    def on_bound(self):
        """绑定成功后可做一次自检（GUI 客户端会用它做本地回环测试）；基类不做事。"""
        pass

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 不设 SO_REUSEADDR：第二个实例会直接报“端口已被占用”。
        # 之前设了它，两个程序能抢同一个端口，包被先绑定的那个收走 —— 手机显示已连接、这个窗口收包 0 就是这么来的。
        try:
            self.sock.bind(("0.0.0.0", self.port))
        except OSError as exc:
            p("[错误] 无法监听 UDP 端口 %d: %s（这个端口只能有一个程序在用：把另一个客户端或 receiver.py 关掉）" % (self.port, exc))
            return 1

        # ADB 只能转发 TCP：电脑端 adb reverse tcp:PORT tcp:PORT，手机连 127.0.0.1:PORT
        if self.tcp_enabled:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.tcp_socket.bind(("0.0.0.0", self.port))
                self.tcp_socket.listen(16)
            except OSError as exc:
                p("[错误] 无法监听 TCP 端口 %d: %s（ADB 那条收不了；Wi-Fi 的 UDP 照常）" % (self.port, exc))
                self.tcp_socket = None
                self.tcp_enabled = False

        if self.tcp_socket is not None:
            p("[监听] UDP 0.0.0.0:%d + TCP 0.0.0.0:%d（手机走 ADB 时只能连 TCP：手机上填 127.0.0.1:%d，电脑先 adb reverse tcp:%d tcp:%d）（Ctrl+C 退出）"
              % (self.port, self.port, self.port, self.port, self.port))
        else:
            p("[监听] UDP 0.0.0.0:%d（只有 UDP，TCP 被 --no-tcp 或绑定失败关掉了）（Ctrl+C 退出）" % self.port)
        if self.lazy_pad:
            p("[虚拟手柄] 收到第一帧才创建；超时没包会自动拔下（Steam 不会一进客户端就显示手柄已连接）")
        try:
            self.on_bound()
        except Exception as exc:
            p("[自检] %s" % exc)
        last_rx = time.time()

        while self.running:
            try:
                fds = [self.sock]
                if self.tcp_socket is not None:
                    fds.append(self.tcp_socket)
                fds.extend(c.sock for c in self.conns)
                # 有震动要发时把 select 超时缩短，别让震动包最多等 0.5 秒
                readable, _, _ = select.select(fds, [], [], 0.05 if self._rumble_q else 0.5)
                self.drain_rumble()
                if not readable:
                    # 超时检查：只在进入/离开超时状态时各打印一次，避免刷屏
                    self.maybe_print_status()
                    idle = time.time() - last_rx
                    if idle > self.timeout and not self._warned_timeout:
                        self._warned_timeout = True
                        p("[超时] %.0f 秒未收到状态包（程序继续运行，等待数据）；如果手机端显示已连接但这边收包是 0，包多半被另一个接收端收走了（关掉旧窗口），或手机走的网络到不了这个 IP（移动数据 / 不同网段 / AP 隔离）" % self.timeout)
                        if self.lazy_pad and self.pad is not None:
                            self.release_gamepad("超过 %.0f 秒没发包" % self.timeout)
                    continue

                got_data = False
                for fd in readable:
                    if fd is self.sock:
                        data, addr = self.sock.recvfrom(4096)
                        if not data:
                            continue
                        got_data = True
                        self.via = "UDP"
                        self.reply_conn = None
                        self.handle_data(data, addr)
                    elif fd is self.tcp_socket:
                        if self.accept_conn() is not None:
                            got_data = True
                    else:
                        conn = self.conn_of(fd)
                        if conn is None:
                            continue
                        got_data = True
                        if not self.read_frames(conn):
                            self.close_conn(conn)
                if got_data:
                    last_rx = time.time()
                self.maybe_print_status()
            except KeyboardInterrupt:
                break
            except OSError as exc:
                p("[socket 错误] %s" % exc)
                time.sleep(0.5)

        self.cleanup()
        p("[退出] 共收到 %d 个有效状态包，忽略 %d 个无效包" % (self.packet_count, self.invalid_count))
        return 0

    def release_gamepad(self, reason=""):
        """把虚拟手柄从 ViGEmBus 上拔下（Steam 就看不到手柄了），下次收到包再重新挂上。"""
        if self.backend is not None:
            # 只靠 GC 跑一次 __del__（unregister + target_remove + free）；
            # 手动调 __del__ 会在解释器退出时再跑一次，对已经 free 的指针二次 free → 进程崩。
            self.backend.close()
            self.backend = None      # 必须置空：handle_state 只在 backend is None 时才重建，
            self.pad = None          # 否则空闲拔下之后再来包不会重新插上（Steam 就一直看不到）
            p("[拔下] 虚拟手柄已从 ViGEmBus 移除%s" % ("（%s）" % reason if reason else ""))
            return
        if self.pad is None:
            return
        try:
            for obj in list(self.button_objs.values()) + list(self.dpad_objs.values()):
                if obj is not None:
                    self.pad.release_button(obj)
            self.pad.reset()
            self.pad.update()
        except Exception as exc:
            p("[清理] %s" % exc)
        try:
            # 只靠 GC 跑一次 VGamepad.__del__（unregister + target_remove + free）。
            # 手动调 __del__ 会在解释器退出时再跑一次，对已经 free 的指针二次 free → 进程崩。
            self.pad = None
            self.button_objs = {}
            self.dpad_objs = {}
            gc.collect()
        except Exception as exc:
            p("[清理] 拔下虚拟手柄失败: %s" % exc)
        p("[拔下] 虚拟手柄已从 ViGEmBus 移除%s" % ("（%s）" % reason if reason else ""))

    def cleanup(self):
        """优雅退出：释放所有按键、复位虚拟手柄、关闭 socket。"""
        if self.backend is not None:
            self.backend.close()
            self.pad = None
            p("[清理] 虚拟手柄已释放（后端 %s）" % self.backend.kind)
        elif self.pad is not None:
            try:
                for obj in list(self.button_objs.values()) + list(self.dpad_objs.values()):
                    if obj is not None:
                        self.pad.release_button(obj)
                self.pad.reset()
                self.pad.update()
                p("[清理] 虚拟手柄已释放")
            except Exception as exc:
                p("[清理] 虚拟手柄释放失败: %s" % exc)
        sock = getattr(self, "sock", None)
        if sock is not None:
            try:
                sock.close()
                p("[清理] UDP socket 已关闭")
            except Exception:
                pass
        for c in list(self.conns):
            self.close_conn(c, "退出时关闭")
        tcp = getattr(self, "tcp_socket", None)
        if tcp is not None:
            try:
                tcp.close()
                p("[清理] TCP socket 已关闭")
            except Exception:
                pass


def _motor_values(vibration):
    """从 vgamepad 的震动对象中取左右马达强度（不同版本属性名不同）。"""
    left = getattr(vibration, "strong_motor", None)
    right = getattr(vibration, "weak_motor", None)
    if left is None:
        left = getattr(vibration, "left_motor", getattr(vibration, "left", 0))
    if right is None:
        right = getattr(vibration, "right_motor", getattr(vibration, "right", 0))
    return clamp(left, 0, 255) or 0, clamp(right, 0, 255) or 0


def _fmt_changed(changed):
    parts = []
    if "buttons" in changed:
        on = [BUTTON_BITS[i][1] for i in range(11) if (changed["buttons"] >> i) & 1]
        parts.append("buttons=%d[%s]" % (changed["buttons"], ",".join(on) if on else "-"))
    if "hat" in changed:
        parts.append("hat=%d" % changed["hat"])
    for f in STICK_FIELDS:
        if f in changed:
            parts.append("%s=%d" % (f, changed[f]))
    for f in TRIGGER_FIELDS:
        if f in changed:
            parts.append("%s=%d" % (f, changed[f]))
    return " ".join(parts)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="接收安卓端手柄状态（UDP + TCP/ADB 隧道）并映射为虚拟 Xbox 360 手柄（XInput）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口，UDP 和 TCP 都用它（默认 %d）" % DEFAULT_PORT)
    ap.add_argument("--console", action="store_true", help="输出走命令行（仍然会创建虚拟手柄，Steam 能认到）")
    ap.add_argument("--no-pad", action="store_true", help="不创建虚拟手柄、只看打印（Steam 看不到手柄）")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="无数据超时秒数（默认 %.0f）" % DEFAULT_TIMEOUT)
    ap.add_argument("--status-interval", type=float, default=1.0,
                    help="运行信息刷新间隔秒数（默认 1，0 = 关闭；安卓第一屏已不再显示这些信息）")
    ap.add_argument("--no-ack", action="store_true", help="不回 ack（少一半回包，代价是测不了输入路径往返）")
    ap.add_argument("--no-tcp", action="store_true", help="只监听 UDP（关掉 ADB 隧道的 TCP）")
    ap.add_argument("--backend", choices=("x360", "ds4"), default="x360",
                    help="虚拟手柄后端：x360（XInput，默认）或 ds4（HID，Steam Input 原生认）；"
                         "X360 验证不过会自动退到 DS4")
    args = ap.parse_args()

    r = Receiver(args.port, args.console, args.timeout, args.no_pad, args.backend)
    r.status_interval = args.status_interval
    r.ack_enabled = not args.no_ack
    r.tcp_enabled = not args.no_tcp

    def on_signal(signum, frame):
        r.running = False

    try:
        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)
    except Exception:
        pass

    r.init_gamepad()
    try:
        sys.exit(r.run())
    except KeyboardInterrupt:
        r.cleanup()
        sys.exit(0)


if __name__ == "__main__":
    main()
