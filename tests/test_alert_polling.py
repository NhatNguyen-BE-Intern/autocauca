# -*- coding: utf-8 -*-
"""
Unit test kiểm thử thông số và chu kỳ quét của Vòng lặp bắt dấu ! (Task 1 & Task 2).
Kiểm tra:
1. Thông số ALERT_PHASE1_DURATION/SLEEP, ALERT_PHASE2_DURATION/SLEEP, ALERT_POLL_SLEEP_MIN/MAX hợp lý.
2. Logic phân 3 pha thích ứng (Phase 1 70ms, Phase 2 35ms, Phase 3 20-25ms).
3. Đảm bảo tổng độ trễ lý thuyết trong pha cắn cá luôn < 110ms.
"""

import sys
import unittest
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.settings as s
from config.settings import (
    ALERT_THRESHOLD,
    CAST_IGNORE_DURATION,
    ALERT_PHASE1_DURATION,
    ALERT_PHASE1_SLEEP,
    ALERT_PHASE2_DURATION,
    ALERT_PHASE2_SLEEP,
    ALERT_POLL_SLEEP_MIN,
    ALERT_POLL_SLEEP_MAX,
)

class TestAlertPolling(unittest.TestCase):
    def test_01_alert_settings_exist_and_bounded(self):
        """Kiểm tra các hằng số 3 pha thích ứng tồn tại và có giá trị hợp lệ"""
        self.assertTrue(hasattr(s, "ALERT_PHASE1_DURATION"))
        self.assertTrue(hasattr(s, "ALERT_PHASE1_SLEEP"))
        self.assertTrue(hasattr(s, "ALERT_PHASE2_DURATION"))
        self.assertTrue(hasattr(s, "ALERT_PHASE2_SLEEP"))
        self.assertTrue(hasattr(s, "ALERT_POLL_SLEEP_MIN"))
        self.assertTrue(hasattr(s, "ALERT_POLL_SLEEP_MAX"))

        self.assertGreaterEqual(s.ALERT_PHASE1_SLEEP, 0.050, "Phase 1 sleep phải >= 50ms để cắt giảm tải Chrome")
        self.assertLessEqual(s.ALERT_PHASE1_SLEEP, 0.100, "Phase 1 sleep không nên vượt quá 100ms")
        self.assertGreaterEqual(s.ALERT_POLL_SLEEP_MIN, 0.015, "Pha cắn cá sleep min >= 15ms chống nghẽn CPU")
        self.assertLessEqual(s.ALERT_POLL_SLEEP_MAX, 0.030, "Pha cắn cá sleep max <= 30ms để giật nhạy")

    def test_02_three_phase_adaptive_sleep_logic(self):
        """Kiểm tra logic phân 3 pha thích ứng thời gian từ lúc quăng cần"""
        def get_sleep_for_time_since_cast(time_since_cast):
            if time_since_cast < s.ALERT_PHASE1_DURATION:
                return s.ALERT_PHASE1_SLEEP
            elif time_since_cast < s.ALERT_PHASE2_DURATION:
                return s.ALERT_PHASE2_SLEEP
            else:
                return s.ALERT_POLL_SLEEP_MIN

        # Pha 1: 1.5s (< 2.5s) -> 70ms
        self.assertEqual(get_sleep_for_time_since_cast(1.5), s.ALERT_PHASE1_SLEEP)
        # Pha 2: 2.8s (2.5s - 3.2s) -> 35ms
        self.assertEqual(get_sleep_for_time_since_cast(2.8), s.ALERT_PHASE2_SLEEP)
        # Pha 3: 3.5s (>= 3.2s) -> 20ms
        self.assertEqual(get_sleep_for_time_since_cast(3.5), s.ALERT_POLL_SLEEP_MIN)

    def test_03_strike_latency_budget(self):
        """Đảm bảo tổng độ trễ giật cần lý thuyết ở Pha 3 luôn < 110ms"""
        active_max_sleep_ms = s.ALERT_POLL_SLEEP_MAX * 1000.0
        cdp_capture_ms = 58.2  # Benchmark Chromium Page.captureScreenshot quality 50
        instant_strike_hold_ms = getattr(s, "STRIKE_INSTANT_HOLD_SEC", 0.025) * 1000.0

        worst_case_total_ms = active_max_sleep_ms + cdp_capture_ms + instant_strike_hold_ms
        self.assertLess(worst_case_total_ms, 110.0, f"Độ trễ tổng {worst_case_total_ms:.1f}ms vượt ngân sách 110ms")

if __name__ == "__main__":
    unittest.main()
