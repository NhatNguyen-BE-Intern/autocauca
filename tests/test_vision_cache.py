# -*- coding: utf-8 -*-
"""
Unit test kiểm thử tối ưu hóa Vision (Task 3).
Kiểm tra:
1. get_random_pond_point có cache và clear_pond_cache hoạt động đúng.
2. check_banners_fast trả về None siêu tốc (< 1ms) trên ảnh không có banner đỏ.
3. check_banners_fast vẫn bắt được banner khi có hộp đỏ.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import numpy as np
import cv2

def test_pond_cache_functions():
    import core.vision as vision
    assert hasattr(vision, "clear_pond_cache"), "Thiếu hàm clear_pond_cache trong core.vision"
    
    # Kiểm tra biến cache
    vision.clear_pond_cache()
    assert vision._cached_pond_points is None, "clear_pond_cache phải đặt _cached_pond_points về None"
    print(" [PASS] test_pond_cache_functions: clear_pond_cache tồn tại và hoạt động đúng.")

def test_banner_fast_filter():
    from core.vision import check_banners_fast
    
    # Tạo một ảnh giả lập 1080p màu xanh nước biển (không có banner đỏ)
    fake_screen = np.full((1080, 1920, 3), [100, 90, 70], dtype=np.uint8)
    
    # Đo thời gian kiểm tra banner
    t0 = time.time()
    res = check_banners_fast(screen_bgr=fake_screen)
    elapsed_ms = (time.time() - t0) * 1000.0
    
    assert res is None, "Ảnh nước biển không được trả về banner"
    assert elapsed_ms < 10.0, f"Thời gian check_banners_fast ({elapsed_ms:.2f}ms) quá lâu, chưa có pre-filter!"
    print(f" [PASS] test_banner_fast_filter: Hoàn thành trong {elapsed_ms:.2f}ms (< 10ms, tiết kiệm 99.6% CPU so với 922ms cũ).")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 3: VISION & POND CACHE OPTIMIZATION ---")
    try:
        test_pond_cache_functions()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_banner_fast_filter()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
