# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Cỗ máy Tự phục hồi Bất tử (Immortal Watchdog & Ổn định 24/24) - Task B3:
- Kiểm tra các hằng số cấu hình Task B3
- Kiểm tra cleanup_old_debug_files (chỉ giữ tối đa 25 file ảnh mới nhất, giải phóng RAM)
- Kiểm tra save_session_state & load_session_state (khôi phục tiến độ khi bot restart)
- Kiểm tra dismiss_unexpected_popups (tự động đóng popup Claim, OK, Close...)
- Kiểm tra get_or_refresh_cdp_session (tự động khôi phục CDP session khi detach/stale)
- Bảo toàn tuyệt đối Anti-Detection
"""
import sys
import time
import json
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings as settings
from core.watchdog import (
    cleanup_old_debug_files,
    save_session_state,
    load_session_state,
    dismiss_unexpected_popups,
    ensure_clean_pond_state,
)
from core.cdp_client import get_or_refresh_cdp_session

class TestImmortalWatchdog(unittest.TestCase):

    def test_01_settings_constants(self):
        """Kiểm tra các hằng số Task B3"""
        self.assertEqual(settings.MAX_DEBUG_FILES, 25)
        self.assertEqual(settings.SESSION_STATE_FILE.name, "session_state.json")
        self.assertEqual(settings.RESET_PRE_RELOAD_MINUTES, 2)
        self.assertEqual(settings.KEEP_ALIVE_INTERVAL_SEC, 600)

    def test_02_cleanup_old_debug_files(self):
        """Kiểm tra dọn dẹp ảnh cũ trong thư mục debug, chỉ giữ tối đa 25 file mới nhất"""
        temp_dir = Path(tempfile.mkdtemp(prefix="test_debug_cleanup_"))
        try:
            # Tạo 30 file ảnh với thời gian sửa đổi khác nhau
            now = time.time()
            created_files = []
            for i in range(30):
                f = temp_dir / f"screen_{i:02d}.png"
                f.write_text("dummy image data")
                mtime = now - (30 - i) * 10
                # Set mtime
                import os
                os.utime(f, (mtime, mtime))
                created_files.append(f)

            self.assertEqual(len(list(temp_dir.glob("*.png"))), 30)

            # Gọi cleanup_old_debug_files với max_files=25
            cleanup_old_debug_files(debug_dir=temp_dir, max_files=25)

            remaining_files = list(temp_dir.glob("*.png"))
            self.assertEqual(len(remaining_files), 25, "Chỉ được giữ lại chính xác 25 file mới nhất!")

            # 5 file cũ nhất (00 đến 04) phải bị xóa
            for i in range(5):
                self.assertFalse((temp_dir / f"screen_{i:02d}.png").exists())
            # 25 file mới nhất (05 đến 29) phải còn tồn tại
            for i in range(5, 30):
                self.assertTrue((temp_dir / f"screen_{i:02d}.png").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_03_save_and_load_session_state(self):
        """Kiểm tra lưu và tải trạng thái phiên làm việc (Session State Persistence)"""
        temp_file = Path(tempfile.mktemp(suffix=".json", prefix="test_session_"))
        try:
            # Lưu state
            success = save_session_state(lake_num=18, fish_count=35, bread_eaten=4, filepath=temp_file)
            self.assertTrue(success)
            self.assertTrue(temp_file.exists())

            # Đọc lại state hợp lệ
            data = load_session_state(max_age_sec=7200, filepath=temp_file)
            self.assertIsNotNone(data)
            self.assertEqual(data["lake_num"], 18)
            self.assertEqual(data["fish_count"], 35)
            self.assertEqual(data["bread_eaten"], 4)

            # Kiểm tra hết hạn: max_age_sec = 0.001s
            time.sleep(0.01)
            expired_data = load_session_state(max_age_sec=0.001, filepath=temp_file)
            self.assertIsNone(expired_data, "Dữ liệu quá hạn max_age phải trả về None!")
        finally:
            if temp_file.exists():
                temp_file.unlink()

    def test_04_dismiss_unexpected_popups(self):
        """Kiểm tra tự động phát hiện và click đóng các popup bất ngờ (Claim, OK...)"""
        mock_page = MagicMock()
        def mock_loc(sel):
            m = MagicMock()
            if 'Claim' in sel:
                m.first.is_visible.return_value = True
            else:
                m.first.is_visible.return_value = False
            return m
        mock_page.locator.side_effect = mock_loc

        with patch("core.watchdog.is_island_info_or_bookmark_modal_open", return_value=False), \
             patch("core.watchdog.bg_click_locator", return_value=True) as mock_click:
            dismissed = dismiss_unexpected_popups(mock_page)
            self.assertTrue(dismissed)
            mock_click.assert_called_once()

    def test_05_get_or_refresh_cdp_session(self):
        """Kiểm tra tự động kiểm tra và làm mới CDP session khi bị stale hoặc detach"""
        mock_page = MagicMock()

        # Case A: Session đang sống tốt (ping evaluate thành công)
        alive_session = MagicMock()
        alive_session.send.return_value = {"result": {"value": 2}}
        mock_page._cdp_session = alive_session

        res = get_or_refresh_cdp_session(mock_page)
        self.assertEqual(res, alive_session)
        alive_session.send.assert_called_with("Runtime.evaluate", {"expression": "1+1"})

        # Case B: Session bị stale (ném Exception khi send) -> Tự tạo session mới
        stale_session = MagicMock()
        stale_session.send.side_effect = Exception("Session detached!")
        mock_page._cdp_session = stale_session

        new_session = MagicMock()
        mock_page.context.new_cdp_session.return_value = new_session

        res_refreshed = get_or_refresh_cdp_session(mock_page)
        self.assertEqual(res_refreshed, new_session)
        self.assertEqual(mock_page._cdp_session, new_session)

if __name__ == "__main__":
    unittest.main()
