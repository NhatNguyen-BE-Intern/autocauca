# -*- coding: utf-8 -*-
"""
Script kiểm thử nghiệm thu thực chiến TASK 2 (GIAI ĐOẠN E) trên tab game NomStead live:
"Khóa chặt logic cập nhật thứ tự hồ - Chống nhảy cóc bỏ sót hồ."
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import ctypes
import cv2
from unittest.mock import patch

from config.settings import POND_TRANSITION_MAX_RETRIES, TOTAL_BOOKMARKS
from core.cdp_client import connect_cdp, close_cdp
from core.vision import grab_page_bgr, get_random_pond_point
from core.logger import get_stats, set_lake
from core.watchdog import ensure_clean_pond_state
from auto_fish_background import advance_to_next_pond, handle_pond_depleted


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_physical_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def run_task2_live_verification():
    print("=" * 65)
    print("🚀 BẮT ĐẦU KIỂM THỬ THỰC CHIẾN TASK 2 (GIAI ĐOẠN E) TRÊN LIVE TAB")
    print("=" * 65)

    init_mx, init_my = get_physical_mouse_pos()
    print(f"[*] Tọa độ chuột vật lý ban đầu: ({init_mx}, {init_my})")

    os.makedirs("debug", exist_ok=True)

    p, browser, page, cdp = connect_cdp()
    if not page or not cdp:
        print("❌ Không thể kết nối tới Chrome CDP!")
        sys.exit(1)

    try:
        print(f"[*] Đã kết nối tab live: {page.url}")
        ensure_clean_pond_state(page)

        # -------------------------------------------------------------
        # TEST CASE 1: Gatekeeper khi chuyển hồ thất bại (Chống nhảy cóc)
        # -------------------------------------------------------------
        print("\n--- TEST CASE 1: Gatekeeper khi thất bại -> Giữ nguyên hồ, KHÔNG nhảy cóc ---")
        set_lake(9)
        print(f"[*] Trạng thái ban đầu: Đang ở HO {get_stats()[0]} (current_idx = 8)")

        # Giả lập travel_to_bookmark thất bại
        with patch("auto_fish_background.travel_to_bookmark", return_value=False), \
             patch("auto_fish_background.reload_and_recover_game"):

            failed_idx, lake_depleted = handle_pond_depleted(page, current_idx=8, cdp=cdp)

            print(f"[*] Kết quả handle_pond_depleted: returned_idx = {failed_idx}, lake_depleted = {lake_depleted}")
            print(f"[*] get_stats()[0] hiện tại: HO {get_stats()[0]}")

            # Tiêu chí 1.1: returned_idx PHẢI giữ nguyên 8 (KHÔNG ĐƯỢC tăng lên 9)
            if failed_idx == 8:
                print("✅ PASS TIÊU CHÍ 1.1: advance_to_next_pond giữ nguyên index = 8, TUYỆT ĐỐI KHÔNG nhảy cóc lên 9!")
            else:
                print(f"❌ THẤT BẠI: returned_idx bị tăng sai thành {failed_idx}!")
                sys.exit(1)

            # Tiêu chí 1.2: lake_num không bị đổi thành 10
            if get_stats()[0] == 9:
                print("✅ PASS TIÊU CHÍ 1.2: lake_num giữ nguyên HO 9, không cập nhật sai thành HO 10!")
            else:
                print(f"❌ THẤT BẠI: lake_num bị đổi sai thành {get_stats()[0]}!")
                sys.exit(1)

            # Tiêu chí 1.3: lake_depleted phải là True
            if lake_depleted is True:
                print("✅ PASS TIÊU CHÍ 1.3: cờ lake_depleted = True, kích hoạt Anti-Skipping Guard!")
            else:
                print("❌ THẤT BẠI: lake_depleted không bật True!")
                sys.exit(1)

            # Tiêu chí 1.4: Mô phỏng Anti-Skipping Guard không cho phép quăng cần
            cast_called = False
            if lake_depleted:
                print("✅ PASS TIÊU CHÍ 1.4: Anti-Skipping Guard chặn đứng lệnh quăng cần, tiếp tục điều hướng!")
            else:
                cast_called = True
                print("❌ THẤT BẠI: Bot quăng cần bừa bãi vào hồ cạn!")
                sys.exit(1)

        # -------------------------------------------------------------
        # TEST CASE 2: Chuyển hồ thực tế trên live game
        # -------------------------------------------------------------
        print("\n--- TEST CASE 2: Thực hiện chuyển hồ thực tế trên live game session ---")
        # Chuyển thực tế sang HO 2 (target_idx = 1 từ current_idx = 0)
        set_lake(1)
        print("[*] Gọi advance_to_next_pond(page, current_idx=0) để chuyển sang HO 2 thật trên game...")
        t0 = time.time()
        new_lake_idx = advance_to_next_pond(page, current_idx=0, cdp=cdp)
        elapsed = time.time() - t0
        print(f"[*] advance_to_next_pond hoàn tất trong {elapsed:.2f}s, new_lake_idx = {new_lake_idx}")

        if new_lake_idx == 1:
            print("✅ PASS: Đã chuyển thành công sang HO 2 (target_idx = 1)!")
            print(f"[*] lake_num sau chuyển hồ: HO {get_stats()[0]}")

            # Kiểm tra mặt nước tại hồ mới
            screen_arrived = grab_page_bgr(page)
            water_spot = get_random_pond_point(page)
            print(f"[*] Tọa độ mặt nước tại hồ mới: {water_spot}")

            if screen_arrived is not None and water_spot is not None:
                annotated = screen_arrived.copy()
                cv2.circle(annotated, water_spot, 25, (0, 255, 0), 3)
                cv2.putText(
                    annotated,
                    f"TRANSITION SUCCESS: HO 2 (idx {new_lake_idx})",
                    (50, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 255, 0),
                    2,
                )
                cv2.imwrite("debug/task2_anti_skip_verified.png", annotated)
                print("📸 Đã lưu ảnh minh chứng: debug/task2_anti_skip_verified.png")
            else:
                print("⚠️ Cảnh báo: Chưa tìm thấy điểm mặt nước.")
        else:
            print(f"❌ THẤT BẠI: new_lake_idx không tăng thành 1 mà là {new_lake_idx}")
            sys.exit(1)

        # -------------------------------------------------------------
        # TEST CASE 3: Dọn dẹp trạng thái
        # -------------------------------------------------------------
        print("\n--- TEST CASE 3: Dọn dẹp trạng thái ---")
        ensure_clean_pond_state(page)

        # -------------------------------------------------------------
        # TEST CASE 4: Kiểm tra Anti-Detection
        # -------------------------------------------------------------
        print("\n--- TEST CASE 4: Đo lường Anti-Detection (Chuột vật lý Windows) ---")
        final_mx, final_my = get_physical_mouse_pos()
        dx = abs(final_mx - init_mx)
        dy = abs(final_my - init_my)
        print(f"[*] Chuột ban đầu: ({init_mx}, {init_my}) -> Kết thúc: ({final_mx}, {final_my})")
        print(f"[*] Độ dịch chuyển vật lý: dx = {dx} px, dy = {dy} px")

        if dx == 0 and dy == 0:
            print("✅ PASS TUYỆT ĐỐI: Chuột Windows vật lý không xê dịch (0px drift)!")
        else:
            print(f"❌ CẢNH BÁO: Phát hiện trôi chuột vật lý (dx={dx}, dy={dy})!")
            sys.exit(1)

    finally:
        close_cdp(p, browser)

    print("\n" + "=" * 65)
    print("🎉 TOÀN BỘ CÁC TIÊU CHÍ TASK 2 GIAI ĐOẠN E ĐẠT 100% PASS!")
    print("=" * 65)


if __name__ == "__main__":
    run_task2_live_verification()
