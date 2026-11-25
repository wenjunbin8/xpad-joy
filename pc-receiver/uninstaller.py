#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xpad-joy 电脑客户端 卸载程序（窗口版，中文界面）

跑源代码：  py -3 uninstaller.py
打包（和 打包卸载程序.bat 里一致）：
  py -3 -m PyInstaller --onefile --windowed --name Xpad-joy-Uninstaller uninstaller.py

只删我们自己放进去的东西：安装目录里的 Xpad-joy.exe / 安装说明.txt / 安装信息.txt / Xpad-joy.log，
加上桌面的 Xpad-joy.lnk（先读它的 TargetPath，确实指向这个安装目录才删，指向别处就不动），
还有安装引导在注册表里登记的那条（HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Xpad-joy）。
目录里别的文件一律不动；目录删空后连目录一起删。
安装位置不用用户选：按可靠程度自动认 —— ① 卸载程序自己所在的目录（用户就是在安装位置里双击它的）
② 注册表里安装引导记录的 InstallLocation ③ 桌面快捷方式指向的目录 ④ 默认 LOCALAPPDATA 下的 Xpad-joy。
卸载程序自己也在安装目录里（安装引导会把它复制过去），所以删自己靠一条临时副本：主进程把
自己复制到 %TEMP% 再跑 --cleanup，1 秒后由那条副本删掉安装目录（含这个卸载程序）和它自己。
驱动默认不卸：界面里有一个勾选项「卸载 ViGEmBus 驱动」，勾了才动 —— 先走官方在 HKLM 登记的卸载程序
（静默），没有就 pnputil /delete-driver 驱动存储里那份 inf，再 sc delete，再试着删 .sys（内核驱动还加载
在内存里时删不掉，要重启）。这些都要管理员，跑之前会弹一次 UAC；用 Start-Process -WindowStyle Hidden，
所以只有 UAC 弹窗、不闪黑窗口。没勾就只报状态、一个字都不动。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

NO_WINDOW = 0x08000000 if os.name == "nt" else 0

DRIVER_SERVICE = "ViGEmBus"
# 安装引导会复制过来的东西（adb 那三个是走 USB 那条用的，装过才在、没装过就跳过）
OUR_FILES = ("Xpad-joy.exe", "安装说明.txt", "安装信息.txt", "Xpad-joy.log", "Xpad-joy-Uninstaller.log",
             "adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
SELF_LOG = "Xpad-joy-Uninstaller.log"
SELF_NAME = "Xpad-joy-Uninstaller.exe"
ALLOWED = set(OUR_FILES) | {SELF_NAME}
SHORTCUT_NAME = "Xpad-joy.lnk"
INFO_FILE = "安装信息.txt"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Xpad-joy"

BG = "#111519"
CARD = "#1B2128"
ACCENT = "#3B82F6"
INK = "#E8EDF2"
MUTED = "#8A94A0"
OK = "#3FBF7F"
BAD = "#E0565C"

try:
    import tkinter as tk
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


LOG_OVERRIDE = ""
LOG_DISABLED = False


def log_file():
    if LOG_OVERRIDE:
        return LOG_OVERRIDE
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "Xpad-joy-Uninstaller.log")


def out(msg, write_log=True):
    text = str(msg)
    if sys.stdout is not None:
        try:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    if write_log and not LOG_DISABLED:
        try:
            with open(log_file(), "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass


def bundled_path(name):
    """打包后从 PyInstaller 的临时解压目录取内置文件（icon.ico）；跑源代码时从脚本目录取。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, name)
    return path if os.path.exists(path) else ""


def set_window_icon(root):
    """窗口和任务栏用生成的图标（tools/make_icon.py 产物 icon.ico）；没有就用默认图标，不报错。"""
    try:
        ico = bundled_path("icon.ico")
        if ico:
            root.iconbitmap(ico)
    except Exception:
        pass


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run(args, timeout=60):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
        result = (r.stdout or "").strip() or (r.stderr or "").strip()
        return r.returncode, result
    except Exception as exc:
        return 1, "执行失败：%s" % exc


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_run(args, timeout=300):
    """需要管理员时用它：Start-Process -Verb RunAs（弹一次 UAC，窗口隐藏，不闪黑窗）。"""
    if not args:
        return 1, "没命令"
    cmd = "Start-Process -FilePath %s -ArgumentList %s -Verb RunAs -WindowStyle Hidden -Wait" % (
        ps_quote(args[0]), ps_quote(" ".join(str(a) for a in args[1:])))
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=timeout)


def run_priv(args, timeout=120):
    """能管理员就直接跑，否则走一次 UAC。"""
    return run(args, timeout=timeout) if is_admin() else elevate_run(args, timeout=timeout)


def driver_uninstall_entry():
    """找 ViGEmBus 在 HKLM 里登记的卸载程序（官方安装程序会写）；返回 (名字, UninstallString)。"""
    if winreg is None:
        return "", ""
    for hive in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                 r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hive) as key:
                for i in range(256):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    except OSError:
                        break
                    with sub:
                        try:
                            name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                        except Exception:
                            name = ""
                        if "vigem" not in name.lower():
                            continue
                        try:
                            un = str(winreg.QueryValueEx(sub, "UninstallString")[0])
                        except Exception:
                            un = ""
                        return name, un
        except Exception:
            continue
    return "", ""


def driver_info():
    """只读检测（勾了「卸载驱动」才会动驱动）。"""
    info = {"installed": False, "state": "", "how": ""}
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Services\%s" % DRIVER_SERVICE) as key:
                info["installed"] = True
                info["how"] = "注册表服务键"
        except FileNotFoundError:
            info["how"] = "注册表里没有 ViGEmBus 服务键"
        except Exception as exc:
            info["how"] = "注册表读失败（%s）" % exc
    code, msg = run(["sc", "query", DRIVER_SERVICE], timeout=20)
    if code == 0 and msg:
        for row in msg.replace("\r", "").split("\n"):
            if "STATE" in row and ":" in row:
                word = row.split(":", 1)[1].strip()
                info["state"] = {"4": "运行中", "1": "已停止", "2": "启动中", "3": "停止中"}.get(word.split()[0], word)
    return info


def shortcut_target(lnk_path):
    """用 PowerShell 读 .lnk 的 TargetPath（读不到返回空）。"""
    if not os.path.exists(lnk_path):
        return ""
    cmd = ("$sh = New-Object -ComObject WScript.Shell; "
           "$l = $sh.CreateShortcut(%s); $l.TargetPath" % ps_quote(lnk_path))
    code, msg = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=30)
    return msg if code == 0 else ""


def self_copy_path():
    """正在跑的那个可执行文件（打包版）或脚本（源代码版）。"""
    return sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0])


def marker_path():
    return os.path.join(tempfile.gettempdir(), "xjoy-uninstall-done.txt")


def append_marker(lines):
    try:
        with open(marker_path(), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def cleanup(target, delay=1.5, wait_for_parent=12.0):
    """由临时副本跑：先删安装目录里属于我们的文件（这时安装目录里那个卸载程序还被窗口占着），写一份
    回报给主窗口；然后等窗口关闭（最多 wait_for_parent 秒），再删那个卸载程序本体和空目录；最后延迟
    3 秒删这条副本自己（正在跑的可执行文件删不了自己）。副本的日志写在 %TEMP%，不往安装目录写。"""
    time.sleep(delay)
    lines = []
    failed = False
    adb_here = os.path.join(target, "adb.exe")
    if os.path.exists(adb_here):
        try:
            subprocess.run([adb_here, "kill-server"], capture_output=True, text=True,
                           timeout=20, creationflags=NO_WINDOW)
        except Exception:
            pass
    for name in sorted(ALLOWED):
        if name == SELF_NAME:
            continue          # 这个文件正被窗口那个进程占着，等窗口退出再删
        path = os.path.join(target, name)
        if os.path.exists(path):
            try:
                os.remove(path)
                lines.append("删了 %s" % name)
            except Exception as exc:
                failed = True
                lines.append("%s 删不掉：%s" % (name, exc))
    lines.append("%s 等窗口关闭后删（最多 12 秒）" % SELF_NAME)
    for line in lines:
        out("  [副本] " + line)
    append_marker(lines)
    got = None
    last_exc = None
    for _ in range(int(wait_for_parent / 0.5)):
        path = os.path.join(target, SELF_NAME)
        if not os.path.exists(path):
            got = "删了 %s（窗口已经关闭）" % SELF_NAME
            break
        try:
            os.remove(path)
            got = "删了 %s（窗口已经关闭）" % SELF_NAME
            break
        except Exception as exc:
            last_exc = exc
            time.sleep(0.5)
    if got is None:
        failed = True
    tail = [got or "%s 还是删不掉（窗口没关或权限被拒）：%s" % (SELF_NAME, last_exc)]
    if os.path.isdir(target):
        rest = sorted(os.listdir(target))
        if not rest:
            try:
                os.rmdir(target)
                tail.append("目录空了 → 连目录一起删（%s）" % target)
            except Exception as exc:
                failed = True
                tail.append("目录删不掉：%s" % exc)
        else:
            tail.append("还有别的文件，保留目录：%s" % ", ".join(rest))
    else:
        tail.append("目录已经不在了")
    for line in tail:
        out("  [副本] " + line)
    append_marker(tail)
    me = self_copy_path()
    # 顺手把 %TEMP% 里之前留下的副本清掉（只清我们自己那个名字）
    try:
        tmpdir = tempfile.gettempdir()
        for name in os.listdir(tmpdir):
            if name.startswith("xjoy-uninstall-cleanup"):
                p = os.path.join(tmpdir, name)
                if p != me:
                    try:
                        os.remove(p)
                        out("  清掉了 %TEMP% 里之前留下的副本：%s" % name)
                    except Exception:
                        pass
    except Exception:
        pass
    if not failed and LOG_OVERRIDE:
        try:
            os.remove(LOG_OVERRIDE)      # 顺利的话 %TEMP% 里什么都不留；有失败才留一份日志
        except Exception:
            pass
    try:
        # 这条副本正在跑，删不了自己：等它退出后再删（PowerShell 延迟删；只有空目录会被 rmdir 删掉，别的文件不动）
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          "Start-Sleep 3; Remove-Item -LiteralPath '%s' -Force" % me.replace("'", "''")],
                         creationflags=NO_WINDOW)
    except Exception as exc:
        out("[副本] 自删失败（在 %%TEMP%% 里，可以手动删）：%s" % exc)


LAST_REG_ERROR = ""


def registry_install_location():
    """读安装引导登记的 InstallLocation（HKCU，普通用户）。读不到返回空，并把原因记在 LAST_REG_ERROR。"""
    global LAST_REG_ERROR
    LAST_REG_ERROR = ""
    if winreg is None:
        LAST_REG_ERROR = "这个 Python 没有 winreg"
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return str(winreg.QueryValueEx(key, "InstallLocation")[0])
    except FileNotFoundError:
        LAST_REG_ERROR = "没登记过这条"
        return ""
    except Exception as exc:
        LAST_REG_ERROR = "读失败（%s）" % exc
        return ""


def own_dir():
    """正在跑的这份程序所在的目录。"""
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(sys.argv[0]))


def detect_install_dir():
    """自动认安装位置，按可靠程度排序（不让用户选）。返回 (目录, 依据, 尝试过程)。"""
    notes = []
    base = own_dir()
    if os.path.exists(os.path.join(base, INFO_FILE)):
        return base, "卸载程序自己就在安装目录里（这里有安装引导写的 %s）" % INFO_FILE, notes
    if os.path.exists(os.path.join(base, "Xpad-joy.exe")):
        return base, "卸载程序自己就在安装目录里（这份 Xpad-joy.exe 和它在一起）", notes
    notes.append("① 自己所在的目录 %s：没找到 %s，也没找到 Xpad-joy.exe" % (base, INFO_FILE))
    loc = registry_install_location()
    if loc:
        if os.path.isdir(loc):
            return loc, "注册表里安装引导登记的 InstallLocation", notes
        notes.append("② 注册表登记的 %s 当时读不到目录（可能刚被删）" % loc)
    else:
        notes.append("② 注册表：%s" % (LAST_REG_ERROR or "没登记过"))
    lnk = os.path.join(os.path.join(os.path.expanduser("~"), "Desktop"), SHORTCUT_NAME)
    target = shortcut_target(lnk)
    if target:
        d = os.path.dirname(target)
        if os.path.isdir(d):
            return d, "桌面快捷方式 %s 指向的目录" % SHORTCUT_NAME, notes
        notes.append("③ 桌面快捷方式指向的目录不存在（%s）" % d)
    else:
        notes.append("③ 桌面快捷方式：%s" % ("没有" if not os.path.exists(lnk) else "读不到目标"))
    default = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Xpad-joy")
    notes.append("④ 兜底用默认位置")
    return default, "默认位置（三条都没找到）", notes


class Uninstaller:
    def __init__(self, root):
        self.root = root
        self.log_lines = []
        self.driver = driver_info()
        self.desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.install_dir, self.how, self.notes = detect_install_dir()
        self._build_ui()
        self.log("识别到的安装位置：%s（存在=%s）" % (self.install_dir, os.path.isdir(self.install_dir)))
        self.log("  依据：%s" % self.how)
        for note in self.notes:
            self.log("  " + note)
        for name in sorted(ALLOWED):
            path = os.path.join(self.install_dir, name)
            if os.path.exists(path):
                self.log("  有 %s（%d KB）%s" % (name, max(1, os.path.getsize(path) // 1024),
                                                 "← 就是我自己" if name == SELF_NAME else ""))
        lnk = os.path.join(self.desktop, SHORTCUT_NAME)
        target = shortcut_target(lnk)
        if os.path.exists(lnk):
            self.log("  桌面快捷方式 %s → %s" % (SHORTCUT_NAME, target or "读不到目标"))
        else:
            self.log("  桌面快捷方式 %s：没有" % SHORTCUT_NAME)
        self.log("  注册表登记：%s" % (registry_install_location() or
                                       "没有（HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Xpad-joy）"))
        self.log("驱动（勾了才卸）：%s" % ("已装（%s）" % (self.driver.get("state") or "状态未知")
                                         if self.driver["installed"] else "未装"))

    def _build_ui(self):
        self.root.title("Xpad-joy 卸载")
        set_window_icon(self.root)
        self.root.configure(bg=BG)
        self.root.minsize(680, 420)

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill=tk.X, padx=12, pady=(12, 6))
        tk.Label(head, text="Xpad-joy 电脑客户端 卸载", bg=BG, fg=INK,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side=tk.LEFT)
        self.driver_label = tk.Label(head, text="", bg=BG, fg=(OK if self.driver["installed"] else BAD),
                                     font=("Microsoft YaHei UI", 11, "bold"))
        self.driver_label.pack(side=tk.RIGHT)
        self.driver_label.config(text="ViGEmBus 驱动：%s" % ("已装" if self.driver["installed"] else "未装"))

        row = tk.Frame(self.root, bg=BG)
        row.pack(fill=tk.X, padx=12, pady=(4, 6))
        tk.Label(row, text="识别到的安装位置", bg=BG, fg=MUTED).pack(side=tk.LEFT)
        self.dir_label = tk.Label(row, text="", bg=BG, fg=INK, font=("Microsoft YaHei UI", 11))
        self.dir_label.pack(side=tk.LEFT, padx=(8, 0))
        self.show_dir()

        status = tk.Frame(self.root, bg=BG)
        status.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.status_label = tk.Label(status, text="", bg=BG, fg=INK, font=("Microsoft YaHei UI", 12, "bold"))
        self.status_label.pack(side=tk.LEFT)
        self.set_status("状态：准备就绪")

        opts = tk.Frame(self.root, bg=BG)
        opts.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.var_driver = tk.BooleanVar(value=False)
        tk.Checkbutton(opts, text="卸载 ViGEmBus 驱动（要管理员，默认不卸；卸了要重装才能用虚拟手柄）",
                       variable=self.var_driver, bg=BG, fg=INK, activebackground=BG, activeforeground=INK,
                       selectcolor=CARD).pack(side=tk.LEFT)

        buttons = tk.Frame(self.root, bg=BG)
        buttons.pack(fill=tk.X, padx=12, pady=(2, 8))
        self.uninstall_button = tk.Button(buttons, text="卸载", bg=ACCENT, fg=INK, activebackground=CARD,
                                          activeforeground=INK, relief=tk.FLAT, width=10, command=self.uninstall)
        self.uninstall_button.pack(side=tk.LEFT)
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

    def log(self, msg):
        self.log_lines.append(str(msg))
        out(msg)
        try:
            self.text.insert(tk.END, str(msg) + "\n")
            self.text.see(tk.END)
        except Exception:
            pass

    def set_status(self, text, color=None):
        self.status_label.config(text=text, fg=(color or INK))

    def show_dir(self):
        self.dir_label.config(text="%s（%s）" % (self.install_dir,
                                                 "存在" if os.path.isdir(self.install_dir) else "不存在"))

    def set_dir(self, value):
        self.install_dir = value
        self.show_dir()

    def uninstall(self):
        target = self.install_dir
        if not target:
            self.set_status("状态：没识别到安装位置", BAD)
            self.log("[卸载] 没识别到安装位置")
            return
        if not os.path.isdir(target):
            self.set_status("状态：识别到的目录不存在（可能已经被删了）", BAD)
            self.log("[卸载] 目录不存在：%s" % target)
            return
        self.uninstall_button.config(state=tk.DISABLED, text="卸载中…")
        self.log("[卸载] 目标：%s（依据：%s）" % (target, self.how))

        # adb 的服务进程可能正占着安装目录里的 adb.exe：先把它关掉再删
        adb_here = os.path.join(target, "adb.exe")
        if os.path.exists(adb_here):
            try:
                r = subprocess.run([adb_here, "kill-server"], capture_output=True, text=True,
                                   timeout=20, creationflags=NO_WINDOW)
                self.log("[adb] 先跑一次 adb kill-server（释放被占用的 adb.exe）：%s"
                         % ((r.stdout or r.stderr or "无输出").strip() or "没消息"))
            except Exception as exc:
                self.log("[adb] adb kill-server 失败（不影响删文件）：%s" % exc)

        for name in OUR_FILES:
            if name == SELF_LOG:
                continue  # 这个文件正被自己写着，删不了；交给临时副本
            path = os.path.join(target, name)
            if not os.path.exists(path):
                self.log("[卸载] 没有 %s" % name)
                continue
            try:
                os.remove(path)
                self.log("[卸载] 删了 %s" % name)
            except PermissionError:
                self.log("[卸载] %s 删不掉（文件正在被占用，先关掉客户端再卸载）" % name)
            except Exception as exc:
                self.log("[卸载] %s 删失败：%s" % (name, exc))

        lnk = os.path.join(self.desktop, SHORTCUT_NAME)
        if os.path.exists(lnk):
            target_path = shortcut_target(lnk)
            if target_path.lower().startswith(os.path.join(target, "Xpad-joy.exe").lower()):
                try:
                    os.remove(lnk)
                    self.log("[快捷方式] 桌面 %s 指向这个安装位置 → 删了" % SHORTCUT_NAME)
                except Exception as exc:
                    self.log("[快捷方式] 删除失败：%s" % exc)
            else:
                self.log("[快捷方式] 桌面 %s 指向别处（%s）→ 不动" % (SHORTCUT_NAME, target_path or "读不到"))
        else:
            self.log("[快捷方式] 桌面上没有 %s" % SHORTCUT_NAME)

        if winreg is not None:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
                self.log("[注册表] 删了 HKCU\\%s（设置里的应用条目也一起没了）" % UNINSTALL_KEY)
            except FileNotFoundError:
                self.log("[注册表] 没有登记过这条（HKCU\\%s）→ 不用删" % UNINSTALL_KEY)
            except Exception as exc:
                self.log("[注册表] 删失败：%s（这是 HKCU 自己那条，普通用户就能删）" % exc)
        else:
            self.log("[注册表] 这个 Python 没有 winreg，跳过硬删除")

        self.remove_driver()

        # 正在被自己占用的东西删不掉（这个卸载程序本体 + 它自己正在写的日志）：让一条临时副本收尾
        still = [n for n in (SELF_NAME, SELF_LOG) if os.path.exists(os.path.join(target, n))]
        if still:
            src = self_copy_path()
            frozen = bool(getattr(sys, "frozen", False))
            tmp = os.path.join(tempfile.gettempdir(), "xjoy-uninstall-cleanup" + (".exe" if frozen else ".py"))
            try:
                if os.path.exists(marker_path()):
                    os.remove(marker_path())
                shutil.copy2(src, tmp)
                cmd = [tmp, "--cleanup", target] if frozen else [sys.executable, tmp, "--cleanup", target]
                subprocess.Popen(cmd, creationflags=NO_WINDOW)
                global LOG_DISABLED
                LOG_DISABLED = True      # 安装目录里的日志马上要被副本删掉：别再写回那里
                self.log("[收尾] 正在被自己占用、删不掉：%s → 交给临时副本（它 1.5 秒后删这些、空目录和它自己）"
                         % ", ".join(still))
                self.set_status("状态：等临时副本回报…")
                self.polls = 0
                self.root.after(300, self.poll_marker)
                return
            except Exception as exc:
                self.log("[收尾] 起临时副本失败：%s（这些要手动删）" % exc)

        rest = sorted(os.listdir(target))
        if not rest:
            try:
                os.rmdir(target)
                self.log("[目录] 已经空了 → 连目录一起删（%s）" % target)
            except Exception as exc:
                self.log("[目录] 空但删不掉：%s" % exc)
        else:
            self.log("[目录] 还有别的文件，保留目录：%s" % ", ".join(rest))

        self.log("[完成] 客户端文件、桌面快捷方式、注册表登记都清理完了%s" % (
            "（驱动没勾就没动）" if not self.var_driver.get() else "（驱动那步看上面）"))
        self.set_status("状态：卸载完成 ✓", OK)
        self.uninstall_button.config(state=tk.NORMAL, text="卸载")

    def remove_driver(self):
        if not self.var_driver.get():
            self.log("[驱动] 没勾「卸载 ViGEmBus 驱动」→ 没动（客户端还要它才能建虚拟手柄）")
            return
        self.log("[驱动] 开始卸 ViGEmBus（要管理员，会弹一次 UAC）")
        self.log("  提醒：卸掉之后游戏里看不到手柄，要重新装（https://github.com/nefarius/ViGEmBus/releases）")
        done = False
        name, un = driver_uninstall_entry()
        if un:
            self.log("  官方登记的卸载程序：%s → %s" % (name or "（没名字）", un))
            if "msiexec" in un.lower():
                guid = ""
                for token in un.replace('"', "").split():
                    if token.startswith("/X") or token.startswith("/x"):
                        guid = token[2:]
                if guid:
                    code, msg = run_priv(["msiexec.exe", "/x", guid, "/qb"], timeout=600)
                    self.log("  msiexec /x %s /qb → 退出码 %d：%s" % (guid, code, msg or "无输出"))
                    done = True
                else:
                    self.log("  UninstallString 里没有产品码，读不出该跑什么")
            else:
                exe = un.replace('"', "").split()[0]
                for flags in (["/VERYSILENT", "/SUPPRESSRESTARTS"], ["/SILENT"], ["/quiet"]):
                    code, msg = run_priv([exe] + flags, timeout=600)
                    self.log("  %s %s → 退出码 %d：%s" % (exe, " ".join(flags), code, msg or "无输出"))
                    if not driver_info()["installed"]:
                        done = True
                        break
        else:
            self.log("  HKLM 的 应用和功能 里没找到这个驱动的卸载程序（官方安装程序不一定登记）")

        if not done:
            code, msg = run(["pnputil", "/enum-drivers"], timeout=120)
            inf = ""
            for block in msg.replace("\r", "").split("\n\n"):
                if DRIVER_SERVICE.lower() in block.lower():
                    m = re.search(r"(?:发布名称|Published name)\s*[:：]\s*(\S+\.inf)", block, re.I)
                    if m:
                        inf = m.group(1)
                        break
            if inf:
                code, msg = run_priv(["pnputil", "/delete-driver", inf, "/uninstall"], timeout=300)
                self.log("  pnputil /delete-driver %s /uninstall → 退出码 %d：%s" % (inf, code, msg or "无输出"))
            else:
                self.log("  驱动存储里没找到 ViGEmBus 的 inf（%s）→ 只能走官方卸载程序或设备管理器"
                         % (msg or "读不到（可能要管理员）"))

        if driver_info()["installed"]:
            code, msg = run_priv(["sc.exe", "delete", DRIVER_SERVICE], timeout=120)
            self.log("  sc delete %s → 退出码 %d：%s" % (DRIVER_SERVICE, code, msg or "无输出"))
            drv = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers",
                               "%s.sys" % DRIVER_SERVICE)
            if os.path.exists(drv):
                try:
                    os.remove(drv)
                    self.log("  删了 %s" % drv)
                except Exception as exc:
                    self.log("  %s 删不掉（驱动还加载在内核里，重启后再删）" % drv)
            else:
                self.log("  驱动文件已经不在了（%s）" % drv)
        else:
            self.log("  服务已经没了 → 不用 sc delete（驱动文件一般被卸载程序一起删了）")

        info = driver_info()
        self.driver = info
        self.driver_label.config(text="ViGEmBus 驱动：%s" % (("还在（%s）" % (info.get("state") or "已安装"))
                                                            if info["installed"] else "已卸 ✓"),
                                 fg=(BAD if info["installed"] else OK))
        if info["installed"]:
            self.log("  结果：驱动还在（%s）—— 内核驱动要重启才算卸干净，或者用官方卸载程序" % (info.get("state") or "-"))
        else:
            self.log("  结果：驱动卸掉了 ✓（重启一次最干净）")

    def poll_marker(self):
        """等临时副本的回报文件，看到了就显示明显的完成状态。"""
        marker = marker_path()
        if os.path.exists(marker):
            try:
                text = open(marker, encoding="utf-8").read()
            except Exception:
                text = ""
            for line in text.strip().split("\n"):
                if line:
                    self.log("  [副本] " + line)
            self.set_status("状态：卸载完成 ✓（这个卸载程序自己在窗口关闭后最多 12 秒内被副本删掉）", OK)
            self.uninstall_button.config(state=tk.NORMAL, text="卸载")
            self.log("[完成] 窗口关闭后 3 秒内，安装目录里的 %s 会被副本删掉（连空目录）。" % SELF_NAME)
            self.root.after(3000, self.quit)
            return
        self.polls = getattr(self, "polls", 0) + 1
        if self.polls < 20:
            self.root.after(300, self.poll_marker)
        else:
            self.set_status("状态：副本没回报（权限被拒或 powershell 用不了）—— 那个文件要手动删", BAD)
            self.uninstall_button.config(state=tk.NORMAL, text="卸载")

    def quit(self):
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="Xpad-joy 卸载程序：删安装目录里的客户端文件和桌面快捷方式（不卸驱动）")
    ap.add_argument("--check", action="store_true", help="只列出会删什么，不动文件（给脚本用）")
    ap.add_argument("--cleanup", metavar="DIR", help="由临时副本调用：1.5 秒后删安装目录里属于我们的文件 + 副本自己")
    ap.add_argument("--install-dir", default=None, help="手动指定安装位置（不填就自动认）")
    args = ap.parse_args()

    if args.cleanup:
        global LOG_OVERRIDE
        LOG_OVERRIDE = os.path.join(tempfile.gettempdir(), "xjoy-uninstall-cleanup.log")
        cleanup(args.cleanup)
        return 0

    install_dir, how, notes = detect_install_dir()
    if args.install_dir:
        install_dir, how, notes = args.install_dir, "命令行 --install-dir", []
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")

    if args.check:
        out("安装位置=%s 存在=%s（依据：%s）" % (install_dir, os.path.isdir(install_dir), how))
        for note in notes:
            out("  " + note)
        out("  注册表登记=%s" % (registry_install_location() or "没有"))
        for name in sorted(ALLOWED):
            path = os.path.join(install_dir, name)
            if os.path.exists(path):
                note = "（靠临时副本）" if name == SELF_NAME else ""
                out("  %s 会删%s" % (name, note))
            else:
                out("  %s 没有" % name)
        lnk = os.path.join(desktop, SHORTCUT_NAME)
        out("  桌面快捷方式 %s：%s" % (SHORTCUT_NAME,
                                       "会删（指向 %s）" % (shortcut_target(lnk) or "读不到")
                                       if os.path.exists(lnk) else "没有"))
        info = driver_info()
        out("驱动=%s（%s，没勾「卸载 ViGEmBus 驱动」就不动）" % (info["installed"], info.get("state", "")))
        return 0

    root = tk.Tk()
    inst = Uninstaller(root)
    if args.install_dir:
        inst.set_dir(args.install_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
