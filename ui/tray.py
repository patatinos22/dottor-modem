import ctypes
from ctypes import wintypes
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_DESTROY = 0x0002
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 42
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002
NIIF_ERROR = 0x00000003

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

ID_OPEN = 1001
ID_SPEEDTEST = 1002
ID_DNS = 1003
ID_EXIT = 1004

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", POINT)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def _create_circle_hicon(r: int, g: int, b: int) -> wintypes.HICON:
    size = 16
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = size
    bmi.biHeight = -size
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    bits = ctypes.c_void_p()
    hdc = user32.GetDC(None)
    hbm_color = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    user32.ReleaseDC(None, hdc)

    if not hbm_color or not bits.value:
        return user32.LoadIconW(None, ctypes.cast(32512, wintypes.LPCWSTR))

    buf = (ctypes.c_uint32 * (size * size)).from_address(bits.value)
    cx = cy = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist <= 5.4:
                px = (0xFF << 24) | (r << 16) | (g << 8) | b
            elif dist <= 7.0:
                px = (0xFF << 24) | (0xF8 << 16) | (0xFA << 8) | 0xFC
            else:
                px = 0x00000000
            buf[y * size + x] = px

    hbm_mask = gdi32.CreateBitmap(size, size, 1, 1, None)
    ii = ICONINFO(fIcon=True, xHotspot=0, yHotspot=0, hbmMask=hbm_mask, hbmColor=hbm_color)
    hicon = user32.CreateIconIndirect(ctypes.byref(ii))
    gdi32.DeleteObject(hbm_color)
    if hbm_mask:
        gdi32.DeleteObject(hbm_mask)
    return hicon


class WinSystemTray:
    COLORS = {"ok": (16, 185, 129), "warn": (245, 158, 11), "err": (239, 68, 68)}

    def __init__(self, on_open, on_speedtest, on_cycle_dns, on_exit) -> None:
        self.on_open = on_open
        self.on_speedtest = on_speedtest
        self.on_cycle_dns = on_cycle_dns
        self.on_exit = on_exit
        self.hwnd: wintypes.HWND | None = None
        self.icons: dict[str, wintypes.HICON] = {}
        self.current_state = "ok"
        self.active = False
        self._wnd_proc_ref = WNDPROC(self._wnd_proc)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        try:
            hinst = kernel32.GetModuleHandleW(None)
            cls_name = "DottorModemTrayClass_v10"
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wnd_proc_ref
            wc.hInstance = hinst
            wc.lpszClassName = cls_name
            user32.RegisterClassExW(ctypes.byref(wc))

            self.hwnd = user32.CreateWindowExW(0, cls_name, "DottorModemTray", 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self.hwnd:
                return

            for key, rgb in self.COLORS.items():
                self.icons[key] = _create_circle_hicon(*rgb)

            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = self.icons["ok"]
            nid.szTip = "Dottor Modem — Connessione Attiva"

            if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                self.active = True

            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self.active = False

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            ev = lparam & 0xFFFF
            if ev in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.on_open()
            elif ev == WM_RBUTTONUP:
                self._show_context_menu(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_context_menu(self, hwnd) -> None:
        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return
        user32.AppendMenuW(hmenu, MF_STRING, ID_OPEN, "Apri Dottor Modem")
        user32.AppendMenuW(hmenu, MF_STRING, ID_SPEEDTEST, "Misura Velocità (5s)")
        user32.AppendMenuW(hmenu, MF_STRING, ID_DNS, "Cambia DNS Rapido")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, ID_EXIT, "Esci")

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(hmenu)

        if cmd == ID_OPEN:
            self.on_open()
        elif cmd == ID_SPEEDTEST:
            self.on_speedtest()
        elif cmd == ID_DNS:
            self.on_cycle_dns()
        elif cmd == ID_EXIT:
            self.on_exit()

    def update_status(self, state: str, tooltip: str) -> None:
        if not self.active or not self.hwnd:
            return
        st = state if state in self.icons else "ok"
        self.current_state = st
        try:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_ICON | NIF_TIP
            nid.hIcon = self.icons[st]
            nid.szTip = tooltip[:126]
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def notify(self, title: str, message: str, level: str = "info") -> None:
        if not self.active or not self.hwnd:
            return
        flag = NIIF_ERROR if level == "err" else (NIIF_WARNING if level == "warn" else NIIF_INFO)
        try:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_INFO
            nid.szInfoTitle = title[:62]
            nid.szInfo = message[:250]
            nid.dwInfoFlags = flag
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def stop(self) -> None:
        if self.hwnd:
            try:
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = self.hwnd
                nid.uID = 1
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                user32.PostMessageW(self.hwnd, WM_DESTROY, 0, 0)
            except Exception:
                pass
        for hicon in self.icons.values():
            try:
                user32.DestroyIcon(hicon)
            except Exception:
                pass
        self.icons.clear()
        self.active = False
