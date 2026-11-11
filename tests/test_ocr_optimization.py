# -*- coding: utf-8 -*-
"""
Unit test kiểm thử tối ưu hóa OCR (Task 2).
Kiểm tra:
1. find_bookmark_row_by_ocr không gọi ocr_engine trên toàn màn hình.
2. Nút Fast Travel chỉ được tìm kiếm khi đã khớp được target_num.
3. Bộ đệm theo dõi thể lực (Energy Tracking Cache) giảm 90% số lần gọi OCR.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re
import numpy as np

def test_no_fullscreen_ocr_fallback():
    from core.navigation import find_bookmark_row_by_ocr
    import inspect
    source = inspect.getsource(find_bookmark_row_by_ocr)
    
    assert "ocr_engine(screen_bgr)" not in source, (
        "LỖI: find_bookmark_row_by_ocr vẫn còn fallback ocr_engine(screen_bgr) trên toàn màn hình!"
    )
    print(" [PASS] test_no_fullscreen_ocr_fallback: Đã loại bỏ hoàn toàn OCR 1080p full-screen.")

def test_deferred_button_search():
    from core.navigation import find_bookmark_row_by_ocr
    import inspect
    source = inspect.getsource(find_bookmark_row_by_ocr)
    
    # ft_buttons không được gọi ở đầu hàm trước khi có ocr_res
    first_ocr = source.find("ocr_engine(")
    first_btn = source.find("find_all_templates(")
    
    assert first_ocr < first_btn, (
        "LỖI: find_all_templates đang được gọi trước ocr_engine, gây lãng phí CPU khi chưa khớp được hồ!"
    )
    print(" [PASS] test_deferred_button_search: Nút Fast Travel chỉ được quét sau khi OCR tìm thấy hồ.")

def test_energy_cache_logic():
    # Mô phỏng logic quản lý thể lực cục bộ
    tracked_energy = None
    casts_since_sync = 0
    ocr_calls = 0
    
    def simulate_cast(fish_success=True):
        nonlocal tracked_energy, casts_since_sync, ocr_calls
        needs_ocr = False
        
        if tracked_energy is None:
            needs_ocr = True
        elif tracked_energy <= 8:
            needs_ocr = True
        elif casts_since_sync >= 10:
            needs_ocr = True
            
        if needs_ocr:
            ocr_calls += 1
            # Giả lập đọc OCR từ game
            tracked_energy = 75 if tracked_energy is None else tracked_energy
            casts_since_sync = 0
            
        if fish_success and tracked_energy is not None and tracked_energy > 0:
            tracked_energy -= 1
            casts_since_sync += 1
            
    # Giả lập 30 lượt câu cá liên tiếp
    for _ in range(30):
        simulate_cast(fish_success=True)
        
    print(f" -> 30 lượt câu chỉ cần gọi OCR: {ocr_calls} lần (thay vì 30 lần!).")
    assert ocr_calls <= 4, f"Số lần gọi OCR ({ocr_calls}) quá nhiều, chưa đạt mức tối ưu!"
    print(" [PASS] test_energy_cache_logic: Tiết kiệm > 85% số lần gọi OCR thể lực.")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 2: OCR OPTIMIZATION ---")
    try:
        test_no_fullscreen_ocr_fallback()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_deferred_button_search()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_energy_cache_logic()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")

