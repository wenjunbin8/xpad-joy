"""沙箱外对照：用 Steam(hidapi) 那套方式枚举 HID 接口、打开设备、读一个输入报告。
只读，不改任何驱动。输出写到 hid_probe.log。
"""
import ctypes
import os
import time
from ctypes import wintypes

import vgamepad as vg

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hid_probe.log")
HID_GUID = (0x745a17a0, 0x74d3, 0x11d0, b"\xb6\xfe\x00\xa0\xc9\x0f\x57\xda")


def w(msg):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


class Guid(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class IfData(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("Guid", Guid),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


class DetailSmall(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("path", ctypes.c_wchar * 1)]


def lines():
    setupapi = ctypes.CDLL("setupapi.dll", use_last_error=True)
    setupapi.SetupDiGetClassDevsW.argtypes = (ctypes.POINTER(Guid), ctypes.c_char_p,
                                              ctypes.c_void_p, wintypes.DWORD)
    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_longlong
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = (ctypes.c_longlong, ctypes.c_void_p,
                                                      ctypes.POINTER(Guid), wintypes.DWORD,
                                                      ctypes.POINTER(IfData))
    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = (ctypes.c_longlong,
                                                          ctypes.POINTER(IfData), ctypes.c_void_p,
                                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                          ctypes.c_void_p)
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL

    g = Guid()
    g.Data1, g.Data2, g.Data3 = HID_GUID[0], HID_GUID[1], HID_GUID[2]
    g.Data4 = (ctypes.c_ubyte * 8)(*HID_GUID[3])
    for flags in (0x20 | 0x01, 0x01, 0x21, 0x20):
        h = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, flags)
        err = ctypes.get_last_error()
        s = "flags=%s handle=%s err=%s" % (hex(flags), h, err)
        if h in (None, -1):
            w(s)
            continue
        cb = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4
        d = IfData()
        d.cbSize = ctypes.sizeof(IfData)
        paths = []
        i = 0
        while i < 400 and setupapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(g), i, ctypes.byref(d)):
            size = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), None, 0, ctypes.byref(size), None)
            if size.value:
                buf = (ctypes.c_char * size.value)()
                view = DetailSmall.from_buffer(buf)
                view.cbSize = cb
                if setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), buf, size.value,
                                                             ctypes.byref(size), None):
                    paths.append(buf[cb:].decode("utf-16-le", "ignore").split("\x00")[0])
            i += 1
        w(s + " 接口数=" + str(len(paths)))
        w("  跟 045E 有关: " + repr([p for p in paths if "045e" in p.lower()]))
        setupapi.SetupDiDestroyDeviceInfoList(h)
        return paths
    return []


def try_open(path):
    kernel = ctypes.CDLL("kernel32.dll", use_last_error=True)
    hid = ctypes.CDLL("hid.dll", use_last_error=True)
    fh = kernel.CreateFileW(path, 0, 3, None, 3, 0, None)
    if fh in (None, -1):
        w("  打不开 err=" + str(ctypes.get_last_error()))
        return
    class Attrs(ctypes.Structure):
        _fields_ = [("Size", wintypes.DWORD), ("VendorID", wintypes.USHORT),
                    ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]
    a = Attrs()
    a.Size = ctypes.sizeof(Attrs)
    ok = hid.HidD_GetAttributes(fh, ctypes.byref(a))
    w("  打开 OK attributes=%s vid=%s pid=%s" % (bool(ok), hex(a.VendorID), hex(a.ProductID)))
    class Prep(ctypes.Structure):
        _fields_ = [("Size", wintypes.DWORD), ("Count", wintypes.ULONG)]
    hid.HidD_GetPreparsedData.argtypes = (ctypes.c_longlong, ctypes.POINTER(ctypes.c_void_p))
    hid.HidD_GetPreparsedData.restype = wintypes.BOOL
    hid.HidP_GetCaps.argtypes = (ctypes.c_void_p, ctypes.POINTER(Prep))
    hid.HidP_GetCaps.restype = wintypes.LONG
    pdat = ctypes.c_void_p()
    if hid.HidD_GetPreparsedData(fh, ctypes.byref(pdat)):
        caps = Prep()
        r = hid.HidP_GetCaps(pdat, ctypes.byref(caps))
        w("  caps ret=%s input_report_len=%d output_report_len=%d" % (r, caps.Size, caps.OutputReportByteLength))
        hid.HidD_FreePreparsedData(pdat)
    kernel.CloseHandle(fh)


if __name__ == "__main__":
    open(OUT, "w", encoding="utf-8").close()
    w("沙箱外对照 " + time.strftime("%H:%M:%S"))
    gp = vg.VX360Gamepad()
    gp.press_button(4096)
    gp.left_trigger(128)
    gp.update()
    w("target " + str(gp.get_index()))
    paths = lines()
    for p in [x for x in paths if "045e" in x.lower()][:3]:
        try_open(p)
    gp.reset()
    gp.update()
