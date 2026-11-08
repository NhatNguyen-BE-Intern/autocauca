# -*- coding: utf-8 -*-
"""
NomStead Auto Fishing - Fishing Logic & Reset Scheduler Module
Handles high-framerate alert scanning (~71 FPS), rapid reaction hook strikes,
anti-detection micro-breaks, and server 3-hour reset cycle scheduling.
"""

import time
import datetime
import random
import cv2
import numpy as np
import pyautogui
import keyboard

from src.config import (
    TOTAL_BOOKMARKS,
    RESET_HOURS,
    MAX_FISHING_WAIT,
    ALERT_INTERVAL,
    THRESH_ALERT,
    img_alert_gray
)
from src.controller import tether_mouse
from src.navigation import travel_to_bookmark, check_pond_empty, ensure_clean_pond_state
from src.energy import check_insufficient_energy_and_eat

current_bookmark_idx = 0
ponds_visited_since_break = 0
last_reset_hour_triggered = -1

# =========================================================================
# 1. ALERT (!) SCANNER & FISHING STRIKE (MULTI-RESOLUTION AWARE)
# =========================================================================
_cached_alert_tpls = None
_cached_alert_h = None

def get_scaled_alert_templates(screen_h):
    """Tự động cache các mẫu dấu chấm than theo độ phân giải màn hình (~71 FPS)."""
    global _cached_alert_tpls, _cached_alert_h
    if _cached_alert_h == screen_h and _cached_alert_tpls is not None:
        return _cached_alert_tpls
    if img_alert_gray is None:
        return []

    base_scale = screen_h / 1080.0
    if 0.95 <= base_scale <= 1.05:
        scales = [1.0]
    else:
        scales = [round(base_scale * 0.9, 3), round(base_scale, 3), round(base_scale * 1.1, 3)]

    tpls = []
    for s in scales:
        tw = max(1, int(round(img_alert_gray.shape[1] * s)))
        th = max(1, int(round(img_alert_gray.shape[0] * s)))
        interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR
        scaled = cv2.resize(img_alert_gray, (tw, th), interpolation=interp) if s != 1.0 else img_alert_gray
        tpls.append((scaled, tw, th))

    _cached_alert_tpls = tpls
    _cached_alert_h = screen_h
    return tpls

def find_alert_fast(sct, threshold=THRESH_ALERT):
    """Quét siêu tốc (71+ FPS) dấu chấm than (!) tại ROI trung tâm câu cá (tương thích mọi độ phân giải)."""
    if img_alert_gray is None:
        return None
    mon = sct.monitors[1]
    roi = {
        'left': int(mon['left'] + mon['width'] * 0.35),
        'top': int(mon['top'] + mon['height'] * 0.22),
        'width': int(mon['width'] * 0.30),
        'height': int(mon['height'] * 0.40)
    }
    raw = sct.grab(roi)
    gray_roi = cv2.cvtColor(np.array(raw), cv2.COLOR_BGRA2GRAY)

    tpls = get_scaled_alert_templates(mon['height'])
    for tpl, tw, th in tpls:
        res = cv2.matchTemplate(gray_roi, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            return (roi['left'] + max_loc[0] + tw // 2,
                    roi['top'] + max_loc[1] + th // 2)
    return None

def execute_strike(cast_x, cast_y, reaction_delay=None):
    """Thực hiện giật cần tại tọa độ cast_x, cast_y với độ trễ phản xạ tự nhiên."""
    if reaction_delay is None:
        reaction_delay = random.uniform(0.04, 0.08)
    time.sleep(reaction_delay)

    # Đưa chuột chính xác về vị trí quăng cần
    pyautogui.moveTo(cast_x, cast_y)
    pyautogui.mouseDown()
    time.sleep(0.04)
    pyautogui.mouseUp()
    print(f"  [!] CÁ CẮN CÂU! (Phản xạ: {reaction_delay:.3f}s) -> Đã giật cần tại ({cast_x}, {cast_y})!")

# =========================================================================
# 2. MICRO-BREAKS & SERVER RESET SCHEDULER
# =========================================================================
def maybe_take_micro_break():
    """Tự động nghỉ giải lao ngắn sau 5-8 hồ để chống phát hiện anti-bot."""
    global ponds_visited_since_break
    ponds_visited_since_break += 1
    if ponds_visited_since_break >= random.randint(5, 8):
        pause_sec = random.randint(15, 30)
        print(f"\n[Chống phát hiện] Tạm nghỉ giải lao {pause_sec} giây...")
        for _ in range(pause_sec):
            if keyboard.is_pressed('q'):
                return
            time.sleep(1)
        ponds_visited_since_break = 0

def get_next_reset_datetime():
    """Tính thời điểm giờ Reset tiếp theo (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h)."""
    now = datetime.datetime.now()
    for h in RESET_HOURS:
        candidate = now.replace(hour=h, minute=0, second=15, microsecond=0)
        if candidate > now:
            return candidate
    tomorrow = now + datetime.timedelta(days=1)
    return tomorrow.replace(hour=RESET_HOURS[0], minute=0, second=15, microsecond=0)

def wait_until_next_reset_hour():
    """Đứng yên tại chỗ chờ đến giờ Reset tiếp theo khi đã câu hết cả 40 hồ."""
    global current_bookmark_idx, last_reset_hour_triggered
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
    last_reset_hour_triggered = target_time.hour
    current_bookmark_idx = 0
    return True

def check_server_reset_hour(sct):
    """Nếu đang câu dở ở các hồ sau mà đồng hồ bước qua giờ Reset -> Quay về HO 1."""
    global current_bookmark_idx, last_reset_hour_triggered
    now = datetime.datetime.now()
    if now.hour in RESET_HOURS and now.minute < 15:
        if last_reset_hour_triggered != now.hour:
            last_reset_hour_triggered = now.hour
            if current_bookmark_idx > 0:
                print(f"🌟 Đã điểm giờ Reset ({now.hour}:00)! Lập tức quay về HO 1 (Hồ ngon nhất)!")
                current_bookmark_idx = 0
                travel_to_bookmark(sct, 1, scroll_top_first=True)
                return True
    return False
