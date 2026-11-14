# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Xác nhận Câu trúng/hụt và Hiển thị Log Chuẩn xác (Task 3):
1. verify_harvest_or_banner nhận diện cụm chữ cố định "and I got" và các biến thể regex.
2. Tầng xác thực giảm thể lực song song.
3. Trả về 'miss' khi không câu được sau timeout.
4. Kiểm thử log_catch_success và log_catch_miss.
"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from core.energy import verify_harvest_or_banner
from core.logger import log_catch_success, log_catch_miss
import core


class TestCatchVerification(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()
        self.fake_screen = np.zeros((1080, 1920, 3), dtype=np.uint8)

    @patch("core.energy.check_banners_fast", return_value=None)
    @patch("core.energy.get_current_energy", return_value=None)
    @patch("core.energy.has_ocr", return_value=True)
    def test_01_verify_harvest_detects_and_i_got_phrase(
        self, mock_has_ocr, mock_get_energy, mock_banners
    ):
        """Nhận diện chính xác cụm chữ cố định 'and I got' qua regex ghép toàn bộ OCR boxes"""
        test_ocr_boxes = [
            # Case A: Tách 2 box
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "The water was calm,", 0.95),
             ([[0, 0], [10, 0], [10, 10], [0, 10]], "and I got Salmon!", 0.98)],
            # Case B: Chữ I bị OCR nhận diện nhầm thành số 1
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "and 1 got Trout!", 0.90)],
            # Case C: Chữ I bị OCR nhận diện nhầm thành chữ l thường
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "and l got Bass!", 0.90)],
            # Case D: Tách rời từng từ
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "and", 0.95),
             ([[0, 0], [10, 0], [10, 10], [0, 10]], "I", 0.95),
             ([[0, 0], [10, 0], [10, 10], [0, 10]], "got", 0.95),
             ([[0, 0], [10, 0], [10, 10], [0, 10]], "Carp", 0.95)],
        ]

        for boxes in test_ocr_boxes:
            mock_ocr_engine = MagicMock(return_value=(boxes, None))
            with patch("core.energy.get_ocr_engine", return_value=mock_ocr_engine), \
                 patch("core.energy.grab_page_bgr", return_value=self.fake_screen):
                res = verify_harvest_or_banner(self.mock_page, timeout=0.2, pre_energy=50)
                self.assertEqual(res, 'success', f"Thất bại khi nhận diện OCR boxes: {boxes}")

    @patch("core.energy.check_banners_fast", return_value=None)
    @patch("core.energy.has_ocr", return_value=False)
    def test_02_verify_harvest_detects_energy_drop(self, mock_has_ocr, mock_banners):
        """Xác thực thành công qua tầng kiểm tra giảm thể lực song song (pre=50 -> cur=48)"""
        with patch("core.energy.get_current_energy", return_value=48), \
             patch("core.energy.grab_page_bgr", return_value=self.fake_screen):
            res = verify_harvest_or_banner(self.mock_page, timeout=0.2, pre_energy=50)
            self.assertEqual(res, 'success')

    @patch("core.energy.check_banners_fast", return_value=None)
    @patch("core.energy.get_current_energy", return_value=50)
    @patch("core.energy.has_ocr", return_value=True)
    def test_03_verify_harvest_returns_miss_on_timeout(
        self, mock_has_ocr, mock_get_energy, mock_banners
    ):
        """Trả về 'miss' khi hết timeout mà không thấy banner thu hoạch và thể lực không đổi"""
        mock_ocr_engine = MagicMock(return_value=([], None))
        with patch("core.energy.get_ocr_engine", return_value=mock_ocr_engine), \
             patch("core.energy.grab_page_bgr", return_value=self.fake_screen):
            res = verify_harvest_or_banner(self.mock_page, timeout=0.2, pre_energy=50)
            self.assertEqual(res, 'miss')

    def test_04_logger_and_core_export_log_catch_miss(self):
        """Kiểm tra export log_catch_miss trong core và core.logger"""
        self.assertTrue(hasattr(core, "log_catch_miss"))
        self.assertTrue(callable(core.log_catch_miss))

    @patch("builtins.print")
    def test_05_log_formats(self, mock_print):
        """Kiểm tra định dạng log chuẩn xác cho câu thành công và câu hụt"""
        log_catch_success(5)
        mock_print.assert_called()
        success_output = mock_print.call_args[0][0]
        self.assertIn("CÂU THÀNH CÔNG!", success_output)
        self.assertIn("HO 5", success_output)

        mock_print.reset_mock()
        log_catch_miss(5)
        mock_print.assert_called()
        miss_output = mock_print.call_args[0][0]
        self.assertIn("Giật hụt cá (Miss) tại HO 5", miss_output)

    @patch("core.energy.check_banners_fast", return_value=None)
    def test_06_dom_verify_detects_and_i_got(self, mock_banners):
        """DOM Fast-Path: Nhận diện thành công khi DOM xuất hiện 'and I got'"""
        page = MagicMock()
        page.evaluate.side_effect = [
            None,  # initial_toast
            {'toast': 'the water was calm, and i got salmon!', 'energy': 48, 'xp': 362285}
        ]
        res = verify_harvest_or_banner(page, timeout=0.5, pre_energy=49)
        self.assertEqual(res, 'success')

    @patch("core.energy.check_banners_fast", return_value=None)
    def test_07_dom_verify_detects_empty(self, mock_banners):
        """DOM Fast-Path: Nhận diện hồ cạn khi DOM xuất hiện 'nothing left'"""
        page = MagicMock()
        page.evaluate.side_effect = [
            None,
            {'toast': 'nothing left to catch here right now...', 'energy': 48, 'xp': 362284}
        ]
        res = verify_harvest_or_banner(page, timeout=0.5, pre_energy=48)
        self.assertEqual(res, 'empty')

    @patch("core.energy.check_banners_fast", return_value=None)
    def test_08_dom_verify_detects_trash(self, mock_banners):
        """DOM Fast-Path: Nhận diện câu trúng rác khi DOM xuất hiện 'trash'"""
        page = MagicMock()
        page.evaluate.side_effect = [
            None,
            {'toast': 'i pulled up some trash...', 'energy': 48, 'xp': 362284}
        ]
        res = verify_harvest_or_banner(page, timeout=0.5, pre_energy=48)
        self.assertEqual(res, 'trash')

    @patch("core.energy.check_banners_fast", return_value=None)
    def test_09_dom_verify_detects_energy(self, mock_banners):
        """DOM Fast-Path: Nhận diện thiếu thể lực khi DOM xuất hiện 'insufficient'"""
        page = MagicMock()
        page.evaluate.side_effect = [
            None,
            {'toast': 'your energy level is insufficient.', 'energy': 1, 'xp': 362284}
        ]
        res = verify_harvest_or_banner(page, timeout=0.5, pre_energy=1)
        self.assertEqual(res, 'energy')

    @patch("core.energy.check_banners_fast", return_value=None)
    def test_10_dom_verify_detects_energy_drop(self, mock_banners):
        """DOM Fast-Path: Nhận diện thành công khi thể lực giảm qua DOM"""
        page = MagicMock()
        page.evaluate.side_effect = [
            None,
            {'toast': '', 'energy': 47, 'xp': 362284}
        ]
        res = verify_harvest_or_banner(page, timeout=0.5, pre_energy=48)
        self.assertEqual(res, 'success')

    @patch("core.energy.check_banners_fast", return_value=None)
    def test_11_dom_verify_stale_toast_ignored(self, mock_banners):
        """Stale Toast Guard: Bỏ qua toast cũ có từ trước cú giật nếu nội dung không đổi"""
        page = MagicMock()
        stale_text = 'the water was calm, and i got salmon!'
        page.evaluate.side_effect = [
            stale_text,  # initial_toast có sẵn từ trước
            {'toast': stale_text, 'energy': 48, 'xp': 362284},
            {'toast': stale_text, 'energy': 48, 'xp': 362284},
        ]
        with patch("core.energy.has_ocr", return_value=False):
            res = verify_harvest_or_banner(page, timeout=0.15, pre_energy=48)
            self.assertEqual(res, 'miss')

    def test_12_get_energy_dom_and_fallback(self):
        """Kiểm tra get_energy: ưu tiên DOM và fallback sang OCR khi không có page"""
        from core.energy import get_energy
        mock_page = MagicMock()
        mock_page.evaluate.return_value = 52
        self.assertEqual(get_energy(page=mock_page), 52)

        with patch("core.energy.get_current_energy", return_value=45):
            self.assertEqual(get_energy(page=None, screen_bgr=self.fake_screen), 45)


if __name__ == '__main__':
    unittest.main()
