#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xpad-joy 电脑客户端 安装引导（窗口版，中文界面）

跑源代码：  py -3 installer.py
打包（和 打包安装引导.bat 里一致）：
  py -3 -m PyInstaller --onefile --windowed --name Xpad-joy-Installer ^
      --add-data "Xpad-joy.exe;." --add-data "vendor/ViGEmBus_1.22.0_x64_x86_arm64.exe;." installer.py

界面只有：驱动状态、安装位置（可选）、桌面快捷方式勾选项、安装 / 退出 两个按钮、日志区。
点「安装」就做三件事：
  1) 把客户端 Xpad-joy.exe 复制到安装位置（+ 安装说明.txt）；
  2) 勾了「桌面快捷方式」才建桌面 .lnk（用 PowerShell 的 WScript.Shell COM）；
  3) 检测不到 ViGEmBus 驱动时，静默跑内置的驱动安装程序。
卸载用另一个程序：uninstaller.py / Xpad-joy-Uninstaller.exe（只删我们自己放进去的文件和桌面
快捷方式，不碰驱动）。不 pip install 任何东西，也不联网：驱动安装程序是打包时打进 exe 的
（官方 nefarius/ViGEmBus release v1.22.0 的 ViGEmBus_1.22.0_x64_x86_arm64.exe，SHA256 见 README）。
不强制管理员：只有装驱动那一步需要，非管理员时弹一次 UAC。
"""

import argparse
import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

# 引导本身是 windowed（没有控制台）：子进程（sc / powershell / 驱动安装程序）不能再闪黑窗口
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

DRIVER_SERVICE = "ViGEmBus"
DRIVER_FILE = "ViGEmBus_1.22.0_x64_x86_arm64.exe"
CLIENT_EXE = "Xpad-joy.exe"
BUILD_STAMP = "2026-11-27-C（日志首行写版本号 + InstallLocation 和 UninstallString 都用反斜杠）"
UNINSTALLER_EXE = "Xpad-joy-Uninstaller.exe"
SHORTCUT_NAME = "Xpad-joy.lnk"
INFO_FILE = "安装信息.txt"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Xpad-joy"
PORT = 27042
# 走 USB（ADB 隧道）那条要 adb：打包时把 platform-tools 里的这三个文件打进 exe，安装时复制到安装位置
ADB_FILES = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
ADB_DIR = "platform-tools"
ADB_FALLBACK = r"D:\Android\SDK\platform-tools\adb.exe"

BG = "#111519"
CARD = "#1B2128"
ACCENT = "#3B82F6"
INK = "#E8EDF2"
MUTED = "#8A94A0"
OK = "#3FBF7F"
BAD = "#E0565C"

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as exc:
    try:
        print("[错误] 打不开窗口：这个 Python 没有可用的 tkinter（%s）" % exc)
    except Exception:
        pass
    sys.exit(1)

try:
    import winreg
except Exception:
    winreg = None


def res_path(name):
    """打包后从 PyInstaller 的临时解压目录取内置文件；跑源代码时从脚本目录取（驱动包在 vendor 目录里）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(base, name), os.path.join(base, "vendor", name)):
        if os.path.exists(cand):
            return cand
    return os.path.join(base, name)


def set_window_icon(root):
    """窗口和任务栏用生成的图标（tools/make_icon.py 产物 icon.ico，打包时 --add-data 带进来）；
    没有这个文件就用 Tk 默认图标，不报错。"""
    try:
        ico = res_path("icon.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass


def ps_quote(value):
    """把路径写成 PowerShell 里的单引号字符串（单引号翻倍）。"""
    return "'" + str(value).replace("'", "''") + "'"


def write_uninstall_info(install_dir):
    """登记到 HKCU 的"应用和功能"（普通用户就能写）：卸载程序靠这条认安装位置。"""
    if winreg is None:
        return "这个 Python 没有 winreg，没登记（卸载程序靠目录和快捷方式认位置）"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Xpad-joy 电脑客户端")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0")
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Xpad-joy")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, os.path.normpath(install_dir))
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ,
                              os.path.normpath(os.path.join(install_dir, UNINSTALLER_EXE)))
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, os.path.join(install_dir, CLIENT_EXE))
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        return "已登记（HKCU\\%s）" % UNINSTALL_KEY
    except Exception as exc:
        return "登记失败：%s（不影响卸载，靠目录和快捷方式也能认位置）" % exc


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def log_file():
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "Xpad-joy-Installer.log")


def out(msg, write_log=True):
    """控制台在就打印；windowed 打包版没有控制台，所以写日志文件（--check 也能看到结果）。"""
    text = str(msg)
    if sys.stdout is not None:
        try:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    if write_log:
        try:
            with open(log_file(), "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass


def run(args, timeout=60):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
        result = (r.stdout or "").strip() or (r.stderr or "").strip()
        return r.returncode, result
    except Exception as exc:
        return 1, "执行失败：%s" % exc


def find_adb(extra_dir=""):
    """PATH 里的 adb → 安装位置里我们放进去的 adb → 本机 SDK 的固定位置；都没有返回空。"""
    found = shutil.which("adb")
    if found:
        return found
    for cand in (os.path.join(extra_dir, "adb.exe") if extra_dir else "",
                 res_path(os.path.join(ADB_DIR, "adb.exe")), ADB_FALLBACK):
        if cand and os.path.exists(cand):
            return cand
    return ""


def adb_devices(adb, timeout=30):
    return run([adb, "devices"], timeout=timeout)


def pnp_android(limit=8):
    """用 Get-PnpDevice 看现在插着的 Android/ADB 设备和有问题码的设备（读不到就返回空，不弹窗口）。"""
    cmd = ("$ErrorActionPreference='SilentlyContinue'; "
           "$a = Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'Android|ADB' }; "
           "if ($a) { $a | ForEach-Object { '插着的设备：{0} | 状态={1} | 问题={2} | 类={3}' -f $_.FriendlyName, "
           "$_.Status, $_.Problem, $_.Class } } else { '现在没插着 Android/ADB 设备（插上线、手机开 USB 调试再看）' }; "
           "$p = Get-PnpDevice -PresentOnly | Where-Object { $_.Problem -and $_.Problem -ne 'CM_PROB_PHANTOM' } "
           "| Select-Object -First %d; "
           "if ($p) { '有问题的设备：' + (($p | ForEach-Object { '{0}（{1}）' -f $_.FriendlyName, $_.Problem }) -join '; ') } "
           "else { '插着的设备里没有问题设备（驱动都正常）' }" % limit)
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=60)


def adb_lines(msg):
    """adb devices 的输出里真正的设备行（跳过表头和空行）。"""
    return [l for l in (msg or "").replace("\r", "").split("\n")
            if l.strip() and not l.startswith("*") and "List of devices" not in l]


def make_shortcut(lnk_path, target, workdir, description):
    cmd = (
        "$sh = New-Object -ComObject WScript.Shell; "
        "$lnk = $sh.CreateShortcut(%s); "
        "$lnk.TargetPath = %s; "
        "$lnk.WorkingDirectory = %s; "
        "$lnk.Description = %s; "
        "$lnk.Save()"
    ) % (ps_quote(lnk_path), ps_quote(target), ps_quote(workdir), ps_quote(description))
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=30)


def driver_info():
    """返回 {installed, state, starttype, imagepath, driverfile, how}。"""
    info = {"installed": False, "state": "", "starttype": "", "imagepath": "",
            "driverfile": "", "how": ""}
    start_types = {0: "系统引导", 1: "系统", 2: "自动", 3: "手动", 4: "禁用"}
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Services\%s" % DRIVER_SERVICE) as key:
                info["installed"] = True
                info["how"] = "注册表服务键"
                try:
                    info["imagepath"] = winreg.QueryValueEx(key, "ImagePath")[0]
                except Exception:
                    pass
                try:
                    info["starttype"] = start_types.get(winreg.QueryValueEx(key, "Start")[0], "?")
                except Exception:
                    pass
        except FileNotFoundError:
            info["how"] = "注册表里没有 ViGEmBus 服务键"
        except Exception as exc:
            info["how"] = "注册表读失败（%s）" % exc

    # sc query 拿运行状态：驱动装了但没启动时，注册表也在，所以两步都要
    code, msg = run(["sc", "query", DRIVER_SERVICE], timeout=20)
    if code == 0 and msg:
        for row in msg.replace("\r", "").split("\n"):
            if "STATE" in row and ":" in row:
                word = row.split(":", 1)[1].strip()
                info["state"] = {"4": "运行中", "1": "已停止", "2": "启动中", "3": "停止中"}.get(word.split()[0], word)
        if not info["installed"]:
            info["installed"] = True
            info["how"] = "sc query（注册表没读到，但服务存在）"
    elif not info["installed"]:
        info["state"] = "sc query 说服务不存在"

    drv = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "%s.sys" % DRIVER_SERVICE)
    if os.path.exists(drv):
        info["driverfile"] = drv
    return info


def readme_text(install_dir, driver):
    lines = [
        "Xpad-joy 电脑客户端",
        "安装位置：%s" % install_dir,
        "",
        "1. 双击 Xpad-joy.exe（只有 GUI 窗口，没有黑窗口）。运行信息和出错信息会写进"
        "同目录的 Xpad-joy.log。",
        "2. 第一次跑要放行防火墙（客户端界面里有按钮，UDP + TCP %d）。" % PORT,
        "3. 走 USB 时手机只能连 TCP：先跑 adb reverse tcp:%d tcp:%d（客户端启动时自动跑一次，"
        "之后每 30 秒补一次），手机上填 127.0.0.1:%d。走 Wi-Fi 手机上填这台电脑的 IP。" % (PORT, PORT, PORT),
        "4. 走 USB 还要手机驱动：安装时检测过（adb devices + 设备管理器）。adb devices 里看不到设备就是"
        "驱动或线的问题：插上线、手机开 USB 调试、换数据线；Windows 10/11 一般自动给 ADB 设备装 WinUSB，"
        "厂商手机要装厂商驱动。PATH 里没有 adb 时，客户端会找安装位置里这份 adb.exe。",
        "5. 虚拟手柄要靠 ViGEmBus 驱动：%s" % ("本机已装（%s）" % (driver.get("state") or "已安装")),
        "   没驱动时客户端其它部分照常，只是游戏里看不到手柄。",
        "   要重装驱动：https://github.com/nefarius/ViGEmBus/releases（v1.22.0，要管理员）。",
        "6. 卸载：双击同目录的 Xpad-joy-Uninstaller.exe（它会自己认安装位置，不用你选）—— 删我们放进去的"
        "文件（含 adb 那三个）、桌面快捷方式和注册表里那条登记；界面里勾了「卸载 ViGEmBus 驱动」才会动驱动"
        "（要管理员、弹一次 UAC）；它也会把自己和空目录删掉（靠一条临时副本收尾）。",
        "",
        "手机端（App）不在这里装：装 APK 或用扫码连接。",
    ]
    return "\n".join(lines) + "\n"


class Installer:
    def __init__(self, root):
        self.root = root
        self.log_lines = []
        self.q = queue.Queue()
        self.driver = driver_info()
        self.install_dir = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Xpad-joy")
        self.desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self._build_ui()
        self.on_main(self.pump)
        self.log("检测：%s" % ("已装 ViGEmBus" if self.driver["installed"] else "没装 ViGEmBus"))
        for key in ("state", "starttype", "imagepath", "driverfile", "how"):
            if self.driver.get(key):
                self.log("  %s = %s" % (key, self.driver[key]))
        arch = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "?"
        self.log("  系统架构 = %s（驱动包是 x64/x86/arm64 通用包）" % arch)

    def _build_ui(self):
        self.root.title("Xpad-joy 安装引导")
        set_window_icon(self.root)
        self.root.configure(bg=BG)
        self.root.minsize(680, 420)

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill=tk.X, padx=12, pady=(12, 6))
        tk.Label(head, text="Xpad-joy 电脑客户端 安装引导", bg=BG, fg=INK,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side=tk.LEFT)
        self.driver_label = tk.Label(head, text="", bg=BG, fg=(OK if self.driver["installed"] else BAD),
                                     font=("Microsoft YaHei UI", 11, "bold"))
        self.driver_label.pack(side=tk.RIGHT)
        self._show_driver()

        row = tk.Frame(self.root, bg=BG)
        row.pack(fill=tk.X, padx=12, pady=(4, 6))
        tk.Label(row, text="安装位置", bg=BG, fg=MUTED).pack(side=tk.LEFT)
        self.dir_entry = tk.Entry(row, bg=CARD, fg=INK, relief=tk.FLAT, width=52)
        self.dir_entry.insert(0, self.install_dir)
        self.dir_entry.pack(side=tk.LEFT, padx=(8, 6))
        tk.Button(row, text="浏览…", bg=CARD, fg=INK, activebackground=ACCENT, activeforeground=INK,
                  relief=tk.FLAT, command=self.browse).pack(side=tk.LEFT)

        opts = tk.Frame(self.root, bg=BG)
        opts.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.var_desktop = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text="桌面快捷方式", variable=self.var_desktop, bg=BG, fg=INK,
                       activebackground=BG, activeforeground=INK, selectcolor=CARD).pack(side=tk.LEFT)

        opts2 = tk.Frame(self.root, bg=BG)
        opts2.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.var_adb = tk.BooleanVar(value=True)
        tk.Checkbutton(opts2, text="adb（走 USB 那条要用）：复制到安装位置 + 检测手机驱动",
                       variable=self.var_adb, bg=BG, fg=INK, activebackground=BG, activeforeground=INK,
                       selectcolor=CARD).pack(side=tk.LEFT)

        status = tk.Frame(self.root, bg=BG)
        status.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.status_label = tk.Label(status, text="", bg=BG, fg=INK, font=("Microsoft YaHei UI", 12, "bold"))
        self.status_label.pack(side=tk.LEFT)
        self.set_status("状态：就绪（点 安装 就装）")

        buttons = tk.Frame(self.root, bg=BG)
        buttons.pack(fill=tk.X, padx=12, pady=(2, 8))
        self.install_button = tk.Button(buttons, text="安装", bg=ACCENT, fg=INK, activebackground=CARD,
                                        activeforeground=INK, relief=tk.FLAT, width=10, command=self.start_install)
        self.install_button.pack(side=tk.LEFT)
        tk.Button(buttons, text="退出", bg=CARD, fg=INK, activebackground=ACCENT, activeforeground=INK,
                  relief=tk.FLAT, width=10, command=self.quit).pack(side=tk.LEFT, padx=(8, 0))

        box = tk.Frame(self.root, bg=CARD)
        box.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.text = tk.Text(box, bg=CARD, fg=INK, relief=tk.FLAT, height=15, wrap=tk.WORD,
                            font=("Consolas", 10))
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 4), pady=8)
        bar = tk.Scrollbar(box)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=bar.set)
        bar.configure(command=self.text.yview)

    def set_status(self, text, color=None):
        self.status_label.config(text=text, fg=(color or INK))

    def log(self, msg):
        # 只在 Tk 主线程里写界面；其它线程用 log_async（写队列，主线程 pump 出来）
        self.log_lines.append(str(msg))
        out(msg)
        try:
            self.text.insert(tk.END, str(msg) + "\n")
            self.text.see(tk.END)
        except Exception:
            pass

    def log_async(self, msg):
        self.q.put(str(msg))

    def on_main(self, fn):
        try:
            self.root.after(0, fn)
        except RuntimeError:
            fn()   # 没在 mainloop 里（脚本直接调用）时就地执行

    def pump(self):
        try:
            while True:
                self.log(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self.pump)

    def _show_driver(self):
        text = ("ViGEmBus 驱动：已装（%s）" % (self.driver.get("state") or "状态未知")
                if self.driver["installed"] else "ViGEmBus 驱动：未检测到")
        self.driver_label.config(text=text, fg=(OK if self.driver["installed"] else BAD))

    def set_dir(self, value):
        self.dir_entry.delete(0, tk.END)
        self.dir_entry.insert(0, value)

    def browse(self):
        picked = filedialog.askdirectory(initialdir=self.dir_entry.get() or self.install_dir,
                                         title="选一个安装位置")
        if picked:
            self.set_dir(picked)

    def target_dir(self):
        return (self.dir_entry.get() or "").strip() or self.install_dir

    def recheck(self):
        self.driver = driver_info()
        self.on_main(self._show_driver)

    def start_install(self):
        target = self.target_dir()
        desktop = self.var_desktop.get()
        adb = self.var_adb.get()
        self.install_button.config(state=tk.DISABLED, text="安装中…")
        self.set_status("状态：安装中…")
        self.on_main(lambda: self.log("[安装] 开始 → %s（桌面快捷方式：%s；adb/驱动检测：%s）"
                                      % (target, "要建" if desktop else "不建", "要跑" if adb else "不跑")))
        threading.Thread(target=self.install, args=(target, desktop, adb), daemon=True).start()

    def install(self, target, desktop, adb=True):
        self.log_async("[版本] 安装引导 %s" % BUILD_STAMP)
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as exc:
            self.log_async("[安装] 建目录失败：%s（换一个位置或手动建）" % exc)
            self.on_main(lambda: self.set_status("状态：安装失败（建不了这个目录）", BAD))
            self.on_main(lambda: self.install_button.config(state=tk.NORMAL, text="安装"))
            return
        src_exe = res_path(CLIENT_EXE)
        if not os.path.exists(src_exe):
            self.log_async("[安装] 找不到内置的 %s（打包时没 --add-data）" % CLIENT_EXE)
            self.on_main(lambda: self.install_button.config(state=tk.NORMAL, text="安装"))
            return
        try:
            shutil.copy2(src_exe, os.path.join(target, CLIENT_EXE))
            self.log_async("[安装] %s → %s" % (CLIENT_EXE, os.path.join(target, CLIENT_EXE)))
        except Exception as exc:
            self.log_async("[安装] 复制客户端失败：%s" % exc)
            self.on_main(lambda: self.set_status("状态：安装失败（复制不了客户端）", BAD))
            self.on_main(lambda: self.install_button.config(state=tk.NORMAL, text="安装"))
            return
        try:
            with open(os.path.join(target, "安装说明.txt"), "w", encoding="utf-8") as f:
                f.write(readme_text(target, self.driver))
            self.log_async("[安装] 安装说明.txt 已写入")
        except Exception as exc:
            self.log_async("[安装] 写安装说明失败：%s" % exc)

        src_un = res_path(UNINSTALLER_EXE)
        if os.path.exists(src_un):
            try:
                shutil.copy2(src_un, os.path.join(target, UNINSTALLER_EXE))
                self.log_async("[安装] 卸载程序也放在安装目录里了：%s" % os.path.join(target, UNINSTALLER_EXE))
            except Exception as exc:
                self.log_async("[安装] 复制卸载程序失败：%s" % exc)
        else:
            self.log_async("[安装] 引导里没有内置卸载程序（先跑 打包卸载程序.bat，再打包引导）")

        try:
            with open(os.path.join(target, INFO_FILE), "w", encoding="utf-8") as f:
                f.write("Xpad-joy 电脑客户端 安装信息\n"
                        "安装位置：%s\n"
                        "装的时间：%s\n"
                        "卸载：同目录的 %s（它靠这个目录、注册表或桌面快捷方式认安装位置）\n"
                        "注册表：HKCU\\%s\n" % (target, time.strftime("%Y-%m-%d %H:%M:%S"),
                                                UNINSTALLER_EXE, UNINSTALL_KEY))
            self.log_async("[安装] 安装信息.txt 已写入")
        except Exception as exc:
            self.log_async("[安装] 写安装信息失败：%s" % exc)
        self.log_async("[安装] 应用和功能里登记：%s" % write_uninstall_info(target))

        if desktop:
            lnk = os.path.join(self.desktop, "Xpad-joy.lnk")
            code, msg = make_shortcut(lnk, os.path.join(target, CLIENT_EXE), target, "Xpad-joy 电脑客户端")
            self.log_async("[快捷方式] 桌面 %s：%s" % (SHORTCUT_NAME,
                                                       msg or ("已创建" if code == 0 else "失败（退出码 %d）" % code)))

        if adb:
            self.install_adb(target)

        # 不管驱动有没有装过，这一步都跑（按你说的：每次都执行安装操作）
        self.install_driver(target)

        self.log_async("[完成] 双击 %s 就能用（第一次要放行防火墙）。" % os.path.join(target, CLIENT_EXE))
        self.on_main(lambda: self.set_status("状态：安装完成 ✓（就是这个位置）", OK))
        self.root.after(0, lambda: self.install_button.config(state=tk.NORMAL, text="安装"))

    def install_adb(self, target):
        """走 USB（ADB 隧道）那条要 adb 和手机驱动：先保证 adb 在（没有就复制到安装位置），再检测驱动。"""
        self.log_async("[adb] 开始（走 USB 那条要 adb + 手机驱动；走 Wi-Fi 不用 adb）")
        in_path = shutil.which("adb")
        if in_path:
            adb = in_path
            self.log_async("  PATH 里已经有 adb：%s（不再复制）" % in_path)
        else:
            src = res_path(os.path.join(ADB_DIR, "adb.exe"))
            if os.path.exists(src):
                adb = os.path.join(target, "adb.exe")
                for name in ADB_FILES:
                    s = res_path(os.path.join(ADB_DIR, name))
                    if not os.path.exists(s):
                        continue
                    try:
                        shutil.copy2(s, os.path.join(target, name))
                        self.log_async("  复制 %s → 安装位置（客户端会先找 PATH，再找自己同目录）" % name)
                    except Exception as exc:
                        self.log_async("  复制 %s 失败：%s" % (name, exc))
                self.log_async("  这样“执行 adb reverse”按钮就有得用（客户端的 find_adb() 认安装位置里的 adb）")
            else:
                adb = ADB_FALLBACK if os.path.exists(ADB_FALLBACK) else ""
                if not adb:
                    self.log_async("  没有可用的 adb：PATH 里没有、引导里也没打包（打包时加 "
                                   "--add-data \"vendor/platform-tools;platform-tools\"）；"
                                   "走 Wi-Fi（UDP）不需要 adb，走 USB 才要")
                    return
                self.log_async("  用本机这个 adb：%s" % adb)
        if not adb or not os.path.exists(adb):
            self.log_async("  找不到可用的 adb（走 USB 那条要在电脑上跑 adb reverse）")
            return

        code, msg = adb_devices(adb)
        lines = adb_lines(msg)
        self.log_async("  adb devices（退出码 %d）：%s" % (code, " / ".join(lines) or "没设备"))
        if any("unauthorized" in l.lower() for l in lines):
            self.log_async("  驱动没问题：手机上点“允许 USB 调试”就行，授权后 adb devices 会显示 device")
            return
        if any("offline" in l.lower() for l in lines):
            code2, msg2 = run([adb, "kill-server"], timeout=30)
            code3, msg3 = adb_devices(adb, timeout=30)
            again = adb_lines(msg3)
            self.log_async("  设备是 offline（驱动在但没授权/服务乱了）：adb kill-server 后再看 → %s"
                           % (" / ".join(again) or "还是没设备"))
            return
        if lines:
            self.log_async("  设备认到了 → 驱动是好的（ADB 走 WinUSB，单程通常几 ms）")
            return

        code2, msg2 = pnp_android()
        self.log_async("  设备管理器侧：%s" % (msg2 or "读不到（可能要管理员）"))
        code3, msg3 = run([adb, "kill-server"], timeout=30)
        code4, msg4 = adb_devices(adb, timeout=30)
        again = adb_lines(msg4)
        self.log_async("  重启 adb 服务后再看：%s" % (" / ".join(again) or "还是没有设备"))
        self.log_async("  真缺驱动的话按这个顺序：① 插上线、手机开 USB 调试 ② 换线/换口（有的线只有电没有数据）"
                       "③ Windows 10/11 一般会自动给 ADB 设备装 WinUSB ④ 厂商手机装厂商驱动（小米/华为/OPPO 的"
                       "手机助手里带）⑤ 设备管理器里右键那个设备 → 更新驱动 → 选 Android ADB Interface；"
                       "官方 Google USB driver（含 android_winusb.inf，只覆盖 Google 设备）："
                       "https://developer.android.com/tools/releases/platform-tools")

    def install_driver(self, log_dir=None):
        """每次都跑一遍驱动安装程序（不管之前有没有装过），全程静默；要管理员（非管理员时弹一次 UAC）。"""
        setup = res_path(DRIVER_FILE)
        if not os.path.exists(setup):
            self.log_async("[驱动] 引导里没有驱动安装程序：只能自己下 https://github.com/nefarius/ViGEmBus/releases")
            return
        if self.driver["installed"]:
            self.log_async("[驱动] 已经装了（%s）→ 按你说的照样跑一遍安装程序（覆盖装/修复）"
                           % (self.driver.get("state") or "已安装"))
        if not is_admin():
            self.log_async("[驱动] 当前不是管理员：这一步会弹一次 UAC 确认")
        # 从二进制里读出来的开关是 WiX burn 那一套：/quiet /qn /passive /qb /norestart /log（没有 /S、/silent）
        # 退出码：0 = 跑完；3010 = 跑完但要重启；其他 = 开关不认或装失败
        base = log_dir or os.environ.get("TEMP", "")
        log_path = os.path.join(base, "xjoy-vigem.log") if base else ""
        switch_sets = (["/quiet", "/norestart"], ["/qn", "/norestart"], ["/passive", "/norestart"], ["/S"], ["/silent"])
        run_code = None
        used = ""
        for flags in switch_sets:
            args = list(flags)
            if log_path:
                args += ["/log", log_path]
            self.log_async("[驱动] 静默安装，试 %s …" % " ".join(args))
            if is_admin():
                code, result = run([setup] + args, timeout=600)
            else:
                cmd = "Start-Process -FilePath %s -ArgumentList %s -Verb RunAs -Wait" % (
                    ps_quote(setup), ps_quote(" ".join(args)))
                code, result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=600)
            self.log_async("[驱动] 退出码 %d：%s" % (code, result or "无输出"))
            if code in (0, 3010):
                run_code = code
                used = " ".join(args)
                break
        if log_path and os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
                for ln in lines[-8:]:
                    self.log_async("[驱动·日志] %s" % ln)
            except Exception as exc:
                self.log_async("[驱动·日志] 读 %s 失败：%s" % (log_path, exc))
        self.recheck()
        info = self.driver
        if run_code is None:
            self.log_async("[驱动] 每个开关都没跑通（试过的：%s）。这个包只认图形界面时的办法：管理员双击 "
                           "%s 点完，再重启。" % (" / ".join(" ".join(s) for s in switch_sets), setup))
            return
        self.log_async("[驱动] 按 %s 跑完（退出码 %d）" % (used, run_code))
        if run_code == 3010:
            self.log_async("[驱动] 安装程序说要走一次重启（退出码 3010）：重启后驱动才真正上去")
        if not info["installed"]:
            self.log_async("[驱动] 跑完了但检测还是没装：看上面那几行驱动日志（多半是权限或设备节点没重建）")
            return
        state = info.get("state") or "-"
        self.log_async("[驱动] 跑完后的状态：%s（启动类型 %s，来源 %s）"
                       % (state, info.get("starttype") or "-", info.get("how") or "-"))
        if state == "运行中":
            self.log_async("[驱动] 驱动在跑：重开客户端就能建虚拟手柄")
        else:
            self.log_async("[驱动] 服务键在但没跑：要管理员跑 sc config ViGEmBus start= demand 然后重启；"
                           "设备管理器里那个总线节点不能报 Problem 31（跑完安装程序不一定能修设备节点，这一条要重启）")


    def quit(self):
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="Xpad-joy 安装引导：检测 ViGEmBus 驱动 + 选安装位置 + 静默安装")
    ap.add_argument("--check", action="store_true", help="只检测驱动，不打开窗口（给脚本用）")
    ap.add_argument("--install-dir", default=None, help="默认安装位置（不填用 %%LOCALAPPDATA%%\\Xpad-joy）")
    args = ap.parse_args()

    info = driver_info()
    if args.check:
        out("installed=%s state=%s start=%s imagepath=%s driverfile=%s how=%s"
            % (info["installed"], info.get("state", ""), info.get("starttype", ""),
               info.get("imagepath", ""), info.get("driverfile", ""), info.get("how", "")))
        out("adb=%s（内置打包位置 %s；装的时候如果没有就复制到安装位置）"
            % (find_adb() or "没有", res_path(os.path.join(ADB_DIR, "adb.exe"))))
        return 0 if info["installed"] else 2

    root = tk.Tk()
    inst = Installer(root)
    if args.install_dir:
        inst.set_dir(args.install_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
