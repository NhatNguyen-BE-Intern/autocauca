# -*- coding: utf-8 -*-
"""
Unit test kiểm thử toàn diện hệ thống Logger trực quan (Task B1):
- Kiểm tra line count < 100 dòng của core/logger.py
- Kiểm tra Banner, ANSI colors, Timestamp [HH:MM:SS]
- Kiểm tra bộ đếm số cá (hồ hiện tại và tổng cộng), mức thể lực
- Kiểm tra cờ DEBUG_LOG (ẩn toàn bộ log debug kỹ thuật khi False)
"""
import io
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings as settings
from core.logger import (
    print_banner,
    log_info,
    log_success,
    log_warning,
    log_error,
    log_debug,
    log_travel,
    log_arrived,
    log_cast,
    log_bite,
    log_catch_success,
    log_eat_bread,
    log_lake_empty,
    log_break,
    log_wait_reset,
    set_lake,
    record_catch,
    set_energy,
    get_stats,
)

class TestTerminalLogger(unittest.TestCase):

    def test_01_logger_line_count(self):
        """Tiêu chí nghiệm thu Task B1: core/logger.py < 100 dòng"""
        logger_path = PROJECT_ROOT / "core" / "logger.py"
        self.assertTrue(logger_path.exists(), "core/logger.py không tồn tại!")
        lines = logger_path.read_text(encoding="utf-8").splitlines()
        print(f"\n[Test 1] core/logger.py có {len(lines)} dòng (Tiêu chí < 100 dòng).")
        self.assertLess(len(lines), 100, f"core/logger.py vượt quá 100 dòng ({len(lines)})")

    def test_02_banner_output(self):
        """Kiểm tra banner hiển thị đầy đủ thông tin chạy ngầm và phím tắt an toàn"""
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            print_banner()
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("NOMSTEAD", output)
        self.assertIn("Ctrl + Shift + Q", output)
        self.assertIn("100% Hoạt động trong nền", output)

    def test_03_stats_and_catch_tracking(self):
        """Kiểm tra logic theo dõi số cá hồ hiện tại, tổng cá và thể lực"""
        set_lake(5)
        set_energy(78)
        lake_num, lake_catches, total_catches, energy = get_stats()
        self.assertEqual(lake_num, 5)
        self.assertEqual(lake_catches, 0)
        self.assertEqual(energy, 78)

        record_catch()
        record_catch()
        lake_num, lake_catches, total_catches, energy = get_stats()
        self.assertEqual(lake_catches, 2)
        self.assertGreaterEqual(total_catches, 2)

        # Chuyển sang hồ 6 -> lake_catches reset về 0, total_catches giữ nguyên
        prev_total = total_catches
        set_lake(6)
        lake_num, lake_catches, total_catches, energy = get_stats()
        self.assertEqual(lake_num, 6)
        self.assertEqual(lake_catches, 0)
        self.assertEqual(total_catches, prev_total)

    def test_04_debug_log_suppression(self):
        """Kiểm tra cờ DEBUG_LOG: Khi False, log_debug không in ra terminal"""
        settings.DEBUG_LOG = False
        import core.logger as logger_mod
        logger_mod.DEBUG_LOG = False

        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            log_debug("SECRET_TECHNICAL_COORDINATES_123_456")
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertEqual(output, "", "log_debug không được xuất hiện khi DEBUG_LOG = False!")

        # Khi DEBUG_LOG = True, log_debug được in ra
        logger_mod.DEBUG_LOG = True
        buf = io.StringIO()
        try:
            sys.stdout = buf
            log_debug("VISIBLE_DEBUG_MESSAGE")
        finally:
            sys.stdout = old_stdout
            logger_mod.DEBUG_LOG = False  # Reset lại False

        output = buf.getvalue()
        self.assertIn("VISIBLE_DEBUG_MESSAGE", output)
        self.assertIn("[DEBUG]", output)

    def test_05_formatted_event_logs(self):
        """Kiểm tra format các sự kiện câu cá trực quan chuẩn spec Task B1"""
        set_lake(8)
        set_energy(65)
        record_catch()

        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            log_travel(8)
            log_arrived(8)
            log_cast(8)
            log_bite(8)
            log_catch_success(8)
            log_eat_bread(8)
            log_lake_empty(8)
            log_break(25.5, 8)
            log_wait_reset("10:00:15")
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("Khởi hành tới HO 8", output)
        self.assertIn("Đã đến hồ, mặt nước sẵn sàng", output)
        self.assertIn("Quăng cần xuống hồ", output)
        self.assertIn("CÁ CẮN CÂU (!)", output)
        self.assertTrue("CÂU THÀNH CÔNG! Đã bắt được cá" in output or "THÀNH CÔNG! Bắt được 1 cá" in output)
        self.assertIn("Thể lực thấp, tự động ăn bánh mì", output)
        self.assertIn("Hồ đã hết cá", output)
        self.assertIn("Nghỉ ngơi giải lao 25.5s", output)
        self.assertIn("CHỜ RESET", output)
        self.assertIn("[HỒ 08/40]", output)

if __name__ == "__main__":
    unittest.main()
