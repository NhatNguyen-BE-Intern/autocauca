# -*- coding: utf-8 -*-
"""
Module Quản lý Thời gian (Scheduler & Anti-Detection):
- Quản lý nhịp nghỉ giải lao ngẫu nhiên (Micro-breaks 15-30s) chống AI anti-cheat.
- Canh chính xác các mốc giờ Reset cá của Server (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h).
- Tự động quay về HO 1 ngay khi Server reset mẻ cá mới.
- Tự động tạm dừng chờ đợi khi đã hoàn thành trọn vẹn cả 40 hồ câu.
"""

import time
import datetime
import random

from config.settings import (
    TOTAL_BOOKMARKS,
    RESET_HOURS,
    AFK_PONDS_MIN,
    AFK_PONDS_MAX,
    AFK_DURATION_MIN,
    AFK_DURATION_MAX,
    RESET_PRE_RELOAD_MINUTES,
    KEEP_ALIVE_INTERVAL_SEC,
)
from core.cdp_client import is_stop_requested
from core.navigation import travel_to_bookmark
from core.logger import log_break, log_wait_reset, log_info, log_debug

# Biến trạng thái nội bộ
_ponds_visited_since_break = 0
_next_break_threshold = random.randint(AFK_PONDS_MIN, AFK_PONDS_MAX)
_last_reset_hour_triggered = -1

def maybe_take_micro_break():
    """Tự động nghỉ ngơi ngẫu nhiên 15-35 giây sau mỗi 5-8 hồ để giả lập hành vi người thật"""
    global _ponds_visited_since_break, _next_break_threshold
    _ponds_visited_since_break += 1
    if _ponds_visited_since_break >= _next_break_threshold:
        pause_sec = random.uniform(AFK_DURATION_MIN, AFK_DURATION_MAX)
        log_break(pause_sec)
        end_time = time.time() + pause_sec
        while time.time() < end_time:
            if is_stop_requested():
                return
            time.sleep(0.5)
        _ponds_visited_since_break = 0
        _next_break_threshold = random.randint(AFK_PONDS_MIN, AFK_PONDS_MAX)

def get_next_reset_datetime():
    """Tính thời điểm giờ Reset tiếp theo (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h)"""
    now = datetime.datetime.now()
    for h in RESET_HOURS:
        candidate = now.replace(hour=h, minute=0, second=15, microsecond=0)
        if candidate > now:
            return candidate
    tomorrow = now + datetime.timedelta(days=1)
    return tomorrow.replace(hour=RESET_HOURS[0], minute=0, second=15, microsecond=0)

def wait_until_next_reset_hour(page=None):
    """
    Đứng yên tại chỗ chờ đến giờ Reset tiếp theo khi đã câu hết cả 40 hồ:
    - Keep-alive micro-ping mỗi KEEP_ALIVE_INTERVAL_SEC (10 phút) để giữ kết nối Chrome CDP.
    - Tự động reload_and_recover_game trước giờ Reset 2 phút (RESET_PRE_RELOAD_MINUTES)
      để nhân vật đã sẵn sàng đứng tại HO 1 lúc 00s (khi cá vừa reset).
    """
    global _last_reset_hour_triggered
    target_time = get_next_reset_datetime()
    log_wait_reset(target_time.strftime('%H:%M:%S'))

    last_keep_alive = time.time()
    pre_reloaded = False

    while datetime.datetime.now() < target_time:
        if is_stop_requested():
            return False
        remaining = int((target_time - datetime.datetime.now()).total_seconds())

        # 1. Thông báo đếm ngược mỗi phút
        if remaining % 60 == 0 and remaining > 0:
            log_info(f"⏳ Đang chờ giờ Reset ({target_time.strftime('%H:%M')})... Còn {remaining // 60} phút.")

        # 2. Keep-alive định kỳ mỗi 10 phút (KEEP_ALIVE_INTERVAL_SEC = 600)
        if time.time() - last_keep_alive >= KEEP_ALIVE_INTERVAL_SEC:
            last_keep_alive = time.time()
            if page is not None:
                try:
                    page.evaluate("() => console.log('keep_alive_ping')")
                    log_debug("Keep-alive micro-ping gửi tới browser thành công.")
                except Exception:
                    pass

        # 3. Tự động reload & chuẩn bị trước giờ Reset 2 phút (RESET_PRE_RELOAD_MINUTES * 60)
        if page is not None and not pre_reloaded and remaining <= (RESET_PRE_RELOAD_MINUTES * 60):
            pre_reloaded = True
            log_info(f"🌟 Còn {remaining // 60} phút tới mốc Reset ({target_time.strftime('%H:%M')})! Tải lại trang web và sẵn sàng tại HO 1...")
            try:
                from core.watchdog import reload_and_recover_game
                reload_and_recover_game(page, current_bookmark_idx=0)
            except Exception as e:
                log_debug(f"Lỗi pre-reload reset: {e}")

        time.sleep(1)

    log_info(f"🌟 Đã tới giờ Reset ({target_time.strftime('%H:%M')})! Bắt đầu chu kỳ câu 40 hồ mới...")
    _last_reset_hour_triggered = target_time.hour
    return True

def check_server_reset_hour(page, current_bookmark_idx):
    """Nếu đang câu dở ở các hồ sau mà đồng hồ bước qua giờ Reset -> Quay về HO 1"""
    global _last_reset_hour_triggered
    now = datetime.datetime.now()
    if now.hour in RESET_HOURS and now.minute < 15:
        if _last_reset_hour_triggered != now.hour:
            _last_reset_hour_triggered = now.hour
            if current_bookmark_idx > 0:
                log_info(f"🌟 Đã điểm giờ Reset ({now.hour}:00)! Lập tức quay về HO 1...")
                travel_to_bookmark(page, 1, scroll_top_first=True)
                return True
    return False
