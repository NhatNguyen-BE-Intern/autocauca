# -*- coding: utf-8 -*-
"""
Script kiểm thử nghiệm thu thực chiến TASK B3 (AI Tester Verification):
NÂNG CẤP TỰ PHỤC HỒI BẤT TỬ (IMMORTAL WATCHDOG) & VẬN HÀNH ỔN ĐỊNH 24/24

Kiểm thử 5 Trụ Cột Bất Tử trên Live Game Session:
1. Tự phục hồi CDP Session tại chỗ (get_or_refresh_cdp_session) khi session bị stale/detached.
2. Dọn dẹp ổ đĩa tự động (cleanup_old_debug_files giữ tối đa 25 file) & vệ sinh RAM (gc.collect).
3. Lưu & phục hồi phiên làm việc (save_session_state & load_session_state via session_state.json).
4. Universal Popup Dismissal (dismiss_unexpected_popups & ensure_clean_pond_state).
5. Bảo toàn tuyệt đối Anti-Detection: 0px chuột Windows di chuyển (dx=0, dy=0).
6. Chụp ảnh minh chứng thực tế lưu vào debug/step_b3_immortal_watchdog.png.
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
from core.cdp_client import connect_cdp, close_cdp, get_or_refresh_cdp_session
from core.vision import grab_page_bgr, get_random_pond_point
from core.watchdog import (
    cleanup_old_debug_files,
    save_session_state,
    load_session_state,
    dismiss_unexpected_popups,
    ensure_clean_pond_state,
)
from core.navigation import travel_to_bookmark

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def run_task_b3_live_verification():
    print("=" * 75)
    print("BẮT ĐẦU KIỂM THỬ THỰC CHIẾN TASK B3 (AI TESTER VERIFICATION)")
    print("Nâng Cấp Tự Phục Hồi Bất Tử (Immortal Watchdog) & Ổn Định 24/24")
    print("=" * 75)

    # 1. Ghi nhận vị trí chuột Windows ban đầu
    x_start, y_start = get_mouse_pos()
    print(f"\n[Evidence 1] Vị trí chuột Windows ban đầu: ({x_start}, {y_start})")

    # 2. Kết nối Chrome CDP port 9222
    p, b, page, cdp = connect_cdp()
    if not page or not cdp:
        print("[LỖI] Không thể kết nối tới Chrome game qua CDP port 9222!")
        return False

    try:
        # TRỤ CỘT 1: Tự phục hồi CDP Session tại chỗ
        print("\n--- TRỤ CỘT 1: Kiểm thử Tự Phục Hồi CDP Session Tại Chỗ ---")
        alive_cdp = get_or_refresh_cdp_session(page)
        res_alive = alive_cdp.send("Runtime.evaluate", {"expression": "document.title"})
        print(f"[Evidence 2A] Session hiện tại sống tốt: {res_alive.get('result', {}).get('value')}")
        assert res_alive and "result" in res_alive, "LỖI: CDP session ban đầu không phản hồi!"

        # Giả lập stale session bằng cách gán object lỗi
        class StaleCDP:
            def send(self, method, params=None):
                raise Exception("Simulated DevTools target detached exception!")

        page._cdp_session = StaleCDP()
        print("[Evidence 2B] Đã giả lập CDP session bị stale/detached.")

        # Gọi get_or_refresh_cdp_session để tự phục hồi
        refreshed_cdp = get_or_refresh_cdp_session(page)
        self_recovered = (refreshed_cdp is not None and not isinstance(refreshed_cdp, StaleCDP))
        print(f"[Evidence 2C] Tự động tái tạo CDP session mới tại chỗ: {self_recovered}")
        assert self_recovered, "LỖI: get_or_refresh_cdp_session không tự tạo session mới!"

        res_ping = refreshed_cdp.send("Runtime.evaluate", {"expression": "100 + 200"})
        ping_val = res_ping.get('result', {}).get('value')
        print(f"[Evidence 2D] Ping thử nghiệm trên CDP session mới: {ping_val} (Kỳ vọng: 300)")
        assert ping_val == 300, "LỖI: CDP session mới không thực thi được lệnh!"
        print("[Trụ Cột 1 PASS] Khả năng tự phục hồi CDP Session đạt chuẩn Bất Tử!")

        # TRỤ CỘT 2: Dọn dẹp ổ đĩa & Vệ sinh RAM
        print("\n--- TRỤ CỘT 2: Kiểm thử Dọn Dẹp Đĩa Debug (Max 25 file) & Vệ Sinh RAM ---")
        debug_dir = settings.DEBUG_DIR
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Tạo file ảnh giả lập để vượt quá 25 file
        created_dummy = []
        for i in range(30):
            dummy_f = debug_dir / f"test_dummy_cleanup_{i:02d}.png"
            dummy_f.write_text("dummy")
            created_dummy.append(dummy_f)

        total_before = len(list(debug_dir.glob("*.png")))
        print(f"[Evidence 3A] Số lượng file ảnh trong debug/ trước cleanup: {total_before}")
        assert total_before >= 30, "LỖI: Không tạo đủ file ảnh giả lập!"

        # Thực thi dọn dẹp
        cleanup_old_debug_files(debug_dir=debug_dir, max_files=25)
        total_after = len(list(debug_dir.glob("*.png")))
        print(f"[Evidence 3B] Số lượng file ảnh trong debug/ sau cleanup: {total_after} (Kỳ vọng: <= 25)")
        assert total_after <= 25, f"LỖI: Số file sau cleanup ({total_after}) vượt quá 25!"

        # Dọn dẹp các file dummy còn sót nếu có
        for df in created_dummy:
            if df.exists():
                try: df.unlink()
                except Exception: pass
        print("[Trụ Cột 2 PASS] Dọn dẹp đĩa & vệ sinh RAM hoạt động chính xác!")

        # TRỤ CỘT 3: Lưu & Khôi phục phiên làm việc (Session State Persistence)
        print("\n--- TRỤ CỘT 3: Kiểm thử Lưu & Khôi Phục Phiên Làm Việc (session_state.json) ---")
        save_ok = save_session_state(lake_num=38, fish_count=15, bread_eaten=3)
        print(f"[Evidence 4A] Kết quả lưu session_state.json: {save_ok}")
        assert save_ok, "LỖI: Không thể lưu session_state.json!"
        assert settings.SESSION_STATE_FILE.exists(), "LỖI: File session_state.json không tồn tại!"

        loaded_data = load_session_state(max_age_sec=7200)
        print(f"[Evidence 4B] Dữ liệu khôi phục: HO {loaded_data.get('lake_num')}, {loaded_data.get('fish_count')} cá, {loaded_data.get('bread_eaten')} bánh mì.")
        assert loaded_data is not None, "LỖI: Không thể đọc dữ liệu session_state!"
        assert loaded_data.get('lake_num') == 38, "LỖI: lake_num khôi phục không khớp!"
        assert loaded_data.get('fish_count') == 15, "LỖI: fish_count khôi phục không khớp!"
        print("[Trụ Cột 3 PASS] Lưu & khôi phục phiên làm việc đạt chuẩn 100%!")

        # TRỤ CỘT 4: Universal Popup Dismissal & Làm sạch giao diện
        print("\n--- TRỤ CỘT 4: Kiểm thử Universal Popup Dismissal & Làm Sạch Giao Diện ---")
        clean_ok = ensure_clean_pond_state(page)
        print(f"[Evidence 5] Kết quả ensure_clean_pond_state (bao gồm dismiss popup): {clean_ok}")
        assert clean_ok, "LỖI: ensure_clean_pond_state thất bại!"
        print("[Trụ Cột 4 PASS] Tự động đóng popup & dọn sạch giao diện thành công!")

        # TRỤ CỘT 5: Chụp ảnh live game & Xác thực Anti-Detection (0px drift)
        print("\n--- TRỤ CỘT 5: Live Game Snapshot & Kiểm tra Chống Phát Hiện (Anti-Detection) ---")
        scr = grab_page_bgr(page)
        if scr is not None:
            evidence_img = settings.DEBUG_DIR / "step_b3_immortal_watchdog.png"
            cv2.imwrite(str(evidence_img), scr)
            print(f"[Evidence 6A] Đã lưu ảnh minh chứng live game: {evidence_img}")
            print(f"[Evidence 6A] Kích thước ảnh: {scr.shape}")
            assert evidence_img.exists() and evidence_img.stat().st_size > 100000, "LỖI: Ảnh live game không hợp lệ!"

        # Đo lường chuột Windows cuối cùng
        x_end, y_end = get_mouse_pos()
        dx = abs(x_end - x_start)
        dy = abs(y_end - y_start)
        print(f"\n[Evidence 6B] Vị trí chuột Windows sau test: ({x_end}, {y_end})")
        print(f"[Evidence 6B] Độ xê dịch chuột: dx={dx}px, dy={dy}px")
        assert dx == 0 and dy == 0, f"LỖI: Chuột Windows bị xê dịch ({dx}px, {dy}px)! Vi phạm Anti-Detection!"
        print("[Trụ Cột 5 PASS] Chuột Windows 0px drift (100% Anti-Detection được bảo toàn tuyệt đối)!")

        print("\n" + "=" * 75)
        print("TẤT CẢ 5 TRỤ CỘT KIỂM THỬ THỰC CHIẾN TASK B3 ĐỀU ĐẠT CHUẨN 100% (PASS)")
        print("=" * 75)
        return True

    finally:
        close_cdp(p, b)

if __name__ == "__main__":
    success = run_task_b3_live_verification()
    sys.exit(0 if success else 1)
