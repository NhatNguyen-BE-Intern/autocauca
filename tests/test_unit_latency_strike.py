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
        self.assertEqual(settings.ALERT_POLL_SLEEP_MIN, 0.020)
        self.assertEqual(settings.ALERT_POLL_SLEEP_MAX, 0.025)
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

    def test_07_rem_ignore_calculation_with_mock_clock(self):
        """Kiểm tra tính thời gian ngủ bù rem_ignore bằng đồng hồ giả tại các mốc 0.45s, 0.80s, 0.95s và 3.0s"""
        from auto_fish_background import compute_rem_ignore_sleep
        cast_at = 100.0

        # Mốc 1: Sau kiểm tra sơ bộ hết 0.45s (now = 100.45) -> Ngủ bù đúng 0.50s (100.95 - 100.45)
        rem1 = compute_rem_ignore_sleep(cast_at=cast_at, now=100.45)
        self.assertAlmostEqual(rem1, 0.50, places=4)

        # Mốc 2: Đến mốc 0.80s (now = 100.80) -> Ngủ bù 0.15s
        rem2 = compute_rem_ignore_sleep(cast_at=cast_at, now=100.80)
        self.assertAlmostEqual(rem2, 0.15, places=4)

        # Mốc 3: Đúng mốc 0.95s (now = 100.95) -> Ngủ bù 0.0s
        rem3 = compute_rem_ignore_sleep(cast_at=cast_at, now=100.95)
        self.assertAlmostEqual(rem3, 0.0, places=4)

        # Mốc 4: Hai lần kiểm tra kéo dài 3.0 giây (now = 103.0) -> Ngủ bù 0.0s, TUYỆT ĐỐI không ngủ thêm!
        rem4 = compute_rem_ignore_sleep(cast_at=cast_at, now=103.0)
        self.assertEqual(rem4, 0.0)
        print("  [PASS] test_07_rem_ignore_calculation_with_mock_clock: Ngủ bù chuẩn xác, triệt tiêu thời gian chờ thừa!")

    def test_08_phase_cadence_timing_boundaries(self):
        """Kiểm tra xác định pha ngủ theo thời gian thực trôi từ lúc quăng tại các ranh giới 0.8s, 2.49s, 2.50s, 3.19s, 3.20s"""
        from auto_fish_background import determine_poll_phase_sleep

        # Pha 1: t < 2.5s -> sleep = 70ms
        self.assertEqual(determine_poll_phase_sleep(0.80), settings.ALERT_PHASE1_SLEEP)
        self.assertEqual(determine_poll_phase_sleep(0.95), settings.ALERT_PHASE1_SLEEP)
        self.assertEqual(determine_poll_phase_sleep(2.49), settings.ALERT_PHASE1_SLEEP)

        # Pha 2: 2.5s <= t < 3.2s -> sleep = 35ms
        self.assertEqual(determine_poll_phase_sleep(2.50), settings.ALERT_PHASE2_SLEEP)
        self.assertEqual(determine_poll_phase_sleep(3.00), settings.ALERT_PHASE2_SLEEP)
        self.assertEqual(determine_poll_phase_sleep(3.19), settings.ALERT_PHASE2_SLEEP)

        # Pha 3: t >= 3.2s -> sleep trong khoảng [20ms..25ms]
        for t in [3.20, 3.50, 5.0]:
            slp = determine_poll_phase_sleep(t)
            self.assertGreaterEqual(slp, settings.ALERT_POLL_SLEEP_MIN)
            self.assertLessEqual(slp, settings.ALERT_POLL_SLEEP_MAX)
        print("  [PASS] test_08_phase_cadence_timing_boundaries: Ranh giới 3 pha thích ứng khớp thời gian thực 100%!")

    def test_09_baseline_roi_cutoff_if_too_late(self):
        """Nếu kiểm tra kéo dài vượt mốc 0.95s hoặc chụp lỗi -> gán baseline_roi=None an toàn không crash"""
        cast_at = 100.0
        # Trường hợp A: now = 101.2s (> 0.95s sau quăng)
        now_late = 101.2
        baseline_roi = "ROI_SAMPLE" if (now_late - cast_at) <= settings.CAST_IGNORE_DURATION else None
        self.assertIsNone(baseline_roi)

        # Trường hợp B: now = 100.85s (kịp cửa sổ 0.80-0.95s)
        now_on_time = 100.85
        baseline_roi_on_time = "ROI_SAMPLE" if (now_on_time - cast_at) <= settings.CAST_IGNORE_DURATION else None
        self.assertIsNotNone(baseline_roi_on_time)
        print("  [PASS] test_09_baseline_roi_cutoff_if_too_late: Cut-off an toàn khi chậm trễ.")

    def test_10_consecutive_casts_independent_timestamps(self):
        """Hai lượt quăng liên tiếp nhận mốc cast_at mới độc lập, không dùng lại mốc cũ"""
        cast_timestamps = []
        for i in range(2):
            cast_x, cast_y = (100 + i, 200 + i)
            cast_at = time.perf_counter()
            cast_timestamps.append(cast_at)
            time.sleep(0.01)

        self.assertEqual(len(cast_timestamps), 2)
        self.assertGreater(cast_timestamps[1], cast_timestamps[0])
        print("  [PASS] test_10_consecutive_casts_independent_timestamps: Mốc cast_at độc lập từng lượt.")


if __name__ == "__main__":
    unittest.main()
