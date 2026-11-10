# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Bộ bảo vệ an toàn (Safety Guards - Task 1):
1. Chống click Remove bookmark / Bookmark (bg_click_locator).
2. Tự động nhận diện bảng thông tin đảo / Bookmark modal (is_island_info_or_bookmark_modal_open).
3. Kiểm tra tổng quát modal che màn hình (is_any_modal_open).
4. Tự động đóng bảng đảo/modal bằng Cancel/Escape (dismiss_unexpected_popups).
"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from config.settings import FORBIDDEN_CLICK_TEXTS
from core.virtual_input import bg_click_locator
from core.watchdog import (
    is_island_info_or_bookmark_modal_open,
    is_any_modal_open,
    dismiss_unexpected_popups,
)


class TestSafetyGuards(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    def test_01_forbidden_texts_configuration(self):
        """Kiểm tra cấu hình FORBIDDEN_CLICK_TEXTS đầy đủ các từ khóa nguy hiểm"""
        self.assertIn("remove bookmark", FORBIDDEN_CLICK_TEXTS)
        self.assertIn("bookmark", FORBIDDEN_CLICK_TEXTS)
        self.assertIn("unbookmark", FORBIDDEN_CLICK_TEXTS)
        self.assertIn("delete bookmark", FORBIDDEN_CLICK_TEXTS)

    @patch("core.virtual_input.bg_click")
    def test_02_bg_click_locator_blocks_dangerous_buttons(self, mock_bg_click):
        """bg_click_locator phải từ chối click vào các nút Remove Bookmark, Delete Bookmark, Unbookmark, Bookmark"""
        mock_bg_click.return_value = (100, 200)

        # Test các trường hợp nguy hiểm
        dangerous_cases = [
            {"inner_text": "Remove Bookmark", "aria": None, "title": None},
            {"inner_text": "Unbookmark", "aria": None, "title": None},
            {"inner_text": "Delete Bookmark", "aria": None, "title": None},
            {"inner_text": "Bookmark", "aria": None, "title": None},
            {"inner_text": "Bookmark this island", "aria": None, "title": None},
            {"inner_text": "", "aria": "Remove Bookmark button", "title": None},
            {"inner_text": "", "aria": None, "title": "Delete Bookmark"},
        ]

        for case in dangerous_cases:
            mock_loc = MagicMock()
            mock_loc.is_visible.return_value = True
            mock_loc.inner_text.return_value = case["inner_text"]
            mock_loc.get_attribute.side_effect = lambda attr, timeout=None: case.get("aria") if attr == "aria-label" else case.get("title")
            mock_loc.bounding_box.return_value = {"x": 100, "y": 200, "width": 50, "height": 30}

            result = bg_click_locator(self.mock_page, mock_loc)
            self.assertFalse(result, f"Thất bại: bg_click_locator không được click vào '{case}'")
            mock_bg_click.assert_not_called()

    @patch("core.virtual_input.bg_click")
    def test_03_bg_click_locator_allows_safe_bookmarks_tab(self, mock_bg_click):
        """bg_click_locator phải cho phép click vào tab Bookmarks trong Codex (không chặn nhầm tab)"""
        mock_bg_click.return_value = (200, 300)

        safe_cases = [
            {"inner_text": "Bookmarks", "aria": "Bookmarks Tab"},
            {"inner_text": "Tab Bookmarks", "aria": None},
            {"inner_text": "Cancel", "aria": "Cancel dialog"},
            {"inner_text": "Close", "aria": "Close modal"},
        ]

        for case in safe_cases:
            mock_loc = MagicMock()
            mock_loc.is_visible.return_value = True
            mock_loc.inner_text.return_value = case["inner_text"]
            mock_loc.get_attribute.side_effect = lambda attr, timeout=None: case.get("aria") if attr == "aria-label" else None
            mock_loc.bounding_box.return_value = {"x": 200, "y": 300, "width": 60, "height": 25}

            result = bg_click_locator(self.mock_page, mock_loc)
            self.assertTrue(result, f"Thất bại: bg_click_locator phải cho phép click vào '{case}'")
            mock_bg_click.assert_called()
            mock_bg_click.reset_mock()

    def test_04_is_island_info_or_bookmark_modal_open_detection(self):
        """Kiểm tra nhận diện bảng thông tin đảo hoặc modal bookmark đang mở"""
        # Case 1: Có nút Remove Bookmark visible
        mock_loc_dangerous = MagicMock()
        mock_loc_dangerous.is_visible.return_value = True

        mock_page = MagicMock()
        def mock_locator(sel):
            mock = MagicMock()
            if 'Remove Bookmark' in sel:
                mock.first.is_visible.return_value = True
            else:
                mock.first.is_visible.return_value = False
            return mock
        mock_page.locator.side_effect = mock_locator
        mock_page.evaluate.return_value = False

        self.assertTrue(is_island_info_or_bookmark_modal_open(mock_page))

        # Case 2: Không có modal nào mở
        def mock_locator_clean(sel):
            mock = MagicMock()
            mock.first.is_visible.return_value = False
            return mock
        mock_page.locator.side_effect = mock_locator_clean
        mock_page.evaluate.return_value = False

        self.assertFalse(is_island_info_or_bookmark_modal_open(mock_page))

    @patch("core.watchdog.is_codex_open")
    def test_05_is_any_modal_open(self, mock_is_codex_open):
        """Kiểm tra is_any_modal_open phát hiện tất cả các dạng modal che màn hình"""
        mock_page = MagicMock()

        # Case 1: Island modal mở
        with patch("core.watchdog.is_island_info_or_bookmark_modal_open", return_value=True):
            self.assertTrue(is_any_modal_open(mock_page))

        # Case 2: Codex modal mở
        with patch("core.watchdog.is_island_info_or_bookmark_modal_open", return_value=False):
            mock_is_codex_open.return_value = True
            self.assertTrue(is_any_modal_open(mock_page))

        # Case 3: DOM dialog mở
        with patch("core.watchdog.is_island_info_or_bookmark_modal_open", return_value=False):
            mock_is_codex_open.return_value = False
            mock_page.evaluate.return_value = True
            self.assertTrue(is_any_modal_open(mock_page))

        # Case 4: Màn hình hoàn toàn sạch
        with patch("core.watchdog.is_island_info_or_bookmark_modal_open", return_value=False):
            mock_is_codex_open.return_value = False
            mock_page.evaluate.return_value = False
            self.assertFalse(is_any_modal_open(mock_page))

    @patch("core.watchdog.bg_click_locator")
    def test_06_dismiss_unexpected_popups_prioritizes_escape_and_cancel(self, mock_bg_click_loc):
        """dismiss_unexpected_popups phải bấm Escape khi có modal bookmark và click Cancel/Close an toàn"""
        mock_page = MagicMock()

        # Khi phát hiện island/bookmark modal: Bấm Escape ngay
        with patch("core.watchdog.is_island_info_or_bookmark_modal_open", side_effect=[True, False]):
            mock_page.locator.return_value.first.is_visible.return_value = False
            res = dismiss_unexpected_popups(mock_page)
            self.assertTrue(res)
            mock_page.keyboard.press.assert_called_with('Escape')

        # Khi có nút Cancel visible: Click nút Cancel an toàn
        mock_page.reset_mock()
        mock_bg_click_loc.return_value = True
        with patch("core.watchdog.is_island_info_or_bookmark_modal_open", return_value=False):
            def mock_loc(sel):
                m = MagicMock()
                if 'Cancel' in sel:
                    m.first.is_visible.return_value = True
                else:
                    m.first.is_visible.return_value = False
                return m
            mock_page.locator.side_effect = mock_loc
            res = dismiss_unexpected_popups(mock_page)
            self.assertTrue(res)
            mock_bg_click_loc.assert_called()


if __name__ == '__main__':
    unittest.main()
