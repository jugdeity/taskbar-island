"""启动 FastAPI 并在任务栏上方创建常驻无边框窗口。"""
import ctypes
import math
import threading
import time
from ctypes import wintypes

import uvicorn
import webview

from app import db

PORT = 8765
W, H = 387, 40         # 灵动岛（药丸）尺寸，按参考图
EXTRA = 0              # 展开面板时向上增加的高度（前端上报）
X_RATIO = 0.55         # 水平位置：屏幕宽度的比例（截图红框在中间偏右）
TITLE = "TaskbarIsland"

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
# 64 位句柄：必须声明类型，否则被截断成 32 位导致调用失败
user32.FindWindowW.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetWindowRect.argtypes =[wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
db.init()


def serve():
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")


def island_rect(x=None):
    # 读取任务栏真实矩形（物理像素），把岛垂直居中放进去；x 为空时用默认比例
    r = wintypes.RECT()
    user32.GetWindowRect(user32.FindWindowW("Shell_TrayWnd", None), ctypes.byref(r))
    scale = user32.GetDpiForSystem() / 96
    # 向上取整：窗口不能比网页内容窄，否则药丸右端的描边会被裁掉（150% 时 387×1.5=580.5）
    w, h0 = math.ceil(W * scale), math.ceil(H * scale)
    ex = math.ceil(EXTRA * scale)
    if x is None:
        x = int(r.left + (r.right - r.left) * X_RATIO - w / 2)
    x = max(r.left, min(x, r.right - w))  # 限制在任务栏内
    y = r.top + (r.bottom - r.top - h0) // 2 - ex  # 药丸垂直居中于任务栏，面板向上长
    return x, y, w, h0 + ex


class Api:
    def set_extra(self, h):
        """前端上报展开面板的高度，窗口随之向上伸缩。"""
        global EXTRA
        EXTRA = max(0, int(h))

    def drag_start(self):
        """在封面/歌名上按下鼠标时调用：窗口横向跟随鼠标，直到松开左键。"""
        hwnd = user32.FindWindowW(None, TITLE)
        p, r = wintypes.POINT(), wintypes.RECT()
        user32.GetCursorPos(ctypes.byref(p))
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        off = p.x - r.left
        while user32.GetAsyncKeyState(0x01) & 0x8000:
            user32.GetCursorPos(ctypes.byref(p))
            x, y, _, _ = island_rect(p.x - off)
            user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)  # NOSIZE|NOZORDER|NOACTIVATE
            time.sleep(0.01)


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]


def fullscreen_active():
    """前台窗口铺满整个显示器（含任务栏区域）= 全屏，此时任务栏会隐藏。"""
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(fg, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False  # 桌面/任务栏本身
    r = wintypes.RECT()
    user32.GetWindowRect(fg, ctypes.byref(r))
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(fg, 2), ctypes.byref(mi))  # 2 = 最近的显示器
    m = mi.rcMonitor
    return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom


def taskbar_visible():
    """任务栏当前是否显示：自动隐藏收起/被系统隐藏时，露出部分不足一半即视为不可见。"""
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    if not tray or not user32.IsWindowVisible(tray):
        return False
    r = wintypes.RECT()
    user32.GetWindowRect(tray, ctypes.byref(r))
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(tray, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    vw = min(r.right, m.right) - max(r.left, m.left)
    vh = min(r.bottom, m.bottom) - max(r.top, m.top)
    return vw > 0 and vh > 0 and vw * vh * 2 >= (r.right - r.left) * (r.bottom - r.top)


class BLURBEHIND(ctypes.Structure):
    _fields_ = [("flags", wintypes.DWORD), ("enable", wintypes.BOOL),
                ("rgn", wintypes.HANDLE), ("transition", wintypes.BOOL)]


ctypes.windll.gdi32.CreateRectRgn.restype = wintypes.HANDLE
ctypes.windll.gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
ctypes.windll.dwmapi.DwmEnableBlurBehindWindow.argtypes = [wintypes.HWND, ctypes.POINTER(BLURBEHIND)]


def see_through(hwnd):
    """配合 DwmExtendFrameIntoClientArea 开启逐像素透明：空区域的 blur-behind 不产生模糊，
    但让 DWM 按像素 alpha 合成。只扩展框架时 Win11 会把透明区画成纯黑。"""
    rgn = ctypes.windll.gdi32.CreateRectRgn(0, 0, -1, -1)
    ctypes.windll.dwmapi.DwmEnableBlurBehindWindow(hwnd, ctypes.byref(BLURBEHIND(0x1 | 0x2, 1, rgn, 0)))  # ENABLE|BLURREGION
    ctypes.windll.gdi32.DeleteObject(rgn)


def keep_on_top():
    # 每秒强制位置/尺寸并置顶（点击任务栏后系统会把任务栏提到最前）
    HWND_TOPMOST, NOACTIVATE = -1, 0x0010
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000
    pad = [0, 0]
    saved = db.get_setting("x")
    cur_x = int(saved) if saved else None
    last_x = None
    hidden = False
    was_down = False
    while True:
        time.sleep(0.05)
        hwnd = user32.FindWindowW(None, TITLE)
        # 点击悬浮窗以外的任何地方：收起面板
        down = any(user32.GetAsyncKeyState(k) & 0x8000 for k in (0x01, 0x02, 0x04))
        if down and not was_down and hwnd:
            p, wr = wintypes.POINT(), wintypes.RECT()
            user32.GetCursorPos(ctypes.byref(p))
            user32.GetWindowRect(hwnd, ctypes.byref(wr))
            if not (wr.left <= p.x < wr.right and wr.top <= p.y < wr.bottom):
                try:
                    win.evaluate_js("collapsePanel()")
                except Exception:
                    pass
        was_down = down
        if user32.GetAsyncKeyState(0x01) & 0x8000:  # 鼠标左键按住 = 正在拖动，不干预
            continue
        if hwnd:
            # 和任务栏同步：全屏 / 任务栏自动隐藏收起时一起隐藏，任务栏出现时恢复
            fs = fullscreen_active() or not taskbar_visible()
            if fs != hidden:
                user32.ShowWindow(hwnd, 0 if fs else 4)  # SW_HIDE / SW_SHOWNOACTIVATE
                hidden = fs
                if not fs:
                    see_through(hwnd)
            if fs:
                continue
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(ctypes.c_int(1)), 4)  # 保持无 Mica
            # 工具窗口：不在任务栏显示图标
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            want = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            if ex != want:
                user32.ShowWindow(hwnd, 0)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, want)
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                see_through(hwnd)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if last_x is not None and abs(r.left - last_x) > 1:  # 用户拖动过：记住新位置
                cur_x = r.left
            x, y, w, h = island_rect(cur_x)
            if x != last_x:
                db.set_setting("x", x)
            last_x = x
            user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w + pad[0], h + pad[1], NOACTIVATE)
            # WinForms 会扣掉边框尺寸，测得差值后补偿
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            pad[0] += w - (r.right - r.left)
            pad[1] += h - (r.bottom - r.top)


if __name__ == "__main__":
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(1)
    saved = db.get_setting("x")
    x, y, _, _ = island_rect(int(saved) if saved else None)
    win = webview.create_window(TITLE, f"http://127.0.0.1:{PORT}/", x=x, y=y, width=W, height=H,
                                js_api=Api(), frameless=True, on_top=True, resizable=True, min_size=(100, 20), transparent=True)

    def make_glass(window):
        """逐像素透明：窗体底色设为黑 + DWM 玻璃扩展，WebView2 的半透明像素才能真正透出桌面。"""
        from System import Action
        from System.Drawing import Color
        time.sleep(2)
        form = window.native
        form.Invoke(Action(lambda: setattr(form, "BackColor", Color.Black)))

        class MARGINS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]

        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(form.Handle.ToInt32(), ctypes.byref(MARGINS(-1, -1, -1, -1)))
        see_through(form.Handle.ToInt32())
        # 关闭 Win11 的 Mica 背景（深色模式下会把透明区域画成深灰色，四角出现黑边）
        ctypes.windll.dwmapi.DwmSetWindowAttribute(form.Handle.ToInt32(), 38, ctypes.byref(ctypes.c_int(1)), 4)
        threading.Thread(target=keep_on_top, daemon=True).start()

    webview.start(make_glass, win)
