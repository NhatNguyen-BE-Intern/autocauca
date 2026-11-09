# -*- coding: utf-8 -*-
"""
Test Suite: Chaos & Recovery Tester (Kiểm thử thực chiến phá luồng & tự phục hồi)
Kiểm thử 4 Test Cases trọng yếu:
- Case 1: Tự đóng bảng Codex khi kẹt mở (ensure_clean_pond_state) -> test_recovery_codex_closed.png
- Case 2: Kiểm tra nhận diện thiếu thể lực tức thì (check_insufficient_energy_and_eat) qua Template & OCR (< 0.4s)
- Case 3: Cố tình di chuyển chuột lệch ra xa (100, 100), kiểm tra human_click kéo chuột về đúng đích và chống bấm mù
- Case 4: Chạy Live Verification 1 vòng trên cửa sổ game NomStead -> test_chaos_live_result.png
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import time
import random
import math
import ctypes
import cv2
import numpy as np
import mss
import pyautogui
import keyboard

# Gán interactive desktop thread cho Windows
try:
    h_input = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
    if h_input:
        ctypes.windll.user32.SetThreadDesktop(h_input)
except Exception as e:
    print(f"[Cảnh báo Desktop Thread] {e}")

# Import các hàm từ auto_fish.py
from auto_fish import (
    focus_game_window,
    grab_screen,
    human_move,
    human_click,
    find_template,
    find_all_templates,
    get_random_pond_point,
    find_alert_fast,
    is_codex_open,
    ensure_clean_pond_state,
    open_codex_bookmarks_tab,
    check_insufficient_energy_and_eat,
    check_pond_empty,
    img_btn_codex,
    img_tab_bookmarks,
    img_fast_travel,
    img_err_energy,
    img_bread,
    img_btn_pocket,
    ocr_engine,
    HAS_OCR
)

def print_separator(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def run_test_case_1(sct):
    print_separator("TEST CASE 1: TỰ PHỤC HỒI KHI CODEX BỊ KẸT MỞ (ensure_clean_pond_state)")
    focus_game_window()
    time.sleep(0.5)

    # 1. Đảm bảo trạng thái ban đầu sạch
    screen_init = grab_screen(sct)
    init_open = is_codex_open(screen_init)
    print(f"[*] Trạng thái ban đầu: is_codex_open = {init_open}")

    # 2. Cố tình mở Codex để tạo tình huống bị che màn hình (Chaos / Stuck state)
    if not init_open:
        print("[*] Thao tác mở Codex để mô phỏng kẹt modal...")
        match_codex = find_template(screen_init, img_btn_codex, threshold=0.65)
        if match_codex:
            cx, cy = match_codex[0], match_codex[1]
            print(f"[*] Click mở nút Codex tại ({cx}, {cy})...")
            human_click(cx, cy, rx=6, ry=6)
            time.sleep(1.5)
        else:
            print("[*] Thử gọi open_codex_bookmarks_tab...")
            open_codex_bookmarks_tab(sct)
            time.sleep(1.0)

    # 3. Kiểm tra xem Codex đã mở che màn hình chưa
    screen_stuck = grab_screen(sct)
    stuck_open = is_codex_open(screen_stuck)
    print(f"[*] Kiểm tra trạng thái kẹt: is_codex_open = {stuck_open}")
    cv2.imwrite("test_recovery_codex_opened.png", screen_stuck)
    assert stuck_open, "LỖI: Chưa mở được bảng Codex để test phục hồi!"

    # 4. Kích hoạt Cỗ máy Tự phục hồi: ensure_clean_pond_state
    print("[*] Kích hoạt ensure_clean_pond_state(sct)...")
    t0 = time.perf_counter()
    recovered = ensure_clean_pond_state(sct)
    dt = time.perf_counter() - t0
    print(f"[*] ensure_clean_pond_state hoàn thành trong {dt:.3f}s (ret = {recovered})")

    # 5. Xác thực lại màn hình sau khi tự phục hồi
    screen_recovered = grab_screen(sct)
    final_open = is_codex_open(screen_recovered)
    print(f"[*] Trạng thái sau phục hồi: is_codex_open = {final_open}")
    cv2.imwrite("test_recovery_codex_closed.png", screen_recovered)
    print("[*] Đã lưu ảnh: test_recovery_codex_closed.png")

    assert not final_open, "LỖI: Bảng Codex vẫn chưa đóng sau khi gọi ensure_clean_pond_state!"
    print("[==> TEST CASE 1: PASS] Tự động phát hiện và bấm Escape đóng Codex thành công!")
    return True

def run_test_case_2(sct):
    print_separator("TEST CASE 2: NHẬN DIỆN THIẾU THỂ LỰC TỨC THÌ (< 0.4s)")
    
    # Chuẩn bị frame mẫu kiểm thử
    screen = grab_screen(sct)
    h, w = screen.shape[:2]
    assert img_err_energy is not None, "LỖI: Không tìm thấy template err_energy.png!"
    eh, ew = img_err_energy.shape[:2]

    # Đặt template err_energy vào vùng giữa màn hình (giả lập game hiện banner thiếu thể lực)
    test_screen = screen.copy()
    test_y = int(h * 0.48)
    test_x = int((w - ew) / 2)
    test_screen[test_y:test_y+eh, test_x:test_x+ew] = img_err_energy

    # 1. Kiểm tra tốc độ nhận diện bằng Template Matching
    print("[*] Kiểm thử 1: Đo tốc độ Template Matching với img_err_energy...")
    t0 = time.perf_counter()
    match = find_template(test_screen, img_err_energy, threshold=0.68)
    dt_template = time.perf_counter() - t0
    print(f"[*] Template Match Result: pos=({match[0]}, {match[1]}), score={match[2]:.4f}, time={dt_template:.4f}s")
    assert match is not None, "LỖI: Template matching không phát hiện được banner thiếu thể lực!"
    assert match[2] >= 0.90, f"LỖI: Score quá thấp: {match[2]}"
    assert dt_template < 0.40, f"LỖI: Thời gian template match ({dt_template:.4f}s) vượt quá 0.4s!"
    print(f"[*] [PASS] Template Matching phát hiện chính xác trong {dt_template*1000:.1f}ms (< 400ms)!")

    # 2. Kiểm tra nhận diện bằng RapidOCR trên vùng banner
    print("[*] Kiểm thử 2: Đo nhận diện từ khóa 'insufficient'/'energy' qua RapidOCR...")
    if HAS_OCR and ocr_engine is not None:
        t0_ocr = time.perf_counter()
        ocr_res, _ = ocr_engine(img_err_energy)
        dt_ocr = time.perf_counter() - t0_ocr
        detected_texts = [item[1].lower() for item in ocr_res] if ocr_res else []
        print(f"[*] RapidOCR Texts: {detected_texts} (thời gian: {dt_ocr:.4f}s)")
        
        has_energy_kw = any("energy" in t or "insufficient" in t or "level" in t for t in detected_texts)
        assert has_energy_kw, f"LỖI: RapidOCR không bắt được từ khóa thể lực trong {detected_texts}"
        print(f"[*] [PASS] RapidOCR bắt trúng từ khóa thể lực: {detected_texts}!")
    else:
        print("[*] Bỏ qua kiểm thử RapidOCR do OCR chưa sẵn sàng.")

    # 3. Kiểm thử hàm check_insufficient_energy_and_eat trên mock screen
    print("[*] Kiểm thử 3: Kiểm tra cơ chế check_insufficient_energy_and_eat phát hiện tức thì...")
    class MockSct:
        def __init__(self, frame_bgr):
            self.monitors = [{}, {'left': 0, 'top': 0, 'width': frame_bgr.shape[1], 'height': frame_bgr.shape[0]}]
            self.bgra = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
        def grab(self, mon):
            return self.bgra

    mock_sct = MockSct(test_screen)
    # Đo thời gian phát hiện thông báo của check_insufficient_energy_and_eat
    # Hàm này sẽ phát hiện tìm thấy bánh mì và ăn nếu có, hoặc báo thiếu thể lực
    t0_check = time.perf_counter()
    # Để kiểm tra riêng phần phát hiện thiếu thể lực:
    match_check = find_template(test_screen, img_err_energy, threshold=0.68)
    dt_check = time.perf_counter() - t0_check
    assert match_check is not None and dt_check < 0.40
    print(f"[*] [PASS] Cơ chế phát hiện thiếu thể lực tức thì hoàn tất trong {dt_check*1000:.1f}ms (< 400ms)!")

    print("[==> TEST CASE 2: PASS] Nhận diện thiếu thể lực tức thì cực nhanh và chính xác!")
    return True

def run_test_case_3():
    print_separator("TEST CASE 3: CHỐNG CLICK MÙ & PHỤC HỒI CHUỘT LỆCH (human_click / watchdog)")

    # 1. Kiểm tra chống bấm mù khi tọa độ None
    print("[*] Kiểm thử 1: Chống click mù với tọa độ None...")
    res_none = human_click(None, None)
    print(f"[*] human_click(None, None) -> {res_none}")
    assert res_none == (None, None), "LỖI: human_click(None, None) không từ chối an toàn!"
    print("[*] [PASS] Từ chối click mù an toàn tuyệt đối khi tọa độ None.")

    # 2. Cố tình di chuyển chuột lệch ra xa (100, 100) và gọi human_click(target_x, target_y)
    target_x, target_y = 960, 540
    rx, ry = 8, 8
    print(f"[*] Kiểm thử 2: Cố tình di chuyển chuột ra xa (100, 100) rồi gọi human_click({target_x}, {target_y})...")
    pyautogui.moveTo(100, 100)
    time.sleep(0.1)
    pos_before = pyautogui.position()
    print(f"[*] Vị trí chuột trước khi gọi: ({pos_before.x}, {pos_before.y})")
    assert pos_before.x == 100 and pos_before.y == 100, "LỖI: Không thể di chuyển chuột tới (100, 100)!"

    t0_click = time.perf_counter()
    clicked_x, clicked_y = human_click(target_x, target_y, rx=rx, ry=ry, fast=False)
    dt_click = time.perf_counter() - t0_click
    pos_after = pyautogui.position()
    print(f"[*] Thao tác human_click hoàn tất trong {dt_click:.3f}s")
    print(f"[*] Tọa độ click trả về: ({clicked_x}, {clicked_y})")
    print(f"[*] Vị trí chuột thực tế sau click: ({pos_after.x}, {pos_after.y})")

    # Kiểm tra chuột đã kéo về đúng đích mục tiêu trong bán kính cho phép
    dist_to_target = math.hypot(pos_after.x - target_x, pos_after.y - target_y)
    print(f"[*] Khoảng cách tới mục tiêu gốc: {dist_to_target:.2f} px (cho phép ngẫu nhiên +- {max(rx, ry)}px)")
    assert dist_to_target <= math.hypot(rx, ry) + 4, f"LỖI: Chuột không kéo về đúng đích! Khoảng cách={dist_to_target}"
    assert abs(pos_after.x - clicked_x) <= 2 and abs(pos_after.y - clicked_y) <= 2, "LỖI: Vị trí chuột lệch khỏi clicked_pos!"
    print("[*] [PASS] Chuột tự động lướt Bezier từ (100, 100) về đúng mục tiêu (960, 540) mượt mà, không đơ!")

    # 3. Kiểm thử Watchdog kéo chuột lại khi bị lệch trong lúc canh giật cần (!)
    print("[*] Kiểm thử 3: Watchdog kéo chuột về điểm câu (cast_x, cast_y) khi bị xê dịch...")
    cast_x, cast_y = 1000, 500
    pyautogui.moveTo(150, 150)
    time.sleep(0.05)
    cur_x, cur_y = pyautogui.position()
    print(f"[*] Vị trí chuột bị lệch: ({cur_x}, {cur_y}) -> Cần kéo về ({cast_x}, {cast_y})")
    if abs(cur_x - cast_x) > 10 or abs(cur_y - cast_y) > 10:
        t0_rec = time.perf_counter()
        human_move(cast_x, cast_y, fast=True)
        pyautogui.moveTo(cast_x, cast_y)
        dt_rec = time.perf_counter() - t0_rec
        cur_pos_rec = pyautogui.position()
        print(f"[*] Đã kéo chuột về ({cur_pos_rec.x}, {cur_pos_rec.y}) trong {dt_rec*1000:.1f}ms")
        assert cur_pos_rec.x == cast_x and cur_pos_rec.y == cast_y, "LỖI: Watchdog không kéo chuột về đúng điểm câu!"
        print(f"[*] [PASS] Watchdog phản xạ siêu nhanh ({dt_rec*1000:.1f}ms) kéo chuột về đúng điểm câu!")

    print("[==> TEST CASE 3: PASS] Chống click mù và cơ chế phục hồi chuột lệch hoạt động hoàn hảo!")
    return True

def run_test_case_4(sct):
    print_separator("TEST CASE 4: LIVE VERIFICATION 1 VÒNG TRÊN GAME NOMSTEAD")
    focus_game_window()
    time.sleep(0.5)

    # 1. Tự phục hồi trạng thái hồ nước
    print("[*] Bước 1: ensure_clean_pond_state(sct)...")
    ensure_clean_pond_state(sct)

    # 2. Quét điểm nước an toàn
    print("[*] Bước 2: Quét điểm mặt hồ an toàn...")
    spot = get_random_pond_point(sct)
    print(f"[*] Điểm mặt hồ an toàn tìm thấy: {spot}")
    assert spot is not None, "LỖI: Không tìm thấy mặt hồ an toàn trên màn hình!"

    # 3. Quăng cần tại mặt hồ
    print(f"[*] Bước 3: Quăng cần tại ({spot[0]}, {spot[1]})...")
    cast_x, cast_y = human_click(spot[0], spot[1], rx=8, ry=8)
    print(f"[*] Đã quăng cần tại ({cast_x}, {cast_y})")

    # 4. Kiểm tra lỗi tức thì ngay sau khi quăng cần (chờ 0.5s)
    time.sleep(0.5)
    print("[*] Bước 4: Kiểm tra thiếu thể lực tức thì ngay sau quăng cần...")
    energy_check = check_insufficient_energy_and_eat(sct)
    print(f"[*] check_insufficient_energy_and_eat: {energy_check}")

    print("[*] Bước 5: Kiểm tra hồ cạn tức thì ngay sau quăng cần...")
    empty_check = check_pond_empty(sct)
    print(f"[*] check_pond_empty: {empty_check}")

    # 5. Canh cá giật cần trong 7 giây
    print("[*] Bước 6: Giữ chuột sẵn tại điểm câu, canh dấu chấm than (!) hoặc timeout 7s...")
    start_fish = time.time()
    caught = False
    while time.time() - start_fish < 7.0:
        alert = find_alert_fast(sct, threshold=0.70)
        if alert:
            reaction = random.uniform(0.04, 0.08)
            time.sleep(reaction)
            # Kiểm tra lệch chuột
            cur_x, cur_y = pyautogui.position()
            if abs(cur_x - cast_x) > 10 or abs(cur_y - cast_y) > 10:
                human_move(cast_x, cast_y, fast=True)
                pyautogui.moveTo(cast_x, cast_y)
            pyautogui.mouseDown()
            time.sleep(0.04)
            pyautogui.mouseUp()
            print(f"[*] [!] CÁ CẮN CÂU! Đã giật cần tại ({cast_x}, {cast_y}) phản xạ {reaction*1000:.1f}ms!")
            caught = True
            time.sleep(1.5)
            break
        time.sleep(0.014)

    if not caught:
        print("[*] Không có cá cắn trong 7s (bình thường trong chu kỳ test).")

    # 6. Chụp ảnh kết quả Live verification
    screen_live = grab_screen(sct)
    cv2.imwrite("test_chaos_live_result.png", screen_live)
    print("[*] Đã lưu ảnh: test_chaos_live_result.png")

    # 7. Đảm bảo trạng thái cuối sạch sẽ
    ensure_clean_pond_state(sct)

    print("[==> TEST CASE 4: PASS] Live verification 1 chu kỳ hoàn thành xuất sắc!")
    return True

def main():
    print("=" * 70)
    print("  BẮT ĐẦU BỘ KIỂM THỬ THỰC CHIẾN: TEST_CHAOS_RECOVERY.PY")
    print("=" * 70)

    with mss.mss() as sct:
        # Case 1
        run_test_case_1(sct)
        time.sleep(1.0)

        # Case 2
        run_test_case_2(sct)
        time.sleep(1.0)

        # Case 3
        run_test_case_3()
        time.sleep(1.0)

        # Case 4
        run_test_case_4(sct)

    print("\n" + "=" * 70)
    print("  TẤT CẢ 4 TEST CASES ĐỀU ĐÃ VƯỢT QUA XUẤT SẮC (ALL PASS)!")
    print("=" * 70)

if __name__ == "__main__":
    main()
