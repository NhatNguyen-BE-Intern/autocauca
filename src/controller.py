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
    """Configures UTF-8 console, PyAutoGUI, anti-sleep flags, and desktop thread."""
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
# 2. WINDOW FOCUSING
# =========================================================================
def focus_game_window():
    """Tự động tìm và đưa cửa sổ NomStead hoặc Chrome lên màn hình trước và click kích hoạt."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(cur_thread, fg_thread, True)

        found_hwnd = None

        def enum_cb(h, _):
            nonlocal found_hwnd
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                title = buf.value
                if 'NomStead' in title or 'Chrome' in title:
                    user32.ShowWindow(h, 9)  # SW_RESTORE
                    user32.BringWindowToTop(h)
                    user32.SetForegroundWindow(h)
                    found_hwnd = h
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        user32.AttachThreadInput(cur_thread, fg_thread, False)

        if found_hwnd and found_hwnd != fg_hwnd:
            time.sleep(0.2)
            # Click an toàn ở góc trái màn hình để kích hoạt focus
            pyautogui.click(200, 180)
            time.sleep(0.2)
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
