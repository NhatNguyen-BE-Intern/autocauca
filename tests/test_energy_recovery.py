# -*- coding: utf-8 -*-
"""
Unit test kiểm thử Hệ thống Quản lý & Bảo hiểm Thể lực (Task 2):
1. Cấu hình ENERGY_STUCK_TIMEOUT = 35.0.
2. eat_bread với Multiscale template matching & Safe Boundary Clamping.
3. Cấm click khi cy > 0.95*h để tránh thanh Dock đáy màn hình.
4. Tự động kẹp tọa độ an toàn và đo thể lực trước/sau khi ăn.
"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from config.settings import ENERGY_STUCK_TIMEOUT
from core.energy import eat_bread, get_current_energy


class TestEnergyRecovery(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()
        # Tạo ảnh giả lập 1080p (h=1080, w=1920)
        self.fake_screen = np.zeros((1080, 1920, 3), dtype=np.uint8)

    def test_01_energy_stuck_timeout_config(self):
        """Kiểm tra cấu hình ENERGY_STUCK_TIMEOUT nằm trong khoảng 30-40s"""
        self.assertEqual(ENERGY_STUCK_TIMEOUT, 35.0)

    @patch("core.energy.bg_click")
    @patch("core.energy.find_template_multiscale")
    @patch("core.energy.get_current_energy")
    def test_02_eat_bread_multiscale_matching_and_verification(
        self, mock_get_energy, mock_find_multiscale, mock_bg_click
    ):
        """eat_bread sử dụng multiscale template matching và xác thực thể lực tăng sau khi ăn"""
        mock_bg_click.return_value = (960, 900)
        # Bánh mì nằm ở đáy (cx=960, cy_offset=100 tương ứng 756 + 100 = 856px)
        mock_find_multiscale.return_value = (960, 100, 0.92, (940, 80, 40, 40))
        # Thể lực trước khi ăn là 1, sau khi ăn tăng lên 41
        mock_get_energy.side_effect = [1, 41]

        res = eat_bread(self.mock_page, screen_bgr=self.fake_screen)

        self.assertTrue(res)
        mock_find_multiscale.assert_called_once()
        # Kiểm tra scales truyền vào đúng yêu cầu
        scales_arg = mock_find_multiscale.call_args[1].get("scales")
        self.assertEqual(scales_arg, [0.85, 0.90, 0.95, 1.0, 1.05, 1.10])
        self.assertEqual(mock_find_multiscale.call_args[1].get("threshold"), 0.55)
        # Kiểm tra click diễn ra
        mock_bg_click.assert_called_once()
        clicked_x, clicked_y = mock_bg_click.call_args[0][1], mock_bg_click.call_args[0][2]
        self.assertEqual(clicked_x, 960)
        self.assertEqual(clicked_y, 100 + int(1080 * 0.70))  # 100 + 756 = 856

    @patch("core.energy.bg_click")
    @patch("core.energy.find_template_multiscale")
    def test_03_eat_bread_safe_boundary_clamping_forbids_dock_click(
        self, mock_find_multiscale, mock_bg_click
    ):
        """Tuyệt đối CẤM click nếu cy > 0.95*h (tránh thanh Dock đáy màn hình)"""
        # Giả lập vị trí rơi vào thanh Dock: cy = 1040 (vượt quá 0.95 * 1080 = 1026)
        # bottom_roi_y = 756 -> cy_offset = 1040 - 756 = 284
        mock_find_multiscale.return_value = (960, 284, 0.85, (940, 264, 40, 40))

        res = eat_bread(self.mock_page, screen_bgr=self.fake_screen)

        self.assertFalse(res, "Phải từ chối click nếu cy > 0.95*h!")
        mock_bg_click.assert_not_called()

    @patch("core.energy.bg_click")
    @patch("core.energy.find_template_multiscale")
    def test_04_eat_bread_safe_boundary_clamps_out_of_bounds(
        self, mock_find_multiscale, mock_bg_click
    ):
        """Tự động kẹp tọa độ bánh mì nếu hơi lệch ra ngoài khoảng [0.20*w..0.80*w] hoặc [0.70*h..0.94*h]"""
        mock_bg_click.return_value = (384, 756)
        # Giả lập tọa độ quá xa bên trái: cx = 100 (< 0.20 * 1920 = 384)
        # và cy hơi cao: 700 (< 0.70 * 1080 = 756) -> offset = -56
        mock_find_multiscale.return_value = (100, -56, 0.80, (80, -76, 40, 40))

        res = eat_bread(self.mock_page, screen_bgr=self.fake_screen)

        self.assertTrue(res)
        mock_bg_click.assert_called_once()
        clicked_x, clicked_y = mock_bg_click.call_args[0][1], mock_bg_click.call_args[0][2]
        # Phải được kẹp về giá trị biên an toàn tối thiểu:
        # min_x = 0.20 * 1920 = 384
        # min_y = 0.70 * 1080 = 756
        self.assertEqual(clicked_x, int(1920 * 0.20))
        self.assertEqual(clicked_y, int(1080 * 0.70))


if __name__ == '__main__':
    unittest.main()
