import ctypes
import win32con
import win32gui
import win32ui
from PIL import Image, ImageGrab

PW_RENDERFULLCONTENT = 2
OFFSCREEN_MARGIN = 100


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def enum_windows(exclude=()):
    """可視でタイトルありのトップレベルウインドウ [(hwnd, title)]"""
    result = []

    def cb(hwnd, _):
        if hwnd in exclude or not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if title.strip():
            result.append((hwnd, title))
        return True

    win32gui.EnumWindows(cb, None)
    return result


def find_by_title(part, exclude=()):
    part = part.lower()
    for hwnd, title in enum_windows(exclude):
        if part in title.lower() or title.lower() in part:
            return hwnd
    return None


def is_valid(hwnd):
    return bool(hwnd) and win32gui.IsWindow(hwnd)


def get_rect(hwnd):
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    return [l, t, r - l, b - t]


def capture_window(hwnd):
    """PrintWindow で取得。失敗時は画面から ImageGrab。最小化中は None。"""
    if not is_valid(hwnd) or win32gui.IsIconic(hwnd):
        return None
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None
    hwnd_dc = mfc_dc = save_dc = bmp = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        ok = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if ok:
            bits = bmp.GetBitmapBits(True)
            return Image.frombuffer("RGB", (w, h), bits, "raw", "BGRX", 0, 1)
    except Exception:
        pass
    finally:
        try:
            if bmp:
                win32gui.DeleteObject(bmp.GetHandle())
            if save_dc:
                save_dc.DeleteDC()
            if mfc_dc:
                mfc_dc.DeleteDC()
            if hwnd_dc:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass
    try:
        return ImageGrab.grab(bbox=(l, t, r, b), all_screens=True).convert("RGB")
    except Exception:
        return None


def park_window(hwnd, edge=False):
    """画面外（edge=True なら右下端に少し残す）へ退避。元の [x,y,w,h] を返す。"""
    rect = get_rect(hwnd)
    vx = ctypes.windll.user32.GetSystemMetrics(76)
    vy = ctypes.windll.user32.GetSystemMetrics(77)
    vw = ctypes.windll.user32.GetSystemMetrics(78)
    vh = ctypes.windll.user32.GetSystemMetrics(79)
    if edge:
        x, y = vx + vw - 8, vy + vh - 8
    else:
        x, y = vx + vw + OFFSCREEN_MARGIN, vy + vh + OFFSCREEN_MARGIN
    win32gui.SetWindowPos(
        hwnd, 0, x, y, 0, 0,
        win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
    return rect


def restore_window(hwnd, rect):
    x, y, w, h = rect
    win32gui.SetWindowPos(
        hwnd, 0, x, y, w, h, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
