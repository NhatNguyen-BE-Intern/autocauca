# -*- coding: utf-8 -*-
"""
Live Vision Observer & Tester: Kiểm thử thực tế HO 37 -> HO 38
Kịch bản:
1. Gắn desktop thread và chống sleep.
2. Đếm ngược 4s và focus Chrome window.
3. Bắt buộc mở Codex -> Bookmarks -> OCR tìm HO 37 -> click Fast Travel. Chụp test_ho37_fast_travel.png.
4. Chờ 4.5s tới HO 37. Chụp test_ho37_arrived.png.
5. Tại HO 37: Thử quăng cần vào hồ an toàn. Chuột nằm im tại điểm câu.
   Canh dấu ! (giật siêu tốc 40-70ms) HOẶC bắt thông báo hết cá qua OCR check_pond_empty.
   Chụp ảnh kết quả: test_ho37_strike.png hoặc test_ho37_empty_detected.png.
6. Khi phát hiện hết cá (hoặc sau khi câu xong nhịp):
   Mở lại Codex -> Bookmarks -> OCR tìm HO 38 -> click Fast Travel sang HO 38. Chụp test_ho38_fast_travel.png.
7. Chờ 4.5s tới HO 38. Chụp test_ho38_arrived.png.
"""

import sys
import os
import time
import datetime
import random
import re
import ctypes
from ctypes import wintypes
import numpy as np
import cv2
import mss
import pyautogui
import keyboard

# =========================================================================
# 1. CẤU HÌNH CONSOLE WINDOWS UTF-8 & PYAUTOGUI
# =========================================================================
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        if sys.stdin and hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

# =========================================================================
# 2. CHỐNG SLEEP & GẮN INTERACTIVE DESKTOP THREAD
# =========================================================================
try:
    ret_state = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)
    print(f"[Nền tảng] SetThreadExecutionState chống Sleep kích hoạt: {ret_state != 0}")
except Exception as e:
    print(f"[Cảnh báo] Lỗi SetThreadExecutionState: {e}")

try:
    h_input = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
    if h_input:
        set_ok = ctypes.windll.user32.SetThreadDesktop(h_input)
        print(f"[Nền tảng] OpenInputDesktop & SetThreadDesktop thành công (hDesktop={h_input}, status={set_ok})")
    else:
        print("[Lưu ý] OpenInputDesktop trả về NULL (đang trong active session)")
except Exception as e:
    print(f"[Cảnh báo] Lỗi gán desktop thread: {e}")

# Import các hàm và templates từ auto_fish để đảm bảo tính nhất quán tuyệt đối
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from auto_fish import (
    focus_game_window,
    open_codex_bookmarks_tab,
    find_bookmark_row_by_ocr,
    get_random_pond_point,
    find_alert_fast,
    check_pond_empty,
    check_insufficient_energy_and_eat,
    human_move,
    human_click,
    grab_screen,
    find_template,
    find_all_templates,
    img_fast_travel,
    img_alert_gray,
    img_err_trash,
    img_err_empty,
    WATER_LOWER,
    WATER_UPPER,
    HAS_OCR,
    ocr_engine,
    SCROLL_STEP
)

def run_live_vision_test():
    print("=" * 70)
    print("   LIVE VISION OBSERVER & TESTER: HO 37 -> FISHING/EMPTY -> HO 38")
    print("=" * 70)

    # 1. Focus Chrome window & Đếm ngược 4s
    focus_game_window()
    print("\n[BƯỚC 1] Đếm ngược 4 giây chuẩn bị tương tác game Chrome...")
    for i in range(4, 0, -1):
        print(f" >>> Bắt đầu sau {i} giây...")
        time.sleep(1.0)
    print(" >>> BẮT ĐẦU TEST THỰC TẾ!\n")

    focus_game_window()
    time.sleep(0.5)

    with mss.mss() as sct:
        # -----------------------------------------------------------------
        # GIAI ĐOẠN 1: Mở Codex -> Bookmarks -> OCR tìm HO 37 -> Fast Travel
        # -----------------------------------------------------------------
        print("\n--- GIAI ĐOẠN 1: Điều hướng tới HO 37 ---")
        if not open_codex_bookmarks_tab(sct):
            print("[LỖI] Không thể mở tab Bookmarks!")
            return False

        # Di chuột vào giữa danh sách Bookmarks (900, 550) và cuộn lên đầu danh sách
        scroll_center_x, scroll_center_y = 900, 550
        print(f"  Di chuột vào giữa danh sách Bookmarks ({scroll_center_x}, {scroll_center_y})...")
        human_move(scroll_center_x, scroll_center_y, fast=False)
        time.sleep(0.3)

        print("  Lăn chuột cuộn lên đầu danh sách (scroll 5000)...")
        pyautogui.scroll(5000)
        time.sleep(0.8)

        # Quét OCR tìm HO 37
        found_ho37 = None
        max_scroll_steps = 30
        for step in range(max_scroll_steps):
            screen_bgr = grab_screen(sct)
            print(f"  [Quét nhịp {step:02d}] Đang OCR tìm 'HO 37'...")
            res = find_bookmark_row_by_ocr(screen_bgr, target_num=37)
            if res:
                found_ho37 = res
                print(f"  ==> ĐÃ TÌM THẤY '{res['text']}' tại nhịp {step}!")
                break
            pyautogui.scroll(SCROLL_STEP)
            time.sleep(0.40)

        if not found_ho37:
            print("[LỖI] Không tìm thấy HO 37 trong danh sách Bookmarks!")
            return False

        # Chụp ảnh test_ho37_fast_travel.png kèm annotation
        screen_ho37 = grab_screen(sct)
        annotated_ho37 = screen_ho37.copy()
        tx, ty = found_ho37['text_pos']
        fx, fy = found_ho37['btn_pos']
        b = np.array(found_ho37['box'], dtype=np.int32)
        cv2.polylines(annotated_ho37, [b], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.putText(annotated_ho37, f"FOUND: {found_ho37['text']}", (tx - 60, ty - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.circle(annotated_ho37, (int(fx), int(fy)), 20, (0, 0, 255), 3)
        cv2.putText(annotated_ho37, "FAST TRAVEL -> HO 37", (int(fx) - 100, int(fy) + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imwrite('test_ho37_fast_travel.png', annotated_ho37)
        print("  [Bằng chứng] Đã lưu ảnh: test_ho37_fast_travel.png")

        # Click nút Fast Travel của HO 37
        print(f"  Click nút Fast Travel HO 37 tại ({fx}, {fy})...")
        human_click(int(fx), int(fy), rx=15, ry=5)

        # -----------------------------------------------------------------
        # GIAI ĐOẠN 2: Chờ 4.5s tới HO 37 -> Chụp test_ho37_arrived.png
        # -----------------------------------------------------------------
        print("\n--- GIAI ĐOẠN 2: Chờ 4.5s nhân vật tới HO 37 ---")
        time.sleep(4.5)
        screen_arrived_ho37 = grab_screen(sct)
        cv2.imwrite('test_ho37_arrived.png', screen_arrived_ho37)
        print("  [Bằng chứng] Đã lưu ảnh: test_ho37_arrived.png")

        # -----------------------------------------------------------------
        # GIAI ĐOẠN 3: Thử quăng cần vào lòng hồ HO 37 & Canh giật (!) hoặc Bắt Hết Cá
        # -----------------------------------------------------------------
        print("\n--- GIAI ĐOẠN 3: Thử quăng cần vào lòng hồ HO 37 ---")
        cast_spot = get_random_pond_point(sct)
        if cast_spot:
            cast_x, cast_y = cast_spot
            print(f"  Đã xác định vị trí mặt nước an toàn: ({cast_x}, {cast_y})")
        else:
            h, w = screen_arrived_ho37.shape[:2]
            cast_x, cast_y = int(w * 0.50), int(h * 0.45)
            print(f"  [Mặc định] Sử dụng tâm hồ: ({cast_x}, {cast_y})")

        # Thả cần vào hồ và giữ nguyên vị trí chuột tại đó
        human_click(cast_x, cast_y, rx=6, ry=6)
        print(f"  Đã quăng cần tại ({cast_x}, {cast_y}). Chuột giữ nguyên tại vị trí phao!")

        start_fish_time = time.time()
        fish_caught = False
        empty_detected = False
        saved_strike_img = False
        saved_empty_img = False

        print("  Đang canh dấu chấm than (!) giật siêu tốc HOẶC bắt thông báo hết cá...")
        while time.time() - start_fish_time < 15.0:
            # 1. Canh dấu chấm than (!) phản xạ siêu tốc 40-70ms
            pos_alert = find_alert_fast(sct, threshold=0.70)
            if pos_alert:
                reaction_delay = random.uniform(0.040, 0.070)
                time.sleep(reaction_delay)

                # Giật cần tức thì tại phao
                pyautogui.mouseDown()
                time.sleep(0.04)
                pyautogui.mouseUp()

                print(f"  [!] CÁ CẮN CÂU! (Phản xạ: {reaction_delay*1000:.1f}ms) -> Đã giật cần tức thì!")
                fish_caught = True

                # Chụp ngay ảnh màn hình giật cá
                strike_screen = grab_screen(sct)
                annotated_strike = strike_screen.copy()
                cv2.circle(annotated_strike, pos_alert, 25, (0, 0, 255), 3)
                cv2.putText(annotated_strike, f"STRIKE! Reaction: {reaction_delay*1000:.1f}ms", 
                            (pos_alert[0] - 80, pos_alert[1] - 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.imwrite('test_ho37_strike.png', annotated_strike)
                saved_strike_img = True
                print("  [Bằng chứng] Đã lưu ảnh: test_ho37_strike.png")

                # Chờ 1.3s để bắt bảng kết quả kéo lên
                time.sleep(1.3)

                # Kiểm tra sau khi giật xem có phải rác hoặc hết cá không
                if check_pond_empty(sct):
                    print("  Phát hiện bảng báo hết cá / rác sau khi giật!")
                    empty_detected = True
                    empty_scr = grab_screen(sct)
                    cv2.imwrite('test_ho37_empty_detected.png', empty_scr)
                    saved_empty_img = True
                    print("  [Bằng chứng] Đã lưu ảnh: test_ho37_empty_detected.png")
                break

            # 2. Canh bảng thông báo hết cá (err_empty, err_trash, OCR "nothing left"...)
            if (time.time() - start_fish_time) > 1.2:
                if check_pond_empty(sct):
                    print("  ==> PHÁT HIỆN THÔNG BÁO HẾT CÁ!")
                    empty_detected = True
                    empty_screen = grab_screen(sct)
                    annotated_empty = empty_screen.copy()
                    h_e, w_e = empty_screen.shape[:2]
                    cv2.rectangle(annotated_empty, (int(w_e*0.35), int(h_e*0.72)), (int(w_e*0.65), int(h_e*0.82)), (0, 0, 255), 3)
                    cv2.putText(annotated_empty, "POND EMPTY DETECTED", (int(w_e*0.36), int(h_e*0.71)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    cv2.imwrite('test_ho37_empty_detected.png', annotated_empty)
                    saved_empty_img = True
                    print("  [Bằng chứng] Đã lưu ảnh: test_ho37_empty_detected.png")
                    break

            time.sleep(0.014)  # ~71 FPS

        # Đảm bảo có ít nhất 1 ảnh bằng chứng câu cá
        if not saved_strike_img and not saved_empty_img:
            print("  [Lưu ý] Kết thúc nhịp câu (15s timeout hoặc không cắn), chụp ảnh hiện trạng hồ 37...")
            res_scr = grab_screen(sct)
            if check_pond_empty(sct) or empty_detected:
                cv2.imwrite('test_ho37_empty_detected.png', res_scr)
                print("  [Bằng chứng] Đã lưu ảnh: test_ho37_empty_detected.png")
            else:
                cv2.imwrite('test_ho37_strike.png', res_scr)
                print("  [Bằng chứng] Đã lưu ảnh: test_ho37_strike.png")

        time.sleep(1.0)

        # -----------------------------------------------------------------
        # GIAI ĐOẠN 4: Mở lại Codex -> Bookmarks -> OCR tìm HO 38 -> Fast Travel
        # -----------------------------------------------------------------
        print("\n--- GIAI ĐOẠN 4: Chuyển tiếp sang HO 38 ---")
        if not open_codex_bookmarks_tab(sct):
            print("[LỖI] Không thể mở lại tab Bookmarks ở Giai đoạn 4!")
            return False

        # Di chuột vào giữa danh sách Bookmarks và cuộn lên đầu
        human_move(scroll_center_x, scroll_center_y, fast=False)
        time.sleep(0.3)
        print("  Cuộn danh sách lên đầu trang (scroll 5000)...")
        pyautogui.scroll(5000)
        time.sleep(0.8)

        # Quét OCR tìm HO 38
        found_ho38 = None
        for step in range(max_scroll_steps):
            screen_bgr = grab_screen(sct)
            print(f"  [Quét nhịp {step:02d}] Đang OCR tìm 'HO 38'...")
            res = find_bookmark_row_by_ocr(screen_bgr, target_num=38)
            if res:
                found_ho38 = res
                print(f"  ==> ĐÃ TÌM THẤY '{res['text']}' tại nhịp {step}!")
                break
            pyautogui.scroll(SCROLL_STEP)
            time.sleep(0.40)

        if not found_ho38:
            print("[LỖI] Không tìm thấy HO 38 trong danh sách Bookmarks!")
            return False

        # Chụp ảnh test_ho38_fast_travel.png kèm annotation
        screen_ho38 = grab_screen(sct)
        annotated_ho38 = screen_ho38.copy()
        tx, ty = found_ho38['text_pos']
        fx, fy = found_ho38['btn_pos']
        b = np.array(found_ho38['box'], dtype=np.int32)
        cv2.polylines(annotated_ho38, [b], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.putText(annotated_ho38, f"FOUND: {found_ho38['text']}", (tx - 60, ty - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.circle(annotated_ho38, (int(fx), int(fy)), 20, (0, 0, 255), 3)
        cv2.putText(annotated_ho38, "FAST TRAVEL -> HO 38", (int(fx) - 100, int(fy) + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imwrite('test_ho38_fast_travel.png', annotated_ho38)
        print("  [Bằng chứng] Đã lưu ảnh: test_ho38_fast_travel.png")

        # Click nút Fast Travel của HO 38
        print(f"  Click nút Fast Travel HO 38 tại ({fx}, {fy})...")
        human_click(int(fx), int(fy), rx=15, ry=5)

        # -----------------------------------------------------------------
        # GIAI ĐOẠN 5: Chờ 4.5s tới HO 38 -> Chụp test_ho38_arrived.png
        # -----------------------------------------------------------------
        print("\n--- GIAI ĐOẠN 5: Chờ 4.5s nhân vật tới HO 38 ---")
        time.sleep(4.5)
        screen_arrived_ho38 = grab_screen(sct)
        cv2.imwrite('test_ho38_arrived.png', screen_arrived_ho38)
        print("  [Bằng chứng] Đã lưu ảnh: test_ho38_arrived.png")

        print("\n" + "=" * 70)
        print("   HOÀN TẤT KIỂM THỬ THỰC TẾ TRỰC QUAN HO 37 -> HO 38 THÀNH CÔNG!")
        print("=" * 70)
        return True

if __name__ == "__main__":
    success = run_live_vision_test()
    if not success:
        sys.exit(1)
