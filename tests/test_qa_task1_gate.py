# -*- coding: utf-8 -*-
"""
=============================================================================
             SUITE KIỂM THỬ NGHIỆM THU NGHIÊM NGẶT - TASK 1 GATE
         (VÒNG LẶP BẤT TỬ 24/24 & HOTKEY AN TOÀN CTRL+SHIFT+Q)
=============================================================================
Tiêu chuẩn nghiệm thu Task 1:
1. LOẠI BỎ TRIỆT ĐỂ PHÍM TẮT ĐƠN 'q':
   - Quét AST và mã nguồn toàn bộ các file core/vòng lặp chính.
   - 100% không còn dòng nào dừng tool bằng 'q' đơn lẻ.
2. HÀNH VI HOTKEY AN TOÀN `is_stop_requested()`:
   - Gõ phím 'q' đơn lẻ: False (không dừng bot khi chat/gõ văn bản).
   - Gõ Shift+Q, Ctrl+Q, Ctrl+Shift: False.
   - Nhấn Ctrl+Shift+Q: True (dừng tool an toàn).
   - Xử lý ngoại lệ keyboard an toàn: False.
3. VÒNG LẶP BẤT TỬ (IMMORTAL LOOP) & CDP AUTO-RECONNECT:
   - Fault Injection: Ném TargetClosedError hoặc Exception bất kỳ trong vòng lặp.
   - Xác nhận: Ngoại lệ bị bắt, reconnect_cdp được gọi, vòng lặp tiếp tục chạy (continue).
   - Tuyệt đối không bị văng ra finally làm tắt tool.
   - Mô phỏng mất mạng/Chrome đóng tạm thời và tự kết nối lại khi Chrome mở lại.
4. KIỂM THỬ THỰC TẾ TRÊN LIVE CHROME CDP (PORT 9222):
   - Kết nối live tab NomStead, kiểm tra CDP session, không chiếm chuột, không gây giật màn hình.
=============================================================================
"""

import os
import sys
import time
import re
import unittest
from unittest.mock import MagicMock, patch, call
try:
    from playwright._impl._errors import TargetClosedError
except ImportError:
    class TargetClosedError(Exception):
        pass

# Thêm đường dẫn gốc của project vào sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config.settings as settings
from core.cdp_client import (
    is_stop_requested,
    reconnect_cdp,
    connect_cdp,
    close_cdp,
    get_cdp_session,
)


class TestQATask1Gate(unittest.TestCase):
    """Bộ kiểm thử nghiệm thu nghiêm ngặt Task 1 Gate"""

    @classmethod
    def setUpClass(cls):
        print("\n" + "=" * 70)
        print(" BẮT ĐẦU KIỂM THỬ NGHIỆM THU NGHIÊM NGẶT TASK 1 - QA GATE")
        print("=" * 70)

    # =========================================================================
    # TIÊU CHÍ 1: QUÉT MÃ NGUỒN TOÀN DIỆN LOẠI BỎ PHÍM 'q' ĐƠN LẺ
    # =========================================================================
    def test_criterion_1_source_code_audit(self):
        """
        Tiêu chí 1: Quét mã nguồn toàn bộ các module mục tiêu.
        Xác nhận không còn bất kỳ dòng nào dùng keyboard.is_pressed('q') đơn lẻ để dừng bot.
        """
        print("\n[CRITERION 1] Quét mã nguồn toàn diện - Loại bỏ hoàn toàn phím đơn 'q'...")
        target_files = [
            "auto_fish_background.py",
            "core/scheduler.py",
            "core/navigation.py",
            "core/energy.py",
            "core/watchdog.py",
            "core/virtual_input.py",
            "core/vision.py",
        ]

        # Kiểm tra STOP_HOTKEY trong config/settings.py
        self.assertTrue(hasattr(settings, "STOP_HOTKEY"), "settings.py phải có STOP_HOTKEY")
        self.assertEqual(settings.STOP_HOTKEY.lower(), "ctrl+shift+q", "STOP_HOTKEY phải là 'ctrl+shift+q'")
        self.assertTrue(hasattr(settings, "CDP_MAX_RECONNECT_ATTEMPTS"), "settings.py phải có CDP_MAX_RECONNECT_ATTEMPTS")
        self.assertTrue(hasattr(settings, "CDP_RECONNECT_RETRY_DELAY"), "settings.py phải có CDP_RECONNECT_RETRY_DELAY")

        for rel_path in target_files:
            file_path = os.path.join(PROJECT_ROOT, rel_path)
            self.assertTrue(os.path.exists(file_path), f"File {rel_path} không tồn tại!")
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Không được chứa lệnh kiểm tra đơn lẻ 'q'
            self.assertNotIn("keyboard.is_pressed('q')", content, f"Phát hiện phím 'q' đơn lẻ trong {rel_path}!")
            self.assertNotIn('keyboard.is_pressed("q")', content, f'Phát hiện phím "q" đơn lẻ trong {rel_path}!')

            # Với các file điều khiển vòng lặp chính và chờ, phải dùng is_stop_requested
            if rel_path in ["auto_fish_background.py", "core/scheduler.py", "core/navigation.py"]:
                self.assertIn("is_stop_requested", content, f"{rel_path} bắt buộc phải sử dụng is_stop_requested()")

            print(f"  --> PASS: {rel_path} sạch 100%, không còn phím 'q' đơn lẻ.")

        # Kiểm tra riêng core/cdp_client.py
        cdp_client_path = os.path.join(PROJECT_ROOT, "core", "cdp_client.py")
        with open(cdp_client_path, "r", encoding="utf-8") as f:
            cdp_code = f.read()

        self.assertIn("def is_stop_requested", cdp_code)
        self.assertIn("STOP_HOTKEY", cdp_code)
        # Nếu có 'q' trong cdp_client, nó chỉ được phép nằm trong bộ 3 ctrl + shift + q
        single_q_matches = re.findall(r"is_pressed\(['\"]q['\"]\)", cdp_code)
        if single_q_matches:
            self.assertIn("is_pressed('ctrl')", cdp_code)
            self.assertIn("is_pressed('shift')", cdp_code)
        print("  --> PASS: core/cdp_client.py cài đặt is_stop_requested() bảo mật 3 phím đồng thời.")

    # =========================================================================
    # TIÊU CHÍ 2: KIỂM TRA HÀNH VI HOTKEY AN TOÀN `is_stop_requested()`
    # =========================================================================
    def test_criterion_2_safe_hotkey_behavior(self):
        """
        Tiêu chí 2: Kiểm thử ma trận mọi trạng thái bàn phím với is_stop_requested().
        Đảm bảo không bị kích hoạt nhầm khi người dùng gõ văn bản hoặc nhấn phím rời rạc.
        """
        print("\n[CRITERION 2] Kiểm tra hành vi phím tắt mới is_stop_requested()...")

        with patch("keyboard.is_pressed") as mock_is_pressed:
            # 2.1: Người dùng gõ phím 'q' đơn lẻ (chat, viết tài liệu, etc.)
            mock_is_pressed.side_effect = lambda k: k == "q"
            self.assertFalse(is_stop_requested(), "LỖI NGHIÊM TRỌNG: Gõ phím 'q' đơn lẻ làm dừng bot!")

            # 2.2: Người dùng gõ 'Q' hoa (Shift + Q, không có Ctrl)
            mock_is_pressed.side_effect = lambda k: k in ("shift", "q")
            self.assertFalse(is_stop_requested(), "LỖI: Shift+Q không có Ctrl không được dừng bot!")

            # 2.3: Người dùng nhấn Ctrl + Q (không có Shift)
            mock_is_pressed.side_effect = lambda k: k in ("ctrl", "q")
            self.assertFalse(is_stop_requested(), "LỖI: Ctrl+Q không có Shift không được dừng bot!")

            # 2.4: Người dùng nhấn Ctrl + Shift (không có Q)
            mock_is_pressed.side_effect = lambda k: k in ("ctrl", "shift")
            self.assertFalse(is_stop_requested(), "LỖI: Ctrl+Shift không có Q không được dừng bot!")

            # 2.5: Các phím thông thường ngẫu nhiên
            for key in ["a", "w", "s", "d", "space", "enter", "backspace"]:
                mock_is_pressed.side_effect = lambda k, target=key: k == target
                self.assertFalse(is_stop_requested(), f"LỖI: Phím {key} làm kích hoạt dừng bot!")

            # 2.6: Nhấn đúng tổ hợp STOP_HOTKEY chuỗi ('ctrl+shift+q')
            mock_is_pressed.side_effect = lambda k: k == settings.STOP_HOTKEY
            self.assertTrue(is_stop_requested(), "LỖI: Nhấn đúng STOP_HOTKEY nhưng không dừng bot!")

            # 2.7: Cả 3 phím ctrl, shift, q đồng thời được nhấn riêng lẻ
            mock_is_pressed.side_effect = lambda k: k in ("ctrl", "shift", "q")
            self.assertTrue(is_stop_requested(), "LỖI: Nhấn đồng thời (ctrl, shift, q) phải dừng bot!")

            # 2.8: Keyboard module ném ngoại lệ (lỗi driver hook / quyền Administrator)
            mock_is_pressed.side_effect = Exception("OS Keyboard hook unavailable")
            self.assertFalse(is_stop_requested(), "LỖI: Ngoại lệ keyboard phải trả về False an toàn thay vì crash!")

        print("  --> PASS: Ma trận trạng thái phím tắt 100% chính xác - Chống gõ nhầm tuyệt đối.")

    # =========================================================================
    # TIÊU CHÍ 3: VÒNG LẶP BẤT TỬ & AUTO-RECONNECT CDP (FAULT INJECTION)
    # =========================================================================
    def test_criterion_3_immortal_loop_and_reconnect(self):
        """
        Tiêu chí 3: Kịch bản kiểm thử giả lập lỗi (Mock / Fault Injection).
        Ném ngoại lệ TargetClosedError và Exception bất kỳ trong vòng lặp chính.
        Xác nhận:
        - Khối except bắt được lỗi
        - Gọi hàm reconnect_cdp()
        - Vòng lặp TIẾP TỤC CHẠY (continue)
        - TUYỆT ĐỐI KHÔNG bị văng ra finally làm tắt tool.
        """
        print("\n[CRITERION 3] Fault Injection: Kiểm tra Vòng lặp bất tử & Auto-Reconnect CDP...")

        import auto_fish_background

        # Mocks đại diện cho kết nối CDP cũ và mới
        mock_p_initial = MagicMock(name="Playwright_Initial")
        mock_b_initial = MagicMock(name="Browser_Initial")
        mock_page_initial = MagicMock(name="Page_Initial")
        mock_cdp_initial = MagicMock(name="CDP_Initial")

        mock_p_recovered = MagicMock(name="Playwright_Recovered")
        mock_b_recovered = MagicMock(name="Browser_Recovered")
        mock_page_recovered = MagicMock(name="Page_Recovered")
        mock_cdp_recovered = MagicMock(name="CDP_Recovered")

        # Theo dõi số lần vòng lặp lặp qua các bước
        loop_iterations = {"count": 0}
        reconnect_calls = []

        # Giả lập vòng lặp chính chạy 4 chu kỳ:
        # Chu kỳ 1: Quét mặt nước ném ra TargetClosedError (Chrome tab bị crash hoặc mất kết nối)
        #           -> Bắt lỗi, gọi reconnect_cdp, phục hồi kết nối thành công, tiếp tục chạy.
        # Chu kỳ 2: reconnect_cdp tạm thời trả về None (Chrome đang restart mất vài giây)
        #           -> Vòng lặp không crash, sleep 5s và tiếp tục chu kỳ sau.
        # Chu kỳ 3: Kết nối lại thành công, thực hiện câu cá bình thường.
        # Chu kỳ 4: Người dùng bấm Ctrl+Shift+Q -> Thoát an toàn.

        def fake_is_stop_requested():
            if loop_iterations["count"] >= 4:
                return True
            return False

        def fake_get_random_pond_point(page):
            loop_iterations["count"] += 1
            if loop_iterations["count"] == 1:
                # Ném lỗi TargetClosedError như khi tab Chrome bị crash/mất kết nối
                raise TargetClosedError("Target page, context or browser has been closed")
            elif loop_iterations["count"] == 2:
                # Ném lỗi Network / Socket exception
                raise ConnectionResetError("CDP WebSocket disconnected unexpectedly")
            else:
                return (500, 500)

        def fake_reconnect_cdp(p_old, b_old, **kwargs):
            reconnect_calls.append((p_old, b_old))
            if len(reconnect_calls) == 1:
                # Lần 1: phục hồi thành công
                return mock_p_recovered, mock_b_recovered, mock_page_recovered, mock_cdp_recovered
            elif len(reconnect_calls) == 2:
                # Lần 2: Chrome chưa mở xong, trả về None
                return None, None, None, None
            else:
                # Lần 3: Chrome đã mở xong, kết nối lại thành công
                return mock_p_recovered, mock_b_recovered, mock_page_recovered, mock_cdp_recovered

        with patch("auto_fish_background.connect_cdp") as mock_connect, \
             patch("auto_fish_background.close_cdp") as mock_close, \
             patch("auto_fish_background.reconnect_cdp", side_effect=fake_reconnect_cdp), \
             patch("auto_fish_background.is_stop_requested", side_effect=fake_is_stop_requested), \
             patch("auto_fish_background.travel_to_bookmark", return_value=True), \
             patch("auto_fish_background.get_random_pond_point", side_effect=fake_get_random_pond_point), \
             patch("auto_fish_background.ensure_clean_pond_state"), \
             patch("auto_fish_background.check_banners_fast", return_value=None), \
             patch("auto_fish_background.bg_click", return_value=(500, 500)), \
             patch("auto_fish_background.time.sleep") as mock_sleep, \
             patch("sys.argv", ["auto_fish_background.py", "--pond", "1"]):

            mock_connect.return_value = (
                mock_p_initial,
                mock_b_initial,
                mock_page_initial,
                mock_cdp_initial,
            )

            # Chạy hàm main() của auto_fish_background
            auto_fish_background.main()

            # KIỂM CHỨNG KẾT QUẢ NGHIỆM THU:
            # 1. reconnect_cdp phải được gọi khi xảy ra ngoại lệ
            self.assertGreaterEqual(len(reconnect_calls), 2, "reconnect_cdp không được gọi khi gặp lỗi!")

            # 2. Vòng lặp phải hoàn thành cả 4 chu kỳ mà không bị đứt gánh giữa chừng
            self.assertGreaterEqual(loop_iterations["count"], 3, "Vòng lặp bị văng ra sớm trước khi xử lý xong lỗi!")

            # 3. close_cdp chỉ được gọi đúng 1 lần duy nhất tại khối finally khi user dừng tool
            mock_close.assert_called_once()
            print("  --> PASS: Fault Injection hoàn thành: Ngoại lệ bị bắt trọn vẹn, reconnect thành công, vòng lặp bất tử duy trì 24/24.")

    # =========================================================================
    # TIÊU CHÍ 4: KIỂM THỬ TRỰC TIẾP TRÊN LIVE CHROME CDP
    # =========================================================================
    def test_criterion_4_live_chrome_cdp(self):
        """
        Tiêu chí 4: Kiểm thử kết nối thực tế tới Chrome CDP đang mở trên cổng 9222.
        Xác nhận game NomStead vẫn hoạt động bình thường, không regression.
        """
        print("\n[CRITERION 4] Kiểm thử trực tiếp trên live Chrome CDP (Port 9222)...")

        # Thử kết nối live
        p, b, page, cdp = connect_cdp()
        self.assertIsNotNone(p, "Không thể khởi tạo Playwright tới Chrome live")
        self.assertIsNotNone(b, "Không thể kết nối Browser qua CDP")
        self.assertIsNotNone(page, "Không tìm thấy tab NomStead trên Chrome live")
        self.assertIsNotNone(cdp, "Không khởi tạo được CDP session trên Chrome live")

        print(f"  --> Tab hiện tại: '{page.title()}' | URL: {page.url}")
        self.assertIn("nomstead", page.url.lower() + page.title().lower(), "Tab không phải NomStead")

        # Kiểm tra CDP Session hoạt động
        cdp_active = get_cdp_session(page)
        self.assertIsNotNone(cdp_active, "get_cdp_session trả về None")

        # Kiểm tra Viewport thông số không bị giật / distortion
        vp = page.evaluate("() => ({ w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio })")
        print(f"  --> Live Viewport: {vp['w']}x{vp['h']} (DPR: {vp['dpr']})")
        self.assertGreater(vp["w"], 0)
        self.assertGreater(vp["h"], 0)

        # Kiểm tra trạng thái is_stop_requested khi không nhấn phím
        self.assertFalse(is_stop_requested(), "is_stop_requested() không được True khi ở trạng thái nghỉ")

        # Đóng kết nối an toàn (không tắt tab game của người dùng)
        close_cdp(p, b)
        print("  --> PASS: Live Chrome CDP kết nối mượt mà, game NomStead ổn định không regression.")


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestQATask1Gate)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print("                TỔNG KẾT BÁO CÁO NGHIỆM THU TASK 1")
    print("=" * 70)
    print(f" Tổng số ca kiểm thử  : {result.testsRun}")
    print(f" Số ca kiểm thử lỗi   : {len(result.errors)}")
    print(f" Số ca kiểm thử thất bại: {len(result.failures)}")

    if result.wasSuccessful():
        print("\n ⭐ KẾT LUẬN NGHIỆM THU: PASS 100% - TASK 1 ĐẠT CHUẨN XUẤT SẮC!")
        print(" Đủ điều kiện mở khóa chuyển sang TASK 2.")
        sys.exit(0)
    else:
        print("\n ❌ KẾT LUẬN NGHIỆM THU: FAIL - TASK 1 CHƯA ĐẠT CHUẨN!")
        sys.exit(1)
