#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电脑端独立客户端（tkinter 窗口）：

  1) 界面只有两块卡片（照你给的那张图简化）：左边「连接」= 二维码 + 地址 + 一行说明；右边「运行信息」=
     只留必要的那几行（状态、监听、来源、收包路径、收包、速率、延迟 RTT、单程估算、输入往返、包间隔、
     电脑处理），下面一行是最近一条事件 + 没收到包时的自检。二维码内容还是 xpad://<本机IP>:<端口>，
     只用 qrcode 的模块矩阵画到 tkinter Canvas 上，不用 PIL；也可以手输或点「复制地址」：
     - Wi-Fi 这条走 UDP：手机上填这个 IP 和端口。
     - USB 这条走 ADB / hdc 隧道：只能转发 TCP，客户端启动时自动 adb reverse（找不到 adb 就 hdc rport，鸿蒙手机用 hdc），之后每 30 秒补一次，
       手机上只能填 127.0.0.1:PORT，包走 receiver.py 的 TCP 监听。两条可以同时用。
  2) 状态行按"电脑真的收到过包"写（15 秒内有包才算已连接），延迟显示 RTT 和包间隔，能看出是网络慢
     还是手机发得慢。按键状态、震动次数这些不再显示（要看在手机手柄页和下面那行事件）。
  3) 用 vgamepad（ViGEmBus 驱动）把状态映射成一个真正的 Xbox 360 虚拟手柄。

延迟怎么保证：
  - 收包 + 写虚拟手柄都在同一个后台线程里完成，UI 每 200ms 只读一次快照，不参与数据路径。
  - 手机每 2 秒发一个 ping，客户端回 pong；手机算出真实往返延迟（RTT），并在 state 包的可选字段 rtt 里带回来。
  - 界面同时显示 RTT 和包间隔（avg / max），能看出是网络慢还是手机发得慢。

用法（Windows, Python 3.10+）:
    pip install vgamepad
    pip install qrcode        # 只用 qrcode 顶层模块 + qrcode.constants，这台机器没有 PIL 也能跑
    python pc-receiver/client.py
    python pc-receiver/client.py --port 27042 --ip 192.168.1.10
    python pc-receiver/client.py --console        # 输出走命令行（仍然创建虚拟手柄，Steam 认得到）
    python pc-receiver/client.py --no-pad         # 只看运行信息、不建虚拟手柄（Steam 认不到）
    python pc-receiver/client.py --no-tcp         # 只留 UDP（关掉 ADB 隧道的 TCP 监听）
    python pc-receiver/client.py --qr-bg "#FFFFFF" --qr-ink "#111519"   # 二维码底色/墨色（十六进制）
    python pc-receiver/client.py --no-qr          # 不画二维码，只留文本地址手输
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

# 打包成 windowed 版之后本进程没有控制台：Windows 会给它启动的控制路子进程（netsh / adb / powershell）
# 新分配一个控制台窗口，于是双击 exe 会先闪几个黑窗口才出界面。CREATE_NO_WINDOW 就没窗口。
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def log_path():
    """窗口版（pyinstaller --windowed 打包后没有控制台）：消息写到 exe 旁边的 Xpad-joy.log。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "Xpad-joy.log")


def say(msg, show_console=False):
    """消息一定写进日志文件；控制台在（且 show_console）才打印。
    --windowed 打包版没有控制台，所以日志文件是唯一能看到出错信息的地方。"""
    text = str(msg)
    if show_console and sys.stdout is not None:
        try:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


# 二维码：只用 qrcode 的模块矩阵（get_matrix）自己画到 tkinter Canvas 上 ——
# 这台机器没装 PIL，所以绝对不能 import PIL，也不能调用 make_image()。
try:
    import qrcode
    import qrcode.constants
    QR_LIB_OK = True
    QR_LIB_ERR = ""
except Exception as exc:
    QR_LIB_OK = False
    QR_LIB_ERR = "%s（%s）" % (exc, type(exc).__name__)
    say("[二维码] 没有 qrcode 库（pip install qrcode），只能用文本地址手输：%s" % exc, True)

try:
    import tkinter as tk
    from tkinter import ttk
except Exception as exc:
    say("[错误] 打不开窗口：这个 Python 没有可用的 tkinter（%s）" % exc, True)
    say("       命令行版看运行信息：py -3 receiver.py（窗口版需要 tkinter）", True)
    sys.exit(1)

import receiver

BG = "#111519"
CARD = "#1B2128"
ACCENT = "#3B82F6"
INK = "#E7ECF3"
DIM = "#8A94A2"

# 二维码：底色/墨色（命令行 --qr-bg / --qr-ink，十六进制）；一个模块画 6 像素
QR_BG = "#FFFFFF"
QR_INK = "#111519"
QR_MODULE_PX = 6

# PATH 里找不到 adb 时才用这个固定位置
ADB_FALLBACK = r"D:\Android\SDK\platform-tools\adb.exe"
# 鸿蒙手机用 hdc（DevEco Studio 的 toolchains），PATH 里没有时才用这个固定位置
HDC_FALLBACK = r"D:\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe"


def render_qr(canvas, payload, bg, ink, module_px, note=None):
    """把「xpad://IP:端口」画成二维码到 tkinter Canvas 上：只用 qrcode 的模块矩阵（get_matrix），
    不 import PIL、不调 make_image()（这台机器没 PIL）。border=2 就是 quiet zone 留白，
    get_matrix() 已经把这一圈留白算进矩阵里，手机靠它才认得到码。
    成功返回矩阵边长，失败返回 None；出错只写事件区（note），不往外抛。"""
    def say(msg):
        if note:
            try:
                note(msg)
            except Exception:
                pass

    if not QR_LIB_OK:
        say("[二维码] 画不出来：没有 qrcode 库（pip install qrcode），只能用文本地址手输（%s）" % QR_LIB_ERR)
        return None
    try:
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=1, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        size = len(matrix)
        if size <= 20:
            say("[二维码] 画不出来：矩阵只有 %d 格（payload 是空的？）" % size)
            return None
        canvas.delete("all")
        canvas.config(width=size * module_px, height=size * module_px, bg=bg, highlightthickness=0)
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    canvas.create_rectangle(x * module_px, y * module_px,
                                            (x + 1) * module_px, (y + 1) * module_px,
                                            fill=ink, outline=ink)
        say("[二维码] 已画在窗口上（%s），手机扫码优先走 Google Play 服务，失败才走本机相机" % payload)
        return size
    except Exception as exc:
        say("[二维码] 画不出来：%s（%s）" % (exc, type(exc).__name__))
        return None


def add_firewall_rule(port):
    """加 Windows 防火墙入站放行规则（需要管理员权限）：UDP 和 TCP 各一条（ADB 那条只能走 TCP）。"""
    parts = []
    for proto in ("UDP", "TCP"):
        name = "Xpad-joy %s %d" % (proto, port)
        try:
            r = subprocess.run(
                ["netsh", "advfirewall", "firewall", "add", "rule",
                 "name=" + name, "dir=in", "action=allow",
                 "protocol=%s" % proto, "localport=%d" % port],
                capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW,
            )
            out = (r.stdout or "").strip() or (r.stderr or "").strip()
            if r.returncode == 0:
                parts.append("%s %d：%s" % (proto, port, out or "已添加（或规则已存在）"))
            else:
                parts.append("%s %d：返回码 %d（%s，需要管理员权限）" % (proto, port, r.returncode, out or "无输出"))
        except Exception as exc:
            parts.append("%s %d：执行失败（%s，需要管理员权限）" % (proto, port, exc))
    return " | ".join(parts)


def firewall_rule_state(port):
    """看看有没有 Xpad-joy（或旧名 Xjoy / XpadJoy）的放行规则（读取规则通常也要管理员）；UDP 和 TCP 都查。"""
    found = []
    for proto in ("UDP", "TCP"):
        hit = False
        for name in ("Xpad-joy %s %d" % (proto, port), "Xjoy %s %d" % (proto, port), "XpadJoy %s %d" % (proto, port)):
            try:
                r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=" + name],
                                   capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW)
                out = (r.stdout or "").strip()
                if r.returncode == 0 and out and "No rules match" not in out:
                    found.append("已有放行规则（%s）" % name)
                    hit = True
                    break
            except Exception as exc:
                return "读不到防火墙规则：%s（需要管理员）" % exc
        if not hit:
            found.append("没有 %s 的放行规则" % proto)
    return "；".join(found) or "没有放行规则（用下面按钮加，需要管理员）"


def detect_local_ip():
    """界面显示给手机手输的本机 IPv4（走 Wi-Fi 的 UDP 用这个）。走 ADB 时手机上填 127.0.0.1:端口，用不到这个 IP。"""
    return default_route_ip()


def default_route_ip():
    """挑一个最可能和手机同网段的本机 IPv4（只是问路由，不发任何包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def set_window_icon(root):
    """窗口和任务栏用生成的图标（tools/make_icon.py 产物 icon.ico，打包时 --add-data 带进来）；
    没有这个文件就用 Tk 默认图标，不报错。"""
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        ico = os.path.join(base, "icon.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
def find_adb():
    """先 PATH 里的 adb，再找客户端自己同目录（安装引导会把 adb 复制到安装位置），再试
    D:\\Android\\SDK\\platform-tools\\adb.exe；都没有返回 None。"""
    found = shutil.which("adb")
    if found:
        return found
    own = os.path.join(os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                       else os.path.dirname(os.path.abspath(__file__)), "adb.exe")
    if os.path.isfile(own):
        return own
    if os.path.isfile(ADB_FALLBACK):
        return ADB_FALLBACK
    return None


def find_hdc():
    """先 PATH 里的 hdc，再试 DevEco Studio 的 toolchains（鸿蒙手机用 hdc，不是 adb）。"""
    found = shutil.which("hdc")
    if found:
        return found
    if os.path.isfile(HDC_FALLBACK):
        return HDC_FALLBACK
    return None


def run_port_forward(port):
    """先试 adb reverse（安卓），没有 adb 再试 hdc rport（鸿蒙）。两条方向一样：手机上的
    127.0.0.1:PORT 转到电脑。结果写成一行给事件区。"""
    adb_msg = ""
    adb = find_adb()
    if adb:
        try:
            r = subprocess.run([adb, "reverse", "tcp:%d" % port, "tcp:%d" % port],
                               capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
            out = (r.stdout or "").strip() or (r.stderr or "").strip()
            if r.returncode == 0:
                return "adb reverse tcp:%d tcp:%d 已执行（%s）；手机上填 127.0.0.1:%d（adb=%s）" % (port, port, out or "无输出", port, adb)
            adb_msg = "adb 返回码 %d：%s" % (r.returncode, out or "无输出")
        except Exception as exc:
            adb_msg = "adb 执行失败：%s" % exc
    else:
        adb_msg = "没找到 adb"
    hdc = find_hdc()
    if not hdc:
        return "%s，也没找到 hdc：手动跑 hdc rport tcp:%d tcp:%d" % (adb_msg, port, port)
    try:
        r = subprocess.run([hdc, "rport", "tcp:%d" % port, "tcp:%d" % port],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        if r.returncode == 0:
            return "hdc rport tcp:%d tcp:%d 已执行（%s）；鸿蒙手机上填 127.0.0.1:%d（hdc=%s）" % (port, port, out or "无输出", port, hdc)
        return "hdc 返回码 %d：%s（adb 那条：%s）" % (r.returncode, out or "无输出", adb_msg)
    except Exception as exc:
        return "hdc 执行失败：%s（adb 那条：%s）" % (exc, adb_msg)


class GuiClient(receiver.Receiver):
    """复用 receiver.py 的协议与映射，只把运行信息搬到界面上。"""

    def __init__(self, port, ip, force_console=False, no_pad=False, prefer_backend="x360"):
        super().__init__(port, force_console, 10.0, no_pad, prefer_backend)
        self.ip = ip
        self.status = "等待手机连接"
        self.lazy_pad = True     # 收到第一帧才创建虚拟手柄

    def note(self, msg):
        self.events.append(msg)
        if len(self.events) > 8:
            del self.events[0]
        # 窗口版（打包后没有控制台）：界面上只显示最近 8 条，完整的一份写进日志文件
        say(msg, getattr(self, "log_console", False))

    def on_bound(self):
        """本地回环自检：能收到自己发的包说明监听没问题，问题就在防火墙或手机网段。
        放到另一个线程：run() 的接收循环要在这之后才跑，否则 pong 回不来。"""
        def probe_udp():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2.0)
            try:
                s.sendto(json.dumps({"t": "selftest", "ts": 0}).encode("utf-8"), ("127.0.0.1", self.port))
                s.recvfrom(256)
                self.note("UDP 自检 OK：本地回环收得到 → 监听正常；收不到手机包就是防火墙或手机网段问题")
            except Exception as exc:
                self.note("UDP 自检失败：%s（连本地包都收不到，端口可能被别的程序占着）" % exc)
            finally:
                s.close()
        threading.Thread(target=probe_udp, daemon=True).start()

        def probe_tcp():
            """TCP 回环：按帧格式（2 字节大端长度 + payload）发一个 selftest，看能不能收到 pong。"""
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            try:
                s.connect(("127.0.0.1", self.port))
                msg = json.dumps({"t": "selftest", "ts": 0}).encode("utf-8")
                s.sendall(len(msg).to_bytes(2, "big") + msg)
                head = s.recv(2)
                if len(head) < 2:
                    self.note("TCP 自检失败：没读到 2 字节帧长度")
                    return
                n = int.from_bytes(head, "big")
                body = b""
                while len(body) < n:
                    chunk = s.recv(n - len(body))
                    if not chunk:
                        break
                    body += chunk
                obj = json.loads(body.decode("utf-8", "ignore"))
                if isinstance(obj, dict) and obj.get("t") == "pong":
                    self.note("TCP 自检 OK：帧格式（2 字节大端长度 + payload）收发正常，ADB 走的就是这条")
                else:
                    self.note("TCP 自检：收到 %s（不是 pong）" % body)
            except Exception as exc:
                self.note("TCP 自检失败：%s（TCP 监听没起来，--no-tcp 时不做这条）" % exc)
            finally:
                s.close()

        if self.tcp_enabled:
            threading.Thread(target=probe_tcp, daemon=True).start()


def adapter_power_save():
    """查一下活动网卡的省电设置：省电开着，包会被攒到下一次唤醒才发，Wi-Fi 延迟就是这么来的。"""
    cmd = (
        "$n = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | "
        "Where-Object { $_.PhysicalMediaType -eq 802.11 } | Select-Object -First 1; "
        "if (-not $n) { '没有活动的无线网卡（走 ADB 隧道/有线，这条跳过）'; return } "
        "$p = Get-NetAdapterAdvancedProperty -Name $n.Name -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DisplayName -match 'Power' }; "
        "if (-not $p) { $n.Name + ': 驱动不暴露省电项（读不到）'; return } "
        "$n.Name + ': ' + (($p | ForEach-Object { $_.DisplayName + '=' + $_.DisplayValue }) -join '; ')"
    )
    try:
        return subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", cmd], text=True, timeout=8,
            creationflags=NO_WINDOW).strip() or "读不到"
    except Exception as exc:
        return "读不到网卡省电设置（%s）" % exc


def main():
    ap = argparse.ArgumentParser(description="Xpad-joy 电脑客户端：连接地址 + ADB 隧道 + 运行信息 + 虚拟 Xbox 手柄")
    ap.add_argument("--port", type=int, default=receiver.DEFAULT_PORT, help="监听端口，UDP 和 TCP 都用它（默认 %d）" % receiver.DEFAULT_PORT)
    ap.add_argument("--ip", default=None, help="界面显示的电脑 IP（默认自动检测本机 IPv4；走 ADB 时手机上填 127.0.0.1）")
    ap.add_argument("--console", action="store_true", help="输出走命令行（仍然会创建虚拟手柄，Steam 能认到）")
    ap.add_argument("--no-pad", action="store_true", help="不创建虚拟手柄、只看打印（Steam 看不到手柄）")
    ap.add_argument("--no-tcp", action="store_true", help="只留 UDP：不监听 TCP（ADB 只能转发 TCP，所以这条关掉就走不了 ADB）")
    ap.add_argument("--no-ack", action="store_true", help="不回 ack：少一半回包（代价是测不了输入路径往返）")
    ap.add_argument("--qr-bg", default=QR_BG, help="二维码底色（十六进制，默认 %s）" % QR_BG)
    ap.add_argument("--qr-ink", default=QR_INK, help="二维码墨色（十六进制，默认 %s）" % QR_INK)
    ap.add_argument("--no-qr", action="store_true", help="不画二维码，只留文本地址（没有 qrcode 库时也只能这样）")
    ap.add_argument("--backend", choices=("x360", "ds4"), default="x360",
                    help="虚拟手柄后端：x360（XInput，默认）或 ds4（HID，Steam Input 原生认）；"
                         "X360 验证不过会自动退到 DS4")
    args = ap.parse_args()

    ip = args.ip or detect_local_ip()
    client = GuiClient(args.port, ip, force_console=args.console, no_pad=args.no_pad,
                       prefer_backend=args.backend)
    client.ack_enabled = not args.no_ack
    client.tcp_enabled = not args.no_tcp
    payload = "xpad://%s:%d" % (ip, args.port)
    fw_state = firewall_rule_state(args.port)

    # receiver.py 的打印送进界面（界面上只显示最近 8 条）；完整的一份由 note() 写进日志文件
    def emit(msg):
        client.note(msg)

    client.log_console = args.console
    receiver.p = emit

    receiver.p = emit

    def worker():
        # lazy_pad：启动时不创建设备，收到第一帧才创建（否则 Steam 一进客户端就显示手柄已连接）
        try:
            if not client.lazy_pad:
                client.init_gamepad()
            client.status = "监听 UDP + TCP 0.0.0.0:%d" % client.port if client.tcp_enabled else "监听 UDP 0.0.0.0:%d" % client.port
            code = client.run()
        except Exception as exc:
            client.note("[错误] 接收线程出错：%s（%s）" % (exc, type(exc).__name__))
            code = 1
        if code:
            client.status = "启动失败：端口被占用或权限不足"
            # 端口被占：八成是还有一个客户端窗口在跑（那个才是收包的）
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(1.5)
            try:
                probe.connect(("127.0.0.1", client.port))
                client.note("127.0.0.1:%d 连得上 → 这个端口上还有一个程序在监听（多半是旧的客户端窗口没关）：关掉那个窗口再开这个" % client.port)
            except Exception:
                pass
            finally:
                probe.close()

    threading.Thread(target=worker, daemon=True).start()

    def probe():
        client.note("[网卡省电] %s（开着 = 包会被攒到下一次唤醒才发；要低延迟只能走 ADB 隧道/有线，或在设备管理器里把这项关掉）" % adapter_power_save())

    threading.Thread(target=probe, daemon=True).start()

    try:
        root = tk.Tk()
    except Exception as exc:
        say("[错误] 打不开窗口（tkinter）：%s（%s）" % (exc, type(exc).__name__), True)
        say("       这台机器的 Python 没有可用的 tkinter：只能看命令行版 → py -3 client.py --console", True)
        client.running = False
        return 1
    root.title("Xpad-joy 电脑客户端")
    set_window_icon(root)
    root.configure(bg=BG)
    root.minsize(600, 380)

    # 界面简化（照你给的那张图）：左边一个「连接」卡片 = 二维码 + 地址 + 一行说明；
    # 右边一个「运行信息」卡片 = 只留必要的那几行（状态 / 来源 / 收包 / 速率 / 延迟 / 处理）。
    top = tk.Frame(root, bg=BG)
    top.pack(fill=tk.X, padx=12, pady=(12, 6))

    left = tk.Frame(top, bg=CARD)
    left.pack(side=tk.LEFT, fill=tk.BOTH)
    tk.Label(left, text="连接", bg=CARD, fg=ACCENT, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
    qr_canvas = tk.Canvas(left, bg=args.qr_bg, highlightthickness=0)
    qr_canvas.pack(anchor="w", padx=8, pady=(0, 6))
    url_label = tk.Label(left, text=payload, bg=CARD, fg=ACCENT, font=("Consolas", 12), wraplength=250)
    url_label.pack(anchor="w", padx=8)
    qr_caption = tk.Label(left, text="", bg=CARD, fg=DIM, wraplength=250)
    qr_caption.pack(anchor="w", padx=8, pady=(4, 8))

    def draw_qr():
        """按当前 payload（xpad://IP:端口）重画二维码；--no-qr 或者没有 qrcode 库就只留文本地址。"""
        if args.no_qr:
            qr_caption.config(text="（--no-qr：不画二维码，只用文本地址手输）")
            return
        size = render_qr(qr_canvas, payload, args.qr_bg, args.qr_ink, QR_MODULE_PX, note=client.note)
        if size:
            qr_caption.config(text="手机扫这个码：走 Wi-Fi 用上面这个地址；走 ADB 只能 127.0.0.1:%d。"
                                 "扫码优先请求 Google Play 服务（MLS），失败才回退手机相机。" % args.port)
        elif not QR_LIB_OK:
            qr_caption.config(text="没有 qrcode 库（pip install qrcode），只能用文本地址手输")
        else:
            qr_caption.config(text="二维码画不出来（原因看下面那行），先用文本地址手输")

    draw_qr()

    right = tk.Frame(top, bg=CARD)
    right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
    tk.Label(right, text="运行信息", bg=CARD, fg=ACCENT, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
    # grid 和 pack 不能混在同一个容器里：标题用 pack，表格单独放一个用 grid 的子 frame
    table = tk.Frame(right, bg=CARD)
    table.pack(fill=tk.X, padx=8, pady=(0, 8))
    # 运行信息只留 5 行：状态 / 来源 / 收包 / 输入往返 / 按键检测（按下时显示名字，用来确认输入对得上）
    rows = [
        ("状态", "status"), ("来源", "source"), ("收包", "packets"),
        ("输入往返（手机→电脑→手机）", "input"), ("按键检测", "buttons"),
    ]
    labels = {}
    for i, (title, key) in enumerate(rows):
        tk.Label(table, text=title, bg=CARD, fg=DIM).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=2)
        value = tk.Label(table, text="-", bg=CARD, fg=INK, font=("Consolas", 11))
        value.grid(row=i, column=1, sticky="w", pady=2)
        labels[key] = value

    # 只留必要的那两行：没收到包时的自检 + 最近一条事件（长段说明按你的要求删了）
    hint = tk.Label(root, text="", bg=BG, fg=DIM, wraplength=520, anchor="w")
    hint.pack(fill=tk.X, padx=12, pady=(6, 0))
    event_line = tk.Label(root, text="", bg=BG, fg=DIM, wraplength=520, anchor="w")
    event_line.pack(fill=tk.X, padx=12, pady=(4, 0))

    def copy_url():
        root.clipboard_clear()
        root.clipboard_append(payload)
        client.note("地址已复制到剪贴板（走 ADB 填 127.0.0.1:%d）" % args.port)

    def regen():
        nonlocal ip, payload
        ip = detect_local_ip()
        payload = "xpad://%s:%d" % (ip, args.port)
        url_label.config(text=payload)
        draw_qr()

    def redraw_qr():
        draw_qr()

    def port_forward():
        def go():
            msg = run_port_forward(args.port)
            client.note("[转发] %s" % msg)
            if args.console:
                print("[转发] %s" % msg)
        threading.Thread(target=go, daemon=True).start()

    def firewall():
        client.note("[防火墙] %s" % add_firewall_rule(client.port))

    def test_rumble():
        # 只能测"这条链路通不通"，测的是手动发的包；游戏里的震动要靠 ViGEmBus 回调（下面那条注册）
        client.queue_rumble(200, 200, "按钮")
        client.note("已发测试震动（200/200）：手机收到才会震；手机那边看 adb logcat -s XjoyLink")

    buttons = tk.Frame(root, bg=BG)
    buttons.pack(fill=tk.X, padx=12, pady=(0, 10))
    for text, command in (("复制地址", copy_url), ("重新检测 IP", regen), ("重画二维码", redraw_qr),
                          ("执行 adb/hdc 转发", port_forward), ("测试手机震动", test_rumble),
                          ("添加防火墙放行(UDP+TCP)", firewall)):
        tk.Button(buttons, text=text, bg=CARD, fg=INK, activebackground=ACCENT,
                  activeforeground=INK, relief=tk.FLAT, command=command).pack(side=tk.LEFT, padx=(0, 6))

    def keep_tunnel():
        # 开机自动跑一次 adb reverse（安卓）/ hdc rport（鸿蒙），之后每 30 秒补一次
        # （adb / hdc 服务重启会把转发清掉）
        if find_adb() or find_hdc():
            port_forward()
        root.after(30000, keep_tunnel)

    keep_tunnel()

    def refresh():
        try:
            prev = client.prev or {}
            src = "%s:%d" % (client.last_sender[0], client.last_sender[1]) if client.last_sender else "-"
            age = (time.time() - client._last_rx_time) if client._last_rx_time else -1.0
            online = 0 <= age <= 15
            labels["status"].config(text="已连接（最近 %.1f 秒前，走 %s）" % (age, client.via) if online
                                    else "未连接（15 秒内没收到包）")
            labels["source"].config(text=src)
            labels["packets"].config(text="%d（无效 %d · ping %d）" % (client.packet_count, client.invalid_count, client.ping_count))
            labels["input"].config(text="%d ms" % client.input_rtt if client.input_rtt >= 0 else "-")
            pressed = [name for bit, name in receiver.BUTTON_BITS if prev and (prev["buttons"] >> bit) & 1]
            detect = ", ".join(pressed) if pressed else "-"
            if not pressed and prev:
                # 没按下按键时，把动过的十字键 / 摇杆 / 扳机也写出来，方便确认输入对得上
                parts = []
                if prev.get("hat", 8) != 8:
                    parts.append("十字键=%d" % prev.get("hat", 8))
                if prev.get("lx") or prev.get("ly"):
                    parts.append("左(%d,%d)" % (prev.get("lx", 0), prev.get("ly", 0)))
                if prev.get("rx") or prev.get("ry"):
                    parts.append("右(%d,%d)" % (prev.get("rx", 0), prev.get("ry", 0)))
                if prev.get("lt"):
                    parts.append("LT %d%%" % int(prev.get("lt", 0) * 100 / 255))
                if prev.get("rt"):
                    parts.append("RT %d%%" % int(prev.get("rt", 0) * 100 / 255))
                if parts:
                    detect = " ".join(parts)
            labels["buttons"].config(text=detect)
            hint.config(text="" if online else
                        "还没收到包：①手机与电脑同一网段（不是移动数据）②防火墙（%s）③端口一致（%d）"
                        "④走 USB 隧道只能 127.0.0.1，并且电脑已经 adb reverse（安卓）或 hdc rport（鸿蒙）" % (fw_state, client.port))
            recent = list(client.events)
            event_line.config(text=recent[-1] if recent else "-")
        except Exception as exc:
            event_line.config(text="[界面刷新出错] %s（%s）" % (exc, type(exc).__name__))
        root.after(200, refresh)

    refresh()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    client.running = False
    client.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
