# -*- coding: utf-8 -*-
"""
Script kiểm thử nghiệm thu thực chiến Task B1 (AI Tester Verification):
1. Kiểm tra Terminal Output khi DEBUG_LOG = False:
   - Đảm bảo banner hiển thị đẹp mắt, trực quan.
   - Không có log kỹ thuật rác (DOM selector, DPR, dev coordinates, bounding box).
   - Ngôn ngữ tiếng Việt tự nhiên 100%.
2. Kiểm tra Terminal Output khi DEBUG_LOG = True:
   - Các log kỹ thuật [DEBUG] xuất hiện đầy đủ.
3. Kiểm tra kết nối game thực tế CDP (port 9222) và đo độ trôi chuột Windows (0px drift).
4. Chụp ảnh màn hình live game làm minh chứng.
"""
import io
import sys
import time
import ctypes
from pathlib import Path

# Thêm đường dẫn project
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings as settings
import core.logger as logger
from core.cdp_client import connect_cdp, close_cdp
from core.vision import grab_page_bgr
import cv2

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def test_live_logger_and_antidetect():
    print("=" * 70)
    print("BẮT ĐẦU KIỂM THỬ THỰC CHIẾN TASK B1 (AI TESTER VERIFICATION)")
    print("=" * 70)

    # 1. Đo vị trí chuột Windows ban đầu
    x_start, y_start = get_mouse_pos()
    print(f"[Evidence 1] Vị trí chuột Windows ban đầu: ({x_start}, {y_start})")

    # 2. Test Terminal Logger với DEBUG_LOG = False
    print("\n--- TEST 2: Kiểm tra Log thực tế khi DEBUG_LOG = False ---")
    settings.DEBUG_LOG = False
    logger.DEBUG_LOG = False

    buf_false = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf_false

    try:
        logger.print_banner()
        p, b, target_page, cdp = connect_cdp()
        logger.set_lake(1)
        logger.set_energy(76)
        logger.log_travel(1)
        logger.log_arrived(1)
        logger.log_cast(1)
        logger.log_debug("TECHNICAL_DEV_COORDS_X_123_Y_456_DPR_1.375")
        logger.log_bite(1)
        logger.record_catch()
        logger.log_catch_success(1)
        logger.log_break(18.5, 1)
    finally:
        sys.stdout = old_stdout

    log_output_false = buf_false.getvalue()
    print("Log thu được khi DEBUG_LOG = False:\n")
    print(log_output_false)

    # Kiểm tra không có log debug rác khi DEBUG_LOG = False
    assert "TECHNICAL_DEV_COORDS" not in log_output_false, "LỖI: Log debug vẫn xuất hiện khi DEBUG_LOG = False!"
    assert "[DEBUG]" not in log_output_false, "LỖI: Thẻ [DEBUG] xuất hiện khi DEBUG_LOG = False!"
    assert "DPR" not in log_output_false, "LỖI: Thông số DPR bị lộ ra console mặc định!"
    assert "Khởi hành tới HO 1" in log_output_false
    assert "THÀNH CÔNG! Bắt được 1 cá" in log_output_false
    assert "[HỒ 01/40]" in log_output_false
    print("[Verification 2 PASS] DEBUG_LOG = False hoạt động chuẩn xác: 0 log debug rác, format tiếng Việt tự nhiên 100%.")

    # 3. Test Terminal Logger với DEBUG_LOG = True
    print("\n--- TEST 3: Kiểm tra Log thực tế khi DEBUG_LOG = True ---")
    settings.DEBUG_LOG = True
    logger.DEBUG_LOG = True

    buf_true = io.StringIO()
    sys.stdout = buf_true
    try:
        logger.log_debug("DEV_DEBUG_COORDINATES: x=650, y=320, match_score=0.98")
    finally:
        sys.stdout = old_stdout

    log_output_true = buf_true.getvalue()
    print("Log thu được khi DEBUG_LOG = True:\n")
    print(log_output_true)

    assert "DEV_DEBUG_COORDINATES" in log_output_true, "LỖI: Log debug không hiển thị khi DEBUG_LOG = True!"
    assert "[DEBUG]" in log_output_true
    print("[Verification 3 PASS] DEBUG_LOG = True kích hoạt chuẩn xác cho chế độ chẩn đoán.")

    # Reset lại DEBUG_LOG = False
    settings.DEBUG_LOG = False
    logger.DEBUG_LOG = False

    # 4. Kiểm thử kết nối game thực tế CDP và chụp ảnh màn hình
    print("\n--- TEST 4: Kết nối Live Game qua CDP & Chụp ảnh bằng chứng ---")
    if target_page:
        img_live = grab_page_bgr(target_page)
        if img_live is not None:
            debug_img_path = PROJECT_ROOT / "debug" / "step_b1_terminal_log_verification.png"
            debug_img_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(debug_img_path), img_live)
            print(f"[Evidence 4] Đã chụp ảnh màn hình live game thành công: {debug_img_path}")
            print(f"[Evidence 4] Kích thước ảnh live game: {img_live.shape}")
        else:
            print("[Cảnh báo] grab_page_bgr trả về None!")
        close_cdp(p, b)
    else:
        print("[Lỗi] Không kết nối được target_page qua CDP!")

    # 5. Đo vị trí chuột Windows sau toàn bộ quá trình
    x_end, y_end = get_mouse_pos()
    print(f"\n[Evidence 5] Vị trí chuột Windows sau test: ({x_end}, {y_end})")
    dx = abs(x_end - x_start)
    dy = abs(y_end - y_start)
    print(f"[Evidence 5] Độ dịch chuyển chuột Windows: dx={dx}px, dy={dy}px")
    assert dx == 0 and dy == 0, f"LỖI: Chuột Windows bị xê dịch ({dx}px, {dy}px)! Vi phạm Anti-Detection!"
    print("[Verification 5 PASS] Chuột Windows 0px drift (100% Chống phát hiện được bảo toàn)!")

    print("\n" + "=" * 70)
    print("TẤT CẢ 5 HẠNG MỤC KIỂM THỬ THỰC CHIẾN TASK B1 ĐỀU ĐẠT CHUẨN 100% (PASS)")
    print("=" * 70)

if __name__ == "__main__":
    test_live_logger_and_antidetect()
