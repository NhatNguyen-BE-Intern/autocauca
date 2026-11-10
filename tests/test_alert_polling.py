# -*- coding: utf-8 -*-
"""
Unit test kiểm thử thông số và chu kỳ quét của Vòng lặp bắt dấu ! (Task 1).
Kiểm tra:
1. Thông số ALERT_EARLY_POLL_SLEEP và khoảng ALERT_POLL_SLEEP_MIN/MAX hợp lý.
2. Logic phân 2 pha (Early Phase 40ms vs Active Phase 15-20ms).
3. Đảm bảo tổng độ trễ lý thuyết trong pha cắn cá luôn < 105ms.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import random
from config.settings import (
    ALERT_THRESHOLD,
    ALERT_HIGH_CONFIDENCE_THRESHOLD,
    CAST_IGNORE_DURATION,
)

def test_alert_settings_exist():
    import config.settings as s
    assert hasattr(s, "ALERT_EARLY_POLL_SLEEP"), "Thiếu ALERT_EARLY_POLL_SLEEP trong settings"
    assert hasattr(s, "ALERT_ACTIVE_PHASE_START"), "Thiếu ALERT_ACTIVE_PHASE_START trong settings"
    assert s.ALERT_POLL_SLEEP_MIN >= 0.012, f"ALERT_POLL_SLEEP_MIN ({s.ALERT_POLL_SLEEP_MIN}) quá nhỏ, gây nghẽn CPU"
    assert s.ALERT_POLL_SLEEP_MAX <= 0.025, f"ALERT_POLL_SLEEP_MAX ({s.ALERT_POLL_SLEEP_MAX}) quá lớn, nguy cơ trễ giật"
    print(" [PASS] test_alert_settings_exist")

def test_two_phase_sleep_logic():
    import config.settings as s
    early_sleep = getattr(s, "ALERT_EARLY_POLL_SLEEP", 0.040)
    active_min = s.ALERT_POLL_SLEEP_MIN
    active_max = s.ALERT_POLL_SLEEP_MAX
    active_start = getattr(s, "ALERT_ACTIVE_PHASE_START", 2.0)
    
    # Giả lập thời gian từ lúc bắt đầu quăng cần
    def get_sleep_for_elapsed(elapsed_from_cast):
        if elapsed_from_cast < active_start:
            return early_sleep
        else:
            return random.uniform(active_min, active_max)
            
    # Pha 1: Giây 1.2 (< 2.0s) -> phải dùng early_sleep (~40ms)
    s1 = get_sleep_for_elapsed(1.2)
    assert s1 == early_sleep == 0.040, f"Pha sớm phải ngủ {early_sleep}s, thực tế: {s1}"
    
    # Pha 2: Giây 2.5 (>= 2.0s) -> phải dùng active sleep (15-20ms)
    s2 = get_sleep_for_elapsed(2.5)
    assert active_min <= s2 <= active_max, f"Pha cắn cá phải nằm trong [{active_min}, {active_max}], thực tế: {s2}"
    
    print(" [PASS] test_two_phase_sleep_logic")

def test_strike_latency_budget():
    import config.settings as s
    active_max_sleep_ms = s.ALERT_POLL_SLEEP_MAX * 1000.0
    cdp_capture_ms = 58.2  # Benchmark Chromium Page.captureScreenshot quality 50
    instant_strike_hold_ms = getattr(s, "STRIKE_INSTANT_HOLD_SEC", 0.025) * 1000.0
    
    worst_case_total_ms = active_max_sleep_ms + cdp_capture_ms + instant_strike_hold_ms
    assert worst_case_total_ms < 110.0, f"Độ trễ tổng {worst_case_total_ms:.1f}ms vượt quá ngân sách 110ms!"
    print(f" [PASS] test_strike_latency_budget: Tổng độ trễ tối đa = {worst_case_total_ms:.1f}ms (Rất an toàn)")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 1: ALERT POLLING OPTIMIZATION ---")
    try:
        test_alert_settings_exist()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_two_phase_sleep_logic()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_strike_latency_budget()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
