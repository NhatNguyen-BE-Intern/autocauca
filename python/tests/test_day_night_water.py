# python/tests/test_day_night_water.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import core.vision as vision

def test_dual_water_detection_night():
    night_img = cv2.imread("debug_at_ho1.png")
    assert night_img is not None, "debug_at_ho1.png missing"
    points = vision.detect_pond_points_from_screen(night_img)
    assert len(points) > 100, f"Night water points too low: {len(points)}"
    print(f" [PASS] test_dual_water_detection_night: Found {len(points)} safe points.")

def test_dual_water_detection_day():
    day1_path = "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg"
    day1_img = cv2.imread(day1_path)
    assert day1_img is not None, "day1 image missing"
    points1 = vision.detect_pond_points_from_screen(day1_img)
    assert len(points1) > 50, f"Day1 water points too low: {len(points1)}"

    day2_path = "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099466728_a5835b29.jpg"
    day2_img = cv2.imread(day2_path)
    assert day2_img is not None, "day2 image missing"
    points2 = vision.detect_pond_points_from_screen(day2_img)
    assert len(points2) > 50, f"Day2 water points too low: {len(points2)}"
    print(f" [PASS] test_dual_water_detection_day: Day1={len(points1)}, Day2={len(points2)} points.")

def test_cache_validation_day_and_night():
    vision.clear_pond_cache()
    # 1. Day water cache validation
    day_screen = np.full((1080, 1920, 3), [203, 205, 177], dtype=np.uint8)
    vision._cached_pond_points = [(960, 540)]
    vision.grab_page_bgr = lambda page: day_screen
    pt = vision.get_random_pond_point(page=None)
    assert pt == (960, 540), "Cache day water must remain valid"
    assert vision._cached_pond_points is not None, "Day water cache must NOT be cleared"

    # 2. Night water cache validation
    night_screen = np.full((1080, 1920, 3), [100, 90, 72], dtype=np.uint8)
    vision._cached_pond_points = [(960, 540)]
    vision.grab_page_bgr = lambda page: night_screen
    pt_night = vision.get_random_pond_point(page=None)
    assert pt_night == (960, 540), "Cache night water must remain valid"

    # 3. Grass color must invalidate cache
    grass_screen = np.full((1080, 1920, 3), [126, 186, 178], dtype=np.uint8)
    vision.grab_page_bgr = lambda page: grass_screen
    pt_grass = vision.get_random_pond_point(page=None)
    assert pt_grass is None, "Grass color must invalidate cache and return None"
    assert vision._cached_pond_points is None, "Cache must be cleared on grass color"
    print(" [PASS] test_cache_validation_day_and_night passed successfully.")

if __name__ == "__main__":
    test_dual_water_detection_night()
    test_dual_water_detection_day()
    test_cache_validation_day_and_night()
    print("\nALL TASK 1 TESTS PASSED!")
