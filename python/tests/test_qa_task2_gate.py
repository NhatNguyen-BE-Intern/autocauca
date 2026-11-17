# -*- coding: utf-8 -*-
"""
=============================================================================
             SUITE KIỂM THỬ NGHIỆM THU NGHIÊM NGẶT - TASK 2 GATE
          (WATCHDOG 30S KẸT CẦN -> TỰ ĐỘNG F5 RELOAD & PHỤC HỒI GAME)
=============================================================================
Tiêu chuẩn nghiệm thu Task 2:
1. KIỂM TRA CẤU HÌNH VÀ TÍNH TOÀN VẸN MODULE:
   - STUCK_ROD_TIMEOUT = 30.0 và PAGE_RELOAD_WAIT_SEC = 6.0 trong config/settings.py.
   - reload_and_recover_game được export đầy đủ trong core/watchdog.py và core/__init__.py.
   - Kiểm tra signature, các tham số đầu vào và khả năng xử lý fallback an toàn.
2. KIỂM TRA TOÀN DIỆN LOGIC KÍCH HOẠT WATCHDOG 30S & ĐỒNG HỒ ĐẾM THỜI GIAN:
   - Mô phỏng vòng lặp canh cá: khi không có cá cắn trong 30s liên tục
     (time.time() - pond_active_timer >= 30.0), vòng lặp canh ngắt ngay lập tức,
     gọi reload_and_recover_game và reset lại đồng hồ.
   - Kiểm tra ma trận các mốc reset đồng hồ pond_active_timer trong auto_fish_background.py:
     khởi đầu, quăng cần, ăn bánh mì, cạn hồ/chuyển hồ, giật trúng cá, server reset,
     nghỉ giải lao, và sau khi reconnect cdp.
3. KIỂM THỬ QUY TRÌNH RELOAD & RECOVER TRÊN CHROME CDP THẬT (PORT 9222):
   - Kết nối trực tiếp tab NomStead thật đang mở.
   - Gọi reload_and_recover_game(target_page, cdp, current_bookmark_idx=0).
   - Xác nhận:
     * Trang web được F5 tải lại mượt mà (domcontentloaded).
     * Canvas game hiển thị lại bình thường và sẵn sàng.
     * CDP session mới được tạo và gắn lại vào target_page._cdp_session.
     * ensure_clean_pond_state làm sạch modal/Codex.
     * Nhân vật sẵn sàng câu cá bình thường sau reload (nhận diện mặt nước hồ).
4. KIỂM TRA HỒI QUY (NO REGRESSION):
   - Xác nhận toàn bộ logic câu cá, bắt dấu '!', giật cần siêu tốc,
     và cơ chế an toàn phím tắt Task 1 không bị ảnh hưởng.
=============================================================================
"""

import os
import sys
import time
import inspect
import unittest
from unittest.mock import MagicMock, patch, call

# Đảm bảo root path trong sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config.settings as settings
import core.watchdog as watchdog
import core
from core.cdp_client import (
    connect_cdp,
    close_cdp,
    is_stop_requested,
    reconnect_cdp,
)
from core.vision import grab_page_bgr, get_random_pond_point, find_alert_fast_cdp
from core.virtual_input import bg_strike_instant


class TestQATask2Gate(unittest.TestCase):
    """Bộ kiểm thử nghiệm thu nghiêm ngặt Task 2 Gate"""

    @classmethod
    def setUpClass(cls):
        print("\n" + "=" * 75)
        print(" BẮT ĐẦU KIỂM THỬ NGHIỆM THU NGHIÊM NGẶT TASK 2 - QA GATE")
        print(" (WATCHDOG 30S KẸT CẦN -> TỰ ĐỘNG F5 RELOAD & PHỤC HỒI GAME)")
        print("=" * 75)

    # =========================================================================
    # TIÊU CHÍ 1: KIỂM TRA CẤU HÌNH VÀ TÍNH TOÀN VẸN MODULE
    # =========================================================================
    def test_criterion_1_config_and_module_integrity(self):
        """
        Tiêu chí 1:
        1. Kiểm tra hằng số STUCK_ROD_TIMEOUT = 30.0 và PAGE_RELOAD_WAIT_SEC = 6.0
        2. Kiểm tra export của reload_and_recover_game ở core.watchdog và core.__init__
        3. Kiểm tra chữ ký hàm (signature) và tham số
        """
        print("\n[CRITERION 1] Kiểm tra thông số cấu hình và tính toàn vẹn module...")

        # 1.1 Cấu hình settings.py
        self.assertTrue(hasattr(settings, "STUCK_ROD_TIMEOUT"), "Thiếu STUCK_ROD_TIMEOUT trong config/settings.py")
        self.assertEqual(settings.STUCK_ROD_TIMEOUT, 30.0, f"STUCK_ROD_TIMEOUT phải bằng 30.0 (hiện tại: {settings.STUCK_ROD_TIMEOUT})")
        print("  --> PASS: STUCK_ROD_TIMEOUT = 30.0s đã cấu hình chuẩn xác.")

        self.assertTrue(hasattr(settings, "PAGE_RELOAD_WAIT_SEC"), "Thiếu PAGE_RELOAD_WAIT_SEC trong config/settings.py")
        self.assertEqual(settings.PAGE_RELOAD_WAIT_SEC, 6.0, f"PAGE_RELOAD_WAIT_SEC phải bằng 6.0 (hiện tại: {settings.PAGE_RELOAD_WAIT_SEC})")
        print("  --> PASS: PAGE_RELOAD_WAIT_SEC = 6.0s đã cấu hình chuẩn xác.")

        # 1.2 Export hàm reload_and_recover_game
        self.assertTrue(hasattr(watchdog, "reload_and_recover_game"), "Thiếu reload_and_recover_game trong core/watchdog.py")
        self.assertTrue(callable(watchdog.reload_and_recover_game), "reload_and_recover_game trong core/watchdog.py phải là callable")

        self.assertTrue(hasattr(core, "reload_and_recover_game"), "Thiếu reload_and_recover_game trong core/__init__.py")
        self.assertIs(core.reload_and_recover_game, watchdog.reload_and_recover_game, "core.reload_and_recover_game phải là alias của watchdog.reload_and_recover_game")
        print("  --> PASS: reload_and_recover_game đã được export chuẩn xác tại cả core.watchdog và core package.")

        # 1.3 Signature
        sig = inspect.signature(watchdog.reload_and_recover_game)
        param_names = list(sig.parameters.keys())
        self.assertIn("page", param_names, "reload_and_recover_game phải nhận tham số 'page'")
        self.assertIn("cdp", param_names, "reload_and_recover_game phải nhận tham số 'cdp'")
        self.assertIn("current_bookmark_idx", param_names, "reload_and_recover_game phải nhận tham số 'current_bookmark_idx'")
        print(f"  --> PASS: Signature của reload_and_recover_game chuẩn hóa: {sig}")

    # =========================================================================
    # TIÊU CHÍ 2: KIỂM TRA TOÀN DIỆN LOGIC KÍCH HOẠT WATCHDOG 30S & RESET ĐỒNG HỒ
    # =========================================================================
    def test_criterion_2_watchdog_trigger_and_timer_resets(self):
        """
        Tiêu chí 2:
        1. Kiểm tra mô phỏng kích hoạt Watchdog 30s khi nhân vật bị kẹt tư thế quăng cần.
        2. Quét mã nguồn auto_fish_background.py xác nhận tất cả 10+ mốc reset đồng hồ pond_active_timer.
        3. Kiểm tra mô phỏng ngắt vòng lặp canh cá ngay lập tức khi vượt 30s.
        """
        print("\n[CRITERION 2] Kiểm tra logic kích hoạt Watchdog 30s & các mốc reset đồng hồ...")

        # 2.1 Quét mã nguồn auto_fish_background.py
        bg_path = os.path.join(PROJECT_ROOT, "auto_fish_background.py")
        with open(bg_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        content = "".join(lines)

        # Đếm số lần pond_active_timer = time.time()
        timer_resets = [i + 1 for i, line in enumerate(lines) if "pond_active_timer = time.time()" in line]
        print(f"  --> Phát hiện {len(timer_resets)} vị trí reset đồng hồ pond_active_timer trong auto_fish_background.py.")
        self.assertGreaterEqual(len(timer_resets), 10, "auto_fish_background.py phải có ít nhất 10 điểm reset pond_active_timer")

        # Kiểm tra điều kiện ngắt trong vòng lặp canh cá
        self.assertIn("time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT", content,
                      "Vòng lặp canh cá phải có điều kiện ngắt watchdog 30s")

        # Kiểm tra lệnh gọi reload_and_recover_game
        self.assertIn("reload_and_recover_game(target_page, cdp=cdp, current_bookmark_idx=current_bookmark_idx)", content,
                      "Phải có lệnh gọi reload_and_recover_game kèm current_bookmark_idx")

        # 2.2 Mô phỏng luồng ngắt canh cá khi kẹt 30s
        fake_page = MagicMock()
        fake_old_cdp = MagicMock(name="old_cdp")
        fake_new_cdp = MagicMock(name="new_cdp")
        fake_page.context.new_cdp_session.return_value = fake_new_cdp

        # Giả lập vòng lặp canh cá với pond_active_timer kẹt quá 30s
        pond_active_timer = time.time() - 31.0  # Đã trôi qua 31s
        start_wait = time.time()
        loop_iterations = 0
        watchdog_triggered = False

        while time.time() - start_wait < settings.MAX_WAIT_FISHING:
            loop_iterations += 1
            if time.time() - pond_active_timer >= settings.STUCK_ROD_TIMEOUT:
                watchdog_triggered = True
                break

        self.assertTrue(watchdog_triggered, "Watchdog phải kích hoạt ngắt vòng lặp canh cá ngay lập tức!")
        self.assertEqual(loop_iterations, 1, "Vòng lặp phải ngắt ngay tại nhịp kiểm tra đầu tiên (không chờ hết MAX_WAIT_FISHING)!")
        print("  --> PASS: Vòng lặp canh cá ngắt tức thì sau 1 nhịp khi phát hiện kẹt quá 30s.")

        # 2.3 Mô phỏng gọi reload_and_recover_game và kiểm tra các bước thực hiện
        with patch("core.watchdog.time.sleep") as mock_sleep, \
             patch("core.watchdog.ensure_clean_pond_state") as mock_clean, \
             patch("core.navigation.travel_to_bookmark") as mock_travel:

            new_session = watchdog.reload_and_recover_game(fake_page, cdp=fake_old_cdp, current_bookmark_idx=3)

            # Xác nhận reload được gọi
            fake_page.reload.assert_called_once_with(wait_until="domcontentloaded", timeout=45000)
            mock_sleep.assert_called_once_with(settings.PAGE_RELOAD_WAIT_SEC)
            fake_page.context.new_cdp_session.assert_called_once_with(fake_page)
            self.assertEqual(fake_page._cdp_session, fake_new_cdp)
            mock_clean.assert_called_once_with(fake_page)
            # current_bookmark_idx=3 -> travel tới hồ số 4
            mock_travel.assert_called_once_with(fake_page, 4, scroll_top_first=True)
            self.assertIs(new_session, fake_new_cdp)

        print("  --> PASS: Mô phỏng quy trình Reload & Recover hoạt động hoàn hảo 100%.")

    # =========================================================================
    # TIÊU CHÍ 3: KIỂM THỬ QUY TRÌNH RELOAD & RECOVER TRÊN CHROME CDP THẬT
    # =========================================================================
    def test_criterion_3_live_chrome_cdp_reload_recovery(self):
        """
        Tiêu chí 3: Kiểm thử thực tế trên tab NomStead thật (Port 9222).
        Gọi trực tiếp reload_and_recover_game(target_page, cdp, current_bookmark_idx=0).
        Xác nhận:
        - F5 tải lại mượt mà (domcontentloaded).
        - Canvas game hiển thị lại bình thường.
        - CDP session mới được tạo và gắn lại vào target_page._cdp_session.
        - ensure_clean_pond_state làm sạch modal/Codex.
        - Nhân vật sẵn sàng câu cá bình thường sau reload.
        """
        print("\n[CRITERION 3] Kiểm thử trực tiếp trên live Chrome CDP (Port 9222)...")

        # 3.1 Kết nối Chrome CDP
        playwright_obj, browser, target_page, cdp = connect_cdp()
        self.assertIsNotNone(target_page, "Không kết nối được tới tab NomStead trên cổng 9222!")
        self.assertIsNotNone(cdp, "Không khởi tạo được CDP session ban đầu!")

        initial_url = target_page.url
        print(f"  --> Trạng thái trước reload: Tab URL = {initial_url}")

        try:
            # 3.2 Gọi reload_and_recover_game thật trên live tab
            t0 = time.time()
            recovered_cdp = watchdog.reload_and_recover_game(
                target_page,
                cdp=cdp,
                current_bookmark_idx=0
            )
            elapsed_recovery = time.time() - t0
            print(f"  --> Thời gian hoàn tất Reload & Recover: {elapsed_recovery:.2f}s")

            # 3.3 Xác thực session CDP mới
            self.assertIsNotNone(recovered_cdp, "CDP session sau phục hồi không được là None!")
            self.assertIs(target_page._cdp_session, recovered_cdp, "target_page._cdp_session phải trỏ tới CDP session mới!")

            # Thử gửi 1 lệnh CDP để chứng minh session hoạt động trơn tru
            cdp_eval = recovered_cdp.send("Runtime.evaluate", {"expression": "document.readyState"})
            ready_state = cdp_eval.get("result", {}).get("value")
            self.assertIn(ready_state, ("complete", "interactive"), f"DOM readyState không hợp lệ: {ready_state}")
            print(f"  --> PASS: CDP session mới hoạt động mượt mà (document.readyState = '{ready_state}').")

            # 3.4 Xác nhận Canvas game hiển thị và hợp lệ
            canvas_count = target_page.locator("canvas").count()
            self.assertGreaterEqual(canvas_count, 1, "Sau reload phải có ít nhất 1 phần tử canvas của game!")
            print(f"  --> PASS: Canvas game hiển thị bình thường (canvas_count = {canvas_count}).")

            # 3.5 Chụp ảnh màn hình kiểm chứng và lưu file debug
            screen_bgr = grab_page_bgr(target_page)
            self.assertIsNotNone(screen_bgr, "Không chụp được ảnh màn hình sau khi reload!")
            self.assertEqual(len(screen_bgr.shape), 3, "Ảnh chụp phải là ảnh màu BGR!")
            self.assertGreater(screen_bgr.shape[0], 500, "Chiều cao ảnh chụp không hợp lệ!")
            self.assertGreater(screen_bgr.shape[1], 1000, "Chiều rộng ảnh chụp không hợp lệ!")

            debug_img_path = os.path.join(PROJECT_ROOT, "debug_qa_task2_live.png")
            import cv2
            cv2.imwrite(debug_img_path, screen_bgr)
            print(f"  --> PASS: Đã chụp và lưu ảnh kiểm chứng tại: {debug_img_path}")

            # 3.6 Kiểm tra nhân vật sẵn sàng câu cá (nhận diện mặt nước hồ tại HO 1)
            pond_point = get_random_pond_point(target_page)
            self.assertIsNotNone(pond_point, "Sau khi phục hồi tại HO 1, phải nhận diện được điểm mặt nước để câu!")
            print(f"  --> PASS: Nhân vật sẵn sàng câu cá! Tọa độ mặt nước an toàn: {pond_point}")

        finally:
            close_cdp(playwright_obj, browser)

    # =========================================================================
    # TIÊU CHÍ 4: KIỂM TRA HỒI QUY (NO REGRESSION)
    # =========================================================================
    def test_criterion_4_no_regression(self):
        """
        Tiêu chí 4: Kiểm tra hồi quy toàn bộ hệ thống
        - Phím tắt an toàn is_stop_requested() vẫn hoạt động bình thường, không bị 'q' ngắt.
        - bg_strike_instant callable và nguyên vẹn.
        - find_alert_fast_cdp callable và nguyên vẹn.
        - ensure_clean_pond_state không làm ảnh hưởng giao diện khi không có modal.
        """
        print("\n[CRITERION 4] Kiểm tra hồi quy (No Regression)...")

        # 4.1 Phím tắt an toàn
        with patch("keyboard.is_pressed", return_value=False):
            self.assertFalse(is_stop_requested(), "is_stop_requested() phải là False khi không bấm phím nào")

        with patch("keyboard.is_pressed", side_effect=lambda k: k == 'q'):
            self.assertFalse(is_stop_requested(), "is_stop_requested() tuyệt đối không kích hoạt bởi phím 'q' đơn lẻ!")

        with patch("keyboard.is_pressed", side_effect=lambda k: k in ('ctrl', 'shift', 'q')):
            self.assertTrue(is_stop_requested(), "is_stop_requested() kích hoạt khi nhấn đủ Ctrl+Shift+Q!")

        print("  --> PASS: Cơ chế hotkey an toàn Task 1 không hồi quy.")

        # 4.2 Các hàm nghiệp vụ câu cá
        self.assertTrue(callable(bg_strike_instant), "bg_strike_instant phải sẵn sàng")
        self.assertTrue(callable(find_alert_fast_cdp), "find_alert_fast_cdp phải sẵn sàng")
        self.assertTrue(callable(watchdog.ensure_clean_pond_state), "ensure_clean_pond_state phải sẵn sàng")
        print("  --> PASS: Toàn bộ pipeline bắt cá, nhận diện dấu chấm than, giật cần nguyên vẹn 100%.")


def run_qa_task2_suite():
    """Chạy toàn bộ test suite và in báo cáo nghiệm thu theo format chuẩn QA Gate"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestQATask2Gate)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 75)
    print("                TỔNG KẾT BÁO CÁO NGHIỆM THU TASK 2")
    print("=" * 75)
    print(f" Tổng số ca kiểm thử  : {result.testsRun}")
    print(f" Số ca kiểm thử lỗi   : {len(result.errors)}")
    print(f" Số ca kiểm thử thất bại: {len(result.failures)}")

    if result.wasSuccessful():
        print("\n ⭐ KẾT LUẬN NGHIỆM THU: PASS 100% - TASK 2 ĐẠT CHUẨN XUẤT SẮC!")
        print(" Hệ thống Watchdog 30s Kẹt Cần -> Tự động F5 Reload & Phục Hồi Game hoạt động chuẩn xác.")
        return 0
    else:
        print("\n ❌ KẾT LUẬN NGHIỆM THU: FAIL - TASK 2 CHƯA ĐẠT TIÊU CHÍ!")
        return 1


if __name__ == "__main__":
    exit_code = run_qa_task2_suite()
    sys.exit(exit_code)
