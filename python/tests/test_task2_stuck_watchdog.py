# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Task 2: Watchdog 30s Kẹt Cần -> Tự động F5 (Reload) lại web và phục hồi trạng thái game.
Kiểm tra:
1. Cấu hình STUCK_ROD_TIMEOUT = 30.0 và PAGE_RELOAD_WAIT_SEC = 6.0 trong config/settings.py
2. Hàm reload_and_recover_game() trong core/watchdog.py và export qua core/__init__.py
3. Kịch bản reload_and_recover_game: reload, tạo new_cdp, clean modal, travel_to_bookmark
4. Tích hợp và logic kích hoạt Watchdog 30s trong auto_fish_background.py
"""

import sys
import os
import time
import unittest
from unittest.mock import MagicMock, patch

# Đảm bảo root path trong sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config.settings as settings
import core.watchdog as watchdog
import core


class TestTask2StuckWatchdog(unittest.TestCase):

    def test_settings_configuration(self):
        """1. Kiểm tra các hằng số cấu hình STUCK_ROD_TIMEOUT và PAGE_RELOAD_WAIT_SEC"""
        self.assertTrue(hasattr(settings, 'STUCK_ROD_TIMEOUT'), "Thiếu hằng số STUCK_ROD_TIMEOUT trong config/settings.py")
        self.assertEqual(settings.STUCK_ROD_TIMEOUT, 30.0, "STUCK_ROD_TIMEOUT phải bằng 30.0s")

        self.assertTrue(hasattr(settings, 'PAGE_RELOAD_WAIT_SEC'), "Thiếu hằng số PAGE_RELOAD_WAIT_SEC trong config/settings.py")
        self.assertEqual(settings.PAGE_RELOAD_WAIT_SEC, 6.0, "PAGE_RELOAD_WAIT_SEC phải bằng 6.0s")
        print("  [PASS] Cấu hình settings.py đầy đủ và chính xác (30.0s timeout, 6.0s reload wait).")

    def test_watchdog_exports(self):
        """2. Kiểm tra xuất bản reload_and_recover_game trong core/watchdog.py và core/__init__.py"""
        self.assertTrue(hasattr(watchdog, 'reload_and_recover_game'), "Thiếu reload_and_recover_game trong core/watchdog.py")
        self.assertTrue(callable(watchdog.reload_and_recover_game), "reload_and_recover_game phải là callable")

        self.assertTrue(hasattr(core, 'reload_and_recover_game'), "Thiếu reload_and_recover_game trong core/__init__.py")
        self.assertIs(core.reload_and_recover_game, watchdog.reload_and_recover_game)
        print("  [PASS] Hàm reload_and_recover_game đã được xuất bản chính xác ở cả core.watchdog và core.")

    @patch('core.watchdog.time.sleep')
    @patch('core.watchdog.ensure_clean_pond_state')
    def test_reload_and_recover_game_full_flow(self, mock_clean_modal, mock_sleep):
        """3. Kiểm tra toàn bộ luồng hoạt động chuẩn của reload_and_recover_game"""
        mock_page = MagicMock()
        mock_old_cdp = MagicMock(name="old_cdp")
        mock_new_cdp = MagicMock(name="new_cdp")
        mock_page.context.new_cdp_session.return_value = mock_new_cdp

        with patch('core.navigation.travel_to_bookmark') as mock_travel:
            # Test với hồ thứ 1 (current_bookmark_idx = 0 -> target_pond = 1)
            result_cdp = watchdog.reload_and_recover_game(
                mock_page,
                cdp=mock_old_cdp,
                current_bookmark_idx=0
            )

            # 1. page.reload được gọi với đúng tham số
            mock_page.reload.assert_called_once_with(wait_until="domcontentloaded", timeout=45000)

            # 2. time.sleep chờ PAGE_RELOAD_WAIT_SEC (6.0s)
            mock_sleep.assert_called_once_with(settings.PAGE_RELOAD_WAIT_SEC)

            # 3. Tạo new_cdp_session và gắn vào page._cdp_session
            mock_page.context.new_cdp_session.assert_called_once_with(mock_page)
            self.assertEqual(mock_page._cdp_session, mock_new_cdp)

            # 4. Làm sạch trạng thái modal
            mock_clean_modal.assert_called_once_with(mock_page)

            # 5. Di chuyển quay lại đúng hồ hiện tại (idx 0 -> HO 1)
            mock_travel.assert_called_once_with(mock_page, 1, scroll_top_first=True)

            # 6. Trả về new_cdp
            self.assertIs(result_cdp, mock_new_cdp)

        print("  [PASS] reload_and_recover_game thực hiện đầy đủ 6 bước phục hồi thành công.")

    @patch('core.watchdog.time.sleep')
    @patch('core.watchdog.ensure_clean_pond_state')
    def test_reload_and_recover_game_fallback_cdp(self, mock_clean_modal, mock_sleep):
        """4. Kiểm tra fallback trả về cdp cũ khi context.new_cdp_session ném ngoại lệ"""
        mock_page = MagicMock()
        mock_old_cdp = MagicMock(name="old_cdp")
        mock_page.context.new_cdp_session.side_effect = Exception("CDP connection failed")

        with patch('core.navigation.travel_to_bookmark') as mock_travel:
            result_cdp = watchdog.reload_and_recover_game(
                mock_page,
                cdp=mock_old_cdp,
                current_bookmark_idx=None
            )

            # Không nổ exception, fallback về old_cdp
            self.assertIs(result_cdp, mock_old_cdp)
            # current_bookmark_idx is None -> không gọi travel_to_bookmark
            mock_travel.assert_not_called()

        print("  [PASS] reload_and_recover_game fallback an toàn khi gặp sự cố tạo CDP session mới.")

    def test_auto_fish_background_integration(self):
        """5. Kiểm tra mã nguồn auto_fish_background.py có tích hợp đầy đủ Watchdog 30s"""
        bg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'auto_fish_background.py'))
        with open(bg_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Kiểm tra import
        self.assertIn("STUCK_ROD_TIMEOUT", content, "Thiếu import STUCK_ROD_TIMEOUT trong auto_fish_background.py")
        self.assertIn("reload_and_recover_game", content, "Thiếu import reload_and_recover_game trong auto_fish_background.py")

        # Kiểm tra biến pond_active_timer
        self.assertIn("pond_active_timer = time.time()", content, "Thiếu khởi tạo/reset pond_active_timer trong auto_fish_background.py")

        # Kiểm tra log thông báo
        self.assertIn("[WATCHDOG 30S]", content, "Thiếu log nhận diện [WATCHDOG 30S]")
        self.assertIn("Kích hoạt F5 (Reload)", content, "Thiếu log 'Kích hoạt F5 (Reload)'")

        # Kiểm tra điều kiện kích hoạt 30s
        self.assertIn("time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT", content,
                      "Thiếu điều kiện kiểm tra ngưỡng STUCK_ROD_TIMEOUT")

        # Kiểm tra gọi reload_and_recover_game
        self.assertIn("reload_and_recover_game(target_page, cdp=cdp, current_bookmark_idx=current_bookmark_idx)", content,
                      "Thiếu lời gọi reload_and_recover_game")

        print("  [PASS] auto_fish_background.py tích hợp hoàn chỉnh cơ chế Watchdog 30s Kẹt Cần.")


if __name__ == '__main__':
    unittest.main()
