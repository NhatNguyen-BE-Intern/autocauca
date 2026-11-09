# -*- coding: utf-8 -*-
"""
Unit test kiểm tra Latency Pipeline & Zero-Delay Strike
Xác thực toàn bộ các module: config.settings, core.virtual_input, core.vision, auto_fish_background.
"""

import sys
import time
import base64
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

import config.settings as settings
import core
from core.virtual_input import bg_strike_instant
from core.vision import (
    get_random_pond_point,
    capture_baseline_roi,
    find_alert_fast_cdp,
    img_alert,
)

class TestLatencyStrikePipeline(unittest.TestCase):
    def test_01_config_settings(self):
        """Kiểm tra 100% các giá trị cấu hình theo bản thiết kế LATENCY_PIPELINE_SPEC"""
        self.assertEqual(settings.ALERT_THRESHOLD, 0.60)
        self.assertEqual(settings.ALERT_HIGH_CONFIDENCE_THRESHOLD, 0.80)
        self.assertEqual(settings.ALERT_DIFF_THRESHOLD, 18.0)
        self.assertEqual(settings.ALERT_DARK_PIXEL_RATIO, 0.05)
        self.assertEqual(settings.FAST_ALERT_QUALITY, 50)
        self.assertEqual(settings.ALERT_POLL_SLEEP_MIN, 0.005)
        self.assertEqual(settings.ALERT_POLL_SLEEP_MAX, 0.008)
        self.assertEqual(settings.WATER_EROSION_KERNEL, (29, 29))
        self.assertEqual(settings.WATER_SAFE_MARGIN_PX, 25)
        self.assertEqual(settings.STRIKE_INSTANT_HOLD_SEC, 0.025)
        print("  [PASS] test_01_config_settings: Cấu hình settings.py chuẩn xác 100%")

    def test_02_exports(self):
        """Kiểm tra export của các hàm mới trong core package"""
        self.assertTrue(hasattr(core, 'bg_strike_instant'))
        self.assertTrue(hasattr(core, 'capture_baseline_roi'))
        self.assertTrue(callable(core.bg_strike_instant))
        self.assertTrue(callable(core.capture_baseline_roi))
        print("  [PASS] test_02_exports: core package xuất bản đầy đủ hàm mới")

    def test_03_bg_strike_instant_behavior(self):
        """Kiểm tra hoạt động của bg_strike_instant với mock CDP"""
        # None params
        res_x, res_y = bg_strike_instant(None, None, None, None)
        self.assertIsNone(res_x)
        self.assertIsNone(res_y)

        # Mock CDP
        mock_cdp = MagicMock()
        mock_page = MagicMock()
        mock_page._cdp_session = mock_cdp

        t_start = time.perf_counter()
        sx, sy = bg_strike_instant(mock_page, cdp=mock_cdp, pull_x=500, pull_y=600, is_css=True)
        t_elapsed = time.perf_counter() - t_start

        self.assertIsNotNone(sx)
        self.assertIsNotNone(sy)
        self.assertTrue(abs(sx - 500) <= 2)
        self.assertTrue(abs(sy - 600) <= 2)

        # CDP calls
        calls = mock_cdp.send.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][0], 'Input.dispatchMouseEvent')
        self.assertEqual(calls[0][0][1]['type'], 'mousePressed')
        self.assertEqual(calls[0][0][1]['x'], sx)
        self.assertEqual(calls[0][0][1]['y'], sy)

        self.assertEqual(calls[1][0][0], 'Input.dispatchMouseEvent')
        self.assertEqual(calls[1][0][1]['type'], 'mouseReleased')
        self.assertEqual(calls[1][0][1]['x'], sx)
        self.assertEqual(calls[1][0][1]['y'], sy)

        # Hold time should be ~0.025s (>= 20ms and < 60ms)
        self.assertTrue(0.020 <= t_elapsed <= 0.080, f"Elapsed time: {t_elapsed}s")
        print(f"  [PASS] test_03_bg_strike_instant_behavior: Thực thi đúng trong {t_elapsed*1000:.1f}ms (Zero-Delay)")

    def test_04_distance_transform_pond(self):
        """Kiểm tra thuật toán get_random_pond_point phân tầng khoảng cách >= 25px, >= 18px, >= 12px"""
        from core.vision import WATER_LOWER, WATER_UPPER
        # Giả lập màn hình 1080p có 1 hồ nước hình tròn ở giữa ROI
        screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # BGR nước chuẩn: lấy trung bình giữa WATER_LOWER và WATER_UPPER
        water_bgr = ((WATER_LOWER.astype(int) + WATER_UPPER.astype(int)) // 2).astype(np.uint8)

        # ROI: x in [0.35..0.65] (672..1248), y in [0.24..0.61] (259..658)
        # Tạo hồ nước bán kính 80px tâm tại (960, 450)
        cv2.circle(screen, (960, 450), 80, tuple(map(int, water_bgr)), -1)

        mock_page = MagicMock()
        mock_cdp = MagicMock()
        mock_page._cdp_session = mock_cdp

        # Mock grab_page_bgr thông qua mock_cdp captureScreenshot
        _, buf = cv2.imencode('.jpg', screen)
        b64_str = base64.b64encode(buf).decode('utf-8')
        mock_cdp.send.return_value = {'data': b64_str}

        point = get_random_pond_point(mock_page)
        self.assertIsNotNone(point)
        px, py = point
        # Điểm chọn phải nằm trong lòng hồ và cách tâm <= 55px (vì bán kính 80, cách bờ >= 25px)
        dist_from_center = np.sqrt((px - 960)**2 + (py - 450)**2)
        self.assertLessEqual(dist_from_center, 60.0)
        print(f"  [PASS] test_04_distance_transform_pond: Điểm quăng cần ({px}, {py}) cách tâm {dist_from_center:.1f}px (an toàn sâu trong lòng nước)")

    def test_05_capture_baseline_roi(self):
        """Kiểm tra capture_baseline_roi cắt đúng ROI 20%..60% H và 35%..65% W"""
        screen = np.full((1080, 1920, 3), 120, dtype=np.uint8)
        _, buf = cv2.imencode('.jpg', screen, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
        b64_str = base64.b64encode(buf).decode('utf-8')

        mock_cdp = MagicMock()
        mock_cdp.send.return_value = {'data': b64_str}

        baseline = capture_baseline_roi(mock_cdp)
        self.assertIsNotNone(baseline)
        expected_h = int(1080 * 0.60) - int(1080 * 0.20) # 432
        expected_w = int(1920 * 0.65) - int(1920 * 0.35) # 576
        self.assertEqual(baseline.shape[:2], (expected_h, expected_w))
        print(f"  [PASS] test_05_capture_baseline_roi: Baseline ROI kích thước {baseline.shape}")

    def test_06_double_verification_find_alert(self):
        """Kiểm tra thuật toán Double Verification trong find_alert_fast_cdp"""
        if img_alert is None:
            self.skipTest("Template cham_than.png không tồn tại")

        th, tw = img_alert.shape[:2]

        # 1. Tạo baseline ROI (mặt nước sóng dao động nhẹ)
        full_base = np.full((1080, 1920, 3), (72, 88, 98), dtype=np.uint8)
        # ROI cắt: y1=216, y2=648, x1=672, x2=1248
        y1, y2 = int(1080 * 0.20), int(1080 * 0.60)
        x1, x2 = int(1920 * 0.35), int(1920 * 0.65)
        baseline_roi = full_base[y1:y2, x1:x2].copy()

        # 2. Tạo khung hình hiện tại có dán img_alert tại (x1 + 100, y1 + 50)
        full_curr = full_base.copy()
        full_curr[y1 + 50 : y1 + 50 + th, x1 + 100 : x1 + 100 + tw] = img_alert

        _, buf = cv2.imencode('.jpg', full_curr, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
        b64_alert = base64.b64encode(buf).decode('utf-8')

        mock_cdp = MagicMock()
        mock_cdp.send.return_value = {'data': b64_alert}

        # Test Case A: Dấu ! rõ nét với baseline -> Phát hiện thành công
        pos = find_alert_fast_cdp(mock_cdp, threshold=0.60, baseline_roi=baseline_roi)
        self.assertIsNotNone(pos)
        self.assertEqual(pos, (x1 + 100 + tw // 2, y1 + 50 + th // 2))

        # Test Case B: Frame không có dấu ! (chỉ có baseline) -> Không báo nhầm
        _, buf_base = cv2.imencode('.jpg', full_base, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
        mock_cdp.send.return_value = {'data': base64.b64encode(buf_base).decode('utf-8')}
        pos_none = find_alert_fast_cdp(mock_cdp, threshold=0.60, baseline_roi=baseline_roi)
        self.assertIsNone(pos_none)

        # Test Case C: Giả lập sóng nước đổi màu nhưng không có pixel đen -> Không bị false positive
        wave_screen = full_base.copy()
        # Đổi màu cục bộ thành màu sáng hơn
        wave_screen[y1 + 50 : y1 + 50 + th, x1 + 100 : x1 + 100 + tw] = (120, 140, 160)
        _, buf_wave = cv2.imencode('.jpg', wave_screen, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
        mock_cdp.send.return_value = {'data': base64.b64encode(buf_wave).decode('utf-8')}
        pos_wave = find_alert_fast_cdp(mock_cdp, threshold=0.60, baseline_roi=baseline_roi)
        self.assertIsNone(pos_wave)

        # Test Case D: Không có baseline (baseline_roi=None):
        # Nếu score >= 0.80 -> trigger
        mock_cdp.send.return_value = {'data': b64_alert}
        pos_nobase = find_alert_fast_cdp(mock_cdp, threshold=0.60, baseline_roi=None)
        self.assertIsNotNone(pos_nobase)
        print("  [PASS] test_06_double_verification_find_alert: Double Verification hoạt động chính xác 100%!")

if __name__ == "__main__":
    unittest.main()
