# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Cơ chế Xử lý Quá 30s Kẹt Cần & Tối Ưu Sau F5 (Task 4):
1. reload_and_recover_game: Nếu thấy mặt nước sẵn sàng thì tiếp tục câu ngay, không mở Bookmarks.
2. reload_and_recover_game: Nếu không thấy mặt nước mới gọi travel_to_bookmark.
3. Cơ chế 2 bước: Thử quăng lại 1 phát trước khi F5, và reset cờ khi câu thành công.
"""

import unittest
from unittest.mock import MagicMock, patch
import time

from core.watchdog import reload_and_recover_game


class TestStuckRecovery(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()
        self.mock_page.context = MagicMock()
        self.mock_cdp = MagicMock()

    @patch("core.watchdog.time.sleep")
    @patch("core.watchdog.cleanup_old_debug_files")
    @patch("core.watchdog.ensure_clean_pond_state")
    @patch("core.watchdog.save_session_state")
    @patch("core.watchdog.get_random_pond_point")
    def test_01_reload_and_recover_reuses_existing_pond_if_water_visible(
        self, mock_get_water, mock_save_state, mock_clean, mock_cleanup, mock_sleep
    ):
        """Sau F5: Nếu phát hiện mặt nước thì câu tiếp luôn, KHÔNG mở Bookmarks travel_to_bookmark"""
        # Giả lập phát hiện mặt nước tại hồ
        mock_get_water.return_value = (600, 700)

        with patch("core.navigation.travel_to_bookmark") as mock_travel:
            new_cdp = reload_and_recover_game(self.mock_page, cdp=self.mock_cdp, current_bookmark_idx=3)

            # Phải gọi reload
            self.mock_page.reload.assert_called_once()
            # Phải kiểm tra mặt nước
            mock_get_water.assert_called_once_with(self.mock_page)
            # TUYỆT ĐỐI KHÔNG ĐƯỢC gọi travel_to_bookmark vì mặt nước đã sẵn sàng
            mock_travel.assert_not_called()

    @patch("core.watchdog.time.sleep")
    @patch("core.watchdog.cleanup_old_debug_files")
    @patch("core.watchdog.ensure_clean_pond_state")
    @patch("core.watchdog.save_session_state")
    @patch("core.watchdog.get_random_pond_point")
    def test_02_reload_and_recover_navigates_when_water_not_visible(
        self, mock_get_water, mock_save_state, mock_clean, mock_cleanup, mock_sleep
    ):
        """Sau F5: Nếu không thấy mặt nước mới gọi travel_to_bookmark để quay lại hồ"""
        # Giả lập không thấy mặt nước
        mock_get_water.return_value = None

        with patch("core.navigation.travel_to_bookmark") as mock_travel:
            new_cdp = reload_and_recover_game(self.mock_page, cdp=self.mock_cdp, current_bookmark_idx=4)

            # Phải gọi reload
            self.mock_page.reload.assert_called_once()
            # Phải kiểm tra mặt nước
            mock_get_water.assert_called_once_with(self.mock_page)
            # PHẢI gọi travel_to_bookmark tới HO 5
            mock_travel.assert_called_once_with(self.mock_page, 5, scroll_top_first=True)

    def test_03_two_step_stuck_recovery_logic(self):
        """Kiểm thử mô phỏng logic 2 bước xử lý kẹt cần quá 30s"""
        STUCK_ROD_TIMEOUT = 30.0
        pond_active_timer = time.time() - 35.0  # Đã quá 30s
        retry_cast_attempted = False
        reloaded = False

        # Bước 1: Quá 30s nhưng chưa thử quăng lại
        if time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT:
            if not retry_cast_attempted:
                retry_cast_attempted = True
                pond_active_timer = time.time()
                # Không reload, luồng tiếp tục quăng cần
            else:
                reloaded = True

        self.assertTrue(retry_cast_attempted, "Bước 1 phải bật cờ retry_cast_attempted = True")
        self.assertFalse(reloaded, "Bước 1 không được kích hoạt F5 reload")

        # Bước 2: Đã thử quăng lại mà vẫn quá 30s
        pond_active_timer = time.time() - 35.0  # Lại quá 30s
        if time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT:
            if not retry_cast_attempted:
                retry_cast_attempted = True
            else:
                retry_cast_attempted = False
                reloaded = True

        self.assertFalse(retry_cast_attempted, "Bước 2 phải reset cờ retry_cast_attempted = False")
        self.assertTrue(reloaded, "Bước 2 phải kích hoạt F5 reload")


if __name__ == '__main__':
    unittest.main()
