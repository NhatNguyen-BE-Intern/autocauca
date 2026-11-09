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
import keyboard

from config.settings import (
    TOTAL_BOOKMARKS,
    RESET_HOURS,
    AFK_PONDS_MIN,
    AFK_PONDS_MAX,
    AFK_DURATION_MIN,
    AFK_DURATION_MAX,
)
from core.navigation import travel_to_bookmark

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
        print(f"\n[Chống phát hiện] Tự động tạm nghỉ giải lao {pause_sec:.1f} giây (sau {_ponds_visited_since_break} hồ)...")
        end_time = time.time() + pause_sec
        while time.time() < end_time:
            if keyboard.is_pressed('q'):
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

def wait_until_next_reset_hour():
    """Đứng yên tại chỗ chờ đến giờ Reset tiếp theo khi đã câu hết cả 40 hồ"""
    global _last_reset_hour_triggered
    target_time = get_next_reset_datetime()
    print(f"\n⏳ ĐÃ CÂU HẾT CẢ {TOTAL_BOOKMARKS} HỒ! Đứng yên tại chỗ chờ giờ Reset ({target_time.strftime('%H:%M:%S')})...")

    while datetime.datetime.now() < target_time:
        if keyboard.is_pressed('q'):
            return False
        remaining = int((target_time - datetime.datetime.now()).total_seconds())
        if remaining % 60 == 0 and remaining > 0:
            print(f"⏳ Đang chờ giờ Reset ({target_time.strftime('%H:%M')})... Còn {remaining // 60} phút.")
        time.sleep(1)

    print(f"🌟 Đã tới giờ Reset ({target_time.strftime('%H:%M')})! Chuẩn bị quay lại HO 1...")
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
                print(f"🌟 Đã điểm giờ Reset ({now.hour}:00)! Lập tức quay về HO 1 (Hồ ngon nhất)!")
                travel_to_bookmark(page, 1, scroll_top_first=True)
                return True
    return False
