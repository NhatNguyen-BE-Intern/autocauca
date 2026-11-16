# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Tối ưu Dead-time & Smart Transitions (Task B2):
- Kiểm tra các hằng số cấu hình dead-time
- Kiểm tra hàm wait_for_modal_state (polling thông minh mỗi 100ms)
- Kiểm tra hàm wait_for_pond_arrival (smart scene transition polling)
- Kiểm tra advance_to_next_pond gọi scroll_top_first=False
- Đảm bảo 100% tuân thủ Anti-Detection (MOUSE_HOLD, micro-break, etc.)
"""
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import numpy as np

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings as settings
from core.navigation import (
    WATER_LOWER,
    wait_for_modal_state,
    wait_for_pond_arrival,
    travel_to_bookmark,
)
from auto_fish_background import advance_to_next_pond
import auto_fish_background as bot

class TestSmartTransitions(unittest.TestCase):

    def test_ocr_click_does_not_advance_while_bookmarks_still_cover_the_pond(self):
        import core.navigation as nav
        page = MagicMock()
        with patch.object(nav, 'open_codex_bookmarks_tab', return_value=True), \
             patch.object(nav, '_click_bookmark_link', return_value=None), \
             patch.object(nav, '_click_bookmark_by_ocr', return_value=True), \
             patch.object(nav, 'wait_for_modal_state', side_effect=lambda _, condition, **kw: condition()), \
             patch.object(nav, 'grab_page_bgr'), patch.object(nav, 'is_codex_open', return_value=True), \
             patch.object(nav, 'wait_for_pond_arrival', return_value=True):
            self.assertFalse(travel_to_bookmark(page, 3))

    def test_confirmed_reel_only_waits_for_the_remaining_animation(self):
        with patch.object(bot.time, "perf_counter", return_value=12.0), \
             patch.object(bot.time, "sleep") as sleep, \
             patch.object(bot.random, "uniform", return_value=0.5):
            bot.wait_for_reel(10.0)
            sleep.assert_not_called()
            bot.wait_for_reel(11.75)
            sleep.assert_called_once_with(0.25)

    def test_01_deadtime_constants(self):
        """Kiểm tra các hằng số dead-time cấu hình chuẩn Task B2"""
        self.assertEqual(settings.SCENE_TRANSITION_MIN_WAIT, 0.9)
        self.assertEqual(settings.SCENE_TRANSITION_TIMEOUT, 4.5)
        self.assertEqual(settings.SCENE_TRANSITION_POLL_INTERVAL, 0.15)
        self.assertEqual(settings.MODAL_ACTION_POLL_INTERVAL, 0.10)
        self.assertEqual(settings.MODAL_ACTION_TIMEOUT, 1.2)
        self.assertEqual(settings.POST_CATCH_DELAY_MIN, 0.45)
        self.assertEqual(settings.POST_CATCH_DELAY_MAX, 0.70)

    def test_02_wait_for_modal_state(self):
        """Kiểm tra wait_for_modal_state phản xạ tức thì khi modal mở"""
        # Case A: Modal đã mở ngay lập tức -> Hoàn thành tức thì
        t0 = time.time()
        res = wait_for_modal_state(None, lambda: True, timeout=1.0, interval=0.05)
        self.assertTrue(res)
        self.assertLess(time.time() - t0, 0.25)

        # Case B: Modal mở sau 2 nhịp polling (0.10s)
        counter = {"calls": 0}
        def delayed_open():
            counter["calls"] += 1
            return counter["calls"] >= 3

        t0 = time.time()
        res = wait_for_modal_state(None, delayed_open, timeout=1.0, interval=0.05)
        self.assertTrue(res)
        self.assertGreaterEqual(counter["calls"], 3)
        self.assertLess(time.time() - t0, 0.35)

        # Case C: Modal không mở -> timeout sau đúng khoảng thời gian cấu hình
        t0 = time.time()
        res = wait_for_modal_state(None, lambda: False, timeout=0.20, interval=0.05)
        self.assertFalse(res)
        self.assertGreaterEqual(time.time() - t0, 0.18)

    @patch("core.navigation.grab_page_bgr")
    def test_03_wait_for_pond_arrival_fast(self, grab_frame):
        """Kiểm tra wait_for_pond_arrival tiết kiệm ~2.5s khi mặt nước xuất hiện sau min_wait"""
        grab_frame.return_value = np.full((40, 40, 3), WATER_LOWER, dtype=np.uint8)
        t0 = time.time()
        res = wait_for_pond_arrival(None, min_wait=0.2, timeout=2.0, interval=0.05)
        elapsed = time.time() - t0
        self.assertTrue(res)
        # Phải chờ min_wait (0.2s) nhưng không chờ hết timeout (2.0s)
        self.assertGreaterEqual(elapsed, 0.18)
        self.assertLess(elapsed, 0.45)

    @patch("core.navigation.grab_page_bgr")
    def test_04_wait_for_pond_arrival_timeout_fallback(self, grab_frame):
        """Kiểm tra fallback an toàn khi mạng lag hoặc chưa thấy nước kịp thời"""
        grab_frame.return_value = None
        t0 = time.time()
        res = wait_for_pond_arrival(None, min_wait=0.1, timeout=0.3, interval=0.05)
        elapsed = time.time() - t0
        self.assertTrue(res)  # Vẫn trả về True fallback để tiếp tục tiến trình
        self.assertGreaterEqual(elapsed, 0.28)

    @patch("auto_fish_background.travel_to_bookmark")
    @patch("auto_fish_background.maybe_take_micro_break")
    def test_05_advance_to_next_pond_scroll_optimization(self, mock_break, mock_travel):
        """Kiểm tra advance_to_next_pond truyền scroll_top_first=False để bỏ qua 3 nhịp cuộn ngược"""
        mock_travel.return_value = True
        fake_page = MagicMock()

        with patch.object(bot, "save_session_state"), patch.object(bot, "cleanup_old_debug_files"):
            next_idx = advance_to_next_pond(fake_page, current_idx=2)
        self.assertEqual(next_idx, 3)

        mock_travel.assert_called_once_with(fake_page, 4, scroll_top_first=False)

    def test_06_anti_detection_preservation(self):
        """Bảo toàn tuyệt đối 100% Anti-Detection: Giữ nguyên MOUSE_HOLD và nhịp Micro-AFK"""
        self.assertEqual(settings.MOUSE_HOLD_MIN, 0.045)
        self.assertEqual(settings.MOUSE_HOLD_MAX, 0.105)
        self.assertEqual(settings.FAST_MOUSE_HOLD_MIN, 0.025)
        self.assertEqual(settings.FAST_MOUSE_HOLD_MAX, 0.045)
        self.assertEqual(settings.STRIKE_INSTANT_HOLD_SEC, 0.025)
        self.assertGreaterEqual(settings.AFK_DURATION_MIN, 15.0)
        self.assertLessEqual(settings.AFK_DURATION_MAX, 35.0)

if __name__ == "__main__":
    unittest.main()
