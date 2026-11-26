"""虚拟手柄后端层 —— 整个客户端里唯一依赖 ViGEmBus 的地方，这块是重写的版本。

为什么要重写（这条是这轮踩出来的事实，别再退回去）：
  1. "target 建好了" != "设备插上去了"。vgamepad 只有 vigem_target_add（attach + plug 一起做），
     DLL 里没有单独的 plug/unplug。驱动那边插不上时 target_add 甚至可能不报错，但设备在
     PnP 里永远是 Disconnected、XInput 读到的是 1167（未连接）—— 这时候 Steam 和游戏都读不到，
     客户端却看着一切正常（包照收、打印照刷）。所以每个后端必须"验证设备真的看得见"才算成功。
  2. 两个后端，自动选：
     - X360（XInput）：最通用，游戏和 Steam 都直接认；验证 = XInputGetState(玩家号) == 0。
     - DS4（HID）：Steam Input 原生认 HID 手柄；验证 = SetupAPI 枚举 HID 设备接口，看这个
       vid/pid 的设备在不在场。X360 验证失败就自动退到 DS4，并在输出里写清楚用的是哪个。
  3. 只用标准库（ctypes），不 pip 装任何东西。验证是只读的，不打开设备、不写注册表。

Xbox 布局 -> DS4 布局的对应写在下面（手机端显示的是 Xbox 名字，用 DS4 后端时 Steam 里会看到
"PlayStation 4 Controller"，Steam Input 会把它映射成 Xbox 布局，游戏里按键位置不变）。
"""

import ctypes
import gc
import os
import platform
import shutil
import sys
from ctypes import wintypes


def _try_vgamepad():
    """导入 vgamepad，返回 (模块或 None, 失败原因)。

    打包版（PyInstaller onefile）里没有 site-packages，而 vgamepad 在 import 那一刻就
    `CDLL("…/vgamepad/win/vigem/client/<arch>/ViGEmClient.dll")` —— 这个 DLL 不是 Python
    模块，PyInstaller 不会自动收（`Analysis-00.toc` 里根本没有它），所以 exe 里
    `import vgamepad` 直接失败，客户端收得到包却永远不建虚拟手柄（日志里那句
    "未建手柄"就是这么来的，而且一行报错都没有）。修法：打包时 --add-data 把 vigem 目录
    带上，落到 `_MEIPASS/vgamepad/win/vigem/client/<arch>/` 就跟 vgamepad 期望的路径对上；
    这里再兜一次：从 exe 同目录或 `_MEIPASS` 根找到 DLL，补到那个相对路径上再 import。
    """
    try:
        import vgamepad as vg
        return vg, ""
    except Exception as exc:
        first = str(exc)
        if "BUS_NOT_FOUND" in first:
            # 不是"没装 vgamepad"，是驱动没装/没加载：vgamepad 在 import 那一刻就 vigem_connect
            return None, "%s —— 驱动没装（或还没加载）：先装 ViGEmBus，再重开客户端" % first
    if not getattr(sys, "frozen", False):
        return None, first
    arch = "x64" if platform.architecture()[0] == "64bit" else "x86"
    base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    dst = os.path.join(base, "vgamepad", "win", "vigem", "client", arch)
    for src in (os.path.join(base, "ViGEmClient.dll"),
                os.path.join(os.path.dirname(sys.executable), "ViGEmClient.dll")):
        if not os.path.exists(src):
            continue
        try:
            os.makedirs(dst, exist_ok=True)
            shutil.copy2(src, os.path.join(dst, "ViGEmClient.dll"))
            import vgamepad as vg
            return vg, ""
        except Exception as exc:
            return None, "%s（把 %s 补到 %s 后还是不行：%s）" % (first, src, dst, exc)
    return None, first + "（打包版要带这个 DLL：PyInstaller 加 --add-data \"<site-packages>\\vgamepad\\win\\vigem;vgamepad\\win\\vigem\"）"


vg, VG_IMPORT_ERROR = _try_vgamepad()

XINPUT_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167

# 协议 buttons 的 bit -> 显示名（和 receiver.py 里那份是同一套 bit 定义）
BUTTON_BITS = [
    (0, "A"), (1, "B"), (2, "X"), (3, "Y"), (4, "LB"), (5, "RB"),
    (6, "BACK"), (7, "START"), (8, "GUIDE"), (9, "L3"), (10, "R3"),
]

X360_CLASS_CANDIDATES = ("ViGamepad", "XUSB", "VX360Gamepad", "VGamepad")

# bit -> 属性名后缀（老版本是模块级 XBOX_BUTTON_*，新版本是枚举类里的 XUSB_GAMEPAD_*）
X360_NAMES = {
    "A": ("A",), "B": ("B",), "X": ("X",), "Y": ("Y",),
    "LB": ("LB", "LEFT_SHOULDER"), "RB": ("RB", "RIGHT_SHOULDER"),
    "BACK": ("BACK", "SELECT"), "START": ("START",), "GUIDE": ("GUIDE",),
    "L3": ("L3", "LEFT_THUMB"), "R3": ("R3", "RIGHT_THUMB"),
}
X360_DPAD_KEYS = ("DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")
X360_HAT_DPAD = {
    0: ("DPAD_UP",), 1: ("DPAD_UP", "DPAD_RIGHT"), 2: ("DPAD_RIGHT",),
    3: ("DPAD_DOWN", "DPAD_RIGHT"), 4: ("DPAD_DOWN",), 5: ("DPAD_DOWN", "DPAD_LEFT"),
    6: ("DPAD_LEFT",), 7: ("DPAD_UP", "DPAD_LEFT"), 8: (),
}

# Xbox 布局 -> DS4 物理布局
DS4_NAMES = {
    "A": "DS4_BUTTON_CROSS", "B": "DS4_BUTTON_CIRCLE", "X": "DS4_BUTTON_SQUARE",
    "Y": "DS4_BUTTON_TRIANGLE", "LB": "DS4_BUTTON_SHOULDER_LEFT",
    "RB": "DS4_BUTTON_SHOULDER_RIGHT", "BACK": "DS4_BUTTON_SHARE",
    "START": "DS4_BUTTON_OPTIONS", "L3": "DS4_BUTTON_THUMB_LEFT",
    "R3": "DS4_BUTTON_THUMB_RIGHT",
}
DS4_SPECIAL = {"GUIDE": "DS4_SPECIAL_BUTTON_PS"}
# 协议 hat 0..8 和 vgamepad 的 DS4 十字键枚举值正好一一对应（8 = 中立）
DS4_HAT = {
    8: "DS4_BUTTON_DPAD_NONE", 0: "DS4_BUTTON_DPAD_NORTH", 1: "DS4_BUTTON_DPAD_NORTHEAST",
    2: "DS4_BUTTON_DPAD_EAST", 3: "DS4_BUTTON_DPAD_SOUTHEAST", 4: "DS4_BUTTON_DPAD_SOUTH",
    5: "DS4_BUTTON_DPAD_SOUTHWEST", 6: "DS4_BUTTON_DPAD_WEST", 7: "DS4_BUTTON_DPAD_NORTHWEST",
}

STICK_FIELDS = ("lx", "ly", "rx", "ry")
TRIGGER_FIELDS = ("lt", "rt")


# ---------------------------------------------------------------------------
# 验证：XInput 侧
# ---------------------------------------------------------------------------
class _XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("wButtons", wintypes.USHORT),
                ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


def xinput_read(slot):
    """读某个玩家位；返回 (返回码, state) 或 None（读不了）。只读，不写。"""
    try:
        dll = ctypes.CDLL("xinput1_4.dll")
    except Exception:
        return None
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        return None
    # Windows 的 XInput 玩家号是 0..3（Steam 也是按 0..3 扫的），不是 1..4
    if slot < 0 or slot > 3:
        return None
    try:
        st = _XInputState()
        return int(dll.XInputGetState(slot, ctypes.byref(st))), st
    except Exception:
        return None


def xinput_visible(slot):
    """True = 这个玩家位上真的有设备（Steam 能看到）。None = 没法判断。"""
    got = xinput_read(slot)
    if got is None:
        return None
    return got[0] == XINPUT_SUCCESS


# ---------------------------------------------------------------------------
# 验证：HID 侧（DS4 后端走这条）
# ---------------------------------------------------------------------------
class _Guid(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class _DevInfoData(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", _Guid),
                ("DevInst", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


# 这两条是写死的类 GUID。不要用 HidD_GetHidGuid()：在这台机器（至少在这个沙箱里）它返回的是
# 一个错的 GUID（4D1E55B2-…），拿它去 SetupDiGetClassDevs 枚举出来是空的。
HID_CLASS_GUID = (0x745a17a0, 0x74d3, 0x11d0, b"\xb6\xfe\x00\xa0\xc9\x0f\x57\xda")
XNA_COMPOSITE_GUID = (0xd61ca365, 0x5af4, 0x4486, b"\x99\x8b\x9d\xb4\x73\x4c\x6c\xa3")
DIG_PRESENT_ITEMS = 0x00000020


def pnp_class_devices(class_guid):
    """列出这个设备类里"在场"的设备实例 ID。只读；失败返回 None。"""
    try:
        setupapi = ctypes.CDLL("setupapi.dll", use_last_error=True)
    except Exception:
        return None

    setupapi.SetupDiGetClassDevsW.argtypes = (ctypes.POINTER(_Guid), ctypes.c_char_p,
                                              ctypes.c_void_p, wintypes.DWORD)
    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_longlong
    setupapi.SetupDiEnumDeviceInfo.argtypes = (ctypes.c_longlong, wintypes.DWORD,
                                               ctypes.POINTER(_DevInfoData))
    setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInstanceIdW.argtypes = (ctypes.c_longlong,
                                                      ctypes.POINTER(_DevInfoData),
                                                      ctypes.c_wchar_p, wintypes.DWORD,
                                                      ctypes.POINTER(wintypes.DWORD))
    setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = (ctypes.c_longlong,)

    g = _Guid()
    g.Data1 = class_guid[0]
    g.Data2 = class_guid[1]
    g.Data3 = class_guid[2]
    g.Data4 = (ctypes.c_ubyte * 8)(*class_guid[3])

    hset = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, DIG_PRESENT_ITEMS)
    if hset in (None, -1):
        return None

    ids = []
    data = _DevInfoData()
    data.cbSize = ctypes.sizeof(_DevInfoData)
    buf = ctypes.create_unicode_buffer(512)
    i = 0
    while i < 500 and setupapi.SetupDiEnumDeviceInfo(hset, i, ctypes.byref(data)):
        if setupapi.SetupDiGetDeviceInstanceIdW(hset, ctypes.byref(data), buf, 512, None):
            ids.append(buf.value)
        i += 1
    try:
        setupapi.SetupDiDestroyDeviceInfoList(hset)
    except Exception:
        pass
    return ids


def pnp_visible(class_guid, needle):
    """这个类的在场设备里有没有实例 ID 含 needle（Steam 枚举时能看到）。None = 没法判断。"""
    ids = pnp_class_devices(class_guid)
    if ids is None:
        return None
    needle = needle.lower()
    return any(needle in x.lower() for x in ids)


def hid_visible(vid, pid):
    return pnp_visible(HID_CLASS_GUID, "vid_%04x&pid_%04x" % (int(vid), int(pid)))


def xna_visible(vid, pid):
    return pnp_visible(XNA_COMPOSITE_GUID, "vid_%04x&pid_%04x" % (int(vid), int(pid)))



def _resolve(names):
    """在 vgamepad 的枚举类里找属性名（老版本可能在模块级）。"""
    if vg is None:
        return None
    holders = [vg]
    for holder in ("XUSB_BUTTON", "XBOX_BUTTON", "DS4_BUTTONS", "DS4_DPAD_DIRECTIONS",
                   "DS4_SPECIAL_BUTTONS"):
        obj = getattr(vg, holder, None)
        if isinstance(obj, type):
            holders.append(obj)
    for h in holders:
        for n in names:
            v = getattr(h, n, None)
            if v is not None:
                return v
    return None


def _motor_values(args):
    """震动回调的参数形状两种版本都有：老版一个 vibration 对象，新版 (client, target, large, small, ...)。"""
    if len(args) == 1:
        obj = args[0]
        for attr in ("large_motor", "large", "left"):
            if getattr(obj, attr, None) is not None:
                large = getattr(obj, attr)
                small = getattr(obj, "small_motor", getattr(obj, "small", 0))
                try:
                    return int(large), int(small)
                except (TypeError, ValueError):
                    return 0, 0
        return 0, 0
    if len(args) >= 4:
        try:
            return int(args[2]), int(args[3])
        except (TypeError, ValueError):
            return 0, 0
    return 0, 0


class Backend:
    """一个虚拟手柄后端：create -> visible -> apply -> close。"""

    kind = "?"
    display = "?"

    def __init__(self, say=None):
        self.say = say or (lambda msg: None)
        self.pad = None
        self.error = None
        self.verified = None
        self.buttons = {}
        self.notes = []

    def create(self):
        raise NotImplementedError

    def visible(self, baseline=None):
        """baseline = 建 target 之前这个设备类里在场的实例 ID 集合。
        光看"类里有这个 vid/pid"不够：残留节点也会一直在（这台机器上实测就是这种），
        所以必须看建完 target 之后有没有新增节点。"""
        raise NotImplementedError

    def apply(self, state, changed=None):
        raise NotImplementedError

    def register_rumble(self, callback):
        for name in ("register_vibration_callback", "set_vibration_callback",
                     "register_notification"):
            fn = getattr(self.pad, name, None)
            if not callable(fn):
                continue
            def on_vibration(*args):
                left, right = _motor_values(args)
                callback(left, right)
            try:
                fn(on_vibration)
                self.say("[震动回调] 已注册（%s，后端 %s）" % (name, self.kind))
                return True
            except Exception as exc:
                self.notes.append("%s 注册失败: %s" % (name, exc))
        self.say("[提示] 后端 %s 拿不到震动，震动包只打印不回手机" % self.kind)
        return False

    def index(self):
        if self.pad is None:
            return "?"
        try:
            return self.pad.get_index()
        except Exception:
            return "?"

    def xinput_slot(self):
        """XInput 的玩家号（0..3）。vgamepad 的 target 序号从 1 起，所以要减 1。

        减 1 读不到再扫 0..3 —— 但扫到的槽可能是**别的程序**（或上一个没拔干净的进程）建的手柄，
        所以扫到别的槽时要写清楚，不能当成"我们自己的手柄读得到"（之前就是这样误判验证通过）。
        """
        idx = self.index()
        primary = idx - 1 if isinstance(idx, int) else None
        if primary is not None:
            got = xinput_read(primary)
            if got is not None and got[0] == XINPUT_SUCCESS:
                return primary
        for slot in range(4):
            got = xinput_read(slot)
            if got is not None and got[0] == XINPUT_SUCCESS:
                if slot != primary:
                    self.notes.append("XInput 上读得到的是槽 %d（可能是别的程序或上个没拔干净的进程建的手柄；"
                                      "我们自己的 target=%s 没插上）" % (slot, idx))
                return slot
        return primary

    def label(self):
        return "%s（玩家 %s）" % (self.display, self.index())

    def close(self):
        """释放按键 + 拔下。注意：只靠 GC 跑一次 __del__；手动调 __del__ 会在退出时二次 free。"""
        if self.pad is None:
            return
        try:
            for obj in list(self.buttons.values()):
                if obj is not None:
                    self.pad.release_button(obj)
            self.pad.reset()
            self.pad.update()
        except Exception as exc:
            self.notes.append("释放按键失败: %s" % exc)
        self.pad = None
        self.buttons = {}
        gc.collect()


class X360Backend(Backend):
    kind = "X360"
    display = "虚拟 Xbox 360 手柄（XInput）"
    class_guid = XNA_COMPOSITE_GUID
    vid, pid = 0x045E, 0x0289

    def create(self):
        if vg is None:
            raise RuntimeError("这个 Python 没有 vgamepad")
        gamepad_class = None
        class_name = None
        for name in X360_CLASS_CANDIDATES:
            obj = getattr(vg, name, None)
            if isinstance(obj, type) or callable(obj):
                gamepad_class, class_name = obj, name
                break
        if gamepad_class is None:
            raise RuntimeError("vgamepad 里没有可用的手柄类（试过 %s）"
                               % ", ".join(X360_CLASS_CANDIDATES))
        self.pad = gamepad_class()
        self.class_name = class_name
        for bit, label in BUTTON_BITS:
            obj = _resolve(["XUSB_GAMEPAD_" + n for n in X360_NAMES.get(label, (label,))]
                           + ["XBOX_BUTTON_" + n for n in X360_NAMES.get(label, (label,))])
            if obj is None:
                self.notes.append("缺少按钮 %s（该键会被忽略）" % label)
            self.buttons[bit] = obj

    def visible(self, baseline=None):
        """X360 后端：XInput 读得到才算看得见（Steam 和大部分游戏走的就是 XInput）。"""
        seen = xinput_visible(self.xinput_slot())
        if seen is True:
            return True
        if baseline is not None:
            cur = pnp_class_devices(self.class_guid)
            if cur is not None and any(x not in baseline for x in cur):
                self.notes.append("XInput 读不到，但 PnP 里出现了新节点（设备节点在、驱动没跑起来）")
        return seen

    def apply(self, state, changed=None):
        if self.pad is None:
            return False
        dirty = False

        for bit, _label in BUTTON_BITS:
            obj = self.buttons.get(bit)
            if obj is None:
                continue
            if (state["buttons"] >> bit) & 1:
                self.pad.press_button(obj)
            else:
                self.pad.release_button(obj)
            dirty = True

        hat = state["hat"]
        if hat == 8:
            for key in X360_DPAD_KEYS:
                obj = _resolve(["XUSB_GAMEPAD_" + key, "XBOX_BUTTON_" + key])
                if obj is not None:
                    self.pad.release_button(obj)
        else:
            for key in X360_DPAD_KEYS:
                obj = _resolve(["XUSB_GAMEPAD_" + key, "XBOX_BUTTON_" + key])
                if obj is not None:
                    self.pad.release_button(obj)
            for key in X360_HAT_DPAD.get(hat, ()):
                obj = _resolve(["XUSB_GAMEPAD_" + key, "XBOX_BUTTON_" + key])
                if obj is not None:
                    self.pad.press_button(obj)

        def scale(value):
            v = int(value) * 256
            return max(-32768, min(32767, v))

        try:
            if callable(getattr(self.pad, "left_joystick", None)):
                self.pad.left_joystick(scale(state["lx"]), scale(state["ly"]))
                self.pad.right_joystick(scale(state["rx"]), scale(state["ry"]))
            else:
                # 老版本（0.3 之前）是属性，用的就是 -128..127
                self.pad.left_x, self.pad.left_y = state["lx"], state["ly"]
                self.pad.right_x, self.pad.right_y = state["rx"], state["ry"]
        except Exception as exc:
            self.notes.append("摇杆映射失败: %s" % exc)

        try:
            if callable(getattr(self.pad, "left_trigger", None)):
                self.pad.left_trigger(int(state["lt"]))
                self.pad.right_trigger(int(state["rt"]))
            else:
                self.pad.left_trigger = int(state["lt"])
                self.pad.right_trigger = int(state["rt"])
        except Exception as exc:
            self.notes.append("扳机映射失败: %s" % exc)

        if dirty:
            try:
                self.pad.update()
            except Exception as exc:
                self.notes.append("update 失败: %s" % exc)
        return True


class DS4Backend(Backend):
    kind = "DS4"
    display = "虚拟 DualShock 4 手柄（HID，Steam Input 原生认）"
    class_guid = HID_CLASS_GUID
    vid, pid = 0x054C, 0x05C4

    def create(self):
        if vg is None:
            raise RuntimeError("这个 Python 没有 vgamepad")
        cls = getattr(vg, "VDS4Gamepad", None)
        if cls is None:
            raise RuntimeError("vgamepad 里没有 VDS4Gamepad（这个版本太老）")
        self.pad = cls()
        for bit, label in BUTTON_BITS:
            name = DS4_NAMES.get(label)
            if name is None:
                continue
            obj = _resolve([name])
            if obj is None:
                self.notes.append("缺少按钮 %s（该键会被忽略）" % label)
            self.buttons[bit] = obj
        self.special = {}
        for bit, label in BUTTON_BITS:
            name = DS4_SPECIAL.get(label)
            if name:
                self.special[bit] = _resolve([name])
        self.hat_values = {}
        for hat, name in DS4_HAT.items():
            self.hat_values[hat] = _resolve([name])

    def visible(self, baseline=None):
        """DS4 后端：只有"建 target 之后新出现的节点"才算数（类里原有的同 vid/pid 条目是残留）。"""
        cur = pnp_class_devices(self.class_guid)
        if cur is None:
            return None
        key = "vid_%04x&pid_%04x" % (int(self.vid), int(self.pid))
        new = [x for x in cur if key in x.lower() and (baseline is None or x not in baseline)]
        if new:
            return True
        return False

    def apply(self, state, changed=None):
        if self.pad is None:
            return False

        for bit, _label in BUTTON_BITS:
            obj = self.buttons.get(bit)
            on = (state["buttons"] >> bit) & 1
            if obj is not None:
                if on:
                    self.pad.press_button(obj)
                else:
                    self.pad.release_button(obj)
            special = self.special.get(bit)
            if special is not None:
                if on:
                    try:
                        self.pad.press_special_button(special)
                    except Exception as exc:
                        self.notes.append("特殊按键 %d 失败: %s" % (bit, exc))
                else:
                    try:
                        self.pad.release_special_button(special)
                    except Exception as exc:
                        self.notes.append("特殊按键 %d 释放失败: %s" % (bit, exc))

        val = self.hat_values.get(state["hat"])
        if val is not None:
            try:
                self.pad.directional_pad(val)
            except Exception as exc:
                self.notes.append("十字键映射失败: %s" % exc)

        # DS4 报告里摇杆就是 int8（-128..127），和协议一致，不用放大 256 倍
        try:
            self.pad.left_joystick(int(state["lx"]), int(state["ly"]))
            self.pad.right_joystick(int(state["rx"]), int(state["ry"]))
        except Exception as exc:
            self.notes.append("摇杆映射失败: %s" % exc)

        try:
            self.pad.left_trigger(int(state["lt"]))
            self.pad.right_trigger(int(state["rt"]))
        except Exception as exc:
            self.notes.append("扳机映射失败: %s" % exc)

        try:
            self.pad.update()
        except Exception as exc:
            self.notes.append("update 失败: %s" % exc)
        return True


def pick_backend(say=None, prefer="x360"):
    """按 prefer 的顺序试后端，第一个"设备真的看得见"的胜出。返回 (backend, 说明列表)。

    注意：验证失败的后端会被拔下（close），但第一个建起来、验证不了的那个留着当 fallback，
    不然调用方拿到的就是一个已经关闭的 pad。
    """
    if vg is None:
        return None, ["没有 vgamepad（不能 pip 装；打包版要把 ViGEmClient.dll 打进包）。原因：%s"
                      % (VG_IMPORT_ERROR or "未知")]

    order = [X360Backend, DS4Backend] if prefer == "x360" else [DS4Backend, X360Backend]
    notes = []
    fallback = None

    for cls in order:
        baseline = pnp_class_devices(cls.class_guid)
        b = cls(say)
        try:
            b.create()
        except Exception as exc:
            notes.append("%s: 建 target 失败 —— %s" % (b.kind, exc))
            continue
        seen = b.visible(baseline)
        b.verified = seen
        if seen is True:
            if fallback is not None and fallback is not b:
                fallback.close()
            return b, notes
        if seen is None:
            notes.append("%s: target 建好了（玩家 %s），但验证不了设备在不在场" % (b.kind, b.index()))
        else:
            notes.append("%s: target 建好了（玩家 %s）但设备看不见 —— XInput/HID 都读不到，"
                         "Steam 也读不到（驱动那边插不上：总线节点报 Problem 31，或者虚拟设备"
                         "绑不到驱动包）" % (b.kind, b.index()))
        if fallback is None:
            fallback = b
        else:
            b.close()

    return fallback, notes



def selftest(say=print, prefer="x360"):
    """跑一遍：建手柄 -> 验证 -> 按 A + 推左摇杆 + 按 LT -> 读回来 -> 拔下。"""
    backend, notes = pick_backend(say, prefer)
    if backend is None:
        say("[自检] 没有可用后端：" + "；".join(notes))
        return None
    say("[自检] 用 %s（玩家 %s），验证结果 = %s" % (backend.display, backend.index(), backend.verified))
    for n in notes:
        say("        " + n)
    state = {"buttons": 1, "hat": 4, "lx": 100, "ly": -50, "rx": 0, "ry": 0, "lt": 128, "rt": 200}
    backend.apply(state)
    if backend.kind == "X360":
        slot = backend.xinput_slot()
        say("        XInput 玩家号：vgamepad target=%s → XInput slot=%s（0 起）" % (backend.index(), slot))
        got = xinput_read(slot)
        if got:
            code, st = got
            say("        XInput 读回：ret=%d buttons=%s L=(%d,%d) LT=%d RT=%d"
                % (code, hex(st.wButtons), st.sThumbLX, st.sThumbLY, st.bLeftTrigger, st.bRightTrigger))
    backend.close()
    return backend


if __name__ == "__main__":
    selftest()
