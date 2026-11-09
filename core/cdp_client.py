# -*- coding: utf-8 -*-
"""
Module quản lý kết nối Chrome DevTools Protocol (CDP) & Playwright.
Chức năng:
- Kết nối tới Chrome đang chạy port 9222 qua CDP.
- Tự động nhận diện tab NomStead.
- Cố định Viewport 1920x1080 độc lập với kích thước cửa sổ thu nhỏ.
- Khởi tạo CDP Session phục vụ chụp ảnh màn hình ROI siêu tốc.
- Kích hoạt chống Sleep hệ thống Windows (SetThreadExecutionState).
"""

import sys
import time
import ctypes
from playwright.sync_api import sync_playwright
from config.settings import (
    CDP_HOST,
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
    TARGET_KEYWORDS,
    STOP_HOTKEY,
    CDP_RECONNECT_RETRY_DELAY,
    CDP_MAX_RECONNECT_ATTEMPTS,
)

def setup_windows_platform():
    """Cấu hình console UTF-8 và kích hoạt cờ chống Sleep trên Windows"""
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

    try:
        # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) | ES_DISPLAY_REQUIRED (0x00000002)
        ret_state = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)
        return ret_state != 0
    except Exception as e:
        print(f"[Cảnh báo] Lỗi SetThreadExecutionState: {e}")
        return False

def connect_cdp(host=CDP_HOST):
    """
    Kết nối tới trình duyệt Chrome qua CDP.
    Trả về: (playwright_obj, browser, target_page, cdp_session)
    """
    print(f"\n[CDP Client] Đang kết nối tới Chrome Debugging qua {host}...")
    try:
        p = sync_playwright().start()
        browser = p.chromium.connect_over_cdp(host)
    except Exception as e:
        print(f"\n[LỖI KẾT NỐI] Không thể kết nối tới Chrome qua {host}!")
        print(f"Chi tiết: {e}")
        print("\nHƯỚNG DẪN KHẮC PHỤC:")
        print("1. Hãy đóng toàn bộ cửa sổ Chrome đang chạy.")
        print("2. Chạy file 'start_chrome_debug.bat' để mở Chrome hỗ trợ điều khiển ngầm.")
        print("3. Đăng nhập game NomStead (nomstead.com/qn) rồi chạy lại tool.")
        return None, None, None, None

    contexts = browser.contexts
    if not contexts:
        print("[LỖI] Không tìm thấy context trình duyệt nào.")
        return p, browser, None, None

    # Tìm kiếm tab NomStead
    target_page = None
    for pg in contexts[0].pages:
        url = pg.url.lower()
        title = pg.title().lower()
        if any(kw in url or kw in title for kw in TARGET_KEYWORDS):
            target_page = pg
            break

    if not target_page:
        if contexts[0].pages:
            print("  [Cảnh báo] Chưa thấy tab NomStead rõ ràng, chọn tab đầu tiên...")
            target_page = contexts[0].pages[0]
        else:
            print("[LỖI] Không có tab nào đang mở trong Chrome.")
            return p, browser, None, None

    try:
        target_page.bring_to_front()
    except Exception:
        pass

    print(f"  ==> Đã kết nối tab: '{target_page.title()}' ({target_page.url})")

    # Giữ nguyên Native Viewport tự nhiên của Chrome, không can thiệp để tránh giật khung hình
    print("  ==> Giữ nguyên Native Viewport của Chrome (không gọi set_viewport_size để chống giật màn hình)...")

    try:
        vp_info = target_page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        print(f"  ==> Native CSS Viewport: {vp_info.get('innerWidth')}x{vp_info.get('innerHeight')}, DevicePixelRatio (DPR): {vp_info.get('dpr')}")
    except Exception as e:
        print(f"  [Lưu ý khi lấy thông số Viewport] {e}")

    # Khởi tạo CDP Session để chụp ROI siêu tốc và lưu trữ trực tiếp vào target_page
    cdp = contexts[0].new_cdp_session(target_page)
    target_page._cdp_session = cdp
    try:
        cdp._target_page = target_page
    except Exception:
        pass
    print("  ==> CDP Session đã sẵn sàng và gắn trực tiếp vào target_page._cdp_session.")

    return p, browser, target_page, cdp

def get_cdp_session(page):
    """
    Lấy hoặc khởi tạo CDP session gắn liền với page nếu chưa có hoặc bị mất kết nối.
    """
    if hasattr(page, "_cdp_session") and page._cdp_session is not None:
        return page._cdp_session
    try:
        cdp = page.context.new_cdp_session(page)
        page._cdp_session = cdp
        try:
            cdp._target_page = page
        except Exception:
            pass
        return cdp
    except Exception as e:
        print(f"  [Lỗi get_cdp_session] {e}")
        return None

def close_cdp(playwright_obj, browser):
    """Đóng an toàn kết nối Chrome CDP"""
    try:
        if browser:
            browser.close()
        if playwright_obj:
            playwright_obj.stop()
    except Exception:
        pass

def is_stop_requested():
    """Kiểm tra xem người dùng có nhấn tổ hợp phím dừng an toàn (Ctrl+Shift+Q) hay không"""
    try:
        import keyboard
        return keyboard.is_pressed(STOP_HOTKEY) or (
            keyboard.is_pressed('ctrl') and keyboard.is_pressed('shift') and keyboard.is_pressed('q')
        )
    except Exception:
        return False

def reconnect_cdp(playwright_obj, browser, host=CDP_HOST, max_retries=CDP_MAX_RECONNECT_ATTEMPTS):
    """
    Tự động kết nối lại CDP khi bị ngắt kết nối hoặc gặp lỗi mạng/trình duyệt.
    Đóng connection cũ an toàn, sau đó thử kết nối lại tối đa max_retries lần.
    """
    close_cdp(playwright_obj, browser)
    for attempt in range(1, max_retries + 1):
        if is_stop_requested():
            return None, None, None, None
        print(f"  [Auto-Reconnect CDP] Đang thử kết nối lại (Lần {attempt}/{max_retries})...")
        new_p, new_b, new_page, new_cdp = connect_cdp(host=host)
        if new_page and new_cdp:
            return new_p, new_b, new_page, new_cdp
        time.sleep(CDP_RECONNECT_RETRY_DELAY)
    return None, None, None, None
