"""Native Windows notification-area icon, with no additional runtime dependency.

The hidden window shares Tk's UI thread and message loop. Callbacks only enqueue
actions; all Tk calls happen from App.poll_tray, outside the native window proc.
"""
import ctypes as c
from ctypes import wintypes as w
import logging
from pathlib import Path
import queue

user = c.WinDLL("user32", use_last_error=True)
shell = c.WinDLL("shell32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
LRESULT = c.c_ssize_t
WNDPROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
CLASS = "FabWatch.TrayWindow"
CALLBACK, SHOW = 0x8001, 0x8002


class WindowClass(c.Structure):
    _fields_ = [("style", w.UINT), ("proc", WNDPROC), ("cls_extra", c.c_int),
                ("wnd_extra", c.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
                ("cursor", w.HANDLE), ("brush", w.HANDLE), ("menu", w.LPCWSTR), ("name", w.LPCWSTR)]


class NotifyData(c.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT),
                ("uFlags", w.UINT), ("uCallbackMessage", w.UINT), ("hIcon", w.HICON),
                ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
                ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64),
                ("dwInfoFlags", w.DWORD), ("guidItem", c.c_byte * 16), ("hBalloonIcon", w.HICON)]


def signature(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = result, args
    return fn


signature(kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)
signature(user, "RegisterClassW", w.ATOM, c.POINTER(WindowClass))
signature(user, "UnregisterClassW", w.BOOL, w.LPCWSTR, w.HINSTANCE)
signature(user, "CreateWindowExW", w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
          c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID)
signature(user, "DefWindowProcW", LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
signature(user, "DestroyWindow", w.BOOL, w.HWND)
signature(user, "FindWindowW", w.HWND, w.LPCWSTR, w.LPCWSTR)
signature(user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
signature(user, "RegisterWindowMessageW", w.UINT, w.LPCWSTR)
signature(user, "LoadImageW", w.HANDLE, w.HINSTANCE, w.LPCWSTR, w.UINT, c.c_int, c.c_int, w.UINT)
signature(user, "DestroyIcon", w.BOOL, w.HICON)
signature(user, "CreatePopupMenu", w.HMENU)
signature(user, "AppendMenuW", w.BOOL, w.HMENU, w.UINT, c.c_size_t, w.LPCWSTR)
signature(user, "DestroyMenu", w.BOOL, w.HMENU)
signature(user, "GetCursorPos", w.BOOL, c.POINTER(w.POINT))
signature(user, "SetForegroundWindow", w.BOOL, w.HWND)
signature(user, "TrackPopupMenu", w.UINT, w.HMENU, w.UINT, c.c_int, c.c_int, c.c_int, w.HWND, w.LPVOID)
signature(shell, "Shell_NotifyIconW", w.BOOL, w.DWORD, c.POINTER(NotifyData))


def show_existing():
    hwnd = user.FindWindowW(CLASS, None)
    if hwnd:
        user.PostMessageW(hwnd, SHOW, 0, 0)


class TrayIcon:
    def __init__(self):
        self.events = queue.Queue()
        self.hwnd = self.icon = None
        self.ready = False
        self.instance = kernel.GetModuleHandleW(None)
        self.callback = WNDPROC(self.dispatch)
        self.restart = user.RegisterWindowMessageW("TaskbarCreated")
        self.wc = WindowClass(proc=self.callback, instance=self.instance, name=CLASS)
        self.atom = user.RegisterClassW(c.byref(self.wc))
        try:
            if not self.atom:
                raise c.WinError(c.get_last_error())
            self.hwnd = user.CreateWindowExW(0, CLASS, "Fab Watch", 0, 0, 0, 0, 0,
                                           None, None, self.instance, None)
            if not self.hwnd:
                raise c.WinError(c.get_last_error())
            self.icon = user.LoadImageW(None, str(Path(__file__).with_name("fab-watch.ico")), 1, 32, 32, 0x10)
            if not self.icon:
                raise c.WinError(c.get_last_error())
            self.data = NotifyData(cbSize=c.sizeof(NotifyData), hWnd=self.hwnd, uID=1,
                                   uFlags=7, uCallbackMessage=CALLBACK, hIcon=self.icon,
                                   szTip="Fab Watch · Double-click to open")
            self.ready = bool(shell.Shell_NotifyIconW(0, c.byref(self.data)))
            if not self.ready:
                raise OSError("Windows could not add the Fab Watch tray icon")
        except Exception:
            logging.exception("Tray icon unavailable; closing the window will exit the interface")
            self.close()

    def dispatch(self, hwnd, message, wp, lp):
        try:
            if message == self.restart and hasattr(self, "data"):
                self.ready = bool(shell.Shell_NotifyIconW(0, c.byref(self.data)))
            elif message == SHOW or (message == CALLBACK and lp == 0x203):
                self.events.put("show")
            elif message == CALLBACK and lp == 0x205:
                self.menu(hwnd)
        except Exception:
            logging.exception("Tray action failed")
        return user.DefWindowProcW(hwnd, message, wp, lp)

    def menu(self, hwnd):
        menu = user.CreatePopupMenu()
        try:
            for number, title in ((1, "Open Fab Watch"), (2, "Refresh now"),
                                  (3, "Exit interface (checks continue)")):
                user.AppendMenuW(menu, 0, number, title)
            point = w.POINT()
            user.GetCursorPos(c.byref(point))
            user.SetForegroundWindow(hwnd)
            chosen = user.TrackPopupMenu(menu, 0x100 | 2, point.x, point.y, 0, hwnd, None)
            if chosen in (1, 2, 3):
                self.events.put({1: "show", 2: "refresh", 3: "exit"}[chosen])
            user.PostMessageW(hwnd, 0, 0, 0)
        finally:
            user.DestroyMenu(menu)

    def close(self):
        if hasattr(self, "data"):
            shell.Shell_NotifyIconW(2, c.byref(self.data))
        self.ready = False
        if self.hwnd:
            user.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.icon:
            user.DestroyIcon(self.icon)
            self.icon = None
        if self.atom:
            user.UnregisterClassW(CLASS, self.instance)
            self.atom = None
