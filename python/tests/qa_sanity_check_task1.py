# -*- coding: utf-8 -*-
"""
QA Sanity Check Script - Task 1: Nâng cấp dải màu nước Kép & Cache Validation
Tác giả: Subagent 3 (Tester / QA Engineer)
Mục đích: Kiểm thử độc lập và toàn diện thuật toán nhận diện màu nước kép,
kiểm tra tính hợp lệ của điểm quăng cần (không dính bờ, cọc gỗ dock, hoa súng, bãi cỏ),
và cơ chế tự hủy / xác thực cache khi đổi map/thời gian.
"""

import sys
from pathlib import Path
import cv2
import numpy as np

# Thêm thư mục gốc python vào sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import core.vision as vision
from config.settings import (
    WATER_ROI_X_MIN_RATIO,
    WATER_ROI_X_MAX_RATIO,
    WATER_ROI_Y_MIN_RATIO,
    WATER_ROI_Y_MAX_RATIO,
)

def test_color_samples_is_water_pixel():
    """
    Kiểm tra độc lập is_water_pixel với 5 mẫu màu thực tế:
    1. Cỏ ban ngày: BGR [126, 186, 178] -> False
    2. Đất ban ngày: BGR [111, 141, 155] -> False
    3. Nước ban ngày: BGR [203, 205, 177] -> True
    4. Nước ban đêm: BGR [100, 90, 72] -> True
    5. Cỏ ban đêm: BGR [76, 84, 74] -> False
    """
    test_cases = [
        ("Cỏ ban ngày", np.array([126, 186, 178], dtype=np.uint8), False),
        ("Đất ban ngày", np.array([111, 141, 155], dtype=np.uint8), False),
        ("Nước ban ngày", np.array([203, 205, 177], dtype=np.uint8), True),
        ("Nước ban đêm", np.array([100, 90, 72], dtype=np.uint8), True),
        ("Cỏ ban đêm", np.array([76, 84, 74], dtype=np.uint8), False),
    ]

    print("\n--- [QA TEST 1] KIỂM TRA MẪU MÀU is_water_pixel ---")
    for name, bgr, expected in test_cases:
        actual = vision.is_water_pixel(bgr)
        status = "PASS" if actual == expected else "FAIL"
        print(f" [{status}] {name} {bgr.tolist()}: Kỳ vọng={expected}, Thực tế={actual}")
        assert actual == expected, f"Lỗi nhận diện màu {name}: kỳ vọng {expected}, thực tế {actual}"

def test_cast_points_safety_and_objects():
    """
    Kiểm tra tất cả các điểm quăng cần tạo ra trên các ảnh hồ thực tế:
    - Hồ ban đêm (debug_at_ho1.png)
    - Hồ 1 ban ngày (media_1795099463028_47ebd713.jpg)
    - Hồ 2 ban ngày (media_1795099466728_a5835b29.jpg)
    Xác minh:
    1. 100% điểm quăng cần nằm trọn trong vùng nước hồ (is_water_pixel == True).
    2. Khoảng cách an toàn tới các vật thể (bờ, cỏ, cọc gỗ dock, hoa súng) >= 12px (tầng 1-2 từ 18px đến >25px).
    3. Kiểm tra vùng lân cận (radius = 10px) quanh mọi điểm quăng cần không chạm vào vật thể lạ.
    """
    print("\n--- [QA TEST 2] KIỂM TRA ĐIỂM QUĂNG CẦN & KHOẢNG CÁCH VẬT THỂ ---")

    image_configs = [
        ("Hồ ban đêm (debug_at_ho1.png)", Path(PROJECT_ROOT).parent / "debug_at_ho1.png"),
        ("Hồ 1 ban ngày", Path("C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg")),
        ("Hồ 2 ban ngày", Path("C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099466728_a5835b29.jpg")),
    ]

    for label, img_path in image_configs:
        assert img_path.exists(), f"Không tìm thấy file ảnh: {img_path}"
        img = cv2.imread(str(img_path))
        assert img is not None, f"Không thể đọc file ảnh: {img_path}"

        h, w = img.shape[:2]
        x1, x2 = int(w * WATER_ROI_X_MIN_RATIO), int(w * WATER_ROI_X_MAX_RATIO)
        y1, y2 = int(h * WATER_ROI_Y_MIN_RATIO), int(h * WATER_ROI_Y_MAX_RATIO)
        roi = img[y1:y2, x1:x2]

        mask = vision.get_water_mask(roi)
        dist_map = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

        points = vision.detect_pond_points_from_screen(img)
        assert len(points) > 0, f"{label}: Không tìm thấy điểm nước an toàn nào!"

        # 1. Kiểm tra 100% điểm là nước hồ
        non_water_count = sum(1 for pt in points if not vision.is_water_pixel(img[pt[1], pt[0]]))
        assert non_water_count == 0, f"{label}: Có {non_water_count} điểm rơi vào vùng không phải nước!"

        # 2. Thẩm định Distance Transform (khoảng cách tới bờ / cọc gỗ dock / hoa súng / bãi cỏ)
        distances = [dist_map[pt[1] - y1, pt[0] - x1] for pt in points]
        min_d = min(distances)
        max_d = max(distances)
        avg_d = sum(distances) / len(distances)

        assert min_d >= 12.0, f"{label}: Khoảng cách an toàn tối thiểu vi phạm ngưỡng: {min_d}px < 12px"

        # 3. Quét kiểm tra bán kính 10px quanh 100 điểm ngẫu nhiên
        sample_pts = points if len(points) <= 100 else [points[i] for i in np.random.choice(len(points), 100, replace=False)]
        violations = 0
        for pt in sample_pts:
            px, py = pt
            for dx in range(-10, 11, 2):
                for dy in range(-10, 11, 2):
                    if dx * dx + dy * dy <= 100:
                        test_px = img[py + dy, px + dx]
                        if not vision.is_water_pixel(test_px):
                            violations += 1
                            break
                if violations > 0:
                    break

        assert violations == 0, f"{label}: Có {violations} vi phạm vùng đệm 10px an toàn!"

        print(f" [PASS] {label}:")
        print(f"        + Số điểm nước an toàn: {len(points)}")
        print(f"        + Tỷ lệ nước hồ: 100% ({len(points)}/{len(points)})")
        print(f"        + Khoảng cách vật thể: min={min_d:.2f}px, max={max_d:.2f}px, trung bình={avg_d:.2f}px")
        print(f"        + Vùng đệm 10px an toàn quanh điểm: 100% sạch (0 vi phạm bờ/cọc/hoa súng/cỏ)")

def test_cache_validation_scenarios():
    """
    Kiểm tra toàn diện cơ chế Cache Validation:
    - Khi điểm cache là nước ngày -> Cache hợp lệ, trả về điểm ngay.
    - Khi điểm cache là nước đêm -> Cache hợp lệ, trả về điểm ngay.
    - Khi chuyển sang bãi cỏ ngày [126, 186, 178] -> Cache tự hủy, xóa cache về None.
    - Khi chuyển sang nền đất [111, 141, 155] -> Cache tự hủy, xóa cache về None.
    - Khi chuyển sang bãi cỏ đêm [76, 84, 74] -> Cache tự hủy, xóa cache về None.
    - Khi tọa độ cache vượt biên (out of bounds) -> Cache tự bảo vệ và đặt lại None.
    """
    print("\n--- [QA TEST 3] KIỂM TRA CƠ CHẾ VALIDATION & TỰ HỦY CACHE ---")

    # Kịch bản 1: Nước ban ngày giữ cache
    vision.clear_pond_cache()
    day_screen = np.full((1080, 1920, 3), [203, 205, 177], dtype=np.uint8)
    vision._cached_pond_points = [(500, 500)]
    vision.grab_page_bgr = lambda page: day_screen
    pt = vision.get_random_pond_point(page=None)
    assert pt == (500, 500) and vision._cached_pond_points is not None, "Cache nước ngày phải hợp lệ"
    print(" [PASS] Cache nước ngày: Duy trì hợp lệ và tái sử dụng thành công.")

    # Kịch bản 2: Nước ban đêm giữ cache
    night_screen = np.full((1080, 1920, 3), [100, 90, 72], dtype=np.uint8)
    vision._cached_pond_points = [(500, 500)]
    vision.grab_page_bgr = lambda page: night_screen
    pt = vision.get_random_pond_point(page=None)
    assert pt == (500, 500) and vision._cached_pond_points is not None, "Cache nước đêm phải hợp lệ"
    print(" [PASS] Cache nước đêm: Duy trì hợp lệ và tái sử dụng thành công.")

    # Kịch bản 3: Chuyển sang màu cỏ ban ngày -> Tự động hủy cache
    grass_day = np.full((1080, 1920, 3), [126, 186, 178], dtype=np.uint8)
    vision._cached_pond_points = [(500, 500)]
    vision.grab_page_bgr = lambda page: grass_day
    pt = vision.get_random_pond_point(page=None)
    assert pt is None and vision._cached_pond_points is None, "Cache phải bị xóa khi gặp màu cỏ ngày"
    print(" [PASS] Tự hủy cache khi phát hiện màu cỏ ban ngày: Thành công.")

    # Kịch bản 4: Chuyển sang màu đất ban ngày -> Tự động hủy cache
    dirt_day = np.full((1080, 1920, 3), [111, 141, 155], dtype=np.uint8)
    vision._cached_pond_points = [(500, 500)]
    vision.grab_page_bgr = lambda page: dirt_day
    pt = vision.get_random_pond_point(page=None)
    assert pt is None and vision._cached_pond_points is None, "Cache phải bị xóa khi gặp màu đất ngày"
    print(" [PASS] Tự hủy cache khi phát hiện màu đất ban ngày: Thành công.")

    # Kịch bản 5: Chuyển sang màu cỏ ban đêm -> Tự động hủy cache
    grass_night = np.full((1080, 1920, 3), [76, 84, 74], dtype=np.uint8)
    vision._cached_pond_points = [(500, 500)]
    vision.grab_page_bgr = lambda page: grass_night
    pt = vision.get_random_pond_point(page=None)
    assert pt is None and vision._cached_pond_points is None, "Cache phải bị xóa khi gặp màu cỏ đêm"
    print(" [PASS] Tự hủy cache khi phát hiện màu cỏ ban đêm: Thành công.")

    # Kịch bản 6: Tọa độ ngoài màn hình -> Tự hủy an toàn
    vision._cached_pond_points = [(9999, 9999)]
    vision.grab_page_bgr = lambda page: day_screen
    pt = vision.get_random_pond_point(page=None)
    # Tọa độ ngoài màn hình sẽ bị phát hiện, xóa cache, quét lại từ day_screen -> ra điểm mới hợp lệ
    assert pt is not None and pt != (9999, 9999), "Phải tự hủy điểm lỗi và tái tạo điểm hợp lệ"
    print(" [PASS] Bảo vệ an toàn khi tọa độ cache ngoài màn hình: Thành công.")

def run_qa_sanity_check():
    print("=================================================================")
    print("     QA SANITY CHECK SUITE - TASK 1: DUAL WATER & CACHE VALIDATION")
    print("=================================================================")
    test_color_samples_is_water_pixel()
    test_cast_points_safety_and_objects()
    test_cache_validation_scenarios()
    print("\n=================================================================")
    print("     TẤT CẢ CÁC BÀI TEST QA SANITY CHECK ĐÃ VƯỢT QUA 100%!")
    print("=================================================================")

if __name__ == "__main__":
    run_qa_sanity_check()
