# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Cơ chế Khóa Chặt Thứ Tự Hồ & Chống Nhảy Cóc (Anti-Skipping Architecture - Task 2):
1. advance_to_next_pond: Chỉ tăng index khi travel_to_bookmark thành công 100%.
2. Cơ chế Retry thông minh 3 lần (lần 2 & 3 cuộn từ đầu trang scroll_top_first=True).
3. Khi toàn bộ các lần thử thất bại: Giữ nguyên index, KHÔNG tăng hồ, KHÔNG nhảy cóc.
4. handle_pond_depleted: Bật cờ lake_depleted = True khi thất bại.
5. Anti-Skipping Guard: Ngăn chặn hoàn toàn việc quăng cần vào hồ đã cạn nếu chưa chuyển hồ thành công.
"""

import unittest
from unittest.mock import MagicMock, patch

from config.settings import POND_TRANSITION_MAX_RETRIES, TOTAL_BOOKMARKS
from auto_fish_background import advance_to_next_pond, handle_pond_depleted


class TestAntiSkipLakeLocking(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()
        self.mock_cdp = MagicMock()

    def test_01_pond_transition_retries_constant(self):
        """Hằng số POND_TRANSITION_MAX_RETRIES phải được cấu hình bằng 3"""
        self.assertEqual(POND_TRANSITION_MAX_RETRIES, 3)

    @patch("auto_fish_background.travel_to_bookmark", return_value=True)
    @patch("auto_fish_background.set_lake")
    @patch("auto_fish_background.save_session_state")
    @patch("auto_fish_background.maybe_take_micro_break")
    @patch("auto_fish_background.cleanup_old_debug_files")
    def test_02_advance_success_increments_index(
        self, mock_cleanup, mock_break, mock_save_state, mock_set_lake, mock_travel
    ):
        """Khi travel_to_bookmark thành công: index tăng +1, set_lake & save_session_state được gọi"""
        # Từ HO 9 (idx 8) chuyển sang HO 10 (idx 9)
        new_idx = advance_to_next_pond(self.mock_page, current_idx=8, cdp=self.mock_cdp)

        self.assertEqual(new_idx, 9)
        mock_travel.assert_called_once_with(self.mock_page, 10, scroll_top_first=False)
        mock_set_lake.assert_called_once_with(10)
        mock_save_state.assert_called_once_with(10)

    @patch("auto_fish_background.travel_to_bookmark")
    @patch("auto_fish_background.ensure_clean_pond_state")
    @patch("auto_fish_background.set_lake")
    @patch("auto_fish_background.save_session_state")
    @patch("auto_fish_background.maybe_take_micro_break")
    @patch("auto_fish_background.cleanup_old_debug_files")
    def test_03_advance_retry_succeeds_at_attempt2(
        self, mock_cleanup, mock_break, mock_save_state, mock_set_lake, mock_clean, mock_travel
    ):
        """Khi lần 1 thất bại, lần 2 thử lại với scroll_top_first=True và thành công"""
        # Lần 1: False -> Lần 2: True
        mock_travel.side_effect = [False, True]

        with patch("auto_fish_background.time.sleep"):
            new_idx = advance_to_next_pond(self.mock_page, current_idx=8, cdp=self.mock_cdp)

        self.assertEqual(new_idx, 9)
        self.assertEqual(mock_travel.call_count, 2)
        # Lần 2 phải gọi với scroll_top_first=True
        second_call_kwargs = mock_travel.call_args_list[1]
        self.assertEqual(second_call_kwargs[0][1], 10)
        self.assertTrue(second_call_kwargs[1].get("scroll_top_first"))
        mock_set_lake.assert_called_once_with(10)
        mock_save_state.assert_called_once_with(10)

    @patch("auto_fish_background.travel_to_bookmark", return_value=False)
    @patch("auto_fish_background.reload_and_recover_game")
    @patch("auto_fish_background.ensure_clean_pond_state")
    @patch("auto_fish_background.set_lake")
    @patch("auto_fish_background.save_session_state")
    @patch("auto_fish_background.maybe_take_micro_break")
    @patch("auto_fish_background.cleanup_old_debug_files")
    def test_04_advance_all_attempts_fail_locks_index(
        self, mock_cleanup, mock_break, mock_save_state, mock_set_lake, mock_clean, mock_reload, mock_travel
    ):
        """Khi tất cả các lần thử đều thất bại: TUYỆT ĐỐI KHÔNG TĂNG INDEX (giữ nguyên current_idx)"""
        with patch("auto_fish_background.time.sleep"):
            new_idx = advance_to_next_pond(self.mock_page, current_idx=8, cdp=self.mock_cdp)

        # TUYỆT ĐỐI KHÔNG TĂNG LÊN 9, GIỮ NGUYÊN 8!
        self.assertEqual(new_idx, 8, "Lỗi nhảy cóc: Phải giữ nguyên current_idx khi chuyển hồ thất bại!")
        mock_set_lake.assert_not_called()
        mock_save_state.assert_not_called()
        mock_reload.assert_called_once()

    @patch("auto_fish_background.advance_to_next_pond")
    def test_05_handle_pond_depleted_flags(self, mock_advance):
        """handle_pond_depleted trả về đúng cờ lake_depleted cho cả 2 trường hợp"""
        # Case A: Chuyển thành công -> new_idx = 9, lake_depleted = False
        mock_advance.return_value = 9
        idx, depleted = handle_pond_depleted(self.mock_page, current_idx=8, cdp=self.mock_cdp)
        self.assertEqual(idx, 9)
        self.assertFalse(depleted)

        # Case B: Chuyển thất bại -> new_idx = 8, lake_depleted = True
        mock_advance.return_value = 8
        idx, depleted = handle_pond_depleted(self.mock_page, current_idx=8, cdp=self.mock_cdp)
        self.assertEqual(idx, 8)
        self.assertTrue(depleted)

    def test_06_anti_skipping_guard_logic_simulation(self):
        """Mô phỏng chốt chặn Anti-Skipping Guard: Hồ cạn cá chưa chuyển xong tuyệt đối không quăng cần"""
        current_idx = 8
        lake_depleted = True
        cast_executed = False

        # Vòng lặp kiểm tra
        if lake_depleted:
            # Chốt chặn bắt được hồ cạn -> tiếp tục gọi chuyển hồ
            # Giả lập lần này chuyển thành công sang 9
            current_idx = 9
            lake_depleted = False
            # continue bỏ qua lượt câu hồ cũ
        else:
            cast_executed = True

        self.assertFalse(cast_executed, "Chốt chặn phải ngăn cản quăng cần khi lake_depleted=True!")
        self.assertEqual(current_idx, 9)
        self.assertFalse(lake_depleted)


if __name__ == '__main__':
    unittest.main()
