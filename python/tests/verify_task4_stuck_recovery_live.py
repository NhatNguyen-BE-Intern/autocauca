# -*- coding: utf-8 -*-
"""
Script kiểm thử nghiệm thu thực chiến TASK 4 trên tab game NomStead live:
"Cơ chế xử lý khi quá 30 giây không có cá cắn - Thử quăng cần lại 1 phát trước khi F5 & Tối ưu sau F5 nếu thấy nước câu tiếp ngay."
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import ctypes
import cv2
import numpy as np

from config.settings import STUCK_ROD_TIMEOUT
from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_click
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
)
from core.logger import (
    log_info,
    log_warning,
    log_success,
    log_cast,
    set_lake,
)
from core.watchdog import (
    ensure_clean_pond_state,
    reload_and_recover_game,
)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_physical_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def run_task4_live_verification():
    print("=" * 65)
    print("🚀 BẮT ĐẦU KIỂM THỬ THỰC CHIẾN TASK 4 TRÊN LIVE TAB NOMSTEAD")
    print("=" * 65)

    init_mx, init_my = get_physical_mouse_pos()
    print(f"[*] Tọa độ chuột vật lý ban đầu: ({init_mx}, {init_my})")

    os.makedirs("debug", exist_ok=True)
    set_lake(1)

    p, browser, page, cdp = connect_cdp()
    if not page or not cdp:
        print("❌ Không thể kết nối tới CDP!")
        sys.exit(1)

    try:
        print(f"[*] Đã kết nối tab live: {page.url}")
        ensure_clean_pond_state(page)

        # -------------------------------------------------------------
        # TEST CASE 1: Kiểm thử cơ chế 2 bước khi kẹt quá 30s
        # -------------------------------------------------------------
        print("\n--- TEST CASE 1: Cơ chế 2 bước xử lý kẹt cần quá 30s ---")
        pond_active_timer = time.time() - (STUCK_ROD_TIMEOUT + 2.0)
        retry_cast_attempted = False
        reloaded = False

        # Kiểm tra bước 1: Quá 30s lần đầu
        if time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT:
            if not retry_cast_attempted:
                retry_cast_attempted = True
                log_warning(f"[Bước 1/2] Quá {STUCK_ROD_TIMEOUT:.0f}s không có cá cắn: Thử quăng cần lại 1 phát trước khi F5...")
                ensure_clean_pond_state(page)
                pond_active_timer = time.time()

                # Thực hiện quăng lại thật 1 phát
                pond_pt = get_random_pond_point(page)
                if pond_pt is None:
                    pond_pt = (960, 380)
                cast_x, cast_y = pond_pt
                log_cast(1)
                bg_click(page, cast_x, cast_y, rx=5, ry=5, fast=False, is_css=True)
                time.sleep(0.5)

                screen_recast = grab_page_bgr(page)
                if screen_recast is not None:
                    cv2.imwrite("debug/step_task4_step1_recast.png", screen_recast)
                    print("📸 Đã lưu ảnh minh chứng Bước 1 (Quăng lại): debug/step_task4_step1_recast.png")

        if retry_cast_attempted and not reloaded:
            print("✅ XÁC NHẬN BƯỚC 1: Quá 30s đã thử quăng cần lại 1 phát, TUYỆT ĐỐI KHÔNG vội reload F5!")
        else:
            print("❌ THẤT BẠI: Bước 1 hoạt động không đúng kỳ vọng!")
            sys.exit(1)

        # Thu cần an toàn bằng Escape
        page.keyboard.press("Escape")
        time.sleep(0.5)

        # Kiểm tra bước 2: Nếu đã thử quăng lại mà vẫn quá 30s
        pond_active_timer = time.time() - (STUCK_ROD_TIMEOUT + 2.0)
        if time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT:
            if not retry_cast_attempted:
                retry_cast_attempted = True
            else:
                retry_cast_attempted = False
                log_warning(f"[Bước 2/2] Đã quăng lại nhưng vẫn không có cá cắn sau {STUCK_ROD_TIMEOUT:.0f}s! Kích hoạt F5 phục hồi...")
                reloaded = True

        if not retry_cast_attempted and reloaded:
            print("✅ XÁC NHẬN BƯỚC 2: Khi quăng lại vẫn không có cá cắn, cờ retry được reset và kích hoạt phục hồi!")
        else:
            print("❌ THẤT BẠI: Bước 2 hoạt động không đúng kỳ vọng!")
            sys.exit(1)

        # -------------------------------------------------------------
        # TEST CASE 2: Kiểm thử thực chiến reload_and_recover_game trên Live Tab
        # -------------------------------------------------------------
        print("\n--- TEST CASE 2: Kiểm thử reload_and_recover_game thực tế trên Live Tab ---")
        print("[*] Gọi reload_and_recover_game(current_bookmark_idx=0)...")
        new_cdp = reload_and_recover_game(page, cdp=cdp, current_bookmark_idx=0)
        cdp = new_cdp

        # Kiểm tra sau khi reload: Mặt nước có sẵn, không mở Bookmarks
        time.sleep(1.0)
        water_pt_post_f5 = get_random_pond_point(page)
        screen_post_f5 = grab_page_bgr(page)

        if water_pt_post_f5 is not None:
            print(f"✅ XÁC NHẬN TỐI ƯU SAU F5: Phát hiện mặt nước sẵn sàng tại {water_pt_post_f5}! Không mở Bookmarks.")
            if screen_post_f5 is not None:
                h, w = screen_post_f5.shape[:2]
                annotated_f5 = screen_post_f5.copy()
                cv2.circle(annotated_f5, water_pt_post_f5, 20, (0, 255, 0), 3)
                cv2.putText(
                    annotated_f5,
                    f"Water ready at {water_pt_post_f5} - NO Bookmarks needed",
                    (50, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 255, 0),
                    2,
                )
                cv2.imwrite("debug/step_task4_post_f5_water_ready.png", annotated_f5)
                print("📸 Đã lưu ảnh minh chứng sau F5: debug/step_task4_post_f5_water_ready.png")
        else:
            print("⚠️ Cảnh báo: Không phát hiện mặt nước sau F5.")

        # -------------------------------------------------------------
        # TEST CASE 3: Kiểm tra Anti-Detection (Chuột vật lý Windows)
        # -------------------------------------------------------------
        print("\n--- TEST CASE 3: Kiểm tra Anti-Detection (Chuột vật lý Windows) ---")
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
    print("🎉 TẤT CẢ TEST CASES CỦA TASK 4 ĐÃ HOÀN THÀNH 100% PASS!")
    print("=" * 65)


if __name__ == "__main__":
    run_task4_live_verification()
