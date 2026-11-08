# -*- coding: utf-8 -*-
"""
NomStead Auto Fishing - Controller Module
Handles Windows interactive thread binding, anti-sleep execution state,
game window focusing, and human-like Bezier mouse movement and clicking.
"""

import sys
import time
import math
import random
import ctypes
from ctypes import wintypes
import pyautogui

# =========================================================================
# 1. WINDOWS ENVIRONMENT CONFIGURATION
# =========================================================================
def init_windows_environment():
    """Configures UTF-8 console, DPI awareness, QuickEdit protection, anti-sleep, and desktop thread."""
    if sys.platform == "win32":
        try:
            if sys.stdout and hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if sys.stderr and hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            if sys.stdin and hasattr(sys.stdin, "reconfigure"):
                sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

        # Vô hiệu hóa Windows CMD QuickEdit mode để chống freeze process khi click nhầm vào console
        try:
            kernel32 = ctypes.windll.kernel32
            h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE = -10
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
                # ENABLE_QUICK_EDIT_MODE = 0x0040, ENABLE_EXTENDED_FLAGS = 0x0080
                new_mode = (mode.value & ~0x0040) | 0x0080
                kernel32.SetConsoleMode(h_stdin, new_mode)
        except Exception:
            pass

        # Thiết lập Per-Monitor DPI Aware (2) hoặc Process DPI Aware chống lệch tọa độ MSS / PyAutoGUI
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.01

    try:
        ret_state = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)
        # 0x80000002 = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception as e:
        print(f"[Cảnh báo] Lỗi SetThreadExecutionState: {e}")

    try:
        h_input = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            ctypes.windll.user32.SetThreadDesktop(h_input)
    except Exception as e:
        print(f"[Cảnh báo] Lỗi gán desktop thread: {e}")

# Run initial setup upon import
init_windows_environment()

# =========================================================================
# 2. WINDOW FOCUSING & CONSOLE MANAGEMENT
# =========================================================================
def minimize_console():
    """Thu nhỏ cửa sổ CMD terminal xuống taskbar để không che khuất màn hình game."""
    if sys.platform != "win32":
        return
    try:
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if console_hwnd:
            ctypes.windll.user32.ShowWindow(console_hwnd, 6)  # SW_MINIMIZE = 6
            print("  [Controller] Đã thu nhỏ cửa sổ CMD để đảm bảo tầm nhìn game thông thoáng.")
    except Exception as e:
        print(f"[Cảnh báo] minimize_console error: {e}")

def send_console_to_back():
    """Đưa cửa sổ CMD terminal xuống đáy Z-order."""
    if sys.platform != "win32":
        return
    try:
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if console_hwnd:
            # HWND_BOTTOM = 1, SWP_NOSIZE = 0x0001, SWP_NOMOVE = 0x0002
            ctypes.windll.user32.SetWindowPos(console_hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002)
    except Exception:
        pass

def focus_game_window():
    """
    Tự động tìm và đưa cửa sổ game NomStead hoặc trình duyệt web lên foreground.
    - Tuyệt đối loại trừ cửa sổ CMD Console của tool (`console_hwnd` & `ConsoleWindowClass`).
    - Bỏ qua các cửa sổ có tiêu đề chứa: cmd, powershell, terminal, runner, cauca, auto fish.
    - Nhận diện cửa sổ trình duyệt (Chrome_WidgetWin_1, MozillaWindowClass) hoặc tiêu đề chứa 'nomstead'.
    - Loại bỏ click mù (200, 180) để chống kích hoạt QuickEdit và click ngoài ý muốn.
    """
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        console_hwnd = kernel32.GetConsoleWindow()

        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(cur_thread, fg_thread, True)

        found_hwnd = None
        browser_fallback_hwnd = None

        def enum_cb(h, _):
            nonlocal found_hwnd, browser_fallback_hwnd
            # 1. EXPLICITLY SKIP console_hwnd
            if console_hwnd and h == console_hwnd:
                return True

            if user32.IsWindowVisible(h):
                # 2. Skip ConsoleWindowClass
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(h, class_buf, 256)
                cls_name = class_buf.value
                if cls_name == "ConsoleWindowClass":
                    return True

                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                title = buf.value
                title_lower = title.lower()

                # 3. Skip runner / terminal / powershell / cmd / cauca / auto fish
                skip_keywords = ['cmd', 'powershell', 'terminal', 'runner', 'cauca', 'auto fish']
                if any(k in title_lower for k in skip_keywords):
                    return True

                # 4. Check browser class or title containing NomStead
                is_browser = cls_name in ["Chrome_WidgetWin_1", "MozillaWindowClass"]
                is_nomstead = "nomstead" in title_lower

                if is_nomstead:
                    user32.ShowWindow(h, 9)  # SW_RESTORE
                    user32.BringWindowToTop(h)
                    user32.SetForegroundWindow(h)
                    found_hwnd = h
                    return False
                elif is_browser and browser_fallback_hwnd is None:
                    if any(b in title_lower for b in ['chrome', 'edge', 'brave', 'firefox', 'opera']):
                        browser_fallback_hwnd = h

            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        # Fallback to general browser window if no explicit NomStead title found
        if not found_hwnd and browser_fallback_hwnd:
            user32.ShowWindow(browser_fallback_hwnd, 9)
            user32.BringWindowToTop(browser_fallback_hwnd)
            user32.SetForegroundWindow(browser_fallback_hwnd)
            found_hwnd = browser_fallback_hwnd

        user32.AttachThreadInput(cur_thread, fg_thread, False)

        if found_hwnd and found_hwnd != fg_hwnd:
            time.sleep(0.15)
            # Không click mù vào tọa độ (200, 180) nữa! SetForegroundWindow và BringWindowToTop đã kích hoạt cửa sổ.
    except Exception as e:
        print(f"[Cảnh báo] focus_game_window error: {e}")

# =========================================================================
# 3. HUMAN-LIKE MOUSE MOVEMENT & CLICKING
# =========================================================================
def human_move(target_x, target_y, fast=False):
    """Di chuyển chuột theo đường cong Bezier mô phỏng tay người tự nhiên."""
    start_x, start_y = pyautogui.position()
    dist = math.hypot(target_x - start_x, target_y - start_y)
    if dist < 4:
        return

    curve_mag = min(int(dist * 0.25), 60)
    ctrl_x = (start_x + target_x) / 2 + random.randint(-curve_mag, curve_mag)
    ctrl_y = (start_y + target_y) / 2 + random.randint(-curve_mag, curve_mag)

    steps = random.randint(5, 8) if fast else random.randint(12, 20)
    total_time = random.uniform(0.04, 0.08) if fast else random.uniform(0.14, 0.25)
    sleep_per_step = total_time / steps

    for i in range(1, steps + 1):
        t = i / steps
        bx = int((1 - t)**2 * start_x + 2 * (1 - t) * t * ctrl_x + t**2 * target_x)
        by = int((1 - t)**2 * start_y + 2 * (1 - t) * t * ctrl_y + t**2 * target_y)
        pyautogui.moveTo(bx, by)
        time.sleep(sleep_per_step)

def human_click(x, y, rx=8, ry=8, fast=False, hold_sec=None):
    """Click lệch ngẫu nhiên trong vùng chữ nhật (rx, ry) + giữ chuột tự nhiên, xác thực chống click mù."""
    if x is None or y is None:
        print("  [Cảnh báo] Tọa độ click không hợp lệ (None) -> Hủy bỏ click mù!")
        return None, None
    tx = int(x + random.randint(-rx, rx))
    ty = int(y + random.randint(-ry, ry))
    human_move(tx, ty, fast=fast)

    # Xác thực vị trí con trỏ chuột trước khi nhấn chuột:
    cur_x, cur_y = pyautogui.position()
    if abs(cur_x - tx) > 6 or abs(cur_y - ty) > 6:
        human_move(tx, ty, fast=True)
        pyautogui.moveTo(tx, ty)

    pyautogui.mouseDown()
    if hold_sec is not None:
        time.sleep(hold_sec)
    else:
        time.sleep(random.uniform(0.045, 0.09) if fast else random.uniform(0.06, 0.11))
    pyautogui.mouseUp()
    return tx, ty

def tether_mouse(target_x, target_y, max_drift=15):
    """Giữ chuột không bị trôi quá max_drift pixel so với target."""
    cur_x, cur_y = pyautogui.position()
    if math.hypot(cur_x - target_x, cur_y - target_y) > max_drift:
        pyautogui.moveTo(target_x, target_y)
