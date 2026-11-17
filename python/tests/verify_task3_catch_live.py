# -*- coding: utf-8 -*-
"""
Script kiểm thử nghiệm thu thực chiến TASK 3 trên tab game NomStead live:
"Xác nhận Câu trúng hay Câu hụt dựa trên cụm chữ 'and I got' & Hiển thị Log chuẩn xác."
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import ctypes
import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from config.settings import (
    HARVEST_VERIFY_TIMEOUT,
    ALERT_THRESHOLD,
    CAST_IGNORE_DURATION,
)
from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_click, bg_strike_instant
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    capture_baseline_roi,
    find_alert_fast_cdp,
)
from core.energy import (
    verify_harvest_or_banner,
    get_current_energy,
)
from core.logger import (
    log_cast,
    log_bite,
    log_catch_success,
    log_catch_miss,
    set_lake,
    set_energy,
)
from core.watchdog import ensure_clean_pond_state


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_physical_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def run_task3_live_verification():
    print("=" * 65)
    print("🚀 BẮT ĐẦU KIỂM THỬ THỰC CHIẾN TASK 3 TRÊN LIVE TAB NOMSTEAD")
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

        # Đọc thể lực hiện tại
        screen_bgr = grab_page_bgr(page)
        cur_eng = get_current_energy(screen_bgr) if screen_bgr is not None else 80
        if cur_eng is not None:
            set_energy(cur_eng)
            print(f"[*] Thể lực hiện tại trên live: {cur_eng}/80")

        # -------------------------------------------------------------
        # TEST CASE 1: Nhận diện cụm 'and I got' và log CÂU THÀNH CÔNG
        # -------------------------------------------------------------
        print("\n--- TEST CASE 1: Toast banner có 'and I got' -> verify_harvest == 'success' ---")
        toast_html = """
        const existing = document.getElementById('test_catch_toast');
        if (existing) existing.remove();
        const toast = document.createElement('div');
        toast.id = 'test_catch_toast';
        toast.style.position = 'fixed';
        toast.style.bottom = '22%';
        toast.style.left = '50%';
        toast.style.transform = 'translateX(-50%)';
        toast.style.backgroundColor = '#1e140a';
        toast.style.color = '#ffffff';
        toast.style.fontSize = '24px';
        toast.style.fontWeight = 'bold';
        toast.style.padding = '14px 32px';
        toast.style.border = '3px solid #d4af37';
        toast.style.borderRadius = '10px';
        toast.style.zIndex = '999999';
        toast.style.boxShadow = '0 6px 16px rgba(0,0,0,0.7)';
        toast.innerText = 'The water was calm, and I got Carp!';
        document.body.appendChild(toast);
        """
        page.evaluate(toast_html)
        time.sleep(0.3)

        # Chụp ảnh minh chứng Toast
        screen_toast = grab_page_bgr(page)
        res_success = verify_harvest_or_banner(page, timeout=2.5, pre_energy=None)
        print(f"[*] Kết quả verify_harvest_or_banner: '{res_success}'")

        if res_success == 'success':
            print("✅ XÁC NHẬN: verify_harvest_or_banner phát hiện chính xác cụm 'and I got'!")
            print("[*] Gọi hàm log_catch_success(1):")
            log_catch_success(1)

            if screen_toast is not None:
                h, w = screen_toast.shape[:2]
                annotated = screen_toast.copy()
                # Vẽ bounding box ROI nửa dưới
                cv2.rectangle(
                    annotated,
                    (int(w * 0.15), int(h * 0.40)),
                    (int(w * 0.85), int(h * 0.95)),
                    (0, 255, 0),
                    2,
                )
                cv2.putText(
                    annotated,
                    "SUCCESS: 'and I got Carp!' detected",
                    (int(w * 0.20), int(h * 0.45)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                )
                cv2.imwrite("debug/step_task3_catch_success.png", annotated)
                print("📸 Đã lưu ảnh minh chứng: debug/step_task3_catch_success.png")
        else:
            print(f"❌ THẤT BẠI: Mong muốn 'success' nhưng nhận được '{res_success}'")
            page.evaluate("const el = document.getElementById('test_catch_toast'); if (el) el.remove();")
            sys.exit(1)

        # Xóa toast mô phỏng
        page.evaluate("const el = document.getElementById('test_catch_toast'); if (el) el.remove();")
        time.sleep(0.3)

        # -------------------------------------------------------------
        # TEST CASE 2: Không có 'and I got' (Miss) -> verify_harvest == 'miss'
        # -------------------------------------------------------------
        print("\n--- TEST CASE 2: Không có banner & thể lực không đổi -> verify_harvest == 'miss' ---")
        res_miss = verify_harvest_or_banner(page, timeout=0.8, pre_energy=cur_eng)
        print(f"[*] Kết quả verify_harvest_or_banner: '{res_miss}'")

        if res_miss == 'miss':
            print("✅ XÁC NHẬN: verify_harvest_or_banner trả về 'miss' chuẩn xác!")
            print("[*] Gọi hàm log_catch_miss(1):")
            log_catch_miss(1)

            screen_miss = grab_page_bgr(page)
            if screen_miss is not None:
                h, w = screen_miss.shape[:2]
                annotated_miss = screen_miss.copy()
                cv2.putText(
                    annotated_miss,
                    "MISS: No harvest banner or energy change",
                    (int(w * 0.20), int(h * 0.45)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                )
                cv2.imwrite("debug/step_task3_catch_miss.png", annotated_miss)
                print("📸 Đã lưu ảnh minh chứng: debug/step_task3_catch_miss.png")
        else:
            print(f"❌ THẤT BẠI: Mong muốn 'miss' nhưng nhận được '{res_miss}'")
            sys.exit(1)

        # -------------------------------------------------------------
        # TEST CASE 3: Chu kỳ câu cá thật trên live game
        # -------------------------------------------------------------
        print("\n--- TEST CASE 3: Thực hiện chu kỳ câu thật trên live game ---")
        pond_pt = get_random_pond_point(page)
        if pond_pt is None:
            print("⚠️ Không tìm thấy điểm câu hợp lệ, dùng điểm trung tâm an toàn (960, 380)")
            pond_pt = (960, 380)

        cast_x, cast_y = pond_pt
        print(f"[*] Quăng cần tại mặt hồ: ({cast_x}, {cast_y})")
        log_cast(1)
        bg_click(page, cast_x, cast_y, rx=5, ry=5, fast=False, is_css=True)

        time.sleep(0.35)
        baseline_roi = capture_baseline_roi(cdp, page=page)
        rem_ignore = max(0.0, CAST_IGNORE_DURATION - 0.8)
        if rem_ignore > 0:
            time.sleep(rem_ignore)

        print("[*] Đang canh dấu chấm than (!) qua CDP (tối đa 15s)...")
        start_wait = time.time()
        caught_bite = False

        while time.time() - start_wait < 15.0:
            pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD, baseline_roi=baseline_roi)
            if pos_alert:
                caught_bite = True
                log_bite(1)
                strike_x, strike_y = bg_strike_instant(page, cdp, cast_x, cast_y, is_css=True)
                print(f"[*] Giật cần tại ({strike_x}, {strike_y})")

                live_res = verify_harvest_or_banner(page, timeout=HARVEST_VERIFY_TIMEOUT, pre_energy=cur_eng)
                print(f"[*] Kết quả xác thực sau khi giật cần: '{live_res}'")

                if live_res == 'success':
                    log_catch_success(1)
                elif live_res == 'miss':
                    log_catch_miss(1)
                else:
                    print(f"[*] Banner khác: {live_res}")

                screen_live = grab_page_bgr(page)
                if screen_live is not None:
                    cv2.imwrite("debug/step_task3_live_strike_result.png", screen_live)
                    print("📸 Đã lưu ảnh minh chứng live: debug/step_task3_live_strike_result.png")
                break
            time.sleep(0.01)

        if not caught_bite:
            print("[*] Trong 15s không có cá cắn (hoặc hồ đang chờ). Thu cần an toàn.")
            page.keyboard.press("Escape")
            time.sleep(0.5)

        ensure_clean_pond_state(page)

        # -------------------------------------------------------------
        # TEST CASE 4: Kiểm tra chống phát hiện (Anti-Detection)
        # -------------------------------------------------------------
        print("\n--- TEST CASE 4: Kiểm tra Anti-Detection (Chuột vật lý Windows) ---")
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
    print("🎉 TẤT CẢ 4 TEST CASES CỦA TASK 3 ĐÃ HOÀN THÀNH 100% PASS!")
    print("=" * 65)


if __name__ == "__main__":
    run_task3_live_verification()
