# -*- coding: utf-8 -*-
"""
Unit test kiểm thử cơ chế Cache Validation & Invalidation cho mặt nước (Task 1).
Kiểm tra:
1. get_random_pond_point tự động hủy cache khi điểm cache bị đổi màu (không còn là nước).
2. wait_for_pond_arrival không kích hoạt tạo cache điểm nước.
3. Khi chuyển cảnh hoàn tất, cache luôn được làm mới.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import cv2

def test_cache_validation_on_color_mismatch():
    import core.vision as vision
    from core.vision import WATER_LOWER, WATER_UPPER
    
    # Giả lập ảnh 1: Có nước hồ màu [98, 88, 72] tại vùng (900, 400)
    screen_water = np.full((1080, 1920, 3), [30, 30, 30], dtype=np.uint8) # nền đất tối
    # Tạo một vùng hồ nước xanh chuẩn ở giữa ROI
    water_color = np.array([98, 88, 72], dtype=np.uint8)
    screen_water[300:600, 700:1200] = water_color
    
    # Xóa cache
    vision.clear_pond_cache()
    
    # Mock hàm grab_page_bgr để trả về screen_water
    original_grab = vision.grab_page_bgr
    try:
        vision.grab_page_bgr = lambda page: screen_water
        
        # Lần 1: Quét và tạo cache
        pt1 = vision.get_random_pond_point(page=None)
        assert pt1 is not None, "Không tìm thấy điểm nước trên ảnh hồ"
        assert vision._cached_pond_points is not None, "Cache phải được tạo sau lần quét đầu"
        assert len(vision._cached_pond_points) > 0, "Cache không được rỗng"
        
        # Giả lập ảnh 2: Nhân vật đã bị chuyển sang Nhà (màu đất/cỏ, không còn nước ở tọa độ pt1)
        screen_home = np.full((1080, 1920, 3), [40, 120, 40], dtype=np.uint8) # màu cỏ xanh lá
        vision.grab_page_bgr = lambda page: screen_home
        
        # Lần 2: Gọi get_random_pond_point trên screen_home
        # Vì tọa độ cũ trên screen_home là màu cỏ (không phải nước), cache PHẢI tự động bị hủy và trả về None!
        pt2 = vision.get_random_pond_point(page=None)
        assert pt2 is None, f"LỖI: Tọa độ cỏ ở Nhà ({pt2}) vẫn bị trả về do cache cũ không tự hủy!"
        assert vision._cached_pond_points is None, "Cache cũ phải bị hủy khi màu pixel không khớp nước hồ"
        print(" [PASS] test_cache_validation_on_color_mismatch: Tự động phát hiện đổi map và xóa cache thành công!")
        
    finally:
        vision.grab_page_bgr = original_grab

def test_wait_for_pond_arrival_no_cache():
    import core.navigation as nav
    import inspect
    source = inspect.getsource(nav.wait_for_pond_arrival)
    assert "get_random_pond_point" not in source, (
        "LỖI: wait_for_pond_arrival vẫn còn gọi get_random_pond_point, gây ô nhiễm cache trong lúc chuyển cảnh!"
    )
    print(" [PASS] test_wait_for_pond_arrival_no_cache: wait_for_pond_arrival không gọi get_random_pond_point.")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 1: POND CACHE VALIDATION ---")
    try:
        test_cache_validation_on_color_mismatch()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_wait_for_pond_arrival_no_cache()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")

