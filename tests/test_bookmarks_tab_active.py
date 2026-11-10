# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Cơ chế Chuyển & Xác thực Tab Bookmarks (Giai đoạn E - Task 1):
1. is_bookmarks_tab_active: kiểm tra class 'active' & computed style màu hồng rgb(254, 119, 123),
   đồng thời xác nhận tab 'My tiles' đã inactive.
2. open_codex_bookmarks_tab: 4 attempts retry thông minh.
3. TUYỆT ĐỐI return False nếu sau 4 attempts tab Bookmarks vẫn không active.
4. Kiểm tra hằng số BOOKMARKS_TAB_DEFAULT_CSS_COORD = (707, 214).
"""

import unittest
from unittest.mock import MagicMock, patch

from config.settings import BOOKMARKS_TAB_DEFAULT_CSS_COORD
from core.navigation import is_bookmarks_tab_active, open_codex_bookmarks_tab
import core


class TestBookmarksTabActive(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    def test_01_bookmarks_tab_default_css_coord(self):
        """Tọa độ CSS chuẩn của tab Bookmarks phải là (707, 214)"""
        self.assertEqual(BOOKMARKS_TAB_DEFAULT_CSS_COORD, (707, 214))

    def test_02_is_bookmarks_tab_active_success(self):
        """is_bookmarks_tab_active trả về True khi tab bookmarks active và tab mine inactive"""
        # Case A: evaluate trả về active_bm=True, mine_inactive=True
        self.mock_page.evaluate.side_effect = [True, True]
        self.assertTrue(is_bookmarks_tab_active(self.mock_page))

    def test_03_is_bookmarks_tab_active_failure_cases(self):
        """is_bookmarks_tab_active trả về False khi tab bookmarks chưa active hoặc tab mine còn active"""
        # Case A: Tab bookmarks chưa active
        self.mock_page.evaluate.side_effect = [False]
        self.assertFalse(is_bookmarks_tab_active(self.mock_page))

        # Case B: Tab bookmarks active nhưng tab mine cũng còn active
        self.mock_page.evaluate.side_effect = [True, False]
        self.assertFalse(is_bookmarks_tab_active(self.mock_page))

        # Case C: Page là None
        self.assertFalse(is_bookmarks_tab_active(None))

    @patch("core.navigation.is_codex_open", return_value=True)
    def test_04_open_codex_bookmarks_tab_already_active(self, mock_codex_open):
        """Nếu tab Bookmarks đã active sẵn, trả về True ngay lập tức"""
        with patch("core.navigation.is_bookmarks_tab_active", return_value=True):
            res = open_codex_bookmarks_tab(self.mock_page)
            self.assertTrue(res)

    @patch("core.navigation.time.sleep")
    @patch("core.navigation.is_codex_open", return_value=True)
    @patch("core.navigation.bg_click_locator", return_value=True)
    def test_05_open_codex_bookmarks_tab_active_after_attempt1(
        self, mock_click_loc, mock_codex_open, mock_sleep
    ):
        """Tab Bookmarks active thành công sau Attempt 1 (li[data-ui-tab='bookmarks'])"""
        mock_loc = MagicMock()
        mock_loc.is_visible.return_value = True
        self.mock_page.locator.return_value.first = mock_loc

        # Lần 1 (trước loop): False -> Lần 2 (sau attempt 1): True
        with patch("core.navigation.is_bookmarks_tab_active", side_effect=[False, True]):
            res = open_codex_bookmarks_tab(self.mock_page)
            self.assertTrue(res)
            self.mock_page.locator.assert_called_with('li[data-ui-tab="bookmarks"]')
            mock_click_loc.assert_called_once()

    @patch("core.navigation.time.sleep")
    @patch("core.navigation.is_codex_open", return_value=True)
    @patch("core.navigation.bg_click", return_value=(707, 214))
    def test_06_open_codex_bookmarks_tab_active_after_attempt2(
        self, mock_bg_click, mock_codex_open, mock_sleep
    ):
        """Tab Bookmarks active thành công sau Attempt 2 (CSS coord 707, 214)"""
        # Attempt 1 locator không visible
        mock_loc = MagicMock()
        mock_loc.is_visible.return_value = False
        self.mock_page.locator.return_value.first = mock_loc

        # Lần 1: False -> Attempt 1: False -> Attempt 2: True
        with patch("core.navigation.is_bookmarks_tab_active", side_effect=[False, False, True]):
            res = open_codex_bookmarks_tab(self.mock_page)
            self.assertTrue(res)
            mock_bg_click.assert_called()
            # Kiểm tra tọa độ click là 707, 214
            self.assertEqual(mock_bg_click.call_args[0][1], 707)
            self.assertEqual(mock_bg_click.call_args[0][2], 214)

    @patch("core.navigation.time.sleep")
    @patch("core.navigation.is_codex_open", return_value=True)
    @patch("core.watchdog.ensure_clean_pond_state")
    def test_07_open_codex_bookmarks_tab_fails_safe_when_all_attempts_fail(
        self, mock_clean_pond, mock_codex_open, mock_sleep
    ):
        """TUYỆT ĐỐI trả về False và đóng modal nếu sau 4 attempts tab Bookmarks vẫn không active"""
        # Luôn luôn trả về False
        with patch("core.navigation.is_bookmarks_tab_active", return_value=False):
            res = open_codex_bookmarks_tab(self.mock_page)
            self.assertFalse(res, "Phải trả về False khi tab Bookmarks không thể kích hoạt!")
            mock_clean_pond.assert_called_once_with(self.mock_page)

    def test_08_core_exports_is_bookmarks_tab_active(self):
        """Kiểm tra export is_bookmarks_tab_active từ package core"""
        self.assertTrue(hasattr(core, "is_bookmarks_tab_active"))
        self.assertTrue(callable(core.is_bookmarks_tab_active))


if __name__ == '__main__':
    unittest.main()
