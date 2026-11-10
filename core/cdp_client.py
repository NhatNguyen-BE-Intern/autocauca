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
from core.logger import log_debug, log_info, log_warning, log_error, log_success

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
        log_debug(f"Lỗi SetThreadExecutionState: {e}")
        return False

def connect_cdp(host=CDP_HOST):
    """
    Kết nối tới trình duyệt Chrome qua CDP.
    Trả về: (playwright_obj, browser, target_page, cdp_session)
    """
    log_info("Đang kết nối tới trình duyệt Chrome qua CDP...")
    try:
        p = sync_playwright().start()
        browser = p.chromium.connect_over_cdp(host)
    except Exception as e:
        log_error(f"Không thể kết nối tới Chrome qua {host} ({e})")
        log_info("Hướng dẫn: Chạy start_chrome_debug.bat rồi đăng nhập nomstead.com/qn")
        return None, None, None, None

    contexts = browser.contexts
    if not contexts:
        log_error("Không tìm thấy context trình duyệt nào.")
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
            log_warning("Chưa thấy tab NomStead rõ ràng, chọn tab đầu tiên...")
            target_page = contexts[0].pages[0]
        else:
            log_error("Không có tab nào đang mở trong Chrome.")
            return p, browser, None, None

    try:
        target_page.bring_to_front()
    except Exception:
        pass

    log_success(f"Đã kết nối tab game: '{target_page.title()}'")

    # Giữ nguyên Native Viewport tự nhiên của Chrome, không can thiệp để tránh giật khung hình
    log_debug("Giữ nguyên Native Viewport của Chrome (không gọi set_viewport_size)...")

    try:
        vp_info = target_page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        log_debug(f"Native CSS Viewport: {vp_info.get('innerWidth')}x{vp_info.get('innerHeight')}, DPR: {vp_info.get('dpr')}")
    except Exception as e:
        log_debug(f"Lưu ý khi lấy thông số Viewport: {e}")

    # Khởi tạo CDP Session để chụp ROI siêu tốc và lưu trữ trực tiếp vào target_page
    cdp = contexts[0].new_cdp_session(target_page)
    target_page._cdp_session = cdp
    try:
        cdp._target_page = target_page
    except Exception:
        pass
    log_debug("CDP Session đã sẵn sàng và gắn trực tiếp vào target_page._cdp_session.")

    return p, browser, target_page, cdp

def get_or_refresh_cdp_session(page):
    """
    Tự động kiểm tra và phục hồi CDP session tại chỗ nếu bị detach hoặc stale:
    - Nếu page đã có _cdp_session, gửi ping thử nghiệm nhỏ (Runtime.evaluate 1+1).
    - Nếu lệnh thành công, trả về session hiện tại.
    - Nếu thất bại (stale/detached) hoặc session là None:
      Khởi tạo session mới qua page.context.new_cdp_session(page),
      gắn lại vào page._cdp_session và trả về session mới.
    """
    if page is None:
        return None

    cur_cdp = getattr(page, "_cdp_session", None)
    if cur_cdp is not None:
        try:
            # Ping thử nghiệm kiểm tra tính sống còn của session
            res = cur_cdp.send("Runtime.evaluate", {"expression": "1+1"})
            if res and "result" in res:
                return cur_cdp
        except Exception as e:
            log_debug(f"CDP session cũ bị stale/detach ({e}). Đang tái tạo session mới...")

    try:
        if hasattr(page, "context") and page.context:
            new_cdp = page.context.new_cdp_session(page)
            page._cdp_session = new_cdp
            try:
                new_cdp._target_page = page
            except Exception:
                pass
            log_debug("Đã khởi tạo và làm mới CDP session thành công.")
            return new_cdp
    except Exception as e:
        log_debug(f"Lỗi khi refresh CDP session: {e}")
        return None

    return None

def get_cdp_session(page):
    """
    Lấy hoặc khởi tạo CDP session gắn liền với page nếu chưa có hoặc bị mất kết nối.
    """
    return get_or_refresh_cdp_session(page)

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
        log_warning(f"Mất kết nối CDP -> Thử kết nối lại (Lần {attempt}/{max_retries})...")
        new_p, new_b, new_page, new_cdp = connect_cdp(host=host)
        if new_page and new_cdp:
            return new_p, new_b, new_page, new_cdp
        time.sleep(CDP_RECONNECT_RETRY_DELAY)
    return None, None, None, None
