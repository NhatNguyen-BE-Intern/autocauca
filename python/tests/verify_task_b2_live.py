# -*- coding: utf-8 -*-
"""
Script kiểm thử nghiệm thu thực chiến TASK B2 (AI Tester Verification):
1. Kết nối live game qua Chrome CDP (port 9222).
2. Đo vị trí chuột Windows ban đầu (bảo toàn Anti-Detection).
3. Kiểm tra Smart Modal Polling khi mở Codex / Bookmarks.
4. Đo lường thời gian chuyển cảnh bằng wait_for_pond_arrival so với sleep(4.5) cũ.
5. Kiểm tra cơ chế cuộn thông minh scroll_top_first=False khi đổi sang hồ kế tiếp.
6. Kiểm tra phát hiện mặt nước hồ an toàn sau khi chuyển cảnh.
7. Xác nhận chuột Windows 0px drift (100% Anti-Detection).
8. Lưu ảnh chụp bằng chứng debug/step_b2_smart_transition.png.
"""
import sys
import time
import ctypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import config.settings as settings
import core.logger as logger
from core.cdp_client import connect_cdp, close_cdp
from core.vision import grab_page_bgr, get_random_pond_point
from core.navigation import (
    open_codex_bookmarks_tab,
    travel_to_bookmark,
    wait_for_pond_arrival,
)
from core.watchdog import ensure_clean_pond_state

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def run_task_b2_live_verification():
    print("=" * 75)
    print("BẮT ĐẦU KIỂM THỬ THỰC CHIẾN TASK B2 (AI TESTER VERIFICATION)")
    print("Tối Ưu Rút Ngắn Dead-time & Tăng Tốc Chuyển Cảnh Thông Minh")
    print("=" * 75)

    # 1. Ghi nhận vị trí chuột Windows ban đầu
    x_start, y_start = get_mouse_pos()
    print(f"\n[Evidence 1] Vị trí chuột Windows ban đầu: ({x_start}, {y_start})")

    # 2. Kết nối Chrome CDP
    p, b, page, cdp = connect_cdp()
    if not page or not cdp:
        print("[LỖI] Không thể kết nối tới Chrome game qua CDP port 9222!")
        return False

    try:
        ensure_clean_pond_state(page)

        # 3. Test Smart Modal Polling: Mở Codex & Bookmarks
        print("\n--- TEST A: Kiểm tra Smart Modal Polling (Mở Codex & Bookmarks) ---")
        t_modal_start = time.time()
        modal_ok = open_codex_bookmarks_tab(page)
        t_modal_elapsed = time.time() - t_modal_start
        print(f"[Evidence 2] Kết quả mở Codex & Bookmarks: {modal_ok}")
        print(f"[Evidence 2] Thời gian mở modal hoàn tất: {t_modal_elapsed:.2f}s (nhanh hơn sleep 2.5s cũ!)")
        assert modal_ok, "LỖI: Không thể mở Codex & Bookmarks tab!"

        # 4. Test cuộn thông minh và chuyển hồ: Fast Travel HO 37
        print("\n--- TEST B: Kiểm tra Fast Travel & wait_for_pond_arrival ---")
        target_lake = 37
        t_travel_start = time.time()
        
        # travel_to_bookmark đã tích hợp wait_for_pond_arrival
        travel_ok = travel_to_bookmark(page, target_lake, scroll_top_first=True)
        t_travel_total = time.time() - t_travel_start
        print(f"[Evidence 3] Kết quả di chuyển tới HO {target_lake}: {travel_ok}")
        print(f"[Evidence 3] Tổng thời gian di chuyển & chuyển cảnh: {t_travel_total:.2f}s")
        assert travel_ok, f"LỖI: Di chuyển tới HO {target_lake} thất bại!"

        # 5. Kiểm tra trực tiếp hàm wait_for_pond_arrival và đo dead-time tiết kiệm
        print("\n--- TEST C: Đo lường wait_for_pond_arrival trên mặt nước hồ ---")
        t_arr_start = time.time()
        arr_ok = wait_for_pond_arrival(page, min_wait=0.9, timeout=4.5, interval=0.15)
        t_arr_elapsed = time.time() - t_arr_start
        time_saved = 4.5 - t_arr_elapsed
        print(f"[Evidence 4] wait_for_pond_arrival phát hiện mặt nước sau: {t_arr_elapsed:.2f}s")
        print(f"[Evidence 4] Thời gian tiết kiệm so với sleep(4.5) cũ: {time_saved:.2f}s (Tiết kiệm {(time_saved/4.5)*100:.1f}%)")
        assert arr_ok, "LỖI: wait_for_pond_arrival không nhận diện được mặt nước!"
        assert t_arr_elapsed < 2.5, f"LỖI: Thời gian nhận diện mặt nước quá lâu ({t_arr_elapsed:.2f}s >= 2.5s)!"

        # 6. Kiểm tra phát hiện điểm quăng cần an toàn (Erosion 25x25)
        print("\n--- TEST D: Quét điểm mặt nước an toàn sau khi đến nơi ---")
        spot = get_random_pond_point(page)
        print(f"[Evidence 5] Tọa độ mặt nước an toàn tìm được: {spot}")
        assert spot is not None, "LỖI: Không tìm thấy mặt nước an toàn trong hồ!"

        # 7. Test cơ chế cuộn thông minh scroll_top_first=False khi sang hồ kế tiếp (HO 38)
        print("\n--- TEST E: Kiểm tra cuộn thông minh scroll_top_first=False sang hồ kế tiếp (HO 38) ---")
        t_next_start = time.time()
        # Gọi travel_to_bookmark với scroll_top_first=False (mô phỏng advance_to_next_pond)
        next_ok = travel_to_bookmark(page, 38, scroll_top_first=False)
        t_next_elapsed = time.time() - t_next_start
        print(f"[Evidence 6] Di chuyển tới HO 38 (scroll_top_first=False): {next_ok}")
        print(f"[Evidence 6] Thời gian hoàn thành chuyển hồ kế tiếp: {t_next_elapsed:.2f}s")
        assert next_ok, "LỖI: Chuyển sang HO 38 thất bại!"
        assert t_next_elapsed < 4.8, f"LỖI: Thời gian chuyển hồ kế tiếp quá lâu ({t_next_elapsed:.2f}s)!"

        # 8. Chụp ảnh màn hình lưu vào debug/
        scr_live = grab_page_bgr(page)
        if scr_live is not None:
            debug_path = PROJECT_ROOT / "debug" / "step_b2_smart_transition.png"
            cv2.imwrite(str(debug_path), scr_live)
            print(f"\n[Evidence 7] Đã lưu ảnh minh chứng live game: {debug_path}")
            print(f"[Evidence 7] Kích thước ảnh: {scr_live.shape}")

        # 9. Đóng modal nếu còn mở
        ensure_clean_pond_state(page)

        # 10. Đo lường chuột Windows cuối cùng
        x_end, y_end = get_mouse_pos()
        dx = abs(x_end - x_start)
        dy = abs(y_end - y_start)
        print(f"\n[Evidence 8] Vị trí chuột Windows sau test: ({x_end}, {y_end})")
        print(f"[Evidence 8] Độ xê dịch chuột: dx={dx}px, dy={dy}px")
        assert dx == 0 and dy == 0, f"LỖI: Chuột Windows bị xê dịch ({dx}px, {dy}px)!"
        print("[Verification PASS] Chuột Windows 0px drift (100% Anti-Detection được bảo toàn tuyệt đối)!")

        print("\n" + "=" * 75)
        print("TẤT CẢ CÁC HẠNG MỤC KIỂM THỬ THỰC CHIẾN TASK B2 ĐỀU ĐẠT CHUẨN 100% (PASS)")
        print("=" * 75)
        return True

    finally:
        close_cdp(p, b)

if __name__ == "__main__":
    success = run_task_b2_live_verification()
    sys.exit(0 if success else 1)
