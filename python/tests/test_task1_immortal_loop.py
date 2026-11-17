# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Task 1: Bọc Vòng Lặp Bất Tử 24/24 & Chuyển Phím Tắt Sang Ctrl+Shift+Q.
Kiểm tra:
1. Cấu hình STOP_HOTKEY, CDP_RECONNECT_RETRY_DELAY, CDP_MAX_RECONNECT_ATTEMPTS trong config/settings.py
2. Hàm is_stop_requested() trong core/cdp_client.py
3. Hàm reconnect_cdp() trong core/cdp_client.py (mocked)
4. Sự vắng bóng triệt để của `keyboard.is_pressed('q')` trong auto_fish_background.py, core/scheduler.py, core/navigation.py
5. Cấu trúc Vòng Lặp Bất Tử (Immortal Loop) trong auto_fish_background.py
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Đảm bảo root path trong sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config.settings as settings
from core.cdp_client import is_stop_requested, reconnect_cdp


class TestTask1ImmortalLoop(unittest.TestCase):

    def test_settings_configuration(self):
        """Kiểm tra các biến cấu hình cần thiết trong config/settings.py"""
        self.assertTrue(hasattr(settings, 'STOP_HOTKEY'), "Thiếu biến STOP_HOTKEY trong settings")
        self.assertEqual(settings.STOP_HOTKEY.lower(), 'ctrl+shift+q')

        self.assertTrue(hasattr(settings, 'CDP_RECONNECT_RETRY_DELAY'), "Thiếu biến CDP_RECONNECT_RETRY_DELAY")
        self.assertGreater(settings.CDP_RECONNECT_RETRY_DELAY, 0)

        self.assertTrue(hasattr(settings, 'CDP_MAX_RECONNECT_ATTEMPTS'), "Thiếu biến CDP_MAX_RECONNECT_ATTEMPTS")
        self.assertGreaterEqual(settings.CDP_MAX_RECONNECT_ATTEMPTS, 3)
        print("  [PASS] Cấu hình settings.py chính xác.")

    def test_is_stop_requested(self):
        """Kiểm tra logic nhận diện tổ hợp phím dừng của is_stop_requested"""
        with patch('keyboard.is_pressed') as mock_is_pressed:
            # TH1: Tổ hợp hotkey đầy đủ được nhấn
            mock_is_pressed.side_effect = lambda k: k == settings.STOP_HOTKEY
            self.assertTrue(is_stop_requested())

            # TH2: Cả 3 phím ctrl, shift, q đồng thời được nhấn riêng lẻ
            mock_is_pressed.side_effect = lambda k: k in ('ctrl', 'shift', 'q')
            self.assertTrue(is_stop_requested())

            # TH3: Chỉ nhấn 'q' (không có ctrl/shift) -> Phải trả về False để không ngắt bot khi gõ văn bản
            mock_is_pressed.side_effect = lambda k: k == 'q'
            self.assertFalse(is_stop_requested(), "Chỉ nhấn 'q' không được phép dừng tool!")

            # TH4: Không phím nào được nhấn
            mock_is_pressed.side_effect = lambda k: False
            self.assertFalse(is_stop_requested())

            # TH5: Lỗi phát sinh trong keyboard -> Phải an toàn trả về False
            mock_is_pressed.side_effect = Exception("Driver error")
            self.assertFalse(is_stop_requested())
        print("  [PASS] is_stop_requested() hoạt động chuẩn xác, không bị kích hoạt bởi phím 'q' đơn lẻ.")

    def test_reconnect_cdp_success(self):
        """Kiểm tra reconnect_cdp kết nối lại thành công"""
        mock_p_old = MagicMock()
        mock_b_old = MagicMock()

        mock_p_new = MagicMock()
        mock_b_new = MagicMock()
        mock_page_new = MagicMock()
        mock_cdp_new = MagicMock()

        with patch('core.cdp_client.close_cdp') as mock_close, \
             patch('core.cdp_client.connect_cdp') as mock_connect, \
             patch('core.cdp_client.time.sleep') as mock_sleep:

            # Lần 1 thất bại, lần 2 thành công
            mock_connect.side_effect = [
                (None, None, None, None),
                (mock_p_new, mock_b_new, mock_page_new, mock_cdp_new),
            ]

            p, b, page, cdp = reconnect_cdp(mock_p_old, mock_b_old, max_retries=3)

            mock_close.assert_called_once_with(mock_p_old, mock_b_old)
            self.assertEqual(mock_connect.call_count, 2)
            self.assertIs(p, mock_p_new)
            self.assertIs(b, mock_b_new)
            self.assertIs(page, mock_page_new)
            self.assertIs(cdp, mock_cdp_new)
        print("  [PASS] reconnect_cdp() thử lại và phục hồi thành công.")

    def test_reconnect_cdp_failure(self):
        """Kiểm tra reconnect_cdp khi quá số lần thử tối đa"""
        mock_p_old = MagicMock()
        mock_b_old = MagicMock()

        with patch('core.cdp_client.close_cdp') as mock_close, \
             patch('core.cdp_client.connect_cdp') as mock_connect, \
             patch('core.cdp_client.time.sleep') as mock_sleep:

            mock_connect.return_value = (None, None, None, None)

            p, b, page, cdp = reconnect_cdp(mock_p_old, mock_b_old, max_retries=3)

            mock_close.assert_called_once_with(mock_p_old, mock_b_old)
            self.assertEqual(mock_connect.call_count, 3)
            self.assertIsNone(p)
            self.assertIsNone(b)
            self.assertIsNone(page)
            self.assertIsNone(cdp)
        print("  [PASS] reconnect_cdp() trả về None khi hết số lần thử.")

    def test_no_legacy_q_key_in_target_files(self):
        """Kiểm tra sự vắng bóng triệt để của `keyboard.is_pressed('q')` trong các file mục tiêu"""
        target_files = [
            'auto_fish_background.py',
            'core/scheduler.py',
            'core/navigation.py',
        ]

        for rel_path in target_files:
            abs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel_path))
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Không được chứa keyboard.is_pressed('q') hoặc keyboard.is_pressed("q")
            self.assertNotIn("keyboard.is_pressed('q')", content, f"Vẫn còn keyboard.is_pressed('q') trong {rel_path}")
            self.assertNotIn('keyboard.is_pressed("q")', content, f"Vẫn còn keyboard.is_pressed(\"q\") trong {rel_path}")
            self.assertIn("is_stop_requested", content, f"Chưa tích hợp is_stop_requested trong {rel_path}")
            print(f"  [PASS] {rel_path}: Đã loại bỏ hoàn toàn phím 'q' cũ và tích hợp is_stop_requested.")

    def test_immortal_loop_structure(self):
        """Kiểm tra vòng lặp bất tử trong auto_fish_background.py"""
        bg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'auto_fish_background.py'))
        with open(bg_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Kiểm tra sự hiện diện của các khối thông báo và gọi hàm tự phục hồi
        self.assertIn("reconnect_cdp", content, "Thiếu reconnect_cdp trong auto_fish_background.py")
        self.assertIn("[CẢNH BÁO LỖI HỆ THỐNG]", content, "Thiếu thông báo [CẢNH BÁO LỖI HỆ THỐNG]")
        self.assertIn("[TỰ ĐỘNG PHỤC HỒI]", content, "Thiếu thông báo [TỰ ĐỘNG PHỤC HỒI]")
        self.assertIn("Ctrl + Shift + Q", content, "Thiếu thông báo hướng dẫn Ctrl + Shift + Q")
        print("  [PASS] auto_fish_background.py: Cấu trúc Vòng Lặp Bất Tử 24/24 đầy đủ và hợp lệ.")


if __name__ == '__main__':
    unittest.main()
